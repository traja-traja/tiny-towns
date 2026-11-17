"""MODULE straight_skeleton: generic eligibility and fair shared-family scoring.

Only plane regions are generated for candidate evaluation. The common roof
pipeline builds a closed mesh for the winning candidate, with normal fallback.
"""
from pathlib import Path
import sys,time,math
import numpy as np
import shapely
from roof_config import point_error
from roof_v2 import predict_regions
from roof_candidate_telemetry import record_attempt

def eligibility(poly,cells,cfg):
    simple=poly.simplify(cfg['simplify_m'],preserve_topology=True)
    edges=len(simple.exterior.coords)-1
    hull=poly.convex_hull.area
    rectangle=poly.minimum_rotated_rectangle.area
    concavity=1-poly.area/max(hull,1e-9)
    rectangle_loss=1-poly.area/max(rectangle,1e-9)
    span=float(np.quantile(cells[:,2],.9)-np.quantile(cells[:,2],.1)) if len(cells) else 0.
    reasons=[]
    if poly.area<cfg['min_area_m2']:reasons.append('footprint_too_small')
    if len(cells)<cfg['min_cells']:reasons.append('too_few_cells')
    if len(cells)>cfg['max_cells']:reasons.append('cell_budget')
    if span<cfg['min_height_span_m']:reasons.append('insufficient_pitched_height_span')
    if edges>cfg['max_edges']:reasons.append('outline_complexity_budget')
    shape_evidence=[]
    if len(poly.interiors):shape_evidence.append('courtyard')
    if concavity>=cfg['min_concavity_fraction']:shape_evidence.append('concave_footprint')
    if edges>=cfg['min_edges'] and rectangle_loss>=cfg['min_rectangle_loss_fraction']:shape_evidence.append('nonrectangular_footprint')
    if not shape_evidence:reasons.append('simple_footprint_already_covered_by_templates')
    return dict(eligible=not reasons,reasons=reasons,shape_evidence=shape_evidence,
        footprint_area_m2=float(poly.area),simplified_edges=edges,concavity_fraction=concavity,
        rectangle_loss_fraction=rectangle_loss,height_span_m=span,cells=len(cells),settings=dict(cfg))

def straight_skeleton_proposals(poly,points,cells,settings):
    cfg=settings['straight_skeleton'];start=time.perf_counter()
    gate=eligibility(poly,cells,cfg)
    gate_seconds=time.perf_counter()-start
    if not settings['modules']['straight_skeleton']:
        gate.update(eligible=False,reasons=['module_disabled'])
    if not gate['eligible']:
        record_attempt('straight_skeleton',status='skipped',reason=';'.join(gate['reasons']),count=0,stage='eligibility',overhead_seconds=gate_seconds,gate=gate)
        return [],gate
    record_attempt('straight_skeleton',status='eligible',reason=';'.join(gate['shape_evidence']),count=0,stage='eligibility',overhead_seconds=gate_seconds,gate=gate)
    vendor=Path(__file__).resolve().parents[1]/'.work/roof-skeleton-test/vendor'
    if vendor.is_dir() and str(vendor) not in sys.path:sys.path.insert(0,str(vendor))
    try:
        from roof_skeleton_gables import infer_skeleton_gables
    except ImportError as error:
        gate.update(available=False,error=str(error))
        record_attempt('straight_skeleton',status='skipped',reason='optional_library_unavailable',count=0,stage='availability',error=str(error))
        return [],gate
    tick=time.perf_counter()
    try:
        fit=infer_skeleton_gables(poly,points,settings=dict(build_geometry=False,
            cell_m=settings['sampling']['cell_size_m'],max_gable_candidates=cfg['max_gable_candidates'],
            evidence_inset_m=cfg['evidence_inset_m'],evidence_strip_m=cfg['evidence_strip_m'],
            max_nfev=cfg['max_nfev']))
    except (ValueError,RuntimeError,AssertionError,ZeroDivisionError,shapely.errors.GEOSException) as error:
        gate.update(available=True,failed=True,error=str(error))
        record_attempt('straight_skeleton',status='failed',reason='skeleton_construction_failed',fitting_seconds=time.perf_counter()-tick,error=str(error))
        return [],gate
    elapsed=time.perf_counter()-tick
    accounted=0.;proposals=[]
    bounds=list(map(float,poly.bounds));extent=[bounds[0],bounds[2],bounds[1],bounds[3]]
    for entry,record in zip(fit['_variant_results'],fit['candidates']):
        result=entry['result'];model=result['model'];meta=model['metadata'];regions=model['regions']
        tfit=record['fit_seconds'];tgeo=record['geometry_seconds'];accounted+=tfit+tgeo
        reasons=[reason for evidence in record['evidence'] for reason in evidence.get('reasons',[])]
        record_attempt('straight_skeleton',label=entry['label'],status='considered' if record['accepted'] else 'rejected',
            reason=';'.join(sorted(set(reasons))) or None,fitting_seconds=tfit,geometry_seconds=tgeo,
            reference=record.get('reference'),gable_count=meta['gable_count'],plane_count=meta['nominal_roof_plane_count'])
        if not record['accepted']:continue
        # Same XY cells and same data-loss function as every standard family.
        predicted=predict_regions(regions,cells[:,:2])
        if not np.isfinite(predicted).all():continue
        data_error=point_error(abs(predicted-cells[:,2]),settings['scoring'])
        penalty=cfg['complexity_penalty_m']+cfg['extra_plane_penalty_m']*max(0,meta['nominal_roof_plane_count']-2)+cfg['extra_gable_penalty_m']*meta['gable_count']
        area_penalty=cfg['reference_area_penalty_m']*meta['generalization'].get('changed_area_fraction',0.)
        proposals.append(dict(kind='straight_skeleton',hips=(),parameters=np.array([meta['eave_height_m'],math.tan(math.radians(meta['pitch_degrees']))]),
            score=float(data_error+penalty+area_penalty),data_error_m=float(data_error),complexity_penalty_m=penalty+area_penalty,support_penalty_m=0.,
            strip_regions=regions,ridge_xy=[],eave_height_m=meta['eave_height_m'],ridge_height_m=meta['ridge_height_m'],
            matrix=np.eye(2),extent=extent,plane_count=meta['nominal_roof_plane_count'],
            skeleton_metadata=meta,skeleton_diagnostics=result['diagnostics'],skeleton_gate=gate,
            fitting_seconds=tfit,geometry_seconds=tgeo,telemetry_recorded=True,
            candidate_label=entry['label'],supporting_envelope='bounded_virtual_footprint'))
    for ref in fit['diagnostics']['reference_trials']:
        for skipped in ref.get('skipped_configurations',[]):
            record_attempt('straight_skeleton',label=ref.get('reference','')+' / '+skipped['label'],
                status='rejected',reason=skipped['reason'],stage='construction')
    record_attempt('straight_skeleton',label='reference and partition preparation',count=0,stage='preprocessing',overhead_seconds=max(0.,elapsed-accounted))
    gate.update(available=True,enumerated=fit['diagnostics']['enumeration_count'],fit_variants=len(fit['candidates']),accepted_variants=len(proposals),
        reference_trials=[dict(reference=r['reference'],status=r['status'],candidate_end_count=r.get('candidate_end_count'),enumeration_count=r.get('enumeration_count')) for r in fit['diagnostics']['reference_trials']],
        timing_seconds=elapsed,geometry_deferred=True,scoring_cells=len(cells))
    return proposals,gate
