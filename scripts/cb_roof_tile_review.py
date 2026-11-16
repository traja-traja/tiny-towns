"""Render building details against the existing České Budějovice summer tiles."""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
from html import escape
from io import BytesIO
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work/.preview/ceske-budejovice'
DEFAULT_OUTPUT = ROOT / '.work/cb-roof-inference/map-detail'
TO_WGS84 = Transformer.from_crs(5514, 4326, always_xy=True)
ROOF_NAMES = {'flat': 'plochá', 'shed': 'pultová', 'gabled': 'sedlová',
              'hipped': 'valbová', 'pyramidal': 'stanová', 'pyramid': 'stanová',
              'barrel': 'oblouková', 'mansard': 'mansardová', 'half-hipped': 'polovalbová',
              'compound': 'složená', 'butterfly': 'motýlková', 'multi_flat': 'plochá ve více úrovních',
              'sawtooth': 'pilová'}
STATE_NAMES = {'ok': 'Vypočteno', 'supported': 'Podpořeno výškovými body',
               'review': 'Ke kontrole', 'needs_review': 'Ke kontrole',
               'ambiguous': 'Nejednoznačné', 'no_points': 'Chybí body',
               'unmatched': 'Adresa bez půdorysu', 'insufficient_data': 'Málo bodů',
               'partial': 'Zpracováno částečně'}
REASONS = {'few_fit_cells': 'málo nezávisle pokrytých buněk',
           'low_spatial_coverage': 'slabé pokrytí půdorysu body',
           'low_surface_inlier_fraction': 'málo bodů leží blízko modelu',
           'large_tail_residuals': '90. percentil odstupu od modelu přesahuje 2,5 m',
           'small_gap_between_roof_types': 'podobné skóre více tvarů',
           'compound_split_requires_review': 'rozdělení na díly vyžaduje kontrolu'}


# These two insertions are only applied to the HTML served to this browser.
# The three.js renderer, source scene and existing map tiles are read-only.
MESH_INSERT = r'''    const models = scene.reviewMeshes?.[b.id];
    if (models) {
      for (const m of models) {
        const vertices = m.vertices.map(([x, y, z]) => tv(x, y, z));
        for (const [i, j, k] of m.roof_faces) pushTri(R, vertices[i], vertices[j], vertices[k], C255(b.rc), [0, 0, 0, 0]);
        for (const ids of m.wall_faces) {
          const xyz = ids.map(i => m.vertices[i]);
          const edges = xyz.map((a, i) => [xyz[(i + 1) % 3][0] - a[0], xyz[(i + 1) % 3][1] - a[1]]);
          const [dx, dy] = edges.sort((a, b) => Math.hypot(...b) - Math.hypot(...a))[0];
          const norm = Math.hypot(dx, dy) || 1;
          const sign = dx < -1e-6 || (Math.abs(dx) <= 1e-6 && dy < 0) ? -1 : 1;
          const along = xyz.map(p => sign * (p[0] * dx + p[1] * dy) / norm);
          const start = Math.min(...along), span = Math.max(...along) - start;
          const [a, c, d] = ids.map(i => vertices[i]);
          const uv = xyz.map((p, i) => [along[i] - start, p[2] - b.g, span, b.s]);
          pushTri(W, a, c, d, C255(b.wc), uv);
        }
      }
      continue;
    }
'''

