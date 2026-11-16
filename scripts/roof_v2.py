"""Simple, evidence-gated roof inference; independent of roof_inference.py.

Input/output: local metric XY and heights above ground.  No Roofer, network,
images or learned models. Each candidate is a complete piecewise-planar roof.
The held-out set must be withheld by the caller, never passed to this fitter.
"""
from __future__ import annotations
import os
for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_key, '1')
import math
import time
import numpy as np
import shapely
from scipy.optimize import least_squares
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, Point, LineString, shape, mapping
from roof_v2_geometry import plane_regions, build_mesh

VERSION = '2.3.0'
DEFAULTS = dict(cell_m=.6, max_cells=5000, max_nfev=60,
                tolerance_m=.5, fallback_height=6., allow_compound=True)


def residual_stats(residual):
    r = np.asarray(residual, float)
    r = r[np.isfinite(r)]
    if not len(r):
        return {'n': 0}
    a = np.abs(r)
    result = {'n': len(r), 'median_signed_m': float(np.median(r)),
              'rmse_m': float(np.sqrt(np.mean(r*r))),
              'within_05_fraction': float(np.mean(a <= .5)),
              'above_1m_fraction': float(np.mean(r > 1)),
              'below_minus_1m_fraction': float(np.mean(r < -1))}
    result.update({f'p{p}_m': float(np.percentile(a, p)) for p in (50, 75, 90, 95, 99)})
    return result


def predict_regions(regions, xy):
    """Evaluate only the region containing a point; no cross-region envelope."""
    xy = np.asarray(xy, float)
    out = np.full(len(xy), np.nan)
    for r in regions:
        p = shape(r['polygon'])
        mask = shapely.intersects_xy(p, xy[:, 0], xy[:, 1])
        a, b, c = r['plane']
        out[mask] = xy[mask, 0]*a + xy[mask, 1]*b + c
    return out


def _cells(points, cell):
    ij = np.floor(points[:, :2]/cell).astype(np.int64)
    order = np.lexsort((points[:, 2], points[:, 1], points[:, 0], ij[:, 1], ij[:, 0]))
    ij, points = ij[order], points[order]
    bounds = np.r_[0, 1+np.flatnonzero(np.any(ij[1:] != ij[:-1], axis=1)), len(points)]
    return np.asarray([np.median(points[a:b], axis=0) for a, b in zip(bounds[:-1], bounds[1:])])


def _normals(points, cell):
    """Local height gradients + planarity, not normals of vertical facades."""
    n = len(points)
    if n < 12:
        return np.zeros((n, 2)), np.zeros(n, bool)
    d, ii = cKDTree(points[:, :2]).query(points[:, :2], k=min(16, n), workers=1)
    q = points[ii] - points[ii].mean(axis=1)[:, None, :]
    cov = np.einsum('nki,nkj->nij', q[:, :, :2], q[:, :, :2])
    cov[:, 0, 0] += 1e-8
    cov[:, 1, 1] += 1e-8
    rhs = np.einsum('nki,nk->ni', q[:, :, :2], q[:, :, 2])
    g = np.linalg.solve(cov, rhs[..., None])[..., 0]
    err = q[:, :, 2] - np.einsum('nki,ni->nk', q[:, :, :2], g)
    rough = np.median(np.abs(err), axis=1)
    trusted = (rough < .20) & (d[:, -1] < max(3.0, cell*4)) & (np.linalg.norm(g, axis=1) < 3)
    return g, trusted


def _axes(poly, gradients, trusted):
    proposals = []
    good = trusted & (np.linalg.norm(gradients, axis=1) > .15)
    if good.sum() >= 12:
        angles = (np.arctan2(gradients[good, 1], gradients[good, 0])-np.pi/2) % np.pi
        hist, bins = np.histogram(angles, bins=36, range=(0, np.pi))
        for i in np.argsort(-hist, kind='stable')[:4]:
            m = (angles >= bins[i]) & (angles <= bins[i+1])
            if m.any():
                proposals.append(float(np.median(angles[m])))
    ring = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)[:4]
    edges = np.roll(ring, -1, axis=0)-ring
    e = edges[np.argmax(np.linalg.norm(edges, axis=1))]
    theta = float(math.atan2(e[1], e[0]) % np.pi)
    proposals.extend([theta, (theta+np.pi/2) % np.pi])
    result = []
    for p in proposals:
        if all(abs((p-q+np.pi/2) % np.pi-np.pi/2) > np.deg2rad(13) for q in result):
            result.append(p)
        if len(result) == 3:
            break
    return result


