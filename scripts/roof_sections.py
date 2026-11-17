"""MODULE roof_sections: bounded, robust XY-strip measurements of roof height.

This measures evidence only: it does not change footprints, classify ownership,
or split meshes. All heights are in the input's vertical reference (normally
metres above ground_z). An eave from a section is an EXTRAPOLATED intersection
with the footprint boundary, not a directly observed gutter.
"""
from __future__ import annotations

import math
import time
import numpy as np
import shapely
from shapely.geometry import LineString, shape

DEFAULTS = {
    'enabled': True,
    'cell_m': .5,
    'max_cells': 9000,
    'section_spacing_m': 2.5,
    'section_width_m': 1.6,
    'max_sections': 17,
    'min_sections': 5,
    'end_margin_fraction': .08,
    'transverse_bin_m': .55,
    'min_bins': 7,
    'min_transverse_coverage': .65,
    'min_section_width_m': 3.,
    'edge_exclusion_m': .2,
    'max_profile_bins': 90,
    'ridge_search_count': 25,
    'min_slope_deg': 8.,
    'max_slope_deg': 72.,
    'min_roof_rise_m': .45,
    'max_profile_p80_m': .65,
    'flat_p80_m': .3,
    'ridge_min_improvement_m': .12,
    'min_ridge_sections': 3,
    'min_ridge_fraction': .55,
    'max_ridge_xy_deviation_m': .65,
    'max_ridge_height_deviation_m': .5,
    'step_min_m': 1.,
    'step_window_sections': 2,
    'step_max_local_spread_m': .45,
    'step_min_improvement_m': .3,
    'step_min_side_length_m': 3.,
}


def _robust_fit(a, z):
    """Fixed small IRLS solve; no nonlinear optimizer or maxima fitting."""
    beta = np.linalg.lstsq(a, z, rcond=None)[0]
    for _ in range(5):
        residual = a @ beta-z
        scale = max(.12, 1.4826*float(np.median(abs(residual-np.median(residual)))))
        weights = np.minimum(1., scale/np.maximum(abs(residual), 1e-10))
        beta = np.linalg.lstsq(a*weights[:, None]**.5, z*weights**.5, rcond=None)[0]
    residual = abs(a @ beta-z)
    return beta, float(np.quantile(residual, .8)), float(np.mean(np.minimum(residual, .8)))


def _cells(points, size, maximum):
    ij = np.floor(points[:, :2]/size).astype(np.int64)
    order = np.lexsort((points[:, 2], ij[:, 1], ij[:, 0]))
    points, ij = points[order], ij[order]
    bounds = np.r_[0, 1+np.flatnonzero(np.any(ij[1:] != ij[:-1], axis=1)), len(ij)]
    result = np.array([np.median(points[a:b], axis=0) for a,b in zip(bounds[:-1], bounds[1:])])
    if len(result) > maximum:
        # Spatial order, deterministic bounded sample; preserve raw count in JSON.
        result = result[np.linspace(0, len(result)-1, maximum).astype(int)]
    return result


def _line_parts(geometry):
    if geometry.geom_type == 'LineString':
        yield geometry
    elif hasattr(geometry, 'geoms'):
        for child in geometry.geoms:
            yield from _line_parts(child)


def _fit_profile(x, z, lo, hi, cfg):
    flat_height = float(np.median(z))
    flat_error = float(np.quantile(abs(z-flat_height), .8))
    line, line_error, line_cost = _robust_fit(np.c_[np.ones(len(x)), x], z)
    slope_min = math.tan(math.radians(cfg['min_slope_deg']))
    slope_max = math.tan(math.radians(cfg['max_slope_deg']))
    best = None
    candidates = np.linspace(lo+.18*(hi-lo), hi-.18*(hi-lo), cfg['ridge_search_count'])
    for apex in candidates:
        # Negative coefficients mean both slopes descend away from the apex.
        a = np.c_[np.ones(len(x)), np.maximum(apex-x, 0), np.maximum(x-apex, 0)]
        coefficients, error, cost = _robust_fit(a, z)
        if not (-slope_max <= coefficients[1] <= -slope_min
                and -slope_max <= coefficients[2] <= -slope_min):
            continue
        left, right = coefficients[0]+coefficients[1]*(apex-lo), coefficients[0]+coefficients[2]*(hi-apex)
        if min(coefficients[0]-left, coefficients[0]-right) < cfg['min_roof_rise_m']:
            continue
        if best is None or cost < best['cost']:
            best = dict(cost=cost, p80_error_m=error, ridge_v_m=float(apex),
                        ridge_height_m=float(coefficients[0]),
                        eave_left_m=float(left), eave_right_m=float(right),
                        slope_left_tangent=float(-coefficients[1]),
                        slope_right_tangent=float(-coefficients[2]))
    if best and best['p80_error_m'] <= cfg['max_profile_p80_m'] and line_cost-best['cost'] >= cfg['ridge_min_improvement_m']:
        best.update(kind='pitched', line_improvement_m=float(line_cost-best['cost']))
        return best
    if flat_error <= cfg['flat_p80_m'] and abs(line[1]) < slope_min:
        return dict(kind='flat', height_m=flat_height, p80_error_m=flat_error,
                    eave_left_m=flat_height, eave_right_m=flat_height)
    if line_error <= cfg['max_profile_p80_m']:
        return dict(kind='skillion', height_m=float(line[0]), slope_tangent=float(line[1]),
                    p80_error_m=line_error, eave_left_m=float(line[0]+line[1]*lo),
                    eave_right_m=float(line[0]+line[1]*hi))
    return dict(kind='inconclusive', p80_error_m=min(flat_error, line_error),
                reason='no_supported_simple_section', tentative_ridge=best)


