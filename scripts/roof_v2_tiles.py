"""Isolated, actual-renderer preview of roof-v2 meshes in current CB map tiles.

No inference and no visual scoring take place here.  Source tiles, renderer and
scene remain read-only.  Run without --render first to prepare/validate inputs;
--render renders only the touched summer tiles and writes report.html.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import hashlib
from html import escape
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Polygon, shape
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK = ROOT / '.work/.preview/ceske-budejovice'
DEFAULT_OUTPUT = ROOT / 'cities/ceske-budejovice/experiments/roof-v2/tiles'
ROOFS = ((151, 79, 61), (135, 70, 54), (116, 83, 67), (103, 103, 106),
         (82, 89, 97), (143, 111, 86), (109, 112, 103))
WALLS = ((222, 213, 193), (211, 202, 182), (205, 202, 190), (204, 187, 162),
         (185, 191, 188), (174, 186, 193), (207, 185, 174), (192, 194, 178))
STATUS_COLORS = {'supported': [112, 151, 124], 'uncertain': [192, 151, 84],
                 'fallback': [177, 106, 101], 'unknown': [139, 143, 153]}
STATUS_NAMES = {'supported': 'Bez prahového varování', 'uncertain': 'Ke kontrole',
                'fallback': 'Náhradní model', 'unknown': 'Jistota neuvedena'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                   allow_nan=False) + '\n', encoding='utf-8')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def closest_color(value, palette):
    """Quantize an existing scene color to an explicit muted palette, in Lab."""
    try:
        rgb = np.asarray(value, dtype=float)
        if rgb.shape != (3,) or not np.isfinite(rgb).all():
            raise ValueError('invalid color')
        rgb = np.clip(rgb, 0, 255)
    except (TypeError, ValueError):
        rgb = np.asarray(palette[0], dtype=float)
    def lab(items):
        a = np.asarray(items, dtype=float) / 255
        a = np.where(a <= .04045, a / 12.92, ((a + .055) / 1.055) ** 2.4)
        xyz = a @ np.array([[.4124564, .2126729, .0193339],
                            [.3575761, .7151522, .1191920],
                            [.1804375, .0721750, .9503041]])
        xyz /= np.array([.95047, 1., 1.08883])
        f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
        return np.stack((116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                         200 * (f[..., 1] - f[..., 2])), axis=-1)
    distance = np.sum((lab(palette) - lab(rgb)) ** 2, axis=1)
    return list(palette[int(np.argmin(distance))])


def diagnostic_status(diag):
    """Never invent calibrated probabilities or a confident state from error alone."""
    state = str(diag.get('status', diag.get('confidence_label', ''))).lower()
    flags = set(diag.get('flags') or [])
    if (diag.get('fallback') or state in ('fallback', 'insufficient_data', 'no_data')
            or flags.intersection({'insufficient_data', 'fallback_geometry_not_roof_classification'})):
        return 'fallback'
    if diag.get('needs_review') or diag.get('review_required') or state in (
            'uncertain', 'ambiguous', 'review', 'low', 'low_confidence'):
        return 'uncertain'
    if flags.intersection({'poor_template_fit', 'ambiguous_type', 'incomplete_point_coverage',
        'part_boundaries_need_review', 'optimizer_iteration_limit',
        'higher_ranked_mesh_rejected', 'source_type_disagrees'}):
        return 'uncertain'
    if diag.get('review_required') is False:
        return 'supported'
    if state in ('supported', 'confident', 'high', 'accepted', 'ok'):
        return 'supported'
    return 'unknown'


class Projection:
    """Use the map's exact geo.py projection, including its city HREF."""
    def __init__(self, work, info):
        previous = os.environ.get('IZO_MESTO')
        os.environ['IZO_MESTO'] = str(Path(work) / 'mesto.json')
        try:
            spec = importlib.util.spec_from_file_location('roof_v2_map_geo', ROOT / 'geo.py')
            self.geo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.geo)
        finally:
            if previous is None:
                os.environ.pop('IZO_MESTO', None)
            else:
                os.environ['IZO_MESTO'] = previous
        self.transformer = Transformer.from_crs(5514, 4326, always_xy=True)
        self.image = self.geo.Image2D(info)

    def world(self, xyz):
        xyz = np.asarray(xyz, dtype=float)
        lon, lat = self.transformer.transform(xyz[:, 0], xyz[:, 1])
        x, y = self.geo.to_local(lon, lat)
        return np.column_stack((x, y, xyz[:, 2] - self.geo.HREF))

    def part(self, vertices, origin, ground_z):
        return self.world(np.asarray(vertices, dtype=float) + [*origin, ground_z])

    def pixels(self, vertices):
        return np.column_stack(self.image.px(*np.asarray(vertices, dtype=float).T))[:, :2]