def _robust_error(r):
    # Each cell contributes once; bounded positive chimneys don't dominate.
    a = np.abs(r[np.isfinite(r)])
    if not len(a):
        return 1e6
    return float(.60*np.mean(np.minimum(a, 1.5)) + .40*np.quantile(a, .8))


def _plane_fit(points):
    A = np.c_[points[:, :2], np.ones(len(points))]
    initial = np.linalg.lstsq(A, points[:, 2], rcond=None)[0]
    result = least_squares(lambda p: A@p-points[:, 2], initial,
                           loss='soft_l1', f_scale=.20, max_nfev=35)
    return result.x


def _candidate(kind, poly, points, planes=None, regions=None, penalty=0., params=None):
    if regions is None:
        regions = plane_regions(poly, planes)
    pred = predict_regions(regions, points[:, :2])
    error = _robust_error(points[:, 2]-pred)
    return {'type': kind, 'regions': regions, 'score': error+penalty,
            'fit_error_m': error, 'complexity_penalty_m': penalty,
            'evidence_penalty_m': 0.,
            'stats': residual_stats(points[:, 2]-pred), 'parameters': params or {},
            'rejected': [], 'warnings': [], '_pred': pred}


def _pitched(poly, points, theta, kind, config):
    u = np.array([math.cos(theta), math.sin(theta)])
    v = np.array([-u[1], u[0]])
    verts = shapely.get_coordinates(poly)
    U, V = verts@u, verts@v
    u0, u1, v0, v1 = U.min(), U.max(), V.min(), V.max()
    length, width = u1-u0, v1-v0
    if min(length, width) < 2:
        return None
    xy, z = points[:, :2], points[:, 2]
    uv = np.c_[xy@u, xy@v]
    z10, z90 = np.quantile(z, [.1, .90])
    # Use robust upper slice locations for an initial ridge, never raw maxima.
    peaks = []
    for l, r in zip(np.linspace(u0, u1, 9)[:-1], np.linspace(u0, u1, 9)[1:]):
        selected = (uv[:, 0] >= l) & (uv[:, 0] < r)
        if selected.sum() >= 8:
            top = selected & (z >= np.quantile(z[selected], .85))
            peaks.append(float(np.median(uv[top, 1])))
    peak_v = float(np.clip(np.median(peaks) if peaks else (v0+v1)/2, v0+.15*width, v1-.15*width))
    rise = max(.6, (z90-z10)*1.2)
    slope = np.clip(2*rise/width, .12, 2.)
    # theta is fitted locally; independent opposite slopes allow unequal eaves.
    initial = [theta, peak_v, z90+.2*rise, slope, slope]
    lower = [theta-.14, v0+.10*width, max(1., z10-1), .08, .08]
    upper = [theta+.14, v1-.10*width, max(z90+5, z10+2), 2.8, 2.8]
    if kind == 'hipped':
        initial += [u0+.23*length, u0+.77*length, slope, slope]
        lower += [u0, u0+.52*length, .08, .08]
        upper += [u0+.48*length, u1, 2.8, 2.8]
    elif kind == 'pyramidal':
        initial += [(u0+u1)/2, slope, slope]
        lower += [u0+.10*length, .08, .08]
        upper += [u1-.10*length, 2.8, 2.8]

    def planes_of(p):
        a, rv, h, sl, sr = p[:5]
        uu = np.array([np.cos(a), np.sin(a)])
        vv = np.array([-uu[1], uu[0]])
        planes = [np.r_[sl*vv, h-sl*rv], np.r_[-sr*vv, h+sr*rv]]
        if kind == 'hipped':
            ul, ur, su, sd = p[5:]
            planes += [np.r_[su*uu, h-su*ul], np.r_[-sd*uu, h+sd*ur]]
        elif kind == 'pyramidal':
            cu, su, sd = p[5:]
            planes += [np.r_[su*uu, h-su*cu], np.r_[-sd*uu, h+sd*cu]]
        return np.asarray(planes)

    A = np.c_[xy, np.ones(len(xy))]
    result = least_squares(lambda p: np.min(A@planes_of(p).T, axis=1)-z,
                           np.clip(initial, np.asarray(lower)+1e-7, np.asarray(upper)-1e-7),
                           bounds=(lower, upper), loss='soft_l1', f_scale=.22,
                           max_nfev=config['max_nfev'], ftol=2e-5, xtol=2e-5, gtol=2e-5)
    planes = planes_of(result.x)
    candidate = _candidate(kind, poly, points, planes=planes,
                           penalty={'gabled': .075, 'hipped': .13, 'pyramidal': .12}[kind],
                           params={'axis_rad': float(result.x[0]), 'fit': result.x.tolist(),
                                   'ridge_slice_count': len(peaks), 'converged': bool(result.success)})
    slopes = np.linalg.norm(planes[:, :2], axis=1)
    labels = np.argmin(A@planes.T, axis=1)
    supported = np.abs(candidate['_pred']-z) < .6
    for i in range(len(planes)):
        if np.mean(labels == i) < .015:
            candidate['rejected'].append(f'plane_{i}_negligible_area_support')
        elif np.mean((labels == i) & supported) < (.065 if i < 2 else .035):
            candidate['warnings'].append(f'plane_{i}_weak_point_support')
            candidate['score'] += .035
            candidate['evidence_penalty_m'] += .035
    if np.min(candidate['_pred']) < .8:
        candidate['rejected'].append('roof_below_plausible_wall_height')
    # An angle alone says nothing about visual significance: a 5-degree
    # surface across 30 m still has >2 m relief. Use the actual clipped extent.
    negligible = []
    for i, plane in enumerate(planes):
        region_vertices = [shapely.get_coordinates(shape(r['polygon']))
                           for r in candidate['regions'] if r.get('plane_index') == i]
        if region_vertices:
            xy_region = np.concatenate(region_vertices)
            plane_relief = float(np.ptp(xy_region@plane[:2]))
            if slopes[i] < .115 and plane_relief < .35:
                negligible.append(i)
    if negligible:
        # Mixed flat/pitched roofs remain useful large-volume approximations;
        # they are not falsely labelled as a clean gable/hip/pyramid.
        candidate['type'] = 'compound'
        candidate['parameters']['template_origin'] = kind
        candidate['parameters']['nearly_flat_planes'] = negligible
        candidate['warnings'].append('mixed_shallow_and_pitched_planes')
        candidate['complexity_penalty_m'] += .06
        candidate['score'] += .06
    candidate['_planes'] = planes
    candidate['_labels'] = labels
    return candidate