def _tracks(sections):
    """Keep disjoint courtyard intervals apart, including flat/pitched changes."""
    groups = []
    for section in sections:
        if section['fit']['kind'] == 'insufficient':
            continue
        lo, hi = section['v_range_m']
        matches = []
        for group in groups:
            previous = group[-1]
            if not 0 < section['section_index']-previous['section_index'] <= 2:
                continue
            a, b = previous['v_range_m']
            overlap = max(0., min(hi,b)-max(lo,a)) / max(1e-9, min(hi-lo,b-a))
            if overlap >= .5:
                matches.append((overlap, group))
        if matches:
            max(matches, key=lambda item:item[0])[1].append(section)
        else:
            groups.append([section])
    return groups


def _height(row):
    fit = row['fit']
    if fit['kind'] in ('pitched', 'flat', 'skillion'):
        # Eaves isolate a vertical step from a normal ridge height change caused
        # by a narrowing wing or by a hip. Never split on a peak alone.
        return (fit['eave_left_m']+fit['eave_right_m'])/2
    return np.nan


def _changes(group, origin, u, v, span, cfg, track_id):
    result = []
    rows = [s for s in group if np.isfinite(_height(s))]
    n = cfg['step_window_sections']
    if len(rows) < 2*n:
        return result
    for cut in range(n, len(rows)-n+1):
        before, after = rows[cut-n:cut], rows[cut:cut+n]
        if after[0]['section_index']-before[-1]['section_index'] > 1:
            continue
        a, b = np.array([_height(r) for r in before]), np.array([_height(r) for r in after])
        left, right = float(np.median(a)), float(np.median(b))
        jump = right-left
        spread = max(float(np.ptp(a)), float(np.ptp(b)))
        together = np.r_[a,b]
        one_error = float(np.mean(abs(together-np.median(together))))
        two_error = float(np.mean(np.r_[abs(a-left),abs(b-right)]))
        coordinate = (before[-1]['u_m']+after[0]['u_m'])/2
        if min(coordinate-rows[0]['u_m'], rows[-1]['u_m']-coordinate) < cfg['step_min_side_length_m']:
            continue
        left_steps = np.median([r['fit']['eave_left_m'] for r in after])-np.median([r['fit']['eave_left_m'] for r in before])
        right_steps = np.median([r['fit']['eave_right_m'] for r in after])-np.median([r['fit']['eave_right_m'] for r in before])
        consistent = left_steps*right_steps > 0 and min(abs(left_steps),abs(right_steps)) >= cfg['step_min_m']*.65
        peaks_before = [r['fit']['ridge_height_m'] for r in before if r['fit']['kind']=='pitched']
        peaks_after = [r['fit']['ridge_height_m'] for r in after if r['fit']['kind']=='pitched']
        peak_step = None
        if len(peaks_before)==n and len(peaks_after)==n:
            peak_step = float(np.median(peaks_after)-np.median(peaks_before))
            consistent = consistent and peak_step*jump > 0 and abs(peak_step) >= cfg['step_min_m']*.5
        if abs(jump) < cfg['step_min_m'] or spread > cfg['step_max_local_spread_m'] or not consistent:
            continue
        if one_error-two_error < cfg['step_min_improvement_m']:
            continue
        p = origin+u*coordinate
        result.append(dict(track_id=track_id, u_m=float(coordinate),
            height_step_m=float(jump), before_height_m=left, after_height_m=right,
            ridge_height_step_m=peak_step, eave_left_step_m=float(left_steps),
            eave_right_step_m=float(right_steps), supporting_sections=2*n,
            before_section_ids=[s['id'] for s in before], after_section_ids=[s['id'] for s in after],
            local_spread_m=spread, error_improvement_m=one_error-two_error,
            evidence='repeated_step_in_both_extrapolated_eaves',
            cut_line_xy=[(p-v*span).tolist(),(p+v*span).tolist()],
            meaning='candidate_volume_boundary_not_proof_of_separate_building'))
    return result


