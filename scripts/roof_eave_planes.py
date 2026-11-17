"""Roof variant 3: fit primary eave lines and direction-constrained planes.

Minor footprint notches do not create roof controls. Roof planes are fitted
over a simple supporting envelope, then intersected with the actual footprint.
Straight and L ridges have fixed directions, a free offset, and a shared Z.
"""
from __future__ import annotations
import os
for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_name] = '1'
import itertools
import math
import time
import numpy as np
import shapely
from scipy.optimize import least_squares
from shapely.geometry import Polygon, LineString, box, shape, mapping
from shapely.ops import unary_union, linemerge
from roof_v2 import _cells, _lines, predict_regions
from roof_v2_geometry import plane_regions, build_mesh
from roof_config import DEFAULT_CONFIG, resolve_config, point_error
from roof_parallel import parallel_proposal
from roof_connected_wings import connected_wing_proposals, cap_rollback_candidates
from roof_butterfly import butterfly_proposal
from roof_butterfly_support import build_local_support

VERSION = 'eave-planes-4.10.0'

from roof_candidate_telemetry import record_attempt,record_selection
from roof_skeleton_candidate import straight_skeleton_proposals

def _family(kind,hips=()):
    return ('hipped' if any(hips) else 'gabled') if kind=='straight' else kind



def _groups(values, tolerance=.8):
    groups = []
    for value, weight in sorted(values):
        if groups and abs(value-groups[-1][0]) <= tolerance:
            mean, total = groups[-1]
            groups[-1] = ((mean*total+value*weight)/(total+weight), total+weight)
        else:
            groups.append((float(value), float(weight)))
    return groups


def _frame(poly):
    vertices = np.asarray(poly.exterior.coords)[:-1]
    edges = np.roll(vertices, -1, axis=0)-vertices
    length = np.linalg.norm(edges, axis=1)
    useful = length >= max(3., length.max()*.15)
    angles = np.arctan2(edges[useful, 1], edges[useful, 0])
    # Four-angle mean identifies the principal perpendicular wall directions.
    theta = np.angle(np.sum(length[useful]*np.exp(4j*angles)))/4
    u = np.array([math.cos(theta), math.sin(theta)])
    matrix = np.column_stack((u, [-u[1], u[0]]))
    local = vertices@matrix
    local_edges = np.roll(local, -1, axis=0)-local
    groups = [[], []]
    deviations = []
    for i in np.flatnonzero(useful):
        direction = int(np.argmax(abs(local_edges[i])))
        axis = 1-direction
        deviation = math.degrees(math.atan2(abs(local_edges[i, axis]), abs(local_edges[i, direction])))
        if deviation <= 15:
            groups[axis].append((float((local[i, axis]+local[(i+1) % len(local), axis])/2), length[i]))
            deviations.append(deviation)
    lines = [_groups(g) for g in groups]
    for axis in (0, 1):
        if len(lines[axis]) < 2:
            lines[axis] = [(float(local[:, axis].min()), 1.), (float(local[:, axis].max()), 1.)]
    return matrix, lines, max(deviations, default=0.)


def _layout(poly, matrix, lines):
    local = Polygon(np.asarray(poly.exterior.coords)@matrix)
    u0, u1 = lines[0][0][0], lines[0][-1][0]
    v0, v1 = lines[1][0][0], lines[1][-1][0]
    inner_u, inner_v = u0, v0
    best_missing = 0.
    # Significant missing corner = L footprint. Small recesses remain clipping.
    for ui, _ in lines[0][1:-1]:
        for vi, _ in lines[1][1:-1]:
            corner = box(u0, v0, ui, vi)
            if corner.area > max(8., .08*local.area) and local.intersection(corner).area < .2*corner.area:
                if corner.area > best_missing:
                    best_missing = corner.area
                    inner_u, inner_v = ui, vi
    return [u0, u1, v0, v1, inner_u, inner_v]


def _proposal(kind, hips, matrix, extent, cells, scoring=None):
    # MODULE roof_candidates: fit one simple template to median height cells.
    scoring = scoring or DEFAULT_CONFIG['scoring']
    u0, u1, v0, v1, inner_u, inner_v = extent
    uv = cells[:, :2]@matrix
    z = cells[:, 2]
    z10, z90 = np.quantile(z, [.1, .9])
    bent = kind == 'bent'
    pyramidal = kind == 'pyramidal'
    if bent or pyramidal:
        initial = [.5, .5]; low = [.12, .12]; high = [.88, .88]
    elif kind == 'straight':
        initial = [.5]; low = [.12]; high = [.88]
    else:
        initial, low, high = [], [], []
    for hip in hips:
        if hip:
            initial.append(.22); low.append(.04); high.append(.46)
    initial += [max(.6, z10-.8), max(.6, z90-z10+1.)]
    low += [.5, .05 if kind == 'skillion' else .4]
    high += [max(z90, 1.), max(4., float(np.ptp(z))+4)]

    def geometry(p):
        eave, rise = p[-2:]
        height = eave+rise
        def rising(axis, baseline, peak):
            slope = rise/(peak-baseline)
            a = np.zeros(2); a[axis] = slope
            return np.r_[a, eave-slope*baseline]
        if kind == 'skillion':
            return [[rising(1, v0, v1)]], [[[u0-3, v1], [u1+3, v1]]]
        if pyramidal:
            ru = u0+p[0]*(u1-u0)
            rv = v0+p[1]*(v1-v0)
            # Four horizontal reference eaves, four planes, exactly one apex.
            # Their lower envelope also clips small footprint protrusions.
            return [[rising(0, u0, ru), rising(0, u1, ru),
                     rising(1, v0, rv), rising(1, v1, rv)]], []
        if bent:
            ru = inner_u+p[0]*(u1-inner_u)
            rv = inner_v+p[1]*(v1-inner_v)
            left, right = rising(0, inner_u, ru), rising(0, u1, ru)
            front, back = rising(1, inner_v, rv), rising(1, v1, rv)
            wing_u, wing_v = [front, back, right], [left, right, back]
            index = 2
            start_u, start_v = u0-3, v0-3
            if hips[0]:
                start_u = u0+p[index]*(ru-u0); index += 1
                wing_u.append(rising(0, u0, start_u))
            if hips[1]:
                start_v = v0+p[index]*(rv-v0)
                wing_v.append(rising(1, v0, start_v))
            return [wing_u, wing_v], [[[start_u, rv], [ru, rv], [ru, start_v]]]
        rv = v0+p[0]*(v1-v0)
        planes = [rising(1, v0, rv), rising(1, v1, rv)]
        start, end = u0-3, u1+3
        index = 1
        if hips[0]:
            start = u0+p[index]*(u1-u0); index += 1
            planes.append(rising(0, u0, start))
        if hips[1]:
            end = u1-p[index]*(u1-u0)
            planes.append(rising(0, u1, end))
        return [planes], [[[start, rv], [end, rv]]]

    A = np.c_[uv, np.ones(len(uv))]
    def prediction(p):
        wings, _ = geometry(p)
        return np.max([np.min(A@np.asarray(planes).T, axis=1) for planes in wings], axis=0)
    fit = least_squares(lambda p: prediction(p)-z, initial, bounds=(low, high),
                        loss='soft_l1', f_scale=.25, max_nfev=65,
                        ftol=2e-4, xtol=2e-4, gtol=2e-4)
    pred = prediction(fit.x)
    absolute = abs(pred-z)
    score = point_error(absolute, scoring)
    data_error = float(score)
    penalty = scoring['complexity_m'][kind]+scoring['hip_end_penalty_m']*sum(hips)
    score += penalty
    wings, ridges = geometry(fit.x)
    world_wings = [[[*map(float, matrix@np.asarray(p[:2])), float(p[2])] for p in planes] for planes in wings]
    result = dict(kind=kind, hips=hips, score=float(score), parameters=fit.x,
                data_error_m=data_error, complexity_penalty_m=penalty, support_penalty_m=0.,
                wings=world_wings, ridge_xy=[(np.asarray(r)@matrix.T).tolist() for r in ridges],
                eave_height_m=float(fit.x[-2]), ridge_height_m=float(fit.x[-2]+fit.x[-1]),
                matrix=matrix, extent=extent)
    if pyramidal:
        result['apex_xy'] = (matrix@np.array([u0+fit.x[0]*(u1-u0), v0+fit.x[1]*(v1-v0)])).tolist()
    return result