def _split_polygon(poly, theta, coordinate):
    u = np.array([math.cos(theta), math.sin(theta)])
    v = np.array([-u[1], u[0]])
    xy = shapely.get_coordinates(poly)
    extent = max(np.ptp(xy@u), np.ptp(xy@v), 1)*4
    mid = u*coordinate + v*np.mean(xy@v)
    p = Polygon([mid-v*extent, mid+v*extent, mid+v*extent-u*extent, mid-v*extent-u*extent])
    return poly.intersection(p), poly.difference(p)


def _split_candidates(poly, points, axes, gradients, trusted):
    """Two terrace levels. A real split is required, not two arbitrary z clusters."""
    if trusted.sum() < 15 or np.mean(np.linalg.norm(gradients[trusted], axis=1) < .16) < .50:
        return []
    options = []
    for theta in axes:
        u = np.array([math.cos(theta), math.sin(theta)])
        pos = points[:, :2]@u
        for split in np.quantile(pos, np.linspace(.16, .84, 15)):
            left = pos <= split
            if min(left.sum(), (~left).sum()) < max(12, .12*len(points)):
                continue
            heights = [float(np.median(points[m, 2])) for m in (left, ~left)]
            if abs(heights[0]-heights[1]) < .85:
                continue
            residual = points[:, 2] - np.where(left, heights[0], heights[1])
            score = _robust_error(residual)+.13
            options.append((score, theta, float(split), heights, residual))
    candidates = []
    for score, theta, split, heights, residual in sorted(options, key=lambda o:o[0])[:2]:
        parts = _split_polygon(poly, theta, split)
        if any(p.geom_type != 'Polygon' or p.area < max(10, poly.area*.12) for p in parts):
            continue
        regions = [{'polygon': mapping(p), 'plane': [0., 0., h]} for p, h in zip(parts, heights)]
        c = _candidate('flat_levels', poly, points, regions=regions, penalty=.13,
                       params={'split_axis_rad': theta, 'split_coordinate_m': split, 'heights_m': heights})
        # Most data must follow the levels; badly fit terraces remain candidates
        # for review but cannot suppress a well-supported pitched roof.
        if c['stats']['within_05_fraction'] < .65:
            c['rejected'].append('insufficient_horizontal_level_support')
        candidates.append(c)
    return candidates


