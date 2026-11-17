"""MODULE annex_detection: 2D candidates -> two height profiles -> simple roofs.

No address rules, downloads, images or 3D slicing. Modules/thresholds are in
roof_config.py. The original footprint and every rejected wing are preserved.
This first version only separates small, demonstrably lower flat/skillion
appendages; courtyards and comparable-size wings stay with the existing fitter.
"""
import copy
import time
import numpy as np
import shapely
from shapely.geometry import Polygon, LineString, shape, mapping
from shapely.ops import unary_union
from scipy.optimize import least_squares
from roof_config import resolve_config, point_error
from roof_flat_majority import detect_flat_majority
from roof_flat_protrusions import detect_flat_protrusions
from roof_eave_planes import infer_eave_roof, _frame, _primary_extent, _polygons, _segments
from roof_v2 import _cells, _lines
from roof_v2_geometry import build_mesh


def _main_body(poly, regions):
    """Ignore only floating-point slivers below mesh area tolerance."""
    difference = poly.difference(unary_union(regions))
    pieces = sorted(_polygons(difference), key=lambda p:-p.area)
    if not pieces:
        raise ValueError('Split removes the main body')
    sliver_area = sum(p.area for p in pieces[1:])
    if sliver_area > max(1e-8, poly.area*1e-10):
        raise ValueError('Split would disconnect the main body')
    return pieces[0], sliver_area


def footprint_candidates(poly, cfg):
    """MODULE annex_2d: protrusions beyond each main wall separately.

    A narrow mismatch along another wall must not bend the attachment into an
    L or move a profile into a sliver. A deeper seed locates the real protrusion.
    """
    if poly.geom_type != 'Polygon' or poly.interiors:
        return [], 'courtyard_or_multipart_not_split'
    matrix, lines, _ = _frame(poly)
    u0,u1,v0,v1 = _primary_extent(lines)[:4]
    local = Polygon(np.asarray(poly.exterior.coords)@matrix)
    lo_x,lo_y,hi_x,hi_y = local.bounds
    margin = max(hi_x-lo_x,hi_y-lo_y)+1.
    proposals = []
    for axis, sign, baseline in [(0,-1,u0),(0,1,u1),(1,-1,v0),(1,1,v1)]:
        bounds = [lo_x-margin,lo_y-margin,hi_x+margin,hi_y+margin]
        bounds[axis if sign>0 else axis+2] = baseline
        outside = local.intersection(shapely.box(*bounds))
        seed_bounds = bounds.copy()
        seed_bounds[axis if sign>0 else axis+2] += sign*cfg['profile_edge_exclusion_m']
        for part in _polygons(outside):
            if part.area < cfg['min_area_m2'] or part.area/poly.area > cfg['max_area_fraction']:
                continue
            depth = float(np.max(sign*(shapely.get_coordinates(part)[:,axis]-baseline)))
            if depth < cfg['min_depth_m']:
                continue
            seed = part.intersection(shapely.box(*seed_bounds))
            if seed.is_empty or seed.area < cfg['min_area_m2']:
                continue
            seed = max(_polygons(seed), key=lambda p:p.area)
            center = np.array(seed.representative_point().coords[0])
            tangent_axis = 1-axis
            # Attachment statistics use the substantial appendage width,
            # excluding thin strips caused by slightly oblique main walls.
            coords = shapely.get_coordinates(seed)
            a,b = center.copy(),center.copy()
            a[axis] = b[axis] = baseline
            a[tangent_axis],b[tangent_axis] = coords[:,tangent_axis].min(),coords[:,tangent_axis].max()
            join = LineString([a@matrix.T,b@matrix.T])
            if join.length < cfg['min_attachment_m']:
                continue
            origin = center.copy(); origin[axis] = baseline
            annex = Polygon(np.asarray(part.exterior.coords)@matrix.T)
            proposals.append({'polygon':annex,'origin':origin@matrix.T,
                'profile_center':center@matrix.T,'normal':matrix[:,axis]*sign,
                'tangent':matrix[:,tangent_axis], 'metadata':{
                    'footprint':mapping(annex),'area_m2':annex.area,
                    'area_fraction':annex.area/poly.area,'depth_m':depth,
                    'attachment_length_m':join.length,'attachment_xy':mapping(join)}})
    candidates, used = [],0.
    for candidate in sorted(proposals,key=lambda c:-c['polygon'].area):
        annex = candidate['polygon']
        if (used+annex.area)/poly.area > cfg['max_total_area_fraction']:
            continue
        if any(annex.intersection(c['polygon']).area > 1e-7 for c in candidates):
            continue
        candidates.append(candidate); used += annex.area
        if len(candidates)>=cfg['max_candidates']:
            break
    return candidates, 'candidates_found' if candidates else 'no_significant_protrusion'