def _primary_extent(lines):
    """Main wall pairs by length; a short annex edge need not set the roof span.

    Keep separated pairs only, so two close steps along one wall cannot become
    the entire roof. The full outer envelope remains a competing candidate.
    """
    bounds = []
    for group in lines:
        span = group[-1][0]-group[0][0]
        pairs = [(a, b) for a, b in itertools.combinations(group, 2) if b[0]-a[0] >= .5*span]
        a, b = max(pairs, key=lambda pair: pair[0][1]+pair[1][1])
        bounds.extend([float(a[0]), float(b[0])])
    return [*bounds, bounds[0], bounds[2]]


def _network_proposal(poly, matrix, extent, cells, missing_side=None, scoring=None):
    """Three/four joined roof wings, with shared outer planes and ridge Z.

    Side indices: left, right, bottom, top. A missing side creates an open U;
    all four sides create a closed ridge loop. No address-specific parameters.
    A courtyard supplies inner reference lines; otherwise these are virtual
    controls only and never create an opening in the footprint.
    """
    scoring = scoring or DEFAULT_CONFIG['scoring']
    u0, u1, v0, v1 = extent[:4]
    bounds = np.array([u0, u1, v0, v1], float)
    courtyard = max(poly.interiors, key=lambda r:Polygon(r).area, default=None)
    if courtyard is not None:
        uv_hole = np.asarray(courtyard.coords)@matrix
        inner = np.array([uv_hole[:, 0].min(), uv_hole[:, 0].max(),
                          uv_hole[:, 1].min(), uv_hole[:, 1].max()])
    else:
        inner = bounds+np.array([.35, -.35, .35, -.35])*np.array([u1-u0, u1-u0, v1-v0, v1-v0])
    if np.min(abs(inner-bounds)) < 1.:
        return None
    active = [side for side in range(4) if side != missing_side]
    z = cells[:, 2]; uv = cells[:, :2]@matrix
    A = np.c_[uv, np.ones(len(uv))]
    z10, z90 = np.quantile(z, [.1, .9])
    initial = [.5]*len(active)+[max(.6, z10-.8), max(.6, z90-z10+1.), .45]
    lower = [.06]*len(active)+[.5, .4, .03]
    upper = [.94]*len(active)+[max(1., z90), max(4., float(np.ptp(z))+4), 2.]

    def geometry(p):
        controls = (bounds+inner)/2
        controls[active] = bounds[active]+p[:len(active)]*(inner[active]-bounds[active])
        eave, rise, drop = p[-3:]
        height, inner_eave = eave+rise, eave+rise*(1-drop)
        outside, inside = [], []
        for side in active:
            axis = 0 if side < 2 else 1
            slope = rise/(controls[side]-bounds[side])
            normal = np.zeros(2); normal[axis] = slope
            outside.append(np.r_[normal, eave-slope*bounds[side]])
            slope = (inner_eave-height)/(inner[side]-controls[side])
            normal = np.zeros(2); normal[axis] = slope
            inside.append(np.r_[normal, height-slope*controls[side]])
        left, right, bottom, top = controls
        if missing_side is None:
            path = [[left,bottom],[right,bottom],[right,top],[left,top],[left,bottom]]
        elif missing_side == 0:
            path = [[u0-3,bottom],[right,bottom],[right,top],[u0-3,top]]
        elif missing_side == 1:
            path = [[u1+3,bottom],[left,bottom],[left,top],[u1+3,top]]
        elif missing_side == 2:
            path = [[left,v0-3],[left,top],[right,top],[right,v0-3]]
        else:
            path = [[left,v1+3],[left,bottom],[right,bottom],[right,v1+3]]
        return np.asarray(outside), np.asarray(inside), path

    def prediction(p):
        outside, inside, _ = geometry(p)
        return np.minimum(np.min(A@outside.T, axis=1), np.max(A@inside.T, axis=1))
    fit = least_squares(lambda p:prediction(p)-z, initial, bounds=(lower, upper),
                        loss='soft_l1', f_scale=.25, max_nfev=80,
                        ftol=2e-4, xtol=2e-4, gtol=2e-4)
    outside, inside, path = geometry(fit.x)
    residual = abs(prediction(fit.x)-z)
    kind = 'ring' if missing_side is None else 'u_shaped'
    score = point_error(residual, scoring)
    data_error = float(score)
    penalty = scoring['complexity_m'][kind]
    support_penalty = 0.
    score += penalty
    # A new branch must be supported by nearby measured cells, not only by
    # the footprint. Preserve weak evidence as a diagnostic and score penalty.
    branch_support = []
    for first, last in zip(path[:-1], path[1:]):
        start, end = np.asarray(first), np.asarray(last)
        vector = end-start; length = np.linalg.norm(vector)
        delta = uv-start
        t = delta@vector/(length*length)
        distance = np.abs(delta[:, 0]*vector[1]-delta[:, 1]*vector[0])/length
        near = (t > .05) & (t < .95) & (distance < .9)
        supported = int(np.sum(near & (residual < .6)))
        branch_support.append({'nearby_cells':int(near.sum()), 'supported_cells':supported})
        if supported < 5:
            score += scoring['weak_branch_penalty_m']
            support_penalty += scoring['weak_branch_penalty_m']
    def world(planes):
        return [[*map(float, matrix@p[:2]), float(p[2])] for p in planes]
    return dict(kind=kind, hips=(), score=float(score), parameters=fit.x,
                data_error_m=data_error, complexity_penalty_m=penalty, support_penalty_m=support_penalty,
                outer_planes=world(outside), inner_planes=world(inside),
                ridge_xy=[(np.asarray(path)@matrix.T).tolist()], matrix=matrix, extent=extent,
                eave_height_m=float(fit.x[-3]), ridge_height_m=float(fit.x[-3]+fit.x[-2]),
                courtyard_eave_height_m=float(fit.x[-3]+fit.x[-2]*(1-fit.x[-1])),
                courtyard_reference='existing footprint hole' if courtyard is not None else 'virtual interior lines; footprint unchanged',
                missing_side=missing_side, branch_support=branch_support)