def _normal_gate(candidate, gradients, trusted):
    if '_planes' not in candidate or trusted.sum() < 20:
        return
    planes, labels = candidate['_planes'], candidate['_labels']
    for i, plane in enumerate(planes):
        m = trusted & (labels == i)
        if m.sum() >= 10:
            # Independent slope evidence prevents a sloping bridge over terraces.
            agreement = np.linalg.norm(gradients[m]-plane[:2], axis=1) < max(.18, np.linalg.norm(plane[:2])*.4)
            if agreement.mean() < .30:
                candidate['warnings'].append(f'plane_{i}_local_slopes_disagree')
                candidate['score'] += .10/len(planes)
                candidate['evidence_penalty_m'] += .10/len(planes)


def _fit_candidates(poly, points, config, compound=True):
    gradients, trusted = _normals(points, config['cell_m'])
    axes = _axes(poly, gradients, trusted)
    flat = _candidate('flat', poly, points, planes=[[0, 0, float(np.median(points[:, 2]))]])
    candidates = [flat]
    p = _plane_fit(points)
    shed = _candidate('skillion', poly, points, planes=[p], penalty=.045)
    relief = float(np.ptp(shed['_pred']))
    if relief < .6 or np.linalg.norm(p[:2]) < .08:
        shed['rejected'].append('slope_negligible_at_building_scale')
    if np.linalg.norm(p[:2]) > 2.8 or shed['_pred'].min() < .8:
        shed['rejected'].append('implausible_shed_geometry')
    if trusted.sum() > 20 and np.mean(np.linalg.norm(gradients[trusted]-p[:2], axis=1) < .2) < .35:
        shed['warnings'].append('local_slopes_disagree')
        shed['evidence_penalty_m'] += .10
        shed['score'] += .10
    candidates.append(shed)
    candidates.extend(_split_candidates(poly, points, axes+[a+np.pi/2 for a in axes], gradients, trusted))
    if np.quantile(points[:, 2], .9)-np.quantile(points[:, 2], .1) > .6:
        for theta in axes:
            for kind in ('gabled', 'hipped', 'pyramidal'):
                c = _pitched(poly, points, theta, kind, config)
                if c:
                    _normal_gate(c, gradients, trusted)
                    candidates.append(c)
    accepted = [c for c in candidates if not c['rejected']]
    accepted.sort(key=lambda c:(c['score'], c['type']))
    # Concave footprint: exact large-part split, then independent simple roofs.
    # Only an explicit, substantial improvement justifies the extra geometry.
    rectangularity = poly.area/poly.minimum_rotated_rectangle.area
    if compound and config['allow_compound'] and accepted[0]['fit_error_m'] > .30:
        base = accepted[0]
        decompositions = []
        xy = shapely.get_coordinates(poly.simplify(.35, preserve_topology=True))
        for theta in axes[:2]:
            u = np.array([math.cos(theta), math.sin(theta)])
            projected = xy@u
            point_positions = points[:, :2]@u
            cuts = sorted(set(np.round(np.r_[projected, np.quantile(point_positions, [.25,.4,.5,.6,.75])], 2)))
            for cut in cuts:
                if cut < np.quantile(projected, .2) or cut > np.quantile(projected, .8):
                    continue
                parts = _split_polygon(poly, theta, cut)
                if any(p.geom_type != 'Polygon' or p.area < max(20, poly.area*.18) for p in parts):
                    continue
                rectangularity_score = sum(p.area*(p.area/p.minimum_rotated_rectangle.area) for p in parts)/poly.area
                mask = point_positions <= cut
                if min(mask.sum(), (~mask).sum()) < 24:
                    continue
                # Rank large splits by their simplest plane approximation.
                # This also permits different roof masses inside a rectangular
                # cadastral footprint, without requiring a concave boundary.
                fast_residual = np.zeros(len(points))
                for m in (mask, ~mask):
                    subpoints = points[m]
                    plane = _plane_fit(subpoints)
                    fast_residual[m] = subpoints[:, 2] - (subpoints[:, :2]@plane[:2]+plane[2])
                rank = _robust_error(fast_residual) - .2*rectangularity_score
                decompositions.append((rank, rectangularity_score, parts))
        shortlist = []
        structural = sorted((d for d in decompositions if d[1] > rectangularity+.08), key=lambda d:-d[1])
        if structural:
            shortlist.append(structural[0])
        for proposal in sorted(decompositions, key=lambda d:d[0]):
            if all(not proposal[2][0].equals(p[2][0]) for p in shortlist):
                shortlist.append(proposal)
            if len(shortlist) >= 2:
                break
        for _, _, parts in shortlist:
            regions, types, warnings, evidence_penalty = [], [], [], 0.
            for part_index, part in enumerate(parts):
                mask = shapely.intersects_xy(part, points[:, 0], points[:, 1])
                if mask.sum() < 24:
                    break
                sub, _ = _fit_candidates(part, points[mask], config, compound=False)
                best = min((c for c in sub if not c['rejected']), key=lambda c:c['score'])
                regions.extend(best['regions']); types.append(best['type'])
                warnings.extend(f'part_{part_index}:{w}' for w in best.get('warnings', []))
                evidence_penalty += part.area/poly.area*best.get('evidence_penalty_m', 0.)
            if len(types) == len(parts):
                c = _candidate('compound', poly, points, regions=regions,
                               penalty=.10+.035*len(regions), params={'part_types': types, 'parts': len(parts)})
                c['warnings'] = warnings
                c['evidence_penalty_m'] = evidence_penalty
                c['score'] += evidence_penalty
                if c['fit_error_m'] > base['fit_error_m']-.18:
                    c['rejected'].append('split_improvement_too_small')
                candidates.append(c)
    evidence = {'cell_count': len(points), 'local_plane_count': int(trusted.sum()),
                'horizontal_fraction': float(np.mean(np.linalg.norm(gradients[trusted], axis=1) < .16)) if trusted.any() else None,
                'axis_candidates_rad': axes, 'footprint_rectangularity': float(rectangularity)}
    return candidates, evidence