RENDER_DRIVER = r'''
import fs from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';

const options = JSON.parse(await fs.readFile(process.argv[1], 'utf8'));
const {work, output, info, tiles} = options;
const browser = await chromium.launch({args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  const origin = 'http://roof-review.local';
  const files = new Map([
    ['/render.html', output + '/render.html'],
    ['/build/scene.json', output + '/scene.json'],
    ['/build/ground_summer.png', work + '/build/ground_summer.png'],
    ['/build/lightmap.png', work + '/build/lightmap.png'],
    ['/assets/custom_models.js', work + '/assets/custom_models.js'],
    ...['three.module.js', 'three.core.js'].map(name => [
      '/node_modules/three/build/' + name,
      path.resolve('node_modules/three/build', name),
    ]),
  ]);
  const mime = {'.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png'};
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    const file = url.origin === origin && files.get(url.pathname);
    if (!file) return route.fulfill({status: 404});
    try { await route.fulfill({path: file, contentType: mime[path.extname(file)]}); }
    catch { await route.fulfill({status: 404}); }
  });
  await page.goto(`${origin}/render.html?mpp=${info.mpp}&tile=${info.tile}&alpha=1&season=summer`);
  await page.waitForFunction(() => window.READY === true, null, {timeout: 120000});
  const frame = await page.evaluate(() => INFO);
  if (errors.length || ['x0', 'y1', 'width', 'height', 'mpp', 'tile'].some(key => Math.abs(frame[key] - info[key]) > 1e-7)) {
    throw new Error(`Detail renderer has a different tile grid or failed: ${JSON.stringify({frame, errors})}`);
  }
  for (const [i, j] of tiles) {
    const data = await page.evaluate(([x, y]) => window.renderTile(x, y), [i, j]);
    await fs.writeFile(`${output}/${i}_${j}.png`, Buffer.from(data.split(',')[1], 'base64'));
    console.log(`Vykreslená dlaždice ${i}_${j}`);
  }
} finally {
  await browser.close();
}
'''


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def make_projection(work, info):
    os.environ['IZO_MESTO'] = str(work / 'mesto.json')
    sys.path.insert(0, str(ROOT))
    import geo

    image = geo.Image2D(info)

    def points(xyz):
        xyz = np.asarray(xyz, dtype=float)
        lon, lat = TO_WGS84.transform(xyz[:, 0], xyz[:, 1])
        x, y = geo.to_local(lon, lat)
        return np.column_stack((x, y, xyz[:, 2] - geo.HREF))

    def project(local):
        return np.column_stack(image.px(*np.asarray(local, dtype=float).T))

    def address(lon, lat, height):
        x, y = geo.to_local(lon, lat)
        return np.array([[x, y, height]], dtype=float)

    return points, project, address


def fit_crop(points, width, height):
    x0, y0 = np.min(points[:, :2], axis=0)
    x1, y1 = np.max(points[:, :2], axis=0)
    w = min(width, math.ceil(max(352, x1 - x0 + 144)))
    h = min(height, math.ceil(max(256, y1 - y0 + 120)))
    left = min(max(0, round((x0 + x1 - w) / 2)), width - w)
    top = min(max(0, round((y0 + y1 - h) / 2)), height - h)
    return left, top, left + w, top + h


def prepare(document, scene, source, info, projection):
    to_local, project, address_point = projection
    by_oid = {entry['oid']: entry['id'] for entry in source['buildings'] if entry.get('oid')}
    by_id = {entry['id']: entry for entry in scene['buildings']}
    cases, uploaded = [], {}
    for building in document['buildings']:
        meshes, draw_points, rendered_groups = [], [], defaultdict(list)
        existing_types = []
        for original in building.get('models') or []:
            if not original.get('roof_faces') or not original.get('vertices'):
                continue
            sid = by_oid.get(original.get('scene_oid') or original.get('id') or building.get('id'))
            local = to_local(original['vertices'])
            vertices = project(local)
            ridge = [project(to_local(segment)).tolist() for segment in original.get('ridge') or []]
            apexes = [model['apex'] for model in (original, *(original.get('parts') or []))
                      if model.get('apex') is not None]
            for apex in apexes:
                ridge.append(project(to_local([apex])).tolist())
            eaves = [project(to_local(segment)).tolist() for segment in original.get('eaves') or []]
            valley_segments = original.get('valley') or original.get('valleys') or []
            valleys = [project(to_local(segment)).tolist() for segment in valley_segments]
            mesh = dict(original, scene_id=sid, pixels=vertices, ridge_pixels=ridge,
                        eave_pixels=eaves, valley_pixels=valleys)
            meshes.append(mesh)
            draw_points.extend(vertices)
            if sid in by_id:
                old = by_id[sid]
                existing_types.append(old['r'])
                roof_top = old['e'] + old['rh']
                draw_points.extend(project([[x, y, z] for x, y in old['p'] for z in (old['b'], roof_top)]))
                rendered_groups[sid].append({'vertices': local.tolist(), 'roof_faces': original['roof_faces'],
                                             'wall_faces': original.get('wall_faces', [])})
        if not draw_points and building.get('lon') is not None and building.get('lat') is not None:
            sid = by_oid.get(building.get('id'))
            old = by_id.get(sid, {})
            draw_points.extend(project(address_point(building['lon'], building['lat'], old.get('e', 8))))
        # The same scene building can serve multiple addresses. Upload the first
        # complete geometry and label a conflicting address as an overlay only.
        complete = bool(meshes) and all(m['scene_id'] in by_id for m in meshes)
        if complete:
            complete = all(uploaded.get(key, model) == model for key, model in rendered_groups.items())
        if complete:
            uploaded.update(rendered_groups)
        box = fit_crop(np.asarray(draw_points), info['width'], info['height']) if draw_points else None
        cases.append(dict(building, meshes=meshes, crop=box, renderable=complete,
                          existing_types=list(dict.fromkeys(existing_types))))
    return cases, uploaded