def simple_annex_plane(points, cfg):
    """MODULE annex_roof: robust flat or gentle plane at measured height."""
    xy, z = points[:,:2], points[:,2]
    center = xy.mean(axis=0)
    A = np.c_[xy-center, np.ones(len(points))]
    height = float(np.median(z))
    flat = np.array([0.,0.,height])
    flat_error = float(np.quantile(abs(z-height), .8))
    if flat_error <= cfg['flat_p80_error_m'] or cfg['max_slope_deg']==0:
        return flat, 'flat', flat_error
    fit = least_squares(lambda p:A@p-z, [0.,0.,height], loss='soft_l1', f_scale=.25, max_nfev=30)
    plane = fit.x.copy(); plane[2] -= np.dot(plane[:2], center)
    error = float(np.quantile(abs(np.c_[xy,np.ones(len(xy))]@plane-z), .8))
    slope = float(np.degrees(np.arctan(np.linalg.norm(plane[:2]))))
    if slope <= cfg['max_slope_deg'] and error+cfg['plane_complexity_penalty_m'] < flat_error:
        return plane, 'skillion', error
    return flat, 'flat', flat_error


def height_profiles(cells, candidate, main_poly, plane, cfg):
    """MODULE annex_profiles: orthogonal narrow XY strips, represented as (s,z).

    First crosses the attachment; second traverses the annex parallel to it.
    Width/depth, sample counts, residuals and measured step are saved in JSON.
    """
    origin, normal, tangent = candidate['origin'], candidate['normal'], candidate['tangent']
    center = candidate['profile_center']
    is_annex = shapely.intersects_xy(candidate['polygon'], cells[:,0], cells[:,1])
    is_main = shapely.intersects_xy(main_poly, cells[:,0], cells[:,1])
    predicted = np.c_[cells[:,:2], np.ones(len(cells))]@plane
    records = []
    for name, anchor, axis, cross in [('across_attachment',origin,normal,tangent),
                                      ('along_annex',center,tangent,normal)]:
        delta = cells[:,:2]-anchor
        s, d = delta@axis, delta@cross
        selected = abs(d) <= cfg['profile_width_m']/2
        if name=='across_attachment':
            selected &= (s >= -cfg['profile_inside_m']) & (s <= candidate['metadata']['depth_m']+cfg['profile_width_m'])
        annex_mask = selected & is_annex
        core_mask = selected & is_main
        if name=='across_attachment':
            annex_mask &= s >= cfg['profile_edge_exclusion_m']
            core_mask &= s <= -cfg['profile_edge_exclusion_m']
        count = int(annex_mask.sum())
        error = float(np.quantile(abs(predicted[annex_mask]-cells[annex_mask,2]), .8)) if count else None
        passed = count >= cfg['profile_min_cells'] and error <= cfg['profile_max_p80_error_m']
        step = None
        if name=='across_attachment':
            near_annex = annex_mask & (s <= cfg['profile_inside_m'])
            if core_mask.sum() >= cfg['profile_min_cells'] and near_annex.sum() >= cfg['profile_min_cells']:
                step = float(np.median(cells[core_mask,2])-np.median(cells[near_annex,2]))
                passed = passed and step >= cfg['profile_min_step_m']
            else:
                passed = False
        order = np.flatnonzero(selected); order = order[np.argsort(s[order])]
        records.append({'name':name, 'origin_xy':anchor.tolist(), 'direction_xy':axis.tolist(),
            'width_m':cfg['profile_width_m'], 'annex_cells':count, 'main_cells':int(core_mask.sum()),
            'p80_error_m':error, 'measured_step_m':step, 'passed':bool(passed),
            'samples_sz_m':np.c_[s[order],cells[order,2]].tolist()})
    return records