def validate_mesh(mesh):
    vertices = np.asarray(mesh.get('vertices', []), dtype=float)
    if vertices.ndim != 2 or vertices.shape[1:] != (3,) or len(vertices) < 3:
        raise ValueError('mesh.vertices must be nonempty local XYZ triples')
    if not np.isfinite(vertices).all():
        raise ValueError('mesh contains nonfinite vertices')
    if np.max(np.abs(vertices[:, :2])) > 10000 or np.max(np.abs(vertices[:, 2])) > 1000:
        raise ValueError('mesh is not local XY / above-ground Z in meters')
    for key in ('roof_faces', 'wall_faces', 'ground_faces'):
        faces = mesh.get(key, [])
        if key != 'ground_faces' and not faces:
            raise ValueError(f'mesh.{key} is empty')
        for face in faces:
            if len(face) != 3 or any(isinstance(i, bool) or not isinstance(i, int) for i in face):
                raise ValueError(f'mesh.{key} must contain indexed triangles')
            if min(face) < 0 or max(face) >= len(vertices) or len(set(face)) < 3:
                raise ValueError(f'mesh.{key} contains an invalid index')
            a, b, c = vertices[face]
            if np.linalg.norm(np.cross(b - a, c - a)) < 1e-9:
                raise ValueError(f'mesh.{key} contains a degenerate triangle')
    return vertices


def fit_crop(pixels, info, margin=100):
    pixels = np.asarray(pixels, dtype=float)
    if not len(pixels) or not np.isfinite(pixels).all():
        return None
    lo, hi = pixels.min(axis=0) - margin, pixels.max(axis=0) + margin
    center = (lo + hi) / 2
    size = np.maximum(hi - lo, [352, 288])
    lo = np.maximum(np.floor(center - size / 2), 0).astype(int)
    hi = np.minimum(np.ceil(center + size / 2), [info['width'], info['height']]).astype(int)
    if np.any(hi <= lo):
        return None
    return [int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1])]