def analyze_sections(footprint, train_xyz, config=None, *, axis=None, domain=None):
    """Measure roof cross-sections along ``axis``; optional domain is one wing.

    ``axis`` is the XY direction ALONG a prospective ridge; strips cut across it.
    Explicit domain is intersected with the original footprint. Without axis,
    the longest edge of the minimum rotated rectangle supplies a hypothesis.
    Return values are JSON serializable. A confirmed ridge requires repeated
    two-sided pitched profiles. Changes are hints only, never automatic splits.
    """
    started = time.perf_counter()
    cfg = {**DEFAULTS, **(config or {})}
    unknown = set(cfg)-set(DEFAULTS)
    if unknown:
        raise ValueError('Unknown roof_sections settings: '+', '.join(sorted(unknown)))
    if not cfg['enabled']:
        return dict(enabled=False, sections=[], ridge=None, ridge_tracks=[], eaves={}, longitudinal_changes=[],
                    timing={'total_seconds':time.perf_counter()-started}, settings=cfg)
    for key in ('cell_m','section_spacing_m','section_width_m','transverse_bin_m'):
        if cfg[key] <= 0:
            raise ValueError(key+' must be positive')
    poly = shape(footprint) if isinstance(footprint, dict) else footprint
    if domain is not None:
        poly = poly.intersection(shape(domain) if isinstance(domain,dict) else domain)
    if poly.is_empty or not poly.is_valid:
        raise ValueError('A nonempty valid section domain is required')
    raw = np.asarray(train_xyz, float)
    if raw.ndim != 2 or raw.shape[1] != 3:
        raise ValueError('train_xyz must be an Nx3 array')
    raw = raw[np.isfinite(raw).all(axis=1)]
    raw = raw[shapely.intersects_xy(poly, raw[:,0], raw[:,1])]
    if axis is None:
        coords = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)
        edges = np.diff(coords,axis=0)
        u = edges[np.argmax(np.linalg.norm(edges,axis=1))]
    else:
        u = np.asarray(axis,float)
    if u.shape != (2,) or not np.isfinite(u).all() or np.linalg.norm(u) < 1e-9:
        raise ValueError('axis must be a finite nonzero XY direction')
    u = u/np.linalg.norm(u)
    if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):
        u = -u
    v = np.array([-u[1],u[0]])
    origin = np.asarray(poly.centroid.coords[0])
    q = shapely.get_coordinates(poly)-origin
    projection = q@u
    lo, hi = float(projection.min()), float(projection.max())
    span = float(np.ptp(q@v)+3)
    output = dict(enabled=True, module='roof_sections/1', axis_xy=u.tolist(), cross_axis_xy=v.tolist(),
                  origin_xy=origin.tolist(), sections=[], ridge=None, ridge_tracks=[], eaves={},
                  longitudinal_changes=[], input_points=len(raw), settings=cfg,
                  eave_measurement='extrapolated_profile_at_footprint_edge')
    if len(raw) < cfg['min_bins']*3:
        output.update(status='insufficient_points', cells=0,
                      timing={'total_seconds':time.perf_counter()-started})
        return output
    cells = _cells(raw,cfg['cell_m'],cfg['max_cells'])
    uv = (cells[:,:2]-origin)@np.c_[u,v]
    count = max(cfg['min_sections'], min(cfg['max_sections'], int((hi-lo)/cfg['section_spacing_m'])+1))
    margin = cfg['end_margin_fraction']*(hi-lo)
    positions = np.linspace(lo+margin,hi-margin,count)
    for section_index, coordinate in enumerate(positions):
        center = origin+u*coordinate
        line = LineString([center-v*span,center+v*span]).intersection(poly)
        strips = abs(uv[:,0]-coordinate) <= cfg['section_width_m']/2
        for interval_index, interval in enumerate(_line_parts(line)):
            coords = (np.asarray(interval.coords)-origin)@v
            left,right = float(coords.min()),float(coords.max())
            if right-left < cfg['min_section_width_m']:
                continue
            selected = strips & (uv[:,1]>=left+cfg['edge_exclusion_m']) & (uv[:,1]<=right-cfg['edge_exclusion_m'])
            xx,zz = uv[selected,1],cells[selected,2]
            bins = max(cfg['min_bins'], min(cfg['max_profile_bins'], int((right-left)/cfg['transverse_bin_m'])+1))
            edge = np.linspace(left,right,bins+1)
            bucket = np.clip(np.searchsorted(edge,xx,side='right')-1,0,bins-1)
            samples = np.array([[np.median(xx[bucket==b]),np.median(zz[bucket==b])] for b in np.unique(bucket)])
            coverage = float(np.ptp(samples[:,0])/(right-left)) if len(samples)>1 else 0.
            fit = (_fit_profile(samples[:,0],samples[:,1],left,right,cfg) if len(samples)>=cfg['min_bins'] and coverage>=cfg['min_transverse_coverage']
                   else {'kind':'insufficient','reason':'too_few_transverse_bins'})
            record = dict(id=f'{section_index}:{interval_index}', section_index=section_index,
                          u_m=float(coordinate), v_range_m=[left,right], cells=int(selected.sum()),
                          samples_vz_m=samples.tolist(), fit=fit,
                          transverse_coverage_fraction=coverage,
                          eave_extrapolation_left_m=float(samples[0,0]-left) if len(samples) else None,
                          eave_extrapolation_right_m=float(right-samples[-1,0]) if len(samples) else None,
                          line_xy=[(center+v*left).tolist(),(center+v*right).tolist()])
            output['sections'].append(record)
    for track_id,group in enumerate(_tracks(output['sections'])):
        pitched = [s for s in group if s['fit']['kind']=='pitched']
        changes = _changes(group,origin,u,v,span,cfg,track_id)
        output['longitudinal_changes'].extend(changes)
        if not pitched:
            continue
        distance = np.array([s['u_m'] for s in pitched])
        offset = np.array([s['fit']['ridge_v_m'] for s in pitched])
        height = np.array([s['fit']['ridge_height_m'] for s in pitched])
        coefficients, _, _ = _robust_fit(np.c_[np.ones(len(distance)),distance],offset)
        offset_error = float(np.quantile(abs(np.c_[np.ones(len(distance)),distance]@coefficients-offset),.9))
        height_error = float(np.quantile(abs(height-np.median(height)),.9))
        accepted = len(pitched)>=cfg['min_ridge_sections'] and len(pitched)/len(group)>=cfg['min_ridge_fraction'] and offset_error<=cfg['max_ridge_xy_deviation_m']
        ends = [origin+u*t+v*(coefficients[0]+coefficients[1]*t) for t in (distance.min(),distance.max())]
        ridge = dict(track_id=track_id,supported=bool(accepted),
                     horizontal_supported=bool(accepted and height_error<=cfg['max_ridge_height_deviation_m']),
                     section_count=len(group),pitched_section_count=len(pitched),
                     support_fraction=len(pitched)/len(group),ridge_height_m=float(np.median(height)),
                     ridge_xy_p90_m=offset_error,ridge_height_p90_m=height_error,
                     ridge_line_xyz=[[*p.tolist(),float(np.median(height))] for p in ends],
                     ridge_measurements_xyz=[[*((origin+u*s['u_m']+v*s['fit']['ridge_v_m']).tolist()),s['fit']['ridge_height_m']] for s in pitched],
                     eave_left_m=float(np.median([s['fit']['eave_left_m'] for s in pitched])),
                     eave_right_m=float(np.median([s['fit']['eave_right_m'] for s in pitched])),
                     eave_height_m=float(np.median([h for s in pitched for h in (s['fit']['eave_left_m'],s['fit']['eave_right_m'])])),
                     pitch_tangent=float(np.median([h for s in pitched for h in (s['fit']['slope_left_tangent'],s['fit']['slope_right_tangent'])])),
                     slope_left_tangent=float(np.median([s['fit']['slope_left_tangent'] for s in pitched])),
                     slope_right_tangent=float(np.median([s['fit']['slope_right_tangent'] for s in pitched])),
                     step_candidates=len(changes))
        output['ridge_tracks'].append(ridge)
    confirmed = [r for r in output['ridge_tracks'] if r['supported']]
    if confirmed:
        output['ridge'] = max(confirmed,key=lambda r:r['pitched_section_count'])
        output['eaves'] = {k:output['ridge'][k] for k in ('eave_left_m','eave_right_m')}
    valid_heights = [_height(s) for s in output['sections'] if np.isfinite(_height(s))]
    output['height_summary'] = dict(valid_section_count=len(valid_heights),
        median_eave_m=float(np.median(valid_heights)) if valid_heights else None,
        p10_eave_m=float(np.quantile(valid_heights,.1)) if valid_heights else None,
        p90_eave_m=float(np.quantile(valid_heights,.9)) if valid_heights else None)
    output.update(status='measured', cells=len(cells),
                  timing={'total_seconds':time.perf_counter()-started})
    return output