def _polygons(geometry):
    if geometry.geom_type == 'Polygon':
        yield geometry
    elif hasattr(geometry, 'geoms'):
        for child in geometry.geoms:
            yield from _polygons(child)


def _segments(geometry):
    if geometry.geom_type in ('LineString', 'LinearRing'):
        if geometry.length > .1:
            yield geometry
    elif hasattr(geometry, 'geoms'):
        for child in geometry.geoms:
            yield from _segments(child)


def _regions(poly, proposal):
    if 'upper_planes' in proposal:
        return plane_regions(poly,proposal['upper_planes'],mode='max')
    if 'strip_regions' in proposal:
        return proposal['strip_regions']
    if 'inner_planes' in proposal:
        # min(outer planes, max(inner planes)). Partition the inner envelope
        # first, then intersect every piece with all exterior roof planes.
        result = []
        for region in plane_regions(poly, proposal['inner_planes'], mode='max'):
            result.extend(plane_regions(shape(region['polygon']), proposal['outer_planes']+[region['plane']]))
        return _merge_regions(result)
    wings = [plane_regions(poly, planes) for planes in proposal['wings']]
    if len(wings) == 1:
        return wings[0]
    result = []
    # The two gables share their outer planes, heights and bend. The upper
    # envelope creates a valley at the inside corner, without a vertical seam.
    for first in wings[0]:
        for second in wings[1]:
            intersection = shape(first['polygon']).intersection(shape(second['polygon']))
            for piece in _polygons(intersection):
                if piece.area > 1e-7:
                    result.extend(plane_regions(piece, [first['plane'], second['plane']], mode='max'))
    return _merge_regions(result)


def _merge_regions(result):
    groups = {}
    for region in result:
        key = tuple(np.round(region['plane'], 9))
        groups.setdefault(key, []).append(shape(region['polygon']))
    return [{'polygon': mapping(p), 'plane': list(plane)}
            for plane, pieces in groups.items() for p in _polygons(unary_union(pieces))]


def _near_candidates(ordered, poly, scoring):
    """A measured courtyard network cannot lose a wing just to save planes.

    Ordinary simplicity tolerance still applies inside one roof family. For
    a substantial real courtyard and a best-fitting network, changing family
    requires much closer agreement. No addresses or prescribed roof types.
    """
    if not ordered:
        return [], False
    best = ordered[0]
    minimum_area = max(scoring['min_courtyard_area_m2'], scoring['min_courtyard_area_fraction']*poly.area)
    has_courtyard = any(Polygon(ring).area >= minimum_area for ring in poly.interiors)
    protected = has_courtyard and best['kind'] in ('u_shaped', 'ring', 'connected_wings', 'straight_skeleton')
    near = []
    for proposal in ordered:
        tolerance = scoring['simplification_tolerance_m']
        if protected and proposal['kind'] != best['kind']:
            tolerance = min(tolerance, scoring['courtyard_topology_tolerance_m'])
        if proposal['score'] <= best['score']+tolerance:
            near.append(proposal)
    return near, protected


