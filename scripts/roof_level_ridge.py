"""Small roof templates with one level ridge and level eaves.

The ridge is a segment or an L-shaped chain. Its endpoints may finish at a
gable or inside a hip. Footprint corners and ridge nodes define the surface;
planes are not fitted independently. Irregular sides may need two triangles.
Only cached local XYZ samples are used; no Roofer or image analysis.
"""
from __future__ import annotations
import os
for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_name] = '1'
import itertools
import time
import numpy as np
import shapely
from scipy.optimize import least_squares
from shapely.geometry import Polygon, LineString, Point, shape, mapping
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from roof_v2 import _cells, _lines
from roof_v2_geometry import build_mesh

VERSION = 'level-ridge-1.0'


def _cross2(a, b):
    return a[..., 0]*b[..., 1]-a[..., 1]*b[..., 0]


def _triangulate(ring, xy, high):
    """Minimum-cost polygon triangulation, forbidding a flat ridge plateau."""
    polygon = Polygon(xy[ring])
    if not polygon.is_valid or polygon.area < .01:
        return None
    n = len(ring)
    costs = np.full((n, n), np.inf)
    splits = {}
    for i in range(n-1):
        costs[i, i+1] = 0
    padded = polygon.buffer(1e-7)
    for width in range(2, n):
        for i in range(n-width):
            j = i+width
            for k in range(i+1, j):
                ids = [ring[i], ring[k], ring[j]]
                triangle = Polygon(xy[ids])
                if triangle.area < 1e-7 or not padded.covers(triangle):
                    continue
                count = sum(high[ids])
                if count == 3:
                    continue
                # Prefer roof faces connecting eaves to ridge; avoid flat ears.
                penalty = (20*triangle.area if count == 0 else 0)
                penalty += .01*triangle.length**2/triangle.area
                value = costs[i, k]+costs[k, j]+penalty
                if value < costs[i, j]:
                    costs[i, j] = value
                    splits[i, j] = k
    if not np.isfinite(costs[0, n-1]):
        return None
    def collect(i, j):
        if j <= i+1:
            return []
        k = splits[i, j]
        return [[ring[i], ring[k], ring[j]]]+collect(i, k)+collect(k, j)
    return collect(0, n-1)


