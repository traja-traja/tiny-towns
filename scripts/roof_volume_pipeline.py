"""MODULE volume pipeline: strict footprint width partitions, then evidence-gated height volumes.

Shared local batch adapter. No address rules, recursive splitting or skeleton.
Selection uses training cells only; the original 2D outline is preserved.
"""
import copy
import time
import numpy as np
import shapely
from shapely.geometry import shape
from roof_annex import infer_modular_roof
from roof_longitudinal_split import detect_longitudinal_split
from roof_footprint_connector import detect_footprint_connector
from roof_longitudinal_experiment import fit_partition, VERSION, CHILD_POLICY
from roof_v2 import _cells, predict_regions
from roof_config import resolve_config, ALGORITHM_VERSION
from roof_footprint_regularization import prepare_footprint, attach_footprint_metadata


def _select_volume_variant(scores,detection):
    """Keep the whole body when added volume freedom gives only a near-tie.

    Profile transitions nominate cuts; they do not prove two independent bodies.
    Apply a configurable simplicity tolerance after the extra-volume penalty,
    just as the roof-family selector prefers a simpler shape near the best fit.
    Supported original-wall cuts remain preferred among clearly better splits.
    """
    best=min(scores,key=lambda key:scores[key]['score'])
    settings=detection.get('settings',{})
    tolerance=float(settings.get('snap_selection_tolerance_m',.03))
    whole_tolerance=float(settings.get('whole_selection_tolerance_m',.10))
    if best=='whole':return best,dict(raw_best_variant=best,reason='whole_model_has_best_score')
    whole_gain=scores['whole']['score']-scores[best]['score']
    if whole_gain<=whole_tolerance+1e-12:
        return 'whole',dict(raw_best_variant=best,selected_variant='whole',
            reason='prefer_whole_model_within_simplification_tolerance',
            whole_selection_tolerance_m=whole_tolerance,
            best_split_penalized_gain_m=whole_gain,score_increase_m=whole_gain)
    eligible=[]
    for index,proposal in enumerate(detection.get('candidates',[])):
        key='split_'+str(index+1)
        if key not in scores or not proposal.get('snapping',{}).get('applied'):continue
        if (scores[key]['score']<=scores[best]['score']+tolerance
                and scores['whole']['score']-scores[key]['score']>whole_tolerance):
            eligible.append(key)
    selected=min(eligible,key=lambda key:scores[key]['score']) if eligible else best
    return selected,dict(raw_best_variant=best,selected_variant=selected,
        reason='prefer_supported_original_wall_cut_within_tolerance' if selected!=best else 'lowest_score',
        tolerance_m=tolerance,whole_selection_tolerance_m=whole_tolerance,
        best_split_penalized_gain_m=whole_gain,
        score_increase_m=scores[selected]['score']-scores[best]['score'])