def tile_indices(box, size):
    if box is None:
        return []
    left, top, right, bottom = box
    return [(i, j) for j in range(top // size, (bottom - 1) // size + 1)
            for i in range(left // size, (right - 1) // size + 1)]


def prepare(document, scene, source, info, projection):
    """Return cases and renderer substitutions, without mutating source scene.

    Each source OID maps to all its scene pieces.  Replacement is atomic for an
    OID: every new part must be valid and cover all old pieces, otherwise every
    old piece remains.  Meshes are emitted at one anchor; other IDs just skip.
    """
    if document.get('schema') != 'roof-v2/1':
        raise ValueError('Expected roof-v2/1, not results from the rejected algorithm')
    by_oid = defaultdict(list)
    by_id = {b['id']: b for b in scene['buildings']}
    if len(by_id) != len(scene['buildings']):
        raise ValueError('Scene contains duplicate IDs')
    for entry in source['buildings']:
        if entry.get('oid') is not None and entry['id'] in by_id:
            by_oid[str(entry['oid'])].append(entry['id'])
    cases, replacements, seen = [], {}, set()
    for building in document.get('buildings', []):
        oid = str(building['id'])
        if oid in seen:
            raise ValueError(f'Duplicate source building id: {oid}')
        seen.add(oid)
        ids = sorted(set(by_oid.get(oid, [])))
        case = {'id': oid, 'name': building.get('name') or '',
                'address': building.get('address') or building.get('name') or oid,
                'scene_ids': ids, 'renderable': False, 'errors': [], 'parts': [],
                'source': building.get('source', {}),
                'source_attributes': building.get('source_attributes', {}),
                'footprint_sources': building.get('footprint_sources', []),
                'source_files': building.get('source_files', []),
                'scene_colors': [{'scene_id': sid, 'roof': by_id[sid].get('rc'),
                                  'wall': by_id[sid].get('wc')} for sid in ids]}
        if isinstance(case['address'], list):
            case['address'] = ', '.join(map(str, case['address']))
        pixels, meshes, footprints = [], [], []
        for sid in ids:
            b = by_id[sid]
            old_xyz = [[x, y, z] for x, y in b['p'] for z in
                       (b['b'], b['e'] + b.get('rh', 0))]
            pixels.extend(projection.pixels(old_xyz).tolist())
        if not ids:
            case['errors'].append('Source OID was not found in the current map; no geographic guessing was used.')
        if not building.get('parts'):
            case['errors'].append('No roof-v2 parts are available.')
        for part_index, part in enumerate(building.get('parts', [])):
            try:
                if part.get('status') not in (None, 'inferred'):
                    raise ValueError(f"incomplete input part ({part['status']})")
                result = part['result']
                model = result['model']
                raw_vertices = validate_mesh(model['mesh'])
                origin = np.asarray(part['origin_xy'], dtype=float)
                ground_z = float(part['ground_z'])
                if origin.shape != (2,) or not np.isfinite([*origin, ground_z]).all():
                    raise ValueError('invalid EPSG:5514 origin or absolute ground height')
                vertices = projection.part(raw_vertices, origin, ground_z)
                if not np.isfinite(vertices).all():
                    raise ValueError('projection produced nonfinite coordinates')
                footprint = shape(part['footprint'])
                if footprint.is_empty or not footprint.is_valid or footprint.geom_type not in ('Polygon', 'MultiPolygon'):
                    raise ValueError('invalid local footprint')
                def map_xy(x, y, z=None):
                    coords = np.column_stack((x, y, np.zeros_like(x)))
                    p = projection.part(coords, origin, ground_z)
                    return p[:, 0], p[:, 1]
                footprint_map = transform(map_xy, footprint)
                footprints.append(footprint_map)
                diag = result.get('diagnostics') or {}
                state = diagnostic_status(diag)
                color_sid = max(ids, key=lambda sid: footprint_map.intersection(
                    Polygon(by_id[sid]['p']).buffer(0)).area) if ids else None
                b = by_id[color_sid] if ids else {}
                mesh = {key: deepcopy(model['mesh'].get(key, [])) for key in
                        ('roof_faces', 'wall_faces', 'ground_faces')}
                mesh.update({'vertices': vertices.round(6).tolist(),
                             'ground_z': ground_z - getattr(getattr(projection, 'geo', None), 'HREF', 0),
                             'roof_color': closest_color(b.get('rc'), ROOFS),
                             'wall_color': closest_color(b.get('wc'), WALLS),
                             'diagnostic_color': STATUS_COLORS[state], 'status': state})
                meshes.append(mesh)
                pixels.extend(projection.pixels(vertices).tolist())
                case['parts'].append({'index': part_index, 'type': model.get('type'),
                    'status': state, 'diagnostics': diag, 'timing': result.get('timing', {}),
                    'roof_faces': len(mesh['roof_faces']), 'wall_faces': len(mesh['wall_faces']),
                    'color_reference_scene_id': color_sid,
                    'color_reference': 'baseline scene rc/wc after source and manual overrides',
                    'source_colors': {'roof': b.get('rc'), 'wall': b.get('wc')},
                    'render_colors': {'roof': mesh['roof_color'], 'wall': mesh['wall_color']}})
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                case['errors'].append(f'Part {part_index}: {exc}')
        if ids and footprints and not case['errors']:
            # Allow <= 0.75 m footprint simplification / projection rounding,
            # but never silently delete a disconnected old piece.
            cover = unary_union(footprints).buffer(.75)
            for sid in ids:
                old = Polygon(by_id[sid]['p']).buffer(0)
                fraction = cover.intersection(old).area / max(old.area, 1e-12)
                if fraction < .90:
                    case['errors'].append(f'Scene part {sid} has only {fraction:.1%} footprint coverage; all old parts preserved.')
        case['crop'] = fit_crop(pixels, info)
        if not case['crop']:
            case['errors'].append('Building is outside the preview pixel extent.')
        if meshes and not case['errors']:
            case['renderable'] = True
            for sid in ids:
                replacements[str(sid)] = []
            replacements[str(ids[0])] = meshes
        cases.append(case)
    return cases, replacements


MESH_INSERT = '''
    if (Object.hasOwn(scene.roofV2 || {}, b.id)) {
      window.ROOF_V2_STATS.replaced_scene_ids.push(b.id);
      for (const m of scene.roofV2[b.id]) {
        window.ROOF_V2_STATS.mesh_parts++;
        const vv = m.vertices.map(p => tv(...p));
        const rc = C255(PARAMS.v2diagnostic === '1' ? m.diagnostic_color : m.roof_color);
        for (const ids of m.roof_faces) {
          pushTri(R, ...ids.map(i => vv[i]), rc, [0,0,0,0]);
          window.ROOF_V2_STATS.roof_triangles++;
        }
        for (const ids of m.wall_faces) {
          const xyz = ids.map(i => m.vertices[i]);
          const edges = xyz.map((a,i) => [xyz[(i+1)%3][0]-a[0], xyz[(i+1)%3][1]-a[1]]);
          const [dx,dy] = edges.sort((a,c) => Math.hypot(...c)-Math.hypot(...a))[0];
          const norm = Math.hypot(dx,dy) || 1;
          const sign = dx < -1e-6 || (Math.abs(dx) <= 1e-6 && dy < 0) ? -1 : 1;
          const along = xyz.map(p => sign*(p[0]*dx+p[1]*dy)/norm);
          const start = Math.min(...along), span = Math.max(...along)-start;
          const uv = xyz.map((p,i) => [along[i]-start,p[2]-m.ground_z,span,b.s]);
          pushTri(W, ...ids.map(i => vv[i]), C255(m.wall_color), uv);
          window.ROOF_V2_STATS.wall_triangles++;
        }
      }
      continue;
    }
'''


def patch_renderer(html, info, shadow_size=8192):
    markers = ('    if (b.only) continue;',
               '    if (b.lm && CUSTOM.landmarks?.[b.lm]',
               'const IW = Math.ceil((X1 - X0) / MPP), IH = Math.ceil((Y1 - Y0) / MPP);')
    for marker in markers:
        if html.count(marker) != 1:
            raise ValueError(f'Renderer interface changed (expected one marker): {marker}')
    stats = ('window.ROOF_V2_STATS = {replaced_scene_ids:[],mesh_parts:0,'
             'roof_triangles:0,wall_triangles:0};\n')
    start = 'const scene = await (await fetch(`${DIR}/scene.json`)).json();'
    if html.count(start) != 1:
        raise ValueError('Renderer scene load marker changed')
    html = html.replace(start, start + '\n' + stats)
    html = html.replace(markers[0], MESH_INSERT + markers[0])
    html = html.replace(markers[1],
        '    if (Object.hasOwn(scene.roofV2 || {}, b.id)) continue;\n' + markers[1])
    if shadow_size != 8192:
        shadow = 'const shadowRT = new THREE.WebGLRenderTarget(8192, 8192, { depthTexture: new THREE.DepthTexture(8192, 8192, THREE.FloatType) });'
        if html.count(shadow) != 1:
            raise ValueError('Renderer shadow target marker changed')
        html = html.replace(shadow, shadow.replace('8192', str(int(shadow_size))))
    ready = 'window.READY = true;'
    if html.count(ready) != 1:
        raise ValueError('Renderer ready marker changed')
    html = html.replace(ready, '''
{
  const gl = renderer.getContext();
  const debug = gl.getExtension('WEBGL_debug_renderer_info');
  window.ROOF_V2_STATS.gpu = {vendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
    renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)};
  window.ROOF_V2_STATS.context_lost = gl.isContextLost();
  renderer.domElement.addEventListener('webglcontextlost', () => { window.ROOF_V2_STATS.context_lost = true; });
  const originalRenderTile = window.renderTile;
  window.renderTile = (i,j) => {
    if (gl.isContextLost() || window.ROOF_V2_STATS.context_lost) throw new Error('WebGL context lost before tile');
    const png = originalRenderTile(i,j);
    const error = gl.getError();
    if (error !== gl.NO_ERROR || gl.isContextLost()) throw new Error(`WebGL error after tile: ${error}`);
    const data = octx.getImageData(0,0,TILE,TILE).data;
    let count=0, opaque=0, sum=0, sq=0, low=255, high=0;
    const colors = new Set();
    for (let y=4;y<TILE;y+=8) for (let x=4;x<TILE;x+=8) {
      const k=4*(y*TILE+x); count++;
      if (data[k+3] < 16) continue;
      opaque++;
      const r=data[k],g=data[k+1],b=data[k+2],v=.2126*r+.7152*g+.0722*b;
      sum+=v; sq+=v*v; low=Math.min(low,r,g,b); high=Math.max(high,r,g,b);
      colors.add(((r>>3)<<10)|((g>>3)<<5)|(b>>3));
    }
    const mean=opaque?sum/opaque:0;
    window.ROOF_V2_LAST_PIXEL_QA = {sample_count:count,opaque_pixels:opaque,
      opaque_fraction:opaque/count,unique_rgb:colors.size,rgb_min:low,rgb_max:high,
      luma_variance:opaque?Math.max(0,sq/opaque-mean*mean):0};
    return png;
  };
}
''' + ready)
    return html.replace(markers[2],
        f"GX0 = {info['x0']}; GY1 = {info['y1']}; X0 = GX0 - offV.x; Y1 = GY1 - offV.y;\n"
        f"const IW = {info['width']}, IH = {info['height']};")


@lru_cache(maxsize=4)
def read_tile(path):
    with Image.open(path) as image:
        return image.convert('RGBA')


def crop_tiles(folder, box, size):
    left, top, right, bottom = box
    crop = Image.new('RGBA', (right - left, bottom - top), (27, 35, 51, 255))
    for i, j in tile_indices(box, size):
        crop.alpha_composite(read_tile(Path(folder) / f'{i}_{j}.png'),
                             dest=(i * size - left, j * size - top))
    return crop


def texture_preview(source, destination, max_size):
    """Write only an isolated, reduced-resolution PNG; never mutate source."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError('Texture preview cannot overwrite source')
    with Image.open(source) as image:
        original = list(image.size)
        factor = max(1, math.ceil(max(original) / max_size)) if max_size else 1
        target = [max(1, math.ceil(n / factor)) for n in original]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if factor == 1:
            shutil.copyfile(source, destination)
        else:
            # Integer decimation keeps the source scale exact and also reduces
            # 4600px lightmap to 2300px under a 4000px budget.
            image.resize(target, Image.Resampling.BILINEAR, reducing_gap=3.).save(destination)
    return {'source': str(source), 'path': str(destination), 'original_size': original,
            'preview_size': target, 'reduction_factor': factor,
            'source_sha256': digest(source), 'preview_sha256': digest(destination)}


def tile_pixel_metrics(path):
    """Small deterministic numeric sample; no semantic/AI image assessment."""
    with Image.open(path) as image:
        data = np.asarray(image.convert('RGBA'))[4::8, 4::8]
    alpha = data[..., 3] >= 16
    rgb = data[..., :3][alpha].astype(np.int32)
    colors = ((rgb[:, 0] >> 3) << 10) | ((rgb[:, 1] >> 3) << 5) | (rgb[:, 2] >> 3)
    luminance = rgb @ np.array([.2126, .7152, .0722])
    return {'sample_count': int(alpha.size), 'opaque_pixels': int(alpha.sum()),
            'opaque_fraction': float(alpha.mean()), 'unique_rgb': int(len(np.unique(colors))),
            'luma_variance': float(luminance.var()) if len(luminance) else 0.}


def preview_allocation_estimate(textures, shadow_size, tile_size):
    texture_bytes = sum(math.prod(t['preview_size']) * 4 for t in textures.values())
    return {'texture_rgba_bytes': texture_bytes,
            'texture_with_mipmaps_bytes': math.ceil(texture_bytes * 4 / 3),
            'shadow_color_depth_bytes': shadow_size * shadow_size * 8,
            'postprocess_color_depth_bytes': (tile_size + 8) ** 2 * 8,
            'tile_canvas_rgba_bytes': tile_size * tile_size * 4 * 2,
            'note': 'Allocation estimates only, not peak RAM. Excludes geometry, browser, driver and CPU staging copies.'}


def write_report(output, manifest, background):
    """Images are produced by the real renderer; never substitute mesh overlays."""
    crops = output / 'crops'
    crops.mkdir(exist_ok=True)
    cases, cards, options = manifest['buildings'], [], []
    for i, case in enumerate(cases):
        label = str(case['address'])
        anchor = escape(case['id'], quote=True)
        options.append(f'<option value="{anchor}">{escape(label)}</option>')
        figures = []
        for mode, title, folder in [('before', 'Původní mapa', background),
                                    ('after', 'Nová geometrie', output / 'after'),
                                    ('diagnostic', 'Výpočetní jistota', output / 'diagnostic')]:
            if case['crop'] and (mode == 'before' or manifest['status'] == 'rendered'):
                filename = f'{i:03d}-{mode}.png'
                crop_tiles(folder, case['crop'], manifest['tile_grid']['tile']).save(crops / filename)
                figures.append(f'<figure><a href="crops/{filename}" target="_blank"><img '
                    f'loading="lazy" src="crops/{filename}" alt="{escape(title + ": " + label, quote=True)}"></a>'
                    f'<figcaption>{title}</figcaption></figure>')
            else:
                figures.append(f'<figure class="pending"><p>{title}</p><p>Render není připraven.</p></figure>')
        note = ('; '.join(case['errors']) if case['errors'] else
                ' · '.join(f"{p['type']}: {STATUS_NAMES[p['status']]}" for p in case['parts']))
        cards.append(f'<article id="{anchor}"><h2>{escape(label)}</h2><p>{escape(case["name"])} '
            f'· <a href="../report.html#{anchor}">Otevřít 3D model</a></p>'
            f'<div class="views">{"".join(figures)}</div><p>{escape(note)}</p>'
            f'<details><summary>Číselná diagnostika a původ barev</summary><pre>'
            f'{escape(json.dumps(case, ensure_ascii=False, indent=2))}</pre></details></article>')
    legend = ''.join(f'<span><i style="background:rgb{tuple(color)}"></i>{STATUS_NAMES[state]}</span>'
                     for state, color in STATUS_COLORS.items())
    page = '''<!doctype html><html lang="cs"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Roof v2 · zákres do izomapy</title><style>
*{box-sizing:border-box}body{margin:0;background:#f0eee7;color:#303630;font:16px/1.5 system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:28px}h1{font-size:2.25rem;line-height:1.1}h2{margin:0;font-size:1.3rem}
article{padding:20px;margin:24px 0;background:#fffefa;border:1px solid #d9d7ce;border-radius:10px;scroll-margin-top:20px}
.views{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}figure{margin:0;background:#1b2333;border-radius:5px;overflow:hidden}
img{display:block;width:100%;image-rendering:pixelated}figcaption{padding:7px;color:#fffefa;font-size:.9rem}
.pending{padding:20px;color:#e7e5d9;min-height:180px}.legend{display:flex;gap:18px;flex-wrap:wrap}.legend i{display:inline-block;width:16px;height:16px;vertical-align:middle;margin-right:6px;border-radius:3px}
select{font:inherit;padding:8px;max-width:100%}pre{font-size:.8rem;overflow:auto;max-height:360px;background:#efeee8;padding:16px}
summary,a{color:#34634b}footer{font-size:.85rem;color:#62695f}@media(max-width:850px){.views{grid-template-columns:1fr}main{padding:14px}}
</style><main><h1>Roof v2 · náhled v izomapě</h1>
<p>Stejná poloha, měřítko a letní podklad. Nové střechy a stěny jsou skutečnou geometrií rendereru, včetně zakrytí okolními objekty. Barvy třetího sloupce vyjadřují pouze diagnostiku algoritmu, nikoli ověřenou pravděpodobnost správnosti. Optické hodnocení zůstává na uživateli.</p>
<p>Zelená: bez prahového varování při automatických kontrolách. Oranžová: výpočet vyžaduje kontrolu. Červená: náhradní geometrie při nedostatečných datech. Šedá: stav neuveden. Žádná z barev neznamená vizuálně potvrzenou správnost.</p>
<p>Jde o izolovaný náhled dotčených dlaždic. Produkční mapa se nemění. Kliknutí otevře plné rozlišení výřezu; sousední domy zůstávají v původní podobě.</p>
<p>Stav: __STATUS__ · <a href="manifest.json">technický manifest</a></p>
__RESOLUTION__
<div class="legend">__LEGEND__</div><p><label>Adresa <select id="addresses"><option value="">Vyberte dům</option>__OPTIONS__</select></label></p>
__CARDS__<footer>Podklad © přispěvatelé OpenStreetMap, Overture Maps, ČÚZK. Pouze lokální výpočet a render. Výstup neslouží jako vizuálně ověřený model města.</footer>
</main><script>document.querySelector('#addresses').addEventListener('change',e=>{if(e.target.value){location.hash=e.target.value;document.getElementById(e.target.value).scrollIntoView();}});</script></html>'''
    resolution = manifest.get('preview_resolution', {})
    textures = resolution.get('textures', {})
    notes = []
    for name, entry in textures.items():
        notes.append(f"{name}: {'×'.join(map(str,entry['original_size']))} → {'×'.join(map(str,entry['preview_size']))} px")
    resolution_note = ('<p><strong>Úsporný náhled:</strong> předchozí mapa používá původní plné rozlišení podkladu. '
        'Nový a diagnostický render používají samostatně zmenšené kopie textur: '
        + escape('; '.join(notes)) + f". Stínová mapa: {int(resolution.get('shadow_size',8192))}×{int(resolution.get('shadow_size',8192))} px. "
        'Kamera a měřítko odpovídají původním dlaždicím. Nová geometrie střech se přebírá beze změny z výsledků výpočtu; '
        'snížené rozlišení mění pouze jemnost podkladu a stínů.</p>') if textures else ''
    estimates = resolution.get('estimated_allocations', {})
    if estimates:
        resolution_note += (f"<p>Odhad dat RGBA textur: {estimates['texture_rgba_bytes']/1e6:.1f} MB; "
                            f"barvový a hloubkový buffer stínů: {estimates['shadow_color_depth_bytes']/1e6:.1f} MB. "
                            'Nejde o špičkovou spotřebu RAM; geometrie, prohlížeč a pracovní kopie se přičítají.</p>')
    page = (page.replace('__STATUS__', escape(manifest['status']))
            .replace('__RESOLUTION__', resolution_note)
            .replace('__LEGEND__', legend).replace('__OPTIONS__', ''.join(options))
            .replace('__CARDS__', ''.join(cards)))
    (output / 'report.html').write_text(page, encoding='utf-8')
    (output / 'index.html').write_text('<!doctype html><meta http-equiv="refresh" content="0;url=report.html"><a href="report.html">Náhled střech</a>', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', default=DEFAULT_OUTPUT, type=Path)
    parser.add_argument('--work', default=DEFAULT_WORK, type=Path)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--browser', type=Path)
    parser.add_argument('--software-gpu', action='store_true', help='Explicit local SwiftShader fallback')
    parser.add_argument('--texture-max-size', type=int, default=4000,
                        help='Maximum preview texture dimension; 0 retains original resolution')
    parser.add_argument('--shadow-size', type=int, choices=(1024,2048,4096,8192), default=4096)
    parser.add_argument('--min-free-ram-gb', type=float, default=2.)
    parser.add_argument('--max-ram-gb', type=float, default=4.)
    parser.add_argument('--wait-memory-seconds', type=float, default=0.)
    args = parser.parse_args()
    if args.texture_max_size != 0 and args.texture_max_size < 256:
        parser.error('--texture-max-size must be 0 or at least 256')
    work, output = args.work.resolve(), args.output.resolve()
    if output.is_relative_to(work) or work.is_relative_to(output):
        parser.error('Output must be separate from the current map directory.')
    if not output.is_relative_to(ROOT / 'cities/ceske-budejovice/experiments'):
        parser.error('Output must stay in cities/ceske-budejovice/experiments.')
    from resource_guard import check_budget, run_guarded, keep_awake
    started = time.perf_counter()
    with keep_awake():
        check_budget(100_000_000, force=True)
        background = work / 'build/tiles_summer'
        info = read_json(background / 'info.json')
        scene = read_json(work / 'build/scene.json')
        source = read_json(work / 'build/info_src.json')
        original_paths = [work / 'build/scene.json', work / 'build/info_src.json',
                          background / 'info.json', work / 'render.html',
                          work / 'build/ground_summer.png', work / 'build/lightmap.png']
        original_hashes = {str(p): digest(p) for p in original_paths}
        cases, replacements = prepare(read_json(args.input), scene, source, info, Projection(work, info))
        wanted = sorted({tile for c in cases if c['crop'] for tile in tile_indices(c['crop'], info['tile'])})
        # Hash only the baseline tiles we touch; they are never written.
        for i, j in wanted:
            path = background / f'{i}_{j}.png'
            original_hashes[str(path)] = digest(path)
        output.mkdir(parents=True, exist_ok=True)
        staging = output / 'prepared'
        staging.mkdir(exist_ok=True)
        textures = {name: texture_preview(work / 'build' / name, staging / 'textures' / name,
                                         args.texture_max_size)
                    for name in ('ground_summer.png', 'lightmap.png')}
        html = patch_renderer((work / 'render.html').read_text(encoding='utf-8'), info, args.shadow_size)
        (staging / 'render.html').write_text(html, encoding='utf-8')
        scene_out = dict(scene, roofV2=replacements)
        (staging / 'scene.json').write_text(json.dumps(scene_out, separators=(',', ':'), allow_nan=False), encoding='utf-8')
        config = {'root': str(ROOT), 'work': str(work), 'output': str(output),
                  'staging': str(staging), 'info': info, 'tiles': wanted,
                  'browser': str(args.browser) if args.browser else None,
                  'software_gpu': args.software_gpu,
                  'texture_paths': {name: entry['path'] for name, entry in textures.items()},
                  'preview_resolution': {'textures': textures, 'shadow_size': args.shadow_size},
                  'baseline_pixel_qa': {f'{i}_{j}': tile_pixel_metrics(background / f'{i}_{j}.png') for i,j in wanted},
                  'expected': {'scene_ids': sorted(map(int, replacements)),
                    'mesh_parts': sum(len(v) for v in replacements.values()),
                    'roof_triangles': sum(len(m['roof_faces']) for v in replacements.values() for m in v),
                    'wall_triangles': sum(len(m['wall_faces']) for v in replacements.values() for m in v)}}
        config['preview_resolution']['estimated_allocations'] = preview_allocation_estimate(textures, args.shadow_size, info['tile'])
        write_json(staging / 'config.json', config)
        manifest = {'schema': 'roof-v2-tiles/1', 'status': 'prepared', 'season': 'summer',
                    'input': str(args.input.resolve()), 'input_sha256': digest(args.input),
                    'tile_grid': info, 'tiles': wanted, 'buildings': cases,
                    'original_sha256': original_hashes, 'replaced_scene_ids': config['expected']['scene_ids'],
                    'render_expected': config['expected'], 'palette': {'roofs': ROOFS, 'walls': WALLS},
                    'prepare_seconds': time.perf_counter() - started}
        manifest['preview_resolution'] = config['preview_resolution']
        write_json(output / 'manifest.json', manifest)
        write_json(output / 'color-audit.json', {
            'schema': 'roof-v2-colors/1', 'input_path': str(args.input.resolve()),
            'input_sha256': manifest['input_sha256'],
            'scene_path': str(work / 'build/scene.json'),
            'scene_sha256': original_hashes[str(work / 'build/scene.json')],
            'info_source_path': str(work / 'build/info_src.json'),
            'policy': 'New roofs/facades use only the explicit muted palettes. '
                      'The reference is the current scene color after data/overrides; '
                      'raw input attributes and provenance are retained separately.',
            'palettes': manifest['palette'],
            'buildings': [{'id': c['id'], 'address': c['address'], 'renderable': c['renderable'],
                'raw_source_attributes': c['source_attributes'], 'source': c['source'],
                'footprint_sources': c['footprint_sources'], 'source_files': c['source_files'],
                'scene_colors': c['scene_colors'], 'parts': [{k: p[k] for k in (
                    'index', 'color_reference_scene_id', 'color_reference', 'source_colors',
                    'render_colors')} for p in c['parts']]} for c in cases]})
        error = None
        if args.render and wanted and replacements:
            try:
                command = [shutil.which('node') or 'node', ROOT / 'scripts/roof_v2_tiles_driver.mjs', staging / 'config.json']
                manifest['resources'] = run_guarded(command, ROOT, output / 'render.log',
                    min_available_gb=args.min_free_ram_gb, max_ram_gb=args.max_ram_gb,
                    wait_memory_seconds=args.wait_memory_seconds, reserve_bytes=100_000_000)
                manifest['render'] = read_json(output / 'render-metrics.json')
                if manifest['render'].get('status') != 'validated':
                    raise RuntimeError('Render did not pass GPU and pixel validation')
                manifest['status'] = 'rendered'
            except Exception as exc:
                error = exc
                manifest['status'] = 'render_failed'
                manifest['render_error'] = str(exc)
        if any(digest(Path(p)) != h for p, h in original_hashes.items()):
            raise RuntimeError('A read-only baseline file changed during this run; inspect concurrent jobs.')
        manifest['baseline_unchanged'] = True
        manifest['elapsed_seconds'] = time.perf_counter() - started
        write_json(output / 'manifest.json', manifest)
        write_report(output, manifest, background)
        check_budget(force=True)
        print(json.dumps({'report': str(output / 'report.html'), 'status': manifest['status'],
                          'renderable_buildings': sum(c['renderable'] for c in cases),
                          'total_buildings': len(cases), 'touched_tiles': len(wanted)}, ensure_ascii=False), flush=True)
        if error:
            raise error


if __name__ == '__main__':
    main()