def _guard_main_eave_simplification(poly, best, near, scoring):
    """Do not trade measured main-eave geometry for fewer roof planes.

    Only long real boundary edges aligned with a ridge-supported wing and
    already nearly horizontal at that wing's eave height are references.
    Gable ends, short outline details and unsupported wings are not references.
    Incompatible candidates remain available as geometry fallbacks; this only
    prevents their promotion by the near-equivalent simplicity preference.
    """
    diagnostics = {'enabled':scoring['protect_main_eaves'], 'reference_edges':[],
                   'candidates_not_promoted':[], 'supported_gable_exemptions':[]}
    if not scoring['protect_main_eaves'] or best.get('kind') != 'connected_wings':
        return near, diagnostics
    metadata = best.get('connected_wings', {})
    limits = metadata.get('settings', {})
    frames = metadata.get('wing_frames_xy', [])
    eaves = metadata.get('wing_eaves_m', [])
    domains = [shape(value) for value in metadata.get('wing_domains_xy', [])]
    supported = [r['wing_index'] for r in best.get('branch_support', [])
                 if r.get('supported_cells', 0) >= limits.get('min_ridge_support_cells', 8)
                 and r.get('supported_cells', 0)/max(1, r.get('nearby_cells', 0))
                 >= limits.get('min_ridge_support_fraction', .35)]
    if not supported or '_regions' not in best:
        return near, diagnostics
    references = []
    angle_cos = math.cos(math.radians(scoring['main_eave_parallel_deg']))
    for ring_index, ring in enumerate([poly.exterior, *poly.interiors]):
        coords = np.asarray(ring.coords)
        for edge_index, (a, b) in enumerate(zip(coords[:-1], coords[1:])):
            vector = b-a; length = float(np.linalg.norm(vector))
            if length < scoring['main_eave_min_length_m']:
                continue
            direction = vector/length
            owners = [i for i in supported if i < len(frames) and i < len(eaves)
                      and abs(direction@np.asarray(frames[i])[:, 0]) >= angle_cos]
            if not owners:
                continue
            # Samples just inside the boundary avoid rounded partition seams.
            xy = a+np.linspace(.05, .95, 17)[:, None]*vector
            normal = np.array([-direction[1], direction[0]])*.01
            positive = xy+normal; negative = xy-normal
            inside = shapely.contains_xy(poly, positive[:, 0], positive[:, 1])
            xy = np.where(inside[:, None], positive, negative)
            # A parallel wing elsewhere in the building is not the owner of
            # this eave. Nor is a horizontal filler strip evidence of a slope.
            inset = scoring['main_eave_probe_inset_m']
            inward = np.where(inside[:, None], normal, -normal) / .01
            probes = xy + inward * inset
            slope_supported = np.zeros(len(probes), dtype=bool)
            for region in best['_regions']:
                geometry = shape(region['polygon'])
                covered = shapely.intersects_xy(geometry, probes[:, 0], probes[:, 1])
                gradient = np.asarray(region['plane'][:2])
                cross_slope = inward @ gradient
                along_slope = abs(float(direction @ gradient))
                slope_supported |= covered & (cross_slope > .08) & (along_slope < .08)
            if domains:
                local = np.zeros(len(probes), dtype=bool)
                for owner in owners:
                    if owner < len(domains):
                        local |= shapely.intersects_xy(domains[owner].buffer(.05), probes[:, 0], probes[:, 1])
                slope_supported &= local
            support_fraction = float(slope_supported.mean())
            if support_fraction < scoring['main_eave_min_supported_fraction']:
                continue
            height = predict_regions(best['_regions'], xy)
            if not np.isfinite(height).all():
                continue
            span = float(np.ptp(height))
            eave_delta = min(abs(float(np.median(height))-eaves[i]) for i in owners)
            if span > scoring['main_eave_reference_span_m'] or eave_delta > scoring['main_eave_height_tolerance_m']:
                continue
            references.append((xy, span))
            diagnostics['reference_edges'].append({'ring_index':ring_index, 'edge_index':edge_index,
                'length_m':length, 'xy':[a.tolist(), b.tolist()], 'reference_span_m':span,
                'reference_height_m':float(np.median(height)),
                'local_slope_support_fraction':support_fraction})
    accepted = []
    for proposal in near:
        failures = []
        for index, (xy, reference_span) in enumerate(references):
            # A locally evidenced gable legitimately replaces the hip's low
            # edge. Only its own matching end is exempt, never other eaves.
            evidenced_ends = proposal.get('connected_wings', {}).get('accepted_gable_edges', [])
            supported_gable = False
            for end in evidenced_ends:
                if end.get('supported') is not True or len(end.get('edge_xy', [])) < 2:
                    continue
                band = LineString(end['edge_xy']).buffer(scoring['main_eave_gable_match_distance_m'])
                fraction = float(shapely.intersects_xy(band, xy[:,0], xy[:,1]).mean())
                if fraction >= scoring['main_eave_gable_match_fraction']:
                    supported_gable = True
                    diagnostics['supported_gable_exemptions'].append({'reference_edge_index':index,
                        'candidate':proposal.get('candidate_label'), 'covered_fraction':fraction,
                        'reason':'locally_supported_gable_end'})
                    break
            if supported_gable:
                continue
            height = predict_regions(proposal.get('_regions', []), xy)
            finite = bool(np.isfinite(height).all())
            span = float(np.ptp(height)) if finite else None
            if not finite or span > reference_span+scoring['main_eave_max_span_increase_m']:
                failures.append({'reference_edge_index':index, 'candidate_span_m':span,
                                 'reference_span_m':reference_span})
        if proposal is best or not failures:
            accepted.append(proposal)
        else:
            detail = {'reason':'main_eave_deformation', 'reference_kind':best['kind'],
                      'reference_score':best['score'], 'edges':failures}
            proposal['simplification_guard'] = detail
            diagnostics['candidates_not_promoted'].append({'type':proposal['kind'],
                'score':proposal['score'], **detail})
    return accepted, diagnostics


def _visible_mesh_ridges(mesh):
    """Read horizontal crests from welded mesh adjacency, not float polygons.

    Adjacent roof triangles must both descend from the shared edge. This
    excludes valleys, coplanar triangulation seams and vertical height steps.
    Reading welded vertices also retains ridges whose planar-region outlines
    differ by a submicrometre after numerical noding.
    """
    vertices = np.asarray(mesh['vertices'], float)
    edges = {}
    for face in mesh['roof_faces']:
        for i in range(3):
            a, b, third = face[i], face[(i+1)%3], face[(i+2)%3]
            edges.setdefault(tuple(sorted((a,b))), []).append(third)
    segments = []
    for (a,b), thirds in edges.items():
        if len(thirds) != 2:
            continue
        first,last = vertices[a],vertices[b]
        if abs(first[2]-last[2]) > .05 or np.linalg.norm(first[:2]-last[:2]) < .01:
            continue
        if all(vertices[c,2] < min(first[2],last[2])-.005 for c in thirds):
            segments.append(LineString([first,last]))
    if not segments:
        return []
    lines = linemerge(segments)
    return [[[float(v) for v in point] for point in line.coords]
            for line in _segments(lines) if line.length > .15]