def _lines(model, footprint):
    """Eaves = exterior/courtyard roof boundaries; ridges = shared high edges."""
    regions = [(shape(r['polygon']), np.asarray(r['plane'])) for r in model['regions']]
    ridge, eaves, boundary = [], [], []
    def lines(g):
        if g.geom_type in ('LineString', 'LinearRing'):
            yield g
        elif hasattr(g, 'geoms'):
            for child in g.geoms:
                yield from lines(child)
    def xyz(line, p):
        return [[float(x), float(y), float(x*p[0]+y*p[1]+p[2])] for x,y in line.coords]
    for i, (poly, plane) in enumerate(regions):
        for line in lines(poly.boundary.intersection(footprint.boundary.buffer(1e-6))):
            if line.length > .05:
                coordinates = xyz(line, plane)
                boundary.append(coordinates)
                # A gable-end sloping edge is not an eave. Keep all boundary
                # edges separately and identify only near-horizontal eaves.
                if np.ptp(np.asarray(coordinates)[:, 2]) < .12:
                    eaves.append(coordinates)
        for other, otherplane in regions[i+1:]:
            for line in lines(poly.boundary.intersection(other.boundary)):
                if line.length < .15:
                    continue
                a, b = np.asarray(line.coords[0]), np.asarray(line.coords[-1])
                mid = (a+b)/2
                delta = b-a
                norm = np.array([-delta[1], delta[0]])/max(np.linalg.norm(delta), 1e-9)
                z1, z2 = mid@plane[:2]+plane[2], mid@otherplane[:2]+otherplane[2]
                # Horizontal ridge only: hip inclined edges are not mislabeled.
                if abs(z1-z2) < 1e-4 and abs((a-b)@plane[:2]) < .05 and np.dot(plane[:2], otherplane[:2]) < -.01:
                    descending = []
                    for region, p in ((poly, plane), (other, otherplane)):
                        direction = next((sign*norm for sign in (1, -1)
                                          if region.contains(Point(mid+sign*norm*.02))), None)
                        descending.append(direction is not None and np.dot(p[:2], direction) < -.01)
                    if all(descending):
                        ridge.append(xyz(line, plane))
    return ridge, eaves, boundary