def _template(vertices, edge_a, edge_b, bent, hips, points):
    """Fixed topology; XY of ridge and its boundary endpoints are fitted."""
    n = len(vertices)
    aa, ab = vertices[edge_a], vertices[(edge_a+1) % n]
    ba, bb = vertices[edge_b], vertices[(edge_b+1) % n]
    da, db = ab-aa, bb-ba
    normal_a = np.array([-da[1], da[0]])/np.linalg.norm(da)
    normal_b = np.array([-db[1], db[0]])/np.linalg.norm(db)
    s, t = (aa+ab)/2, (ba+bb)/2
    poly = Polygon(vertices)
    if bent:
        matrix = np.c_[normal_a, -normal_b]
        if abs(np.linalg.det(matrix)) < .5:
            return None
        along = np.linalg.solve(matrix, t-s)
        bend = s+normal_a*along[0]
        if min(along) < 1 or not poly.contains(Point(bend)):
            return None
        path = LineString([s, bend, t])
    else:
        if abs(np.dot(normal_a, normal_b)) < .90:
            return None
        bend = None
        path = LineString([s, t])
    if path.length < 5 or not poly.buffer(1e-7).covers(path):
        return None

    # Boundary endpoints S/T can move only on their original footprint edges.
    initial = [.5, .5]
    low, upper = [.08, .08], [.92, .92]
    if bent:
        initial += bend.tolist()
        lo, hi = vertices.min(axis=0), vertices.max(axis=0)
        low += lo.tolist(); upper += hi.tolist()
    for hip in hips:
        if hip:
            initial += [.23]; low += [.06]; upper += [.44]
    geom_count = len(initial)
    z10, z90 = np.quantile(points[:, 2], [.1, .9])
    initial += [max(1., z10-1), max(1., z90-z10+1.5)]
    low += [.5, .4]; upper += [max(2., z90), max(4., np.ptp(points[:, 2])+4)]
    high = np.zeros(n+2+sum(hips)+(1 if bent else 0), dtype=bool)
    s_id, t_id = n, n+1
    ridge_ids = []
    next_id = n+2
    for end, hip in zip((s_id, t_id), hips):
        if hip:
            ridge_ids.append(next_id); next_id += 1
        else:
            ridge_ids.append(end)
    if bent:
        ridge_ids.insert(1, next_id)
    high[ridge_ids] = True

    def nodes(p):
        s = aa+p[0]*da; t = ba+p[1]*db
        middle = p[2:4] if bent else None
        q = list(vertices)+[s, t]
        index = 4 if bent else 2
        for endpoint, target, hip in zip((s, t), (middle if bent else t, middle if bent else s), hips):
            if hip:
                q.append(endpoint+p[index]*(target-endpoint)); index += 1
        if bent:
            q.append(middle)
        return np.asarray(q)

    p0 = np.asarray(initial)
    xy0 = nodes(p0)
    boundary = []
    for i in range(n):
        boundary.append(i)
        if i == edge_a: boundary.append(s_id)
        if i == edge_b: boundary.append(t_id)
    start, end = boundary.index(s_id), boundary.index(t_id)
    cycle = boundary[start:]+boundary[:start]
    end = cycle.index(t_id)
    cut = [s_id]+[i for i in ridge_ids if i not in (s_id, t_id)]+[t_id]
    side_a = cycle[:end+1]+list(reversed(cut[1:-1]))
    side_b = cycle[end:]+[cycle[0]]+cut[1:-1]
    faces_a = _triangulate(side_a, xy0, high)
    faces_b = _triangulate(side_b, xy0, high)
    if faces_a is None or faces_b is None:
        return None
    faces = np.asarray(faces_a+faces_b, dtype=int)
    triangles = xy0[faces]
    cross0 = _cross2(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    signs = np.sign(cross0)

    def prediction(p, return_geometry=False):
        xy = nodes(p); q = xy[faces]
        heights = p[-2]+high*p[-1]
        A = q[:, 0]; U = q[:, 1]-A; V = q[:, 2]-A
        det = _cross2(U, V)
        safe = np.where(abs(det) < 1e-9, 1e-9, det)
        delta = points[:, None, :2]-A
        beta = (delta[:, :, 0]*V[:, 1]-delta[:, :, 1]*V[:, 0])/safe
        gamma = (U[:, 0]*delta[:, :, 1]-U[:, 1]*delta[:, :, 0])/safe
        inside = (beta >= -1e-8) & (gamma >= -1e-8) & (beta+gamma <= 1+1e-8)
        z = heights[faces]
        values = z[:, 0]+beta*(z[:, 1]-z[:, 0])+gamma*(z[:, 2]-z[:, 0])
        # An invalid fold cannot gain from omitting inconvenient points.
        nearest = np.argmax(np.minimum(np.minimum(beta, gamma), 1-beta-gamma), axis=1)
        owner = np.where(inside.any(axis=1), inside.argmax(axis=1), nearest)
        pred = values[np.arange(len(points)), owner]
        fold = np.minimum(det*signs-.001, 0)*20
        if return_geometry:
            return xy, heights, det*signs, pred
        return np.r_[pred-points[:, 2], fold]

    return dict(initial=p0, bounds=(low, upper), nodes=nodes, predict=prediction,
                faces=faces, high=high, ridge_ids=ridge_ids, boundary=boundary,
                bent=bent, hips=hips, geom_count=geom_count,
                end_edges=[edge_a, edge_b])


def infer_level_roof(footprint, xyz, max_candidates=10):
    started = time.perf_counter()
    poly = orient(shape(footprint) if isinstance(footprint, dict) else footprint, sign=1)
    vertices = np.asarray(poly.exterior.coords)[:-1]
    points = np.asarray(xyz, float)
    points = points[np.isfinite(points).all(axis=1)]
    points = points[shapely.intersects_xy(poly, points[:, 0], points[:, 1])]
    cells = _cells(points, .7)
    if len(cells) < 20:
        raise ValueError('Too few cached roof points')
    # Long edges propose gable/hip ends. Small footprint notches are preserved
    # in the mesh, but do not create separate roof ridges.
    lengths = np.linalg.norm(np.roll(vertices, -1, axis=0)-vertices, axis=1)
    edges = np.flatnonzero(lengths >= max(3., .15*lengths.max()))
    proposals = []
    for a, b in itertools.combinations(edges, 2):
        for bent in (False, True):
            for hips in itertools.product((False, True), repeat=2):
                template = _template(vertices, int(a), int(b), bent, hips, cells)
                if template is None:
                    continue
                residual = template['predict'](template['initial'])[:len(cells)]
                rank = np.mean(np.minimum(abs(residual), 2.))+.07*bent
                proposals.append((float(rank), template))
    if not proposals:
        raise ValueError('No simple connected ridge fits the footprint topology')
    # Keep both straight and bent hypotheses, then fit only this small shortlist.
    shortlist = []
    for bent in (False, True):
        shortlist.extend(sorted((p for p in proposals if p[1]['bent'] == bent), key=lambda p:p[0])[:max_candidates//2])
    fitted = []
    for _, template in shortlist:
        fit = least_squares(template['predict'], template['initial'], bounds=template['bounds'],
                            loss='soft_l1', f_scale=.3, max_nfev=55,
                            ftol=3e-4, xtol=3e-4, gtol=3e-4)
        xy, heights, areas, pred = template['predict'](fit.x, True)
        if np.min(areas) <= 1e-6:
            continue
        absolute = abs(pred-cells[:, 2])
        score = .6*np.mean(np.minimum(absolute, 1.5))+.4*np.quantile(absolute, .8)
        score += .06*template['bent']+.012*sum(template['hips'])
        fitted.append((float(score), template, fit.x, xy, heights))
    if not fitted:
        raise ValueError('Constrained templates folded; original model is retained')
    _, chosen, parameters, xy, heights = min(fitted, key=lambda p:p[0])
    regions = []
    for ids in chosen['faces']:
        triangle = Polygon(xy[ids])
        clipped = triangle.intersection(poly)
        if clipped.is_empty or clipped.area < 1e-7:
            continue
        plane = np.linalg.solve(np.c_[xy[ids], np.ones(3)], heights[ids])
        components = list(clipped.geoms) if hasattr(clipped, 'geoms') else [clipped]
        for component in components:
            if component.geom_type == 'Polygon' and component.area > 1e-7:
                regions.append({'polygon': mapping(component), 'plane': plane.tolist()})
    # Coplanar triangles are a single architectural plane, not extra roof edges.
    merged = []
    for region in regions:
        found = next((r for r in merged if np.max(abs(np.asarray(r['plane'])-region['plane'])) < 1e-6), None)
        if found is None:
            merged.append({'plane': region['plane'], 'polygons': [shape(region['polygon'])]})
        else:
            found['polygons'].append(shape(region['polygon']))
    regions = []
    for group in merged:
        union = unary_union(group['polygons'])
        for piece in (list(union.geoms) if hasattr(union, 'geoms') else [union]):
            if piece.geom_type == 'Polygon':
                regions.append({'polygon': mapping(piece), 'plane': group['plane']})
    mesh = build_mesh(poly, regions)
    if not mesh['diagnostics']['valid']:
        raise ValueError('Cannot close the constrained roof volume')
    model = {'type': 'compound' if chosen['bent'] else ('hipped' if any(chosen['hips']) else 'gabled'),
             'regions': regions, 'mesh': mesh,
             'height_range_m': [float(min(heights)), float(max(heights))]}
    _, eaves, boundary = _lines(model, poly)
    ridge = [[float(xy[i, 0]), float(xy[i, 1]), float(heights[i])] for i in chosen['ridge_ids']]
    model.update(ridge_lines=[ridge], eave_lines=eaves, roof_boundary_lines=boundary,
                 metadata={'ridge_height_m': float(parameters[-2]+parameters[-1]),
                           'eave_height_m': float(parameters[-2]),
                           'ridge_kind': 'bent' if chosen['bent'] else 'straight',
                           'end_types': ['hip' if hip else 'gable' for hip in chosen['hips']],
                           'requested_level_merge_tolerance_m': .5,
                           'automatic_multi_level_detection': False,
                           'level_scope': 'One connected main roof; separate-height wings require a separate part.',
                           'courtyard_policy': 'Clip roof planes to the original hole, without inventing a lowered courtyard roof.'})
    return {'algorithm': VERSION, 'model': model, 'candidates': [],
            'diagnostics': {'status': 'Varianta k optickému posouzení', 'review_required': True,
                            'flags': [], 'train': {'n': len(points)},
                            'visual_assessment_performed': False,
                            'independent_validation_performed': False},
            'timing': {'total_seconds': time.perf_counter()-started}}