def evaluate_annex(candidate, cells, main, main_poly, config, profile_cells=None):
    cfg = config['annex']; meta = copy.deepcopy(candidate['metadata'])
    selected = shapely.intersects_xy(candidate['polygon'], cells[:,0], cells[:,1])
    points = cells[selected]
    meta.update(cells=len(points), accepted=False, reasons=[])
    if len(points) < cfg['min_cells']:
        meta['reasons'].append('insufficient_annex_points')
        return None, meta, 0.
    plane, roof_type, error = simple_annex_plane(points, cfg)
    main_planes = np.array([r['plane'] for r in main['model']['regions']])
    # Only simple main roofs use a lower envelope. L/U/ring roofs are preserved.
    if main['model']['type']=='compound':
        meta['reasons'].append('compound_main_roof_preserved')
        return None, meta, 0.
    extended = np.min(np.c_[points[:,:2],np.ones(len(points))]@main_planes.T, axis=1)
    continuation_error = float(np.quantile(abs(extended-points[:,2]), .8))
    join_xy = np.array(shape(meta['attachment_xy']).coords)
    joinA = np.c_[join_xy,np.ones(len(join_xy))]
    height_step = float(np.median(np.min(joinA@main_planes.T,axis=1)-joinA@plane))
    meta.update(roof_type=roof_type, plane=plane.tolist(), height_at_center_m=float(np.r_[points[:,:2].mean(axis=0),1.]@plane),
                p80_error_m=error, main_continuation_p80_error_m=continuation_error, height_step_m=height_step)
    if error > cfg['max_p80_error_m']:
        meta['reasons'].append('not_a_simple_low_slope_roof')
    below_peak = float(main['model']['metadata']['ridge_height_m']-meta['height_at_center_m'])
    meta['height_below_main_peak_m'] = below_peak
    if below_peak < cfg['min_height_step_m'] or height_step < -cfg['max_join_above_main_m']:
        meta['reasons'].append('no_separate_lower_roof')
    if continuation_error-error < cfg['min_error_improvement_m']:
        meta['reasons'].append('main_roof_continuation_explains_points')
    started = time.perf_counter()
    if config['modules']['annex_profiles']:
        meta['profiles'] = height_profiles(profile_cells if profile_cells is not None else cells,
                                           candidate, main_poly, plane, cfg)
        if not all(p['passed'] for p in meta['profiles']):
            meta['reasons'].append('height_profiles_inconclusive')
    else:
        meta['profiles'] = []; meta['profiles_disabled'] = True
    profile_seconds = time.perf_counter()-started
    meta['accepted'] = not meta['reasons']
    region = {'polygon':mapping(candidate['polygon']), 'plane':plane.tolist(), 'role':'annex'}
    return region if meta['accepted'] else None, meta, profile_seconds