def infer_roof_v2(footprint_local, train_xyz_local_relative, source_type=None, config=None):
    started = time.perf_counter()
    cfg = {**DEFAULTS, **(config or {})}
    poly = shape(footprint_local) if isinstance(footprint_local, dict) else footprint_local
    if not isinstance(poly, Polygon) or not poly.is_valid or poly.area <= 0:
        raise ValueError('Expected valid local Polygon with optional courtyard holes')
    points = np.asarray(train_xyz_local_relative, float).reshape(-1, 3)
    n_original = len(points)
    points = points[np.isfinite(points).all(axis=1)]
    points = points[shapely.intersects_xy(poly, points[:, 0], points[:, 1])]
    points = points[points[:, 2] > .5]
    flags = []
    cell = max(cfg['cell_m'], math.sqrt(poly.area/cfg['max_cells']))
    cells = _cells(points, cell) if len(points) else points
    if len(cells) > cfg['max_cells']:
        cell *= math.sqrt(len(cells)/cfg['max_cells'])*1.03
        cells = _cells(points, cell)
    cfg['cell_m'] = cell
    sparse = len(points) < 30 or len(cells) < 24
    if sparse:
        h = float(np.median(points[:, 2])) if len(points) else float(cfg['fallback_height'])
        candidate = {'type': 'flat', 'regions': [{'polygon': mapping(poly), 'plane': [0., 0., h]}],
                     'score': None, 'rejected': [], 'stats': {}, 'parameters': {'fallback': True}}
        candidates, evidence, ranked = [candidate], {}, [candidate]
        flags += ['insufficient_data', 'fallback_geometry_not_roof_classification']
    else:
        candidates, evidence = _fit_candidates(poly, cells, cfg)
        ranked = sorted((c for c in candidates if not c['rejected']), key=lambda c:(c['score'], c['type']))
        candidate = ranked[0]
        if candidate['stats']['within_05_fraction'] < .75 or candidate['stats']['p90_m'] > 1.:
            flags.append('poor_template_fit')
        # Equivalent orientations of the same family are one alternative.
        other = next((c for c in ranked[1:] if c['type'] != candidate['type']), None)
        if other and other['score']-candidate['score'] < .10:
            flags.append('ambiguous_type')
        coverage = min(1., len(cells)*cell*cell/poly.area)
        evidence['grid_coverage_fraction'] = coverage
        if coverage < .60:
            flags.append('incomplete_point_coverage')
        if candidate['type'] in ('flat_levels', 'compound'):
            flags.append('part_boundaries_need_review')
        if not candidate['parameters'].get('converged', True):
            flags.append('optimizer_iteration_limit')
    fit_end = time.perf_counter()
    # A numerically invalid candidate cannot be exported to tiles.
    mesh_failures = []
    for choice in ranked:
        try:
            mesh = build_mesh(poly, choice['regions'], base_z=0.)
            if not mesh['diagnostics'].get('valid', False):
                raise ValueError('mesh failed closure, winding or volume validation')
            candidate = choice
            break
        except (ValueError, RuntimeError) as exc:
            mesh_failures.append({'type': choice['type'], 'error': str(exc)})
    else:
        raise RuntimeError(f'No candidate with valid mesh: {mesh_failures}')
    if mesh_failures:
        flags.append('higher_ranked_mesh_rejected')
    model = {'type': candidate['type'], 'regions': candidate['regions'], 'mesh': mesh}
    model['ridge_lines'], model['eave_lines'], model['roof_boundary_lines'] = _lines(model, poly)
    roof_indices = np.unique(np.asarray(mesh['roof_faces'], dtype=int).ravel())
    roof_vertices = np.asarray(mesh['vertices'])[roof_indices]
    model['height_range_m'] = [float(roof_vertices[:, 2].min()), float(roof_vertices[:, 2].max())]
    model['apex_points'] = [roof_vertices[np.argmax(roof_vertices[:, 2])].tolist()] if model['type'] == 'pyramidal' else []
    predicted = predict_regions(model['regions'], points[:, :2])
    train = residual_stats(points[:, 2]-predicted)
    # Recompute confidence after the mesh gate; rejected leading candidates
    # cannot act as a better runner-up or retain their fit flags.
    flags = [f for f in flags if f not in ('poor_template_fit', 'ambiguous_type', 'optimizer_iteration_limit', 'part_boundaries_need_review')]
    selected_index = next(i for i, c in enumerate(ranked) if c is candidate)
    remaining = ranked[selected_index+1:]
    other = None
    for alternative in remaining:
        if alternative['type'] == candidate['type']:
            continue
        try:
            trial_mesh = build_mesh(poly, alternative['regions'], base_z=0.)
            if trial_mesh['diagnostics'].get('valid', False):
                other = alternative
                break
        except (ValueError, RuntimeError):
            pass
    gap = other['score']-candidate['score'] if other and candidate['score'] is not None else None
    if not sparse:
        if candidate['stats']['within_05_fraction'] < .75 or candidate['stats']['p90_m'] > 1.:
            flags.append('poor_template_fit')
        if gap is not None and gap < .10:
            flags.append('ambiguous_type')
        if not candidate['parameters'].get('converged', True):
            flags.append('optimizer_iteration_limit')
        if candidate['type'] in ('flat_levels', 'compound'):
            flags.append('part_boundaries_need_review')
        if candidate.get('warnings'):
            flags.append('weak_plane_evidence')
    source_normalized = {'shed':'skillion', 'gable':'gabled', 'hip':'hipped', 'pyramid':'pyramidal'}.get(source_type, source_type)
    if source_type and source_normalized != ('flat' if model['type'] == 'flat_levels' else model['type']):
        flags.append('source_type_disagrees')
    public_candidates = [{k:v for k,v in c.items() if not k.startswith('_') and k != 'regions'}
                         for c in sorted(candidates, key=lambda c:(bool(c['rejected']), c['score'] or 0))]
    return {'algorithm': VERSION, 'model': model,
            'diagnostics': {'review_required': bool(flags), 'flags': sorted(set(flags)),
                            'selected_type': model['type'], 'selection_score': candidate['score'],
                            'runner_up_gap': gap, 'score_is_probability': False,
                            'source_roof_type': source_type, 'train': train,
                            'selection_cells': candidate['stats'], 'evidence': evidence,
                            'input_points': n_original, 'usable_points': len(points),
                            'mesh_rejections': mesh_failures},
            'candidates': public_candidates,
            'timing': {'total_seconds': time.perf_counter()-started,
                       'fit_seconds': fit_end-started,
                       'mesh_seconds': time.perf_counter()-fit_end}}