def _usable_candidate_mesh(mesh, proposal):
    """Connected roof candidates must not leave vertical walls at wing joins."""
    diagnostics = mesh.get('diagnostics', {})
    if not diagnostics.get('valid', False):
        return False
    return not (proposal.get('requires_continuous_roof', False)
                and diagnostics.get('height_step_edge_count', 0) > 0)


def infer_eave_roof(footprint, xyz, allow_networks=False, allow_flat=False, allow_pyramidal=False, config=None, allow_parallel=False):
    started = time.perf_counter()
    cpu_started = time.process_time()
    settings = resolve_config(config)
    scoring, modules = settings['scoring'], settings['modules']
    allow_networks = allow_networks and modules['networks']
    allow_flat = allow_flat and modules['flat']
    allow_pyramidal = allow_pyramidal and modules['pyramidal']
    poly = shape(footprint) if isinstance(footprint, dict) else footprint
    points = np.asarray(xyz, float)
    points = points[np.isfinite(points).all(axis=1)]
    points = points[shapely.intersects_xy(poly, points[:, 0], points[:, 1])]
    # MODULE sampling: keep point density from weighting the roof decision.
    cells = _cells(points, settings['sampling']['cell_size_m'])
    if len(cells) < settings['sampling']['min_cells']:
        raise ValueError('Too few cached points')
    matrix, lines, deviation = _frame(poly)
    fit_started = time.perf_counter()
    proposals = []
    proposal_errors = []
    evidence_rejections = []
    butterfly_support=build_local_support(cells,settings['butterfly']) if modules['butterfly'] and settings['butterfly']['local_direction_check'] else None
    def propose(function, *args):
        family=(_family(args[0],args[1]) if function is _proposal else
                'parallel_gables' if function is parallel_proposal else
                'butterfly' if function is butterfly_proposal else
                'ring' if args[4] is None else 'u_shaped')
        label=family+(' hips='+str(args[1]) if function is _proposal else '')
        tick=time.perf_counter()
        try:
            candidate = function(*args)
            elapsed=time.perf_counter()-tick
            if candidate is not None:
                candidate['fitting_seconds']=elapsed;candidate['candidate_label']=label
            if candidate is not None and candidate.get('evidence_rejections'):
                evidence_rejections.append({'type':candidate['kind'],
                    'reasons':candidate['evidence_rejections'],
                    'score':candidate['score'],
                    'branch_support':candidate.get('branch_support', []),
                    'simplification_guard':candidate.get('simplification_guard')})
                record_attempt(family,label,status='rejected',reason=';'.join(candidate['evidence_rejections']),fitting_seconds=elapsed)
                return
            if candidate is not None and np.isfinite(candidate['score']):
                proposals.append(candidate)
                record_attempt(family,label,fitting_seconds=elapsed)
            else:
                record_attempt(family,label,status='rejected',reason='no_supported_candidate',fitting_seconds=elapsed)
        except (ValueError, FloatingPointError, ZeroDivisionError) as error:
            proposal_errors.append({'stage':'candidate_fit', 'error':str(error)})
            record_attempt(family,label,status='failed',reason=str(error),fitting_seconds=time.perf_counter()-tick)
    connected_started = time.perf_counter()
    if modules.get('connected_wings', False):
        try:
            for candidate in connected_wing_proposals(poly, cells, settings):
                if candidate is not None and np.isfinite(candidate['score']):
                    proposals.append(candidate)
        except (ValueError, FloatingPointError, ZeroDivisionError, shapely.errors.GEOSException) as error:
            proposal_errors.append({'stage':'connected_wings', 'error':str(error)})
    connected_seconds = time.perf_counter()-connected_started
    if allow_flat:
        flat_tick=time.perf_counter()
        height = float(np.median(cells[:, 2]))
        absolute = abs(cells[:, 2]-height)
        score = point_error(absolute, scoring)
        penalty = scoring['complexity_m']['flat']
        proposals.append(dict(kind='flat', hips=(), score=score+penalty, data_error_m=score,
            complexity_penalty_m=penalty, support_penalty_m=0., parameters=np.array([height]),
            wings=[[[0., 0., height]]], ridge_xy=[], eave_height_m=height, ridge_height_m=height,
            matrix=matrix, extent=_layout(poly, matrix, lines)))
        proposals[-1]['fitting_seconds']=time.perf_counter()-flat_tick
        record_attempt('flat',fitting_seconds=proposals[-1]['fitting_seconds'])
    if allow_pyramidal:
        extents = [('main_walls', _primary_extent(lines)), ('outer_bounds', _layout(poly, matrix, lines))]
        seen = set()
        for envelope, extent in extents:
            key = tuple(round(float(v), 6) for v in extent[:4])
            if key in seen:
                continue
            seen.add(key)
            count = len(proposals)
            propose(_proposal, 'pyramidal', (), matrix, extent, cells, scoring)
            if len(proposals) > count:
                candidate = proposals[-1]
                candidate['supporting_envelope'] = envelope
                if not shapely.intersects_xy(poly, *candidate['apex_xy']):
                    proposals.pop()  # A clipped-away apex is not a tent roof.
    for swap in (False, True):
        frame = matrix[:, ::-1] if swap else matrix
        local_lines = lines[::-1] if swap else lines
        extent = _layout(poly, frame, local_lines)
        if allow_parallel and modules['parallel_gables']:
            for count in range(2,settings['parallel_gables']['max_ridges']+1):
                propose(parallel_proposal,poly,frame,extent,cells,count,settings)
        # MODULE primary envelope: a short protrusion must not be the only
        # possible reference eave. Fit the dominant wall pair as an alternative
        # for gables/hips too, then clip planes to the unchanged real footprint.
        simple_extents = [('outer_bounds', extent)]
        if modules['primary_wall_envelope']:
            primary = _primary_extent(local_lines)
            if not np.allclose(primary[:4], extent[:4], atol=1e-6):
                simple_extents.append(('main_walls', primary))
        for envelope, simple_extent in simple_extents:
            if modules['butterfly']:
                for cap_end in ((0,1) if settings['butterfly']['end_cap_required'] else (0,)):
                    before=len(proposals)
                    propose(butterfly_proposal,poly,frame,simple_extent,cells,settings,cap_end,butterfly_support)
                    if len(proposals)>before:
                        proposals[-1]['supporting_envelope']=envelope
            for hips in itertools.product((False, True), repeat=2):
                if modules['straight']:
                    before = len(proposals)
                    propose(_proposal, 'straight', hips, frame, simple_extent, cells, scoring)
                    if len(proposals) > before:
                        proposals[-1]['supporting_envelope'] = envelope
        for sign in (-1, 1):
            f = frame@np.diag([1, sign])
            ls = [local_lines[0], sorted((offset*sign, weight) for offset, weight in local_lines[1])]
            if modules['skillion']:
                propose(_proposal, 'skillion', (), f, _layout(poly, f, ls), cells, scoring)
    for su, sv in itertools.product((-1, 1), repeat=2):
        frame = matrix@np.diag([su, sv])
        local_lines = [sorted((offset*sign, weight) for offset, weight in group)
                       for sign, group in zip((su, sv), lines)]
        extent = _layout(poly, frame, local_lines)
        for hips in itertools.product((False, True), repeat=2):
            if modules['bent']:
                propose(_proposal, 'bent', hips, frame, extent, cells, scoring)
    if allow_networks:
        extent = _layout(poly, matrix, lines)
        for missing in (0, 1, 2, 3, None):
            propose(_network_proposal, poly, matrix, extent, cells, missing, scoring)
    # MODULE skeleton candidate: geometric gate, independent of analytical profiles.
    skeleton_candidates,skeleton_gate=straight_skeleton_proposals(poly,points,cells,settings)
    proposals.extend(skeleton_candidates)
    # MODULE geometry: build the first constructible scored candidate.
    geometry_started = time.perf_counter()
    chosen = None
    ordered = sorted(proposals, key=lambda p:p['score'])
    best_score = ordered[0]['score'] if ordered else None
    near, courtyard_topology_protected = _near_candidates(ordered, poly, scoring)
    # Near-equivalent fits prefer fewer distinct planes, independent of type.
    # This avoids selecting a more complex topology for a few centimetres.
    for candidate in near:
        region_tick=time.perf_counter()
        try:
            candidate['_regions'] = _regions(poly,candidate)
            candidate['plane_count'] = len({tuple(round(v,8) for v in r['plane']) for r in candidate['_regions']})
        except (ValueError, shapely.errors.GEOSException):
            candidate['plane_count'] = float('inf')
        record_attempt(_family(candidate['kind'],candidate['hips']),candidate.get('candidate_label',''),count=0,stage='regions',geometry_seconds=time.perf_counter()-region_tick)
    near, main_eave_guard = _guard_main_eave_simplification(poly, ordered[0], near, scoring) if ordered else (near, {})
    near.sort(key=lambda p:(p['plane_count'],p['score']))
    for candidate in near+[p for p in ordered if not any(p is q for q in near)]:
        mesh_tick=time.perf_counter()
        try:
            regions = candidate['_regions'] if '_regions' in candidate else _regions(poly,candidate)
            initial_mesh_error = None
            try:
                mesh = build_mesh(poly, regions)
            except (ValueError, shapely.errors.GEOSException) as error:
                initial_mesh_error = str(error)
                mesh = {'diagnostics':{'valid':False}}
            if not _usable_candidate_mesh(mesh, candidate) and candidate.get('_cap_original_wings') is not None:
                # Numerically unsafe simplifications are reversible. Retry only
                # this selected candidate, with identical point scoring, before
                # abandoning its entire roof family. No roof is forced by ID.
                rollback_tick = time.perf_counter()
                failed_score = candidate['score']
                recovered = False
                attempts = 0
                for rollback in cap_rollback_candidates(poly, cells, candidate):
                    attempts += 1
                    if rollback['score'] > failed_score + min(.03, scoring['simplification_tolerance_m']):
                        continue
                    try:
                        rollback_regions = rollback['strip_regions']
                        rollback_mesh = build_mesh(poly, rollback_regions)
                    except (ValueError, shapely.errors.GEOSException):
                        continue
                    if not _usable_candidate_mesh(rollback_mesh, rollback):
                        continue
                    candidate.clear(); candidate.update(rollback)
                    regions, mesh = rollback_regions, rollback_mesh
                    candidate['geometry_recovery'] = {'reason':'rejected_numerically_unsafe_cap_merge',
                        'attempts':attempts, 'score_before_recovery':failed_score,
                        'score_after_recovery':candidate['score']}
                    recovered = True
                    break
                record_attempt(_family(candidate['kind'],candidate['hips']),candidate.get('candidate_label',''),
                    count=0,stage='cap_merge_recovery',status='recovered' if recovered else 'failed',
                    reason='unsafe_cap_junction',recovery_seconds=time.perf_counter()-rollback_tick)
            if not _usable_candidate_mesh(mesh, candidate):
                reason = 'Connected roof contains exposed internal height steps' if mesh['diagnostics'].get('valid') else 'Roof planes could not form a closed volume'
                raise ValueError(initial_mesh_error or reason)
            chosen = candidate
            record_attempt(_family(candidate['kind'],candidate['hips']),candidate.get('candidate_label',''),count=0,stage='mesh',geometry_seconds=time.perf_counter()-mesh_tick)
            break
        except (ValueError, shapely.errors.GEOSException) as error:
            candidate['rejected'] = [str(error)]
            record_attempt(_family(candidate['kind'],candidate['hips']),candidate.get('candidate_label',''),count=0,status='failed',stage='mesh',reason=str(error),geometry_seconds=time.perf_counter()-mesh_tick)
    if chosen is None:
        raise ValueError('No candidate could form a closed roof volume')
    record_selection(_family(chosen['kind'],chosen['hips']),chosen.get('candidate_label',''))
    eave = chosen['eave_height_m']; ridge = chosen['ridge_height_m']
    model = {'type': 'butterfly' if chosen['kind']=='butterfly' else 'pyramidal' if chosen['kind']=='pyramidal' else 'flat' if chosen['kind']=='flat' else 'compound' if chosen['kind'] in ('bent', 'u_shaped', 'ring', 'parallel_gables', 'connected_wings', 'straight_skeleton') else
             'skillion' if chosen['kind'] == 'skillion' else 'hipped' if any(chosen['hips']) else 'gabled',
             'mesh': mesh, 'regions': regions}
    detected_ridges, actual_eaves, boundary = _lines(model, poly)
    ridge_heights = chosen.get('ridge_heights_m',[ridge]*len(chosen['ridge_xy']))
    ridges = [[[float(x), float(y), height] for x, y in line.coords]
              for line_xy,height in zip(chosen['ridge_xy'],ridge_heights)
              for line in _segments(poly.intersection(LineString(line_xy)))]
    main_eaves = []
    span = max(poly.bounds[2]-poly.bounds[0], poly.bounds[3]-poly.bounds[1])*4
    for region in regions:
        normal = np.asarray(region['plane'][:2]); c = region['plane'][2]
        size = np.linalg.norm(normal)
        if size < 1e-8:
            continue
        center = normal*(eave-c)/(size*size)
        tangent = np.array([-normal[1], normal[0]])/size
        line = LineString([center-tangent*span, center+tangent*span])
        for segment in _segments(shape(region['polygon']).buffer(1e-6).intersection(line)):
            if segment.length > 1.:
                main_eaves.append([[float(x), float(y), eave] for x, y in segment.coords])
    z_roof = [float(np.dot(xy, r['plane'][:2])+r['plane'][2])
              for r in regions for xy in shapely.get_coordinates(shape(r['polygon']))]
    model.update(ridge_lines=ridges, eave_lines=main_eaves or actual_eaves, roof_boundary_lines=boundary,
                 actual_horizontal_boundary_lines=actual_eaves,
                 height_range_m=[min(z_roof), max(z_roof)],
                 metadata={'ridge_height_m': ridge, 'eave_height_m': eave,
                           'roof_height_m':ridge-eave, 'ridge_kind': chosen['kind'],
                           'end_types': ['hip' if h else 'gable' for h in chosen['hips']],
                           'reference_frame_xy': chosen['matrix'].tolist(),
                           'reference_extent_uv': chosen['extent'],
                           'primary_wall_angle_deviation_deg': float(deviation),
                           'ridge_direction_constrained': True,
                           'ridge_offset_is_free': True,
                           'minor_footprint_features': 'Clip continuous roof planes; do not pin every perimeter vertex to the eave height.',
                           'eaves_are_reference_lines': True,
                           'nonparallel_wall_policy': 'Common main frame; actual clipped edges may slope. No claim that nonparallel wall edges can all be horizontal eaves.',
                           'automatic_neighbor_noise_filter': False,
                           'automatic_multi_level_detection': False,
                           'supporting_envelope': chosen.get('supporting_envelope'),
                           'requires_continuous_roof':chosen.get('requires_continuous_roof',False),
                           'nominal_roof_plane_count': chosen.get('plane_count')})
    if chosen['kind'] == 'pyramidal':
        apex = [*chosen['apex_xy'], ridge]
        model['apex_points'] = [apex]
        model['metadata'].update(apex_height_m=ridge, apex_position_m=apex,
            supporting_envelope=chosen['supporting_envelope'], nominal_roof_plane_count=4,
            ridge_direction_constrained=False, ridge_offset_is_free=False,
            annex_policy='Continuous pyramid planes clipped to the complete footprint; no separate flat annex inferred.')
    if chosen['kind'] == 'butterfly':
        first,second=map(np.asarray,chosen['upper_planes'][:2])
        delta=first[:2]-second[:2];center=-(first[2]-second[2])*delta/float(delta@delta)
        tangent=np.array([-delta[1],delta[0]])/np.linalg.norm(delta)
        valley_line=LineString([center-tangent*span,center+tangent*span])
        sides=[unary_union([shape(r['polygon']) for r in regions if np.allclose(r['plane'],p,atol=1e-7)]) for p in (first,second)]
        exposed=valley_line.intersection(poly).intersection(sides[0].buffer(1e-7)).intersection(sides[1].buffer(1e-7))
        valleys=[[[float(x),float(y),float(np.array([x,y])@first[:2]+first[2])] for x,y in line.coords] for line in _segments(exposed)]
        model.update(ridge_lines=[],valley_lines=valleys,eave_lines=valleys,
                     high_edge_lines=actual_eaves)
        model['metadata'].update(ridge_height_m=None,ridge_kind='butterfly',
            valley_height_m=chosen['valley_height_m'],high_edge_height_m=chosen['high_edge_height_m'],
            valley_depth_m=chosen['valley_depth_m'],nominal_roof_plane_count=len(chosen['upper_planes']),
            butterfly=chosen['butterfly'],
            valley_height_range_m=[min(p[2] for line in valleys for p in line),max(p[2] for line in valleys for p in line)] if valleys else [],
            nominal_ridge_segment_count=0,drainage_policy=chosen['drainage_policy'])
    if chosen['kind'] == 'parallel_gables':
        model['valley_lines'] = [[[float(x),float(y),height] for x,y in line.coords]
            for line_xy,height in zip(chosen['valley_xy'],chosen['valley_heights_m'])
            for line in _segments(poly.intersection(LineString(line_xy)))]
        model['metadata'].update(parallel_ridge_count=chosen['ridge_count'],
            ridge_heights_m=chosen['ridge_heights_m'], valley_heights_m=chosen['valley_heights_m'],
            transverse_profile_m=chosen['cross_section_uvz'],
            symmetric_bays=chosen.get('symmetric_bays',False),
            valleys_at_eave=chosen.get('valleys_at_eave',False),
            bay_widths_m=chosen.get('bay_widths_m',[]),
            bay_slopes_deg=chosen.get('bay_slopes_deg',[]),
            nominal_roof_plane_count=2*chosen['ridge_count'])
    if chosen['kind'] == 'connected_wings':
        detected_ridges = _visible_mesh_ridges(mesh)
        model.update(ridge_lines=detected_ridges, eave_lines=actual_eaves)
        model['metadata'].update(connected_wings=chosen['connected_wings'],
            reference_ridge_heights_m=chosen.get('ridge_heights_m', []),
            ridge_heights_m=sorted({round(float(np.mean(np.asarray(line)[:,2])),6) for line in detected_ridges}),
            nominal_ridge_segment_count=len(detected_ridges),
            ridge_lines_from_actual_regions=True,
            ridge_line_source='welded_roof_mesh_adjacency',
            footprint_modified=False,
            nominal_roof_plane_count=len({tuple(round(v,8) for v in r['plane']) for r in regions}),
            ridge_direction_constrained=True,
            ridge_offset_is_free=chosen['connected_wings'].get('ridge_offsets_fitted',False),
            minor_footprint_features='Primary eave pairs define wing roofs; unchanged footprint clips their union.',
            nonparallel_wall_policy='Each wing has its own local frame; small wall deviations only clip the roof planes.')
    if allow_networks:
        model['metadata'].update(
            courtyard_eave_height_m=chosen.get('courtyard_eave_height_m'),
            courtyard_reference=chosen.get('courtyard_reference'),
            ridge_network_closed=chosen['kind']=='ring',
            nominal_ridge_segment_count=sum(len(r)-1 for r in chosen['ridge_xy']),
            branch_support=chosen.get('branch_support', []),
            footprint_modified=False)
    if chosen['kind'] == 'connected_wings':
        model['metadata']['nominal_ridge_segment_count'] = len(detected_ridges)
    if chosen['kind']=='straight_skeleton':
        model['metadata'].update(chosen['skeleton_metadata'])
        model['metadata'].update(ridge_kind='straight_skeleton',selected=True,
            ridge_offset_is_free=False,ridge_direction_constrained=False,
            eaves_are_reference_lines=True,geometry_deferred_until_selection=True,
            nominal_ridge_segment_count=len(detected_ridges))
        model.update(ridge_lines=detected_ridges,eave_lines=actual_eaves)
    candidates = []
    for index, candidate in enumerate(sorted(proposals, key=lambda p:p['score'])):
        candidates.append({'candidate_id':index, 'type':candidate['kind'], 'score':candidate['score'],
            'status':'Vybráno' if candidate is chosen else 'Alternativa',
            'selected':candidate is chosen, 'rejected':candidate.get('rejected', []),
            'data_error_m':candidate.get('data_error_m'),
            'complexity_penalty_m':candidate.get('complexity_penalty_m'),
            'support_penalty_m':candidate.get('support_penalty_m'),
            'parameters':candidate['parameters'].tolist(), 'hip_ends':list(candidate['hips']),
            'reference_frame_xy':candidate['matrix'].tolist(),
            'reference_extent_uv':candidate['extent'],
            'supporting_envelope':candidate.get('supporting_envelope'),
            'apex_xy':candidate.get('apex_xy'),
            'valley_height_m':candidate.get('valley_height_m'),
            'high_edge_height_m':candidate.get('high_edge_height_m'),
            'butterfly':candidate.get('butterfly'),
            'ridge_count':candidate.get('ridge_count'),
            'plane_count':candidate.get('plane_count') if np.isfinite(candidate.get('plane_count',np.nan)) else None,
            'branch_support':candidate.get('branch_support', []),
            'candidate_label':candidate.get('candidate_label'),
            'fitting_seconds':candidate.get('fitting_seconds'),
            'geometry_seconds':candidate.get('geometry_seconds')})
        if candidate['kind'] == 'connected_wings':
            candidates[-1]['connected_wings'] = candidate['connected_wings']
    other_scores = [p['score'] for p in proposals if p is not chosen and not p.get('rejected')]
    flags = ['higher_ranked_mesh_rejected'] if any(p.get('rejected') for p in proposals) else []
    if chosen['score'] > best_score+1e-8 and any(chosen is p for p in near):
        flags.append('simpler_near_equivalent_candidate')
    if chosen.get('geometry_recovery'):
        model['metadata']['geometry_recovery'] = chosen['geometry_recovery']
        flags.append('cap_merge_safely_rolled_back')
    if chosen.get('connected_wings', {}).get('weakly_supported_wings'):
        flags.append('paired_ridge_weak_branch_support')
    result = {'algorithm': VERSION,
            'model': model, 'candidates': candidates,
            'diagnostics': {'status': 'Varianta k optickému posouzení', 'review_required': True,
                            'flags': flags, 'train': {'n': len(points)}, 'fit_cells':len(cells),
                            'candidate_fit_errors':proposal_errors,
                            'candidate_evidence_rejections':evidence_rejections,
                            'selection_rule':'Robust point error + complexity + support penalty; within tolerance prefer fewer planes. Real courtyard network topology has a tighter cross-family tolerance; simplification cannot deform supported main eaves. Closed geometry required.',
                            'simplification_tolerance_m':scoring['simplification_tolerance_m'],
                            'main_eave_simplification_guard':main_eave_guard,
                            'courtyard_topology_protected':courtyard_topology_protected,
                            'courtyard_topology_tolerance_m':scoring['courtyard_topology_tolerance_m'],
                            'best_unadjusted_score':best_score,
                            'selected_score_above_best_m':chosen['score']-best_score,
                            'runner_up_gap':min(other_scores)-chosen['score'] if other_scores else None,
                            'selection_score':chosen['score'], 'score_is_probability':False,
                            'visual_assessment_performed': False, 'independent_validation_performed': False},
            'timing': {'total_seconds': time.perf_counter()-started,
                       'preprocessing_seconds':fit_started-started,
                       'fitting_seconds':geometry_started-fit_started,
                       'geometry_seconds':time.perf_counter()-geometry_started,
                       'connected_wings_seconds':connected_seconds,
                       'butterfly_local_support_seconds':butterfly_support['total_seconds'] if butterfly_support is not None else 0.,
                       'cpu_seconds':time.process_time()-cpu_started}}

    result['diagnostics']['straight_skeleton']=skeleton_gate
    if chosen['kind']=='straight_skeleton':
        for key in ('candidate_end_edges','end_edge_audit','end_evidence','cap_rejections'):
            result['diagnostics'][key]=chosen['skeleton_diagnostics'].get(key,[])
    return result