def tile_indices(box, size):
    left, top, right, bottom = box
    return [(x, y) for y in range(top // size, (bottom - 1) // size + 1)
            for x in range(left // size, (right - 1) // size + 1)]


def render_tiles(work, staging, scene, models, info, tiles):
    staging.mkdir(parents=True, exist_ok=True)
    html = (work / 'render.html').read_text(encoding='utf-8')
    original_loop = '    if (b.only) continue;'
    detail_loop = '    if (b.lm && CUSTOM.landmarks?.[b.lm]'
    extent = 'const IW = Math.ceil((X1 - X0) / MPP), IH = Math.ceil((Y1 - Y0) / MPP);'
    for marker in (original_loop, detail_loop, extent):
        if html.count(marker) != 1:
            raise ValueError(f'Změnil se vstup rendereru: {marker}')
    html = html.replace(original_loop, MESH_INSERT + original_loop)
    html = html.replace(detail_loop, '    if (scene.reviewMeshes?.[b.id]) continue;\n' + detail_loop)
    # Compare the same pixels even when the proposed geometry changes a scene's extent.
    html = html.replace(extent, f"GX0 = {info['x0']}; GY1 = {info['y1']}; X0 = GX0 - offV.x; Y1 = GY1 - offV.y;\n"
                       f"const IW = {info['width']}, IH = {info['height']};")
    (staging / 'render.html').write_text(html, encoding='utf-8')
    (staging / 'scene.json').write_text(json.dumps(dict(scene, reviewMeshes=models), separators=(',', ':')), encoding='utf-8')
    config = staging / 'tiles.json'
    config.write_text(json.dumps({'work': str(work), 'output': str(staging), 'info': info, 'tiles': tiles}), encoding='utf-8')
    env = os.environ.copy()
    browser_dir = ROOT / '.runtime/browsers'
    if browser_dir.is_dir():
        env.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(browser_dir))
    log = staging / 'render.log'
    with log.open('w', encoding='utf-8') as stream:
        subprocess.run(['node', '--input-type=module', '-e', RENDER_DRIVER, str(config)],
                       cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=240)


@lru_cache(maxsize=16)
def read_tile(path):
    with Image.open(path) as image:
        return image.convert('RGBA')


def crop_tiles(folder, box, size):
    left, top, right, bottom = box
    crop = Image.new('RGBA', (right - left, bottom - top), (27, 35, 51, 255))
    for i, j in tile_indices(box, size):
        tile = read_tile(folder / f'{i}_{j}.png')
        crop.alpha_composite(tile, dest=(i * size - left, j * size - top))
    return crop


def draw_overlay(before, case):
    transparent = Image.new('RGBA', before.size)
    draw = ImageDraw.Draw(transparent)
    left, top, _, _ = case['crop']
    triangles = []
    for model in case['meshes']:
        pixels = model['pixels']
        for face_key, color in (('roof_faces', (205, 134, 67, 210)), ('wall_faces', (245, 220, 172, 203))):
            for face in model.get(face_key) or []:
                vertices = pixels[face]
                triangles.append((float(vertices[:, 2].mean()), color, vertices[:, :2] - [left, top]))
    for _, color, xy in sorted(triangles, key=lambda face: face[0], reverse=True):
        draw.polygon([tuple(p) for p in xy], fill=color, outline=(95, 78, 54, 225))
    return Image.alpha_composite(before, transparent)


def roof_lines_svg(case, kind):
    left, top, right, bottom = case['crop']
    paths = []
    for model in case['meshes']:
        for segment in model[f'{kind}_pixels']:
            coords = ' '.join(f'{x-left:.2f},{y-top:.2f}' for x, y, _ in segment)
            if len(segment) == 1:
                x, y, _ = segment[0]
                paths.append(f'<circle cx="{x-left:.2f}" cy="{y-top:.2f}" r="3"/>')
            elif len(segment) > 1:
                paths.append(f'<polyline points="{coords}"/>')
    return f'<svg class="{kind}" viewBox="0 0 {right-left} {bottom-top}" aria-hidden="true">{"".join(paths)}</svg>'


def data_uri(image):
    stream = BytesIO()
    image.convert('RGB').save(stream, 'PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode('ascii')


def roof_type_label(model):
    kind = str(model.get('type') or '')
    label = ROOF_NAMES.get(kind, kind)
    parts = Counter(part['type'] for part in model.get('parts') or [] if part.get('type'))
    if parts:
        listed = ', '.join(f'{count}× {ROOF_NAMES.get(part, part)}' if count > 1 else ROOF_NAMES.get(part, part)
                           for part, count in parts.items())
        label += f' ({listed})'
    return label


def reasons_label(model):
    reasons = (model.get('diagnostics') or {}).get('reasons') or []
    return ', '.join(REASONS.get(reason, reason.replace('_', ' ')) for reason in reasons)


def card_html(case, before, after, mode, index):
    address = escape(case['address'])
    state = str(case.get('status') or '')
    kinds = ' · '.join(dict.fromkeys(roof_type_label(model) for model in case['meshes']))
    status = STATE_NAMES.get(state, state)
    heading = f'<h2>{address}</h2><p class="meta">{escape(" · ".join(text for text in (kinds, status) if text))}</p>'
    requested = case.get('requested_address')
    if requested and case['address'].casefold() != requested.casefold():
        heading += f'<p class="match">Zadaná adresa: {escape(requested)}</p>'
    figures = ''
    if before is not None:
        old = ' · '.join(ROOF_NAMES.get(kind, kind) for kind in case['existing_types'])
        caption = 'Původní mapa' + (f' · {old}' if old else '')
        figures = f'<figure><div><img loading="lazy" src="{data_uri(before)}" alt="Původní mapa – {address}"></div><figcaption>{escape(caption)}</figcaption></figure>'
    if after is not None:
        caption = 'Nová geometrie v dlaždici' if mode == 'rendered' else 'Průhledný překryv geometrie'
        lines = ''.join(roof_lines_svg(case, kind) for kind in ('ridge', 'eave', 'valley'))
        figures += f'<figure><div><img loading="lazy" src="{data_uri(after)}" alt="Nová geometrie – {address}">{lines}</div><figcaption>{caption}</figcaption></figure>'
    if after is None and before is not None:
        figures += '<p class="missing">Pro tuto adresu nevznikl model.</p>'
    if before is None:
        figures = '<p class="missing">Pro mapový výřez chybí souřadnice.</p>'
    details = []
    for model in case['meshes']:
        diagnostic = model.get('diagnostics') or {}
        if diagnostic:
            pretty = escape(json.dumps(diagnostic, indent=2, ensure_ascii=False))
            residual = diagnostic.get('residuals') or {}
            median = residual.get('median_abs_m')
            p90 = residual.get('p90_abs_m')
            summary = f'{roof_type_label(model)} · diagnostika'
            if median is not None and p90 is not None:
                summary += f' · medián |Δz| {median:.2f} m · P90 {p90:.2f} m'.replace('.', ',')
            reason = reasons_label(model)
            reason_html = f'<p class="reason">{escape(reason.capitalize())}.</p>' if reason else ''
            parts = []
            for part in model.get('parts') or []:
                state = part.get('status') or ''
                text = ' · '.join(filter(None, (roof_type_label(part), STATE_NAMES.get(state, state), reasons_label(part))))
                parts.append(f'<li>{escape(text)}</li>')
            parts_html = f'<ul class="parts">{"".join(parts)}</ul>' if parts else ''
            details.append(f'{reason_html}{parts_html}<details><summary>{escape(summary)}</summary><pre>{pretty}</pre></details>')
    return f'<article id="dum-{index}">{heading}<div class="images">{figures}</div>{"".join(details)}</article>'


PAGE = '''<!doctype html><html lang="cs"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Střechy v centru Českých Budějovic</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#efeee9;color:#262821;font:16px/1.45 system-ui,sans-serif}
main{max-width:960px;margin:auto;padding:2rem clamp(1rem,4vw,2.5rem)}h1{margin:0 0 .5rem;font-size:clamp(2rem,6vw,3.35rem);line-height:1.05;letter-spacing:-.045em}
h2{font-size:1.35rem;line-height:1.15;margin:0}.meta{margin:.3rem 0 .75rem;color:#54594d}.match{margin:-.35rem 0 .75rem;color:#54594d;font-size:.86rem}.controls{display:flex;flex-wrap:wrap;gap:.65rem 1.4rem;align-items:center;margin:1.3rem 0}
.reason,.parts{color:#54594d;font-size:.88rem;margin:.65rem 0 0}.parts{padding-left:1.2rem}
select{max-width:100%;padding:.35rem .5rem;font:inherit;color:inherit;background:white;border:1px solid #bbbead;border-radius:.3rem}
article{background:#faf9f5;border:1px solid #d9d8cf;border-radius:.6rem;padding:clamp(.75rem,2vw,1.2rem);margin:0 0 1.2rem;scroll-margin-top:1rem}
.images{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.8rem}figure{margin:0}figure>div{position:relative;background:#1b2333;border-radius:.25rem;overflow:hidden}
img{display:block;width:100%;image-rendering:pixelated}figcaption{color:#51584c;font-size:.86rem;margin-top:.25rem}.ridge,.eave,.valley{display:none;position:absolute;inset:0;width:100%;height:100%;fill:none;stroke-width:2.25;pointer-events:none;filter:drop-shadow(0 0 1px #282604)}
.ridge{stroke:#fded67}.eave{stroke:#9af3eb;stroke-dasharray:4 2}.valley{stroke:#f7a8db;stroke-dasharray:2 2}
.legend{display:inline-block;width:1rem;height:.2rem;vertical-align:middle;border-radius:1px;box-shadow:0 0 0 1px #575850;margin-left:.18rem}.legend-ridge{background:#fded67}.legend-eave{background:#9af3eb}.legend-valley{background:#f7a8db}
main:has(#ridge-toggle:checked) .ridge,main:has(#eave-toggle:checked) .eave,main:has(#valley-toggle:checked) .valley{display:block}.missing{color:#54594d}details{margin-top:.75rem}summary{cursor:pointer;color:#33594c}pre{overflow:auto;max-height:24rem;background:#efeee9;padding:.65rem;margin:.35rem 0;font-size:.82rem}
footer{color:#54594d;font-size:.85rem}a{color:#33594c}@media(max-width:550px){.images{grid-template-columns:1fr;gap:.55rem}}
</style><main><header><h1>Střechy v centru Českých Budějovic</h1>
<p>Detail z pilotního výřezu izomapy. Oba pohledy mají stejnou polohu a měřítko. Nové dlaždice zobrazují všechny zkoumané modely společně. Modely označené „Ke kontrole“ jsou pracovní odhady.</p>
__SOURCE____NOTE__
<div class="controls"><label>Najít adresu <select id="addresses"><option value="">Vyber adresu</option>__OPTIONS__</select></label>
__LINE_CONTROLS__</div></header>
__CARDS__
<footer>Podklad izomapy · © přispěvatelé OpenStreetMap, Overture Maps, ČÚZK. Střešní geometrie z výškových bodů ČÚZK.</footer></main>
<script>document.querySelector('#addresses').addEventListener('change', event => {
  const target = document.getElementById(event.target.value);
  if (target) { location.hash = target.id; target.scrollIntoView(); }
});</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', default=DEFAULT_OUTPUT, type=Path)
    parser.add_argument('--work', default=WORK, type=Path)
    parser.add_argument('--overlay-only', action='store_true', help='Use a labeled projected mesh overlay without launching Chromium.')
    args = parser.parse_args()
    output, work = args.output.resolve(), args.work.resolve()
    if output.is_relative_to(work):
        parser.error('Use a dedicated output directory outside the source map.')
    input_content = args.input.read_bytes()
    document = json.loads(input_content.decode('utf-8-sig'))
    if document.get('horizontal_crs') != 'EPSG:5514':
        parser.error('Expected EPSG:5514 building coordinates and absolute heights in meters.')
    height_source = (document.get('source') or {}).get('heights') or ''
    height_source = height_source.replace('DMP1G', 'DMP 1G').replace('DMPOK', 'DMP OK')
    background = work / 'build/tiles_summer'
    info = read(background / 'info.json')
    scene = read(work / 'build/scene.json')
    source = read(work / 'build/info_src.json')
    cases, models = prepare(document, scene, source, info, make_projection(work, info))
    size = info['tile']
    wanted = sorted({tile for case in cases if case['renderable'] and case['crop']
                     for tile in tile_indices(case['crop'], size)})
    staging = output / 'rendered-tiles'
    rendered, error = False, None
    output.mkdir(parents=True, exist_ok=True)
    if wanted and not args.overlay_only:
        try:
            render_tiles(work, staging, scene, models, info, wanted)
            rendered = True
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            error = str(exc)
            print(f'Nové dlaždice se nepodařilo vykreslit: {error}', file=sys.stderr)

    cards, entries, options = [], [], []
    for index, case in enumerate(cases, 1):
        before = crop_tiles(background, case['crop'], size) if case['crop'] else None
        after, mode = None, 'no-model'
        if before is not None and case['meshes']:
            if case['renderable'] and rendered:
                after, mode = crop_tiles(staging, case['crop'], size), 'rendered'
            else:
                after, mode = draw_overlay(before, case), 'overlay'
        cards.append(card_html(case, before, after, mode, index))
        options.append(f'<option value="dum-{index}">{escape(case["address"])}</option>')
        entries.append({'address': case['address'], 'mode': mode, 'crop_px': case['crop'],
                        'matched_scene_ids': [model['scene_id'] for model in case['meshes']]})
    note = ('<p>Průhledný překryv promítá navržené stěny a střechy na původní dlaždici. '
            'Sousední budovy při překryvu nezakrývají navrženou geometrii.</p>'
            if any(entry['mode'] == 'overlay' for entry in entries) else '')
    line_controls = []
    for kind, name in (('ridge', 'Hřebeny a vrcholy'), ('eave', 'Okapové hrany'), ('valley', 'Úžlabí')):
        if any(mesh[f'{kind}_pixels'] for case in cases for mesh in case['meshes']):
            line_controls.append(f'<label><input id="{kind}-toggle" type="checkbox"> {name} '
                                 f'<span class="legend legend-{kind}" aria-hidden="true"></span></label>')
    report = output / 'index.html'
    source_note = f'<p>Výškový podklad · {escape(height_source)}</p>' if height_source else ''
    page = (PAGE.replace('__SOURCE__', source_note).replace('__NOTE__', note).replace('__OPTIONS__', ''.join(options))
            .replace('__CARDS__', ''.join(cards)).replace('__LINE_CONTROLS__', ''.join(line_controls)))
    report.write_text(page, encoding='utf-8')
    (output / 'map-detail.json').write_text(json.dumps({'season': 'summer', 'tile_grid': info,
        'height_source': height_source,
        'source_geometry_sha256': hashlib.sha256(input_content).hexdigest(),
        'rendered_tiles': wanted if rendered else [], 'render_error': error, 'buildings': entries},
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(report)


if __name__ == '__main__':
    main()