def infer_volume_roof(footprint,points,config=None,split_config=None,extra_volume_penalty=.10):
    tick=time.perf_counter();cpu=time.process_time()
    poly=shape(footprint) if isinstance(footprint,dict) else footprint
    config=resolve_config(config)
    poly,footprint_metadata=prepare_footprint(poly,config)
    points=np.asarray(points,float)
    points=points[np.isfinite(points).all(axis=1)]
    points=points[shapely.intersects_xy(poly,points[:,0],points[:,1])]
    # MODULE footprint connector: strict local width partitions precede roof fitting.
    # A geometric width transition is not evidence of separate cadastral buildings; it is
    # a conservative modelling partition. No point-height profiles are used.
    fit_config=copy.deepcopy(config)
    fit_config['modules']['observed_ridges']=False
    child_config=copy.deepcopy(fit_config)
    child_config['modules'].update(footprint_regularization=False,footprint_connector=False)
    connector={'accepted':False,'reason':'module_disabled','timing':{'total_seconds':0.}}
    variants={};variant_counts={};errors={};whole=None;longitudinal_seconds=0.
    if config['modules']['footprint_connector']:
        try:connector=detect_footprint_connector(poly,config=config['footprint_connector'])
        except (ValueError,RuntimeError,shapely.errors.GEOSException) as error:
            connector={'accepted':False,'reason':'detector_failed','error':str(error),'timing':{'total_seconds':0.}}
    if connector.get('accepted') and connector.get('candidates'):
        proposal=connector['candidates'][0]
        # The shape may be certain while one part has no usable roof data.
        # In that case preserve the existing fallback instead of inventing it.
        sample=_cells(points,config['sampling']['cell_size_m'])
        supported=[int(shapely.intersects_xy(shape(p),sample[:,0],sample[:,1]).sum())
                   for p in proposal['footprints']]
        connector['part_supported_cells']=supported
        if min(supported,default=0)>=config['sampling']['min_cells']:
            try:
                variants['footprint_connector']=fit_partition(poly,points,proposal,config=child_config)
                variant_counts['footprint_connector']=len(proposal['footprints'])
            except (ValueError,RuntimeError,shapely.errors.GEOSException) as error:
                errors['footprint_connector']=str(error)
                connector['fallback_reason']='partition_roof_fit_failed'
        else:connector['fallback_reason']='insufficient_roof_cells_in_partition'
    connector['partition_used']='footprint_connector' in variants
    connector_seconds=connector.get('timing',{}).get('total_seconds',0.)
    if connector['partition_used']:
        detection=dict(method='footprint_connector',candidates=[proposal],settings=connector.get('settings',{}),
            reason=connector.get('reason','strict_footprint_width_partition'),counts=connector.get('counts',{}),
            timing={'total_seconds':connector_seconds},footprint_connector=connector,
            longitudinal_profiles_skipped=True)
    else:
        # MODULE height partition: unchanged fallback for ambiguous outlines.
        whole=infer_modular_roof(poly,points,config=fit_config,_footprint_prepared=True)
        variants['whole']=whole;variant_counts['whole']=1
        try:detection=detect_longitudinal_split(poly,points,config=split_config)
        except (ValueError,RuntimeError,shapely.errors.GEOSException) as error:
            detection=dict(candidates=[],reason='detector_failed_keep_current_whole_model',counts={},
                error=str(error),timing={'total_seconds':0.})
        longitudinal_seconds=detection['timing']['total_seconds']
        detection['footprint_connector']=connector
        detection['longitudinal_profiles_skipped']=False
        for i,proposal in enumerate(detection['candidates']):
            key='split_'+str(i+1)
            try:
                variants[key]=fit_partition(poly,points,proposal,config=child_config)
                variant_counts[key]=len(proposal['footprints'])
            except (ValueError,RuntimeError,shapely.errors.GEOSException) as error:errors[key]=str(error)
    cells=_cells(points,.6);scores={}
    for key,result in variants.items():
        pred=predict_regions(result['model']['regions'],cells[:,:2]);ok=np.isfinite(pred)
        loss=float(np.mean(np.minimum(abs(pred[ok]-cells[ok,2]),2.))) if len(cells) and ok.all() else 100.
        penalty=extra_volume_penalty*max(0,variant_counts[key]-1)
        scores[key]=dict(data_loss_m=loss,volume_penalty_m=penalty,score=loss+penalty,
            plane_count=len(result['model']['regions']))
    if connector['partition_used']:
        selected='footprint_connector'
        partition_choice=dict(selected_variant=selected,reason='strict_2d_width_partition',
            whole_roof_fitted=False,longitudinal_profiles_skipped=True,
            note='Partition selected by strict footprint proportions; roof scores are diagnostic, not a competing whole-roof fit.')
    else:selected,partition_choice=_select_volume_variant(scores,detection)
    result=variants[selected];children=result.pop('_child_results',[])
    counts={**detection.get('counts',{}),'selected_volume_count':variant_counts[selected],
        'geometry_cuts_applied':max(0,variant_counts[selected]-1),'child_split_calls':0,
        'child_roof_fits':sum(n for k,n in variant_counts.items() if k!='whole')}
    decision=dict(selected_variant=selected,counts=counts,scores=scores,candidate_errors=errors,partition_selection=partition_choice,
        reason=('Strict 2D width partition; each body fitted independently, no longitudinal height profiles or recursive splitting.'
            if connector['partition_used'] else
            'Current whole model versus split candidates; training loss plus volume penalty, keep whole within simplicity tolerance, then prefer supported wall cuts among clearly better splits; no holdout selection.'))
    result['algorithm']=ALGORITHM_VERSION
    result.setdefault('diagnostics',{})['volume_detection']={**detection,'decision':decision,'assembly_algorithm':VERSION}
    result['model'].setdefault('metadata',{}).update(volume_decision=decision,
        volume_count=counts['selected_volume_count'],child_volume_policy=CHILD_POLICY if children else None)
    result['configuration']={'roof':copy.deepcopy(config),'split':detection.get('settings'),
        'extra_volume_penalty_m':extra_volume_penalty}
    selected_timing=copy.deepcopy(result.get('timing',{}))
    result['timing']={'total_seconds':time.perf_counter()-tick,'cpu_seconds':time.process_time()-cpu,
        'whole_roof_seconds':whole['timing']['total_seconds'] if whole is not None else 0.,
        'footprint_connector_seconds':connector_seconds,'longitudinal_detection_seconds':longitudinal_seconds,
        'volume_detection_seconds':connector_seconds+longitudinal_seconds,
        'split_candidates_seconds':sum(v['timing']['total_seconds'] for k,v in variants.items() if k!='whole'),
        'selected_geometry_timing':selected_timing}
    if config['modules']['observed_ridges']:
        from roof_observed_ridges import attach_observed_ridges
        attach_observed_ridges(result,poly,points,config['observed_ridges'])
        measured=result['diagnostics']['observed_ridges']
        for child,volume in zip(children,measured['volumes']):
            child.setdefault('diagnostics',{})['observed_ridges']={**copy.deepcopy(measured),'volumes':[copy.deepcopy(volume)]}
        result['timing']['total_seconds']=time.perf_counter()-tick
        result['timing']['cpu_seconds']=time.process_time()-cpu
    result['_child_results']=children
    return attach_footprint_metadata(result,footprint_metadata)