def _finish_flat_protrusions(result, poly, points, cfg):
    """MODULE flat_protrusions: append measured flat-topped blocks atomically.

    The base roof classification/height stays fixed. Detected XY areas replace
    the underlying base roof cells; build_mesh closes the vertical boundaries.
    Pitched/compound bases and internal tiers are outside this module's scope.
    """
    tick, cpu = time.perf_counter(), time.process_time()
    enabled = cfg['modules']['flat_protrusions']
    model = result['model']
    diagnostic = {'enabled':enabled, 'accepted_count':0, 'detected_count':0,
                  'status':'disabled' if not enabled else 'skipped_non_flat_base'}
    detection_seconds = geometry_seconds = 0.
    model['metadata']['protrusion_count'] = 0
    if enabled and model['type']=='flat' and len(model['regions'])==1:
        base_plane = model['regions'][0]['plane']
        if abs(base_plane[0])+abs(base_plane[1]) < 1e-9:
            height = float(base_plane[2])
            detection_tick = time.perf_counter()
            raised, detection = detect_flat_protrusions(poly, points, height, cfg['flat_protrusions'])
            detection_seconds = time.perf_counter()-detection_tick
            diagnostic.update(detection, enabled=True, detected_count=len(raised), accepted_count=0,
                              status='no_supported_protrusions', base_height_m=height)
            if raised:
                geometry_tick = time.perf_counter()
                try:
                    raised_union = unary_union([shape(r['polygon']) for r in raised])
                    remainder = poly.difference(raised_union)
                    regions = [{'polygon':mapping(p), 'plane':[0.,0.,height]}
                               for p in _polygons(remainder)] + raised
                    mesh = build_mesh(poly, regions)
                    diagnostic['geometry_validation'] = mesh['diagnostics']
                    if not mesh['diagnostics']['valid']:
                        raise ValueError('Flat protrusions do not form a closed valid volume')
                    # Commit only after every surface has passed numerical validation.
                    updated = dict(model, regions=regions, mesh=mesh)
                    _, eaves, boundary = _lines(updated, poly)
                    top = max(float(r['plane'][2]) for r in raised)
                    model.update(regions=regions, mesh=mesh, height_range_m=[height,top],
                                 eave_lines=eaves, actual_horizontal_boundary_lines=eaves,
                                 roof_boundary_lines=boundary, ridge_lines=[])
                    model['metadata'].update(main_roof_type='flat', flat_base_height_m=height,
                        protrusion_count=len(raised), building_top_height_m=top,
                        max_protrusion_height_m=top-height,
                        nominal_roof_plane_count=1+len(raised), footprint_modified=False,
                        protrusion_height_policy='quantile_of_elevated_cell_medians_relative_to_base',
                        protrusion_height_quantile=cfg['flat_protrusions']['height_quantile'],
                        automatic_multi_level_detection=True,
                        multi_level_detection_scope='one flat top per supported elevated component',
                        flat_simplification_scope='one main base plane plus measured raised components')
                    diagnostic.update(status='added', accepted_count=len(raised), geometry_accepted=True,
                                      internal_height_tiers_preserved=False)
                    result['diagnostics'].setdefault('flags', []).append('flat_roof_protrusions_added')
                except (ValueError, shapely.errors.GEOSException) as error:
                    diagnostic.update(status='geometry_fallback', geometry_accepted=False,
                                      geometry_error=str(error), accepted_count=0)
                geometry_seconds = time.perf_counter()-geometry_tick
    result['diagnostics']['flat_protrusions'] = diagnostic
    timing = result['timing']
    timing['flat_protrusions_detection_seconds'] = detection_seconds
    timing['flat_protrusions_geometry_seconds'] = geometry_seconds
    timing['flat_protrusions_seconds'] = time.perf_counter()-tick
    timing['preprocessing_seconds'] = timing.get('preprocessing_seconds',0.)+detection_seconds
    timing['geometry_seconds'] = timing.get('geometry_seconds',0.)+geometry_seconds
    timing['total_seconds'] += timing['flat_protrusions_seconds']
    timing['cpu_seconds'] += time.process_time()-cpu
    return result


