"""Deterministic diagnostic projections of saved models and measured samples.

No inference or image generation service. The interactive HTML remains the
authoritative model viewer; these panels support bounded visual review rounds.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BG = (246, 247, 244)


def font(size):
    for name in ('C:/Windows/Fonts/segoeui.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def project(xyz, oblique=False):
    xyz = np.asarray(xyz, float)
    if xyz.shape[1] == 2:
        xyz = np.c_[xyz, np.zeros(len(xyz))]
    if not oblique:
        return xyz[:, :2] * [1, -1]
    theta = -.7
    u = xyz[:, 0]*math.cos(theta)-xyz[:, 1]*math.sin(theta)
    v = xyz[:, 0]*math.sin(theta)+xyz[:, 1]*math.cos(theta)
    return np.c_[u, -.55*v-.84*xyz[:, 2]]


def transform(points, rect):
    points = np.asarray(points)
    low, high = points.min(axis=0), points.max(axis=0)
    x, y, w, h = rect
    scale = min((w-40)/max(high[0]-low[0], 1), (h-35)/max(high[1]-low[1], 1))
    center = (low+high)/2
    return lambda p: (np.asarray(p)-center)*scale+[x+w/2, y+h/2], scale


def color_height(z, low, high):
    t = float(np.clip((z-low)/max(high-low, .01), 0, 1))
    stops = [(48, 91, 154), (64, 172, 164), (239, 209, 99), (202, 70, 55)]
    k = min(int(t*3), 2); a = t*3-k
    return tuple(int((1-a)*stops[k][j]+a*stops[k+1][j]) for j in range(3))


def draw_panel(image, building, reference, y):
    draw = ImageDraw.Draw(image)
    part = building['parts'][0]; result = part['result']; model = result['model']
    ref = reference.get(building['id'], building)['parts'][0]
    samples = np.asarray(ref.get('point_preview', []), float)
    poly = part['footprint']['coordinates']
    draw.text((18, y+8), building['address'], fill=(30, 47, 43), font=font(21))
    draw.text((430, y+12), 'měřené výšky                 model shora                       model 3D', fill=(54, 70, 66), font=font(16))
    topxy = project(poly[0]); pane_w = image.width//3
    low, high = np.quantile(samples[:, 2], [.05, .95]) if len(samples) else model['height_range_m']
    for column in range(2):
        rect = (column*pane_w, y+43, pane_w, 320)
        tf, scale = transform(topxy, rect)
        if column == 0 and len(samples):
            for p in samples:
                px, py = tf(project([p]))[0]
                radius = max(1, min(4, scale*.27))
                draw.rectangle((px-radius, py-radius, px+radius, py+radius), fill=color_height(p[2], low, high))
        if column == 1:
            for region in model['regions']:
                p = np.asarray(region['plane']); normal = np.r_[-p[:2], 1.]
                normal /= np.linalg.norm(normal)
                light = .72+.25*float(normal@np.array([-.35, -.45, .82]))
                color = tuple(int(c*light) for c in (183, 130, 106))
                rings = region['polygon']['coordinates']
                draw.polygon([tuple(v) for v in tf(project(rings[0]))], fill=color)
                for hole in rings[1:]:
                    draw.polygon([tuple(v) for v in tf(project(hole))], fill=BG)
                for ring in rings:
                    draw.line([tuple(v) for v in tf(project(ring))], fill=(88, 76, 66), width=1)
            for line in model.get('ridge_lines', []):
                draw.line([tuple(v) for v in tf(project(line))], fill=(37, 156, 77), width=3)
        for ring in poly:
            draw.line([tuple(v) for v in tf(project(ring))], fill=(35, 43, 44), width=2)
        draw.text((column*pane_w+18, y+365), f'Výšky P05–P95: {low:.1f}–{high:.1f} m' if column == 0 else str(model['metadata'].get('ridge_kind', model['type'])), fill=(65, 75, 70), font=font(14))

    mesh = model['mesh']; verts = np.asarray(mesh['vertices']); proj = project(verts, True)
    tf, _ = transform(proj, (pane_w*2, y+43, pane_w, 320))
    theta = -.7; direction = np.array([-math.sin(theta)*.84, -math.cos(theta)*.84, .55])
    faces = [(f, True) for f in mesh['roof_faces']]+[(f, False) for f in mesh['wall_faces']]
    for face, roof in sorted(faces, key=lambda f:float(verts[f[0]].mean(axis=0)@direction)):
        tri = verts[face]; normal = np.cross(tri[1]-tri[0], tri[2]-tri[0])
        normal /= max(np.linalg.norm(normal), 1e-12)
        light = .76+.22*float(normal@np.array([-.35, -.45, .82]))
        color = tuple(int(c*light) for c in ((183, 130, 106) if roof else (205, 204, 184)))
        draw.polygon([tuple(v) for v in tf(proj[face])], fill=color)
    draw.text((2*pane_w+18, y+365), f"Skóre {result.get('diagnostics',{}).get('selection_score',0):.3f}; rovin {model['metadata'].get('nominal_roof_plane_count',len(model['regions']))}", fill=(65,75,70), font=font(14))
    draw.line((15, y+395, image.width-15, y+395), fill=(213, 219, 211))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--id', action='append')
    args = parser.parse_args()
    data = json.loads(args.results.read_text(encoding='utf8'))
    reference = json.loads((args.reference or args.results).read_text(encoding='utf8'))
    selected = [b for b in data['buildings'] if not args.id or b['id'] in args.id]
    byid = {b['id']:b for b in reference['buildings']}
    image = Image.new('RGB', (1500, 400*len(selected)), BG)
    for i, building in enumerate(selected):
        draw_panel(image, building, byid, i*400)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output)
    print(json.dumps({'output':str(args.output), 'buildings':len(selected)}))


if __name__ == '__main__':
    main()