def infer_modular_roof(footprint, xyz, config=None):
    """MODULE pipeline: optional annex stage around the existing roof fitter."""
    cfg = resolve_config(config); modules = cfg['modules']
    started, cpu = time.perf_counter(), time.process_time()
    poly = shape(footprint) if isinstance(footprint, dict) else footprint
    points = np.asarray(xyz, float)
    points = points[np.isfinite(points).all(axis=1)]
    points = points[shapely.intersects_xy(poly, points[:,0], points[:,1])]
    # MODULE flat_majority: user's whole-volume simplification precedes annex
    # splitting. Supported horizontal patches may occupy different heights;
    # their area determines the type, the largest patch determines one height.
    flat_started = time.perf_counter()
    flat = {'enabled':bool(modules['flat_majority'] and modules['flat']),
            'accepted':False, 'reason':'disabled'}
    if flat['enabled']:
        cells = _cells(points, cfg['sampling']['cell_size_m']) if len(points) else np.empty((0,3))
        if len(cells) >= cfg['sampling']['min_cells']:
            flat.update(detect_flat_majority(poly, cells, cfg['sampling']['cell_size_m'], cfg['flat_majority']))
        else:
            flat['reason'] = 'insufficient_cells'
        if flat['accepted']:
            height = float(flat['height_m'])
            regions = [{'polygon':mapping(poly), 'plane':[0.,0.,height]}]
            geometry_started = time.perf_counter()
            try:
                if height <= 0:
                    raise ValueError('Representative roof height is not above ground')
                mesh = build_mesh(poly, regions)
                if not mesh['diagnostics']['valid']:
                    raise ValueError('Flat majority roof could not form a closed volume')
            except (ValueError, shapely.errors.GEOSException) as error:
                flat.update(accepted=False, reason='geometry_failed', geometry_error=str(error))
            else:
                model = {'type':'flat', 'mesh':mesh, 'regions':regions, 'ridge_lines':[],
                    'height_range_m':[height,height], 'metadata':{
                        'ridge_kind':'flat', 'ridge_height_m':height, 'eave_height_m':height,
                        'roof_height_m':0., 'nominal_roof_plane_count':1, 'annex_count':0,
                        'footprint_modified':False, 'flat_majority_area_fraction':flat['covered_area_fraction'],
                        'height_levels_collapsed':True, 'minor_features_simplified':True,
                        'representative_height_policy':'area_weighted_median_of_largest_horizontal_patch',
                        'automatic_multi_level_detection':False, 'module_states':modules}}
                _, eaves, boundary = _lines(model, poly)
                model.update(eave_lines=eaves, actual_horizontal_boundary_lines=eaves,
                             roof_boundary_lines=boundary)
                score = point_error(abs(cells[:,2]-height), cfg['scoring'])
                flat_seconds = geometry_started-flat_started
                result = {'algorithm':'modular-roofs-4.9.1', 'configuration':cfg, 'model':model,
                    'candidates':[{'candidate_id':0, 'type':'flat', 'score':score, 'selected':True,
                        'status':'Vybráno podle převahy vodorovné plochy', 'rejected':[],
                        'data_error_m':score, 'complexity_penalty_m':0., 'plane_count':1}],
                    'diagnostics':{'status':'Varianta k optickému posouzení', 'review_required':True,
                        'flags':['flat_majority_whole_building_simplification'],
                        'train':{'n':len(points)}, 'fit_cells':len(cells), 'flat_majority':flat,
                        'annex_detection':{'enabled':modules['annex_detection'], 'accepted_count':0,
                            'candidates':[], 'status':'skipped_flat_majority'},
                        'selection_rule':'Horizontal components satisfy the configured individual, largest and total area thresholds; select the main flat base at the height of the largest patch.',
                        'selection_score':score, 'score_is_probability':False,
                        'complex_candidates_skipped':True, 'visual_assessment_performed':False,
                        'independent_validation_performed':False},
                    'timing':{'total_seconds':time.perf_counter()-started,
                        'cpu_seconds':time.process_time()-cpu, 'preprocessing_seconds':flat_seconds,
                        'fitting_seconds':0., 'geometry_seconds':time.perf_counter()-geometry_started,
                        'flat_majority_seconds':flat_seconds, 'main_roof_seconds':0.,
                        'annex_2d_seconds':0., 'annex_profiles_seconds':0.,
                        'annex_evaluation_seconds':0., 'annex_assembly_seconds':0.}}
                return _finish_flat_protrusions(result, poly, points, cfg)
    flat_seconds = time.perf_counter()-flat_started
    times = {'annex_2d_seconds':0., 'annex_profiles_seconds':0., 'annex_evaluation_seconds':0.,
             'main_roof_seconds':0., 'annex_assembly_seconds':0.}
    calls = []
    def fit_main(geometry):
        mask = shapely.intersects_xy(geometry, points[:,0], points[:,1])
        result = infer_eave_roof(geometry, points[mask], allow_flat=modules['flat'],
            allow_networks=modules['networks'], allow_pyramidal=modules['pyramidal'], config=cfg,
            allow_parallel=modules['parallel_gables'])
        calls.append(result['timing']); times['main_roof_seconds'] += result['timing']['total_seconds']
        return result
    diagnostics = {'enabled':modules['annex_detection'], 'profiles_enabled':modules['annex_profiles'],
                   'candidates':[], 'accepted_count':0, 'status':'disabled'}
    candidates = []
    if modules['annex_detection']:
        tick = time.perf_counter()
        candidates, diagnostics['status'] = footprint_candidates(poly, cfg['annex'])
        times['annex_2d_seconds'] = time.perf_counter()-tick
    accepted = []
    if candidates:
        diagnostics['footprint_candidates'] = [copy.deepcopy(c['metadata']) for c in candidates]
        try:
            tentative, sliver_area = _main_body(poly, [c['polygon'] for c in candidates])
            diagnostics['numerical_sliver_area_m2'] = sliver_area
            main = fit_main(tentative)
            cells = _cells(points, cfg['sampling']['cell_size_m'])
            tick = time.perf_counter()
            # Narrow strips need a finer grid than whole-roof fitting. Reuse
            # the loaded cloud; no mesh slicing or source reread is involved.
            profile_cells = cells
            if modules['annex_profiles']:
                profile_cells = _cells(points, cfg['annex']['profile_cell_size_m'])
                times['annex_profiles_seconds'] += time.perf_counter()-tick
            for candidate in candidates:
                region, meta, seconds = evaluate_annex(candidate, cells, main, tentative, cfg, profile_cells)
                diagnostics['candidates'].append(meta)
                times['annex_profiles_seconds'] += seconds
                if region:
                    accepted.append(region)
            times['annex_evaluation_seconds'] = time.perf_counter()-tick
            if accepted:
                actual_main, sliver_area = _main_body(poly, [shape(r['polygon']) for r in accepted])
                diagnostics['numerical_sliver_area_m2'] = sliver_area
                if len(accepted)!=len(candidates):
                    main = fit_main(actual_main)
                    # Recheck against the final main roof; do not keep a split
                    # justified only by removing a different, rejected wing.
                    tick = time.perf_counter()
                    for candidate, meta in zip(candidates, diagnostics['candidates']):
                        if meta['accepted']:
                            region, checked, seconds = evaluate_annex(candidate, cells, main, actual_main, cfg, profile_cells)
                            meta.update(checked)
                            times['annex_profiles_seconds'] += seconds
                            if region is None:
                                raise ValueError('Annex evidence changed after main-body refit')
                    times['annex_evaluation_seconds'] += time.perf_counter()-tick
                tick = time.perf_counter()
                model = main['model']; main_type = model['type']
                regions = model['regions']+accepted
                mesh = build_mesh(poly, regions)
                if not mesh['diagnostics']['valid']:
                    raise ValueError('Annex assembly is not a closed volume')
                model.update(type='compound', mesh=mesh, regions=regions)
                _, eaves, boundary = _lines(model, poly)
                model['eave_lines'] = eaves; model['roof_boundary_lines'] = boundary
                model['actual_horizontal_boundary_lines'] = eaves
                heights = [float(np.r_[xy,1.]@r['plane']) for r in regions
                           for xy in shapely.get_coordinates(shape(r['polygon']))]
                model['height_range_m'] = [min(heights),max(heights)]
                model['metadata'].update(main_roof_type=main_type, main_footprint=mapping(actual_main),
                    annex_count=len(accepted), footprint_modified=False,
                    automatic_multi_level_detection=True, multi_level_detection_scope='small lower annex candidates only',
                    annex_policy='Separate measured flat/skillion roofs; original footprint preserved.',
                    candidate_evaluation_scope='main body with accepted annex points excluded')
                times['annex_assembly_seconds'] = time.perf_counter()-tick
                diagnostics.update(status='separated', accepted_count=len(accepted))
            else:
                main = fit_main(poly)
                diagnostics['status'] = 'candidates_rejected'
        except (ValueError, shapely.errors.GEOSException) as error:
            diagnostics.update(status='fallback_to_whole_footprint', fallback_reason=str(error), accepted_count=0)
            for meta in diagnostics['candidates']:
                if meta['accepted']:
                    meta.update(accepted=False, reasons=meta['reasons']+['assembly_or_refit_fallback'])
            main = fit_main(poly)
    else:
        main = fit_main(poly)
    main['algorithm'] = 'modular-roofs-4.9.1'
    main['configuration'] = cfg
    main['diagnostics']['annex_detection'] = diagnostics
    main['diagnostics']['flat_majority'] = flat
    main['model']['metadata'].setdefault('annex_count', 0)
    main['model']['metadata']['module_states'] = modules
    main['timing'].update(times)
    main['timing']['preprocessing_seconds'] = sum(t['preprocessing_seconds'] for t in calls)+flat_seconds
    main['timing']['flat_majority_seconds'] = flat_seconds
    main['timing']['fitting_seconds'] = sum(t['fitting_seconds'] for t in calls)
    main['timing']['connected_wings_seconds'] = sum(t.get('connected_wings_seconds',0.) for t in calls)
    main['timing']['geometry_seconds'] = sum(t['geometry_seconds'] for t in calls)+times['annex_assembly_seconds']
    main['timing']['total_seconds'] = time.perf_counter()-started
    main['timing']['cpu_seconds'] = time.process_time()-cpu
    return _finish_flat_protrusions(main, poly, points, cfg)
