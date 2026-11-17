"""MODULE skeleton_gables: isolated skeleton roofs with local end-cap continuation.

The skeleton library constructs the all-hipped partition. Polygonal terminal
faces are replaced by a boundary-compatible continuation of neighboring planes.
Bounded virtual outlines reduce small facade steps. No global plane minimum over a concave building, no
address rules, no AI calls, no selection using holdout points.
"""
from __future__ import annotations
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key]='1'
import copy,itertools,math,time
import numpy as np
import shapely
from shapely.geometry import Polygon,LineString,shape,mapping
from shapely.geometry.polygon import orient
from scipy.optimize import least_squares
from py_straight_skeleton import compute_skeleton,__version__
from roof_v2 import _cells,predict_regions,_lines
from roof_v2_geometry import plane_regions,build_mesh
from roof_config import DEFAULT_CONFIG,point_error

VERSION='skeleton-gable-trial-4-inset-evidence'
DEFAULTS=dict(simplify_m=.30,max_reference_area_change=.03,max_reference_shift_m=.65,
    primary_wall_min_m=3.,primary_wall_max_shift_m=.05,cell_m=.6,
    min_end_edge_m=2.,min_cap_area_m2=2.,max_gable_candidates=6,
    max_ridge_edge_alignment=.65,min_unit_lift_m=.15,
    evidence_inset_m=.8,evidence_strip_m=1.5,min_evidence_cells=6,min_evidence_width_bins=3,
    min_hip_underprediction_m=.20,min_local_improvement_m=.10,
    max_local_residual_m=.80,min_local_support_fraction=.50,
    extra_gable_penalty_m=.005,extra_plane_penalty_m=.005,reference_area_penalty_m=.25,
    virtual_outlines=True,outline_settings={},max_nfev=65,build_geometry=True)


def _polygons(g):
    if g.geom_type=='Polygon' and not g.is_empty:yield g
    elif hasattr(g,'geoms'):
        for p in g.geoms:yield from _polygons(p)


def virtual_footprint(original,cfg):
    # Union makes the virtual roof cover the real outline. Long real facades
    # must remain on the reference boundary; only small recesses may disappear.
    simple=original.simplify(cfg['simplify_m'],preserve_topology=True)
    reference=original.union(simple).simplify(1e-8,preserve_topology=True)
    reason='bounded_virtual_simplification'
    if reference.geom_type!='Polygon' or not reference.is_valid or len(reference.interiors)!=len(original.interiors):
        reference=original;reason='retained_original_topology'
    delta=original.symmetric_difference(reference).area/original.area
    drift=original.hausdorff_distance(reference)
    long_drift=0.
    for ring in [original.exterior,*original.interiors]:
        q=np.asarray(ring.coords)
        for a,b in zip(q[:-1],q[1:]):
            if np.linalg.norm(b-a)<cfg['primary_wall_min_m']:continue
            samples=a+np.linspace(0,1,7)[:,None]*(b-a)
            long_drift=max(long_drift,float(np.max(shapely.distance(shapely.points(samples),reference.boundary))))
    if delta>cfg['max_reference_area_change'] or drift>cfg['max_reference_shift_m'] or long_drift>cfg['primary_wall_max_shift_m']:
        reference=original;reason='retained_original_to_protect_main_eaves'
    reference=orient(reference,sign=1.)
    return reference,dict(reason=reason,original_footprint=mapping(original),reference_footprint=mapping(reference),
        original_edges=len(original.exterior.coords)-1,reference_edges=len(reference.exterior.coords)-1,
        changed_area_fraction=original.symmetric_difference(reference).area/original.area,
        max_boundary_shift_m=original.hausdorff_distance(reference),
        rejected_proposal_primary_wall_shift_m=long_drift,
        real_wall_footprint_preserved=True)


def skeleton_faces(reference):
    skeleton=compute_skeleton(list(reference.exterior.coords)[:-1],
        [list(r.coords)[:-1] for r in reference.interiors])
    faces=[]
    for index,ids in enumerate(skeleton.get_faces()):
        nodes=[skeleton.nodes[i] for i in ids]
        xy=np.array([[n.position.x,n.position.y] for n in nodes],float)
        z=np.array([n.time for n in nodes],float)
        poly=Polygon(xy)
        if not poly.is_valid or poly.area<1e-8:raise ValueError('Invalid skeleton face')
        plane=np.linalg.lstsq(np.c_[xy,np.ones(len(xy))],z,rcond=None)[0]
        if np.max(abs(np.c_[xy,np.ones(len(xy))]@plane-z))>1e-5:raise ValueError('Non-planar skeleton face')
        faces.append(dict(index=index,polygon=poly,plane=plane))
    return faces


from roof_skeleton_caps import terminal_caps,clipped_regions


def _fit(distance,z,cfg):
    start=time.perf_counter()
    initial=[max(.6,float(np.quantile(z,.1))-.3),.7]
    fit=least_squares(lambda p:p[0]+p[1]*distance-z,initial,
        bounds=([.5,.12],[max(initial[0]+.1,float(np.quantile(z,.9))),2.5]),
        loss='soft_l1',f_scale=.35,max_nfev=cfg['max_nfev'])
    height,slope=map(float,fit.x)
    predicted=height+slope*distance
    return height,slope,predicted,time.perf_counter()-start


def _evidence_masks(cells,caps,cfg,actual_footprint):
    # MODULE gable_evidence: use an inset band of the REAL footprint. Virtual
    # facade shifts must not accidentally admit noisy points at the real wall.
    # Cap membership and central facade span still associate cells with an end.
    masks=[];details=[]
    depth=shapely.distance(shapely.points(cells[:,:2]),actual_footprint.boundary)
    inside=shapely.intersects_xy(actual_footprint,cells[:,0],cells[:,1])
    band=inside & (depth>=cfg['evidence_inset_m']) & (depth<=cfg['evidence_strip_m'])
    for cap in caps:
        a,b=np.asarray(cap['edge_xy']);u=(b-a)/cap['edge_length_m']
        relative=cells[:,:2]-a;along=relative@u/cap['edge_length_m']
        mask=shapely.intersects_xy(cap['polygon'],cells[:,0],cells[:,1]) & band & (along>=.15)&(along<=.85)
        bins=len(np.unique(np.clip(np.floor(along[mask]*5),0,4)))
        masks.append(mask);details.append(dict(cells=int(mask.sum()),width_bins=int(bins),
            evidence_inset_m=cfg['evidence_inset_m'],evidence_max_depth_m=cfg['evidence_strip_m'],
            distance_reference='actual_footprint_boundary'))
    return masks,details


def _infer_reference(original,points,reference,generalization,cfg):
    total=time.perf_counter()
    cells=_cells(points,cfg['cell_m'])
    if len(cells)<20:raise ValueError('Insufficient roof cells')
    reference_seconds=0.
    tick=time.perf_counter();faces=skeleton_faces(reference);caps,edge_audit=terminal_caps(reference,faces,cfg)
    skeleton_seconds=time.perf_counter()-tick
    tick=time.perf_counter()
    all_hipped=clipped_regions(faces,caps,(),original)
    base_distance=predict_regions(all_hipped,cells[:,:2])
    if not np.isfinite(base_distance).all():raise ValueError('Skeleton must cover every real-footprint cell')
    base_height,base_slope,base_predicted,base_fit_seconds=_fit(base_distance,cells[:,2],cfg)
    evidence_masks,evidence_details=_evidence_masks(cells,caps,cfg,original)
    common_seconds=time.perf_counter()-tick
    variants=[];records=[];skipped=[]
    for bits in itertools.product((False,True),repeat=len(caps)):
        selected=tuple(i for i,value in enumerate(bits) if value)
        label='all-hipped' if not selected else 'gables-'+'-'.join(str(i+1) for i in selected)
        variant_start=time.perf_counter()
        try:unit=clipped_regions(faces,caps,selected,original,cfg)
        except ValueError as error:
            skipped.append(dict(label=label,reason=str(error)));continue
        distance=predict_regions(unit,cells[:,:2])
        if not np.isfinite(distance).all():
            skipped.append(dict(label=label,reason='incomplete_real_footprint_coverage'));continue
        if selected:height,slope,predicted,fit_seconds=_fit(distance,cells[:,2],cfg)
        else:height,slope,predicted,fit_seconds=base_height,base_slope,base_predicted,base_fit_seconds
        residual=predicted-cells[:,2]
        score=point_error(abs(residual),DEFAULT_CONFIG['scoring'])+len(selected)*cfg['extra_gable_penalty_m']
        checks=[];accepted=True
        for index in selected:
            mask=evidence_masks[index];detail=evidence_details[index]
            observed=cells[mask,2]
            under=float(np.median(observed-base_predicted[mask])) if len(observed) else None
            improvement=float(np.mean(np.minimum(abs(base_predicted[mask]-observed),2.))-np.mean(np.minimum(abs(predicted[mask]-observed),2.))) if len(observed) else None
            support=float(np.mean(abs(predicted[mask]-observed)<=cfg['max_local_residual_m'])) if len(observed) else 0.
            reasons=[]
            if detail['cells']<cfg['min_evidence_cells']:reasons.append('too_few_edge_cells')
            if detail['width_bins']<cfg['min_evidence_width_bins']:reasons.append('too_narrow_edge_support')
            if under is None or under<cfg['min_hip_underprediction_m']:reasons.append('hip_not_systematically_below_points')
            if improvement is None or improvement<cfg['min_local_improvement_m']:reasons.append('gable_has_no_local_improvement')
            if support<cfg['min_local_support_fraction']:reasons.append('insufficient_gable_surface_support')
            accepted=accepted and not reasons
            checks.append(dict(edge_id=caps[index]['id'],**detail,hip_underprediction_m=under,
                local_improvement_m=improvement,local_support_fraction=support,accepted=not reasons,reasons=reasons))
        regions=[dict(polygon=r['polygon'],plane=(slope*np.asarray(r['plane'])+[0,0,height]).tolist()) for r in unit]
        geometry_start=time.perf_counter()
        mesh=None
        if cfg['build_geometry']:
            try:
                mesh=build_mesh(original,regions)
                if not mesh['diagnostics']['valid']:raise ValueError('mesh validation failed')
            except (ValueError,RuntimeError,shapely.errors.GEOSException) as error:
                skipped.append(dict(label=label,reason='invalid_geometry',error=str(error)));continue
        roof_heights=[]
        for region in regions:
            xy=shapely.get_coordinates(shape(region['polygon']))
            roof_heights.extend((np.c_[xy,np.ones(len(xy))]@np.asarray(region['plane'])).tolist())
        metadata=dict(ridge_kind='straight_skeleton_gables',eave_height_m=height,
            ridge_height_m=float(max(roof_heights)),roof_height_m=float(max(roof_heights)-height),
            nominal_roof_plane_count=len({tuple(round(v,8) for v in r['plane']) for r in regions}),
            pitch_degrees=math.degrees(math.atan(slope)),common_eave=True,common_pitch=True,
            gable_edge_ids=[caps[i]['id'] for i in selected],gable_count=len(selected),
            candidate_end_count=len(caps),variant_label=label,evidence_accepted=bool(accepted),
            selected=False,generalization=generalization,footprint_modified=False,
            library='py_straight_skeleton',library_version=__version__,
            construction='Skeleton plus joint local continuation of surviving neighboring planes inside removed end faces; not CGAL.',
            limitation='Only patches with continuous joins and a two-sided terminal peak are admitted; no general weighted skeleton.')
        model=dict(type='compound',mesh=mesh,regions=regions,metadata=metadata,
            height_range_m=[float(min(roof_heights)),float(max(roof_heights))])
        if cfg['build_geometry']:
            model['ridge_lines'],model['eave_lines'],model['roof_boundary_lines']=_lines(model,original)
        else:
            model.update(ridge_lines=[],eave_lines=[],roof_boundary_lines=[])
        model['valley_lines']=[]
        geometry_seconds=time.perf_counter()-geometry_start
        data_error=point_error(abs(residual),DEFAULT_CONFIG['scoring'])
        complexity=cfg['extra_gable_penalty_m']*len(selected)+cfg['extra_plane_penalty_m']*max(0,metadata['nominal_roof_plane_count']-2)
        reference_penalty=cfg['reference_area_penalty_m']*generalization.get('changed_area_fraction',0.)
        score=data_error+complexity+reference_penalty
        record=dict(label=label,score=float(score),data_error_m=data_error,complexity_penalty_m=complexity,reference_penalty_m=reference_penalty,gable_edge_ids=metadata['gable_edge_ids'],
            accepted=bool(accepted),evidence=checks,plane_count=metadata['nominal_roof_plane_count'],
            selected=False,fit_seconds=fit_seconds,geometry_seconds=geometry_seconds,
            total_seconds=time.perf_counter()-variant_start)
        result=dict(algorithm=VERSION,model=model,candidates=[],configuration=copy.deepcopy(cfg),
            timing=dict(total_seconds=record['total_seconds'],fit_seconds=fit_seconds,geometry_seconds=geometry_seconds),
            diagnostics=dict(mesh=mesh['diagnostics'] if mesh is not None else {'deferred':True},end_evidence=checks,training_score=float(score),
                training_cells=len(cells),selection_uses_holdout=False))
        variants.append(dict(label=label,result=result));records.append(record)
    eligible=[i for i,record in enumerate(records) if record['accepted']]
    if not eligible:raise ValueError('No valid accepted skeleton candidate')
    chosen=min(eligible,key=lambda i:(records[i]['score'],len(records[i]['gable_edge_ids'])))
    records[chosen]['selected']=True;variants[chosen]['result']['model']['metadata']['selected']=True
    result=copy.deepcopy(variants[chosen]['result'])
    cap_metadata=[{k:v for k,v in c.items() if k not in ('patch','polygon')} for c in caps]
    result['candidates']=records
    result['diagnostics'].update(candidate_end_edges=cap_metadata,cap_rejections=[e for e in edge_audit if not e['eligible']],end_edge_audit=edge_audit,
        skipped_configurations=skipped,selected_variant=records[chosen]['label'],
        enumeration_count=2**len(caps),valid_variant_count=len(variants),
        selection_rule='Minimum robust training residual plus per-gable penalty, gated by local end evidence. All-hipped fallback always competes.')
    result['timing'].update(total_seconds=time.perf_counter()-total,reference_seconds=reference_seconds,
        skeleton_seconds=skeleton_seconds,common_preprocessing_seconds=common_seconds,
        all_variant_fit_seconds=sum(record['fit_seconds'] for record in records),
        all_variant_geometry_seconds=sum(record['geometry_seconds'] for record in records))
    for entry in variants:
        for key in ('candidate_end_edges','cap_rejections','end_edge_audit','skipped_configurations'):
            entry['result']['diagnostics'][key]=copy.deepcopy(result['diagnostics'][key])
    result['_variant_results']=variants
    return result


def infer_skeleton_gables(footprint,train,settings=None):
    """Compare bounded virtual outlines and all geometrically valid gable sets."""
    tick=time.perf_counter();cfg={**DEFAULTS,**(settings or {})}
    if set(cfg)-set(DEFAULTS):raise ValueError('Unknown skeleton gable setting')
    if not 0<=cfg['evidence_inset_m']<cfg['evidence_strip_m']:
        raise ValueError('Gable evidence requires 0 <= inset < maximum depth')
    original=shape(footprint) if isinstance(footprint,dict) else footprint
    if original.geom_type!='Polygon' or not original.is_valid:raise ValueError('Expected a valid Polygon')
    points=np.asarray(train,float);points=points[np.isfinite(points).all(axis=1)]
    points=points[shapely.intersects_xy(original,points[:,0],points[:,1])]
    if len(points)<20:raise ValueError('Insufficient roof points')
    ref_tick=time.perf_counter()
    if cfg['virtual_outlines']:
        from roof_virtual_outline import propose_virtual_outlines
        refs=propose_virtual_outlines(original,cfg['outline_settings'])
    else:
        ref,meta=virtual_footprint(original,cfg);meta['label']='legacy';refs=[dict(polygon=ref,metadata=meta)]
    reference_seconds=time.perf_counter()-ref_tick
    variants=[];records=[];audits=[];reference_results=[]
    for ref in refs:
        label=ref['metadata']['label']
        try:result=_infer_reference(original,points,ref['polygon'],ref['metadata'],cfg)
        except (ValueError,RuntimeError,shapely.errors.GEOSException) as error:
            audits.append(dict(reference=label,status='failed',error=str(error),generalization=ref['metadata']));continue
        reference_results.append(result)
        audits.append(dict(reference=label,status='complete',generalization=ref['metadata'],
            candidate_end_count=len(result['diagnostics']['candidate_end_edges']),
            end_edge_audit=result['diagnostics']['end_edge_audit'],skipped_configurations=result['diagnostics']['skipped_configurations'],
            enumeration_count=result['diagnostics']['enumeration_count'],valid_variant_count=len(result['_variant_results']),timing=result['timing']))
        for entry,record in zip(result['_variant_results'],result['candidates']):
            entry['label']=label+' / '+entry['label'];record['label']=entry['label'];record['reference']=label;record['selected']=False
            entry['result']['model']['metadata'].update(selected=False,variant_label=entry['label'],reference_label=label)
            variants.append(entry);records.append(record)
    accepted=[i for i,r in enumerate(records) if r['accepted']]
    if not accepted:raise ValueError('No accepted virtual-outline skeleton variant: '+str(audits))
    index=min(accepted,key=lambda i:(records[i]['score'],records[i]['plane_count']))
    records[index]['selected']=True;variants[index]['result']['model']['metadata']['selected']=True
    selected=copy.deepcopy(variants[index]['result']);selected['candidates']=records
    selected['diagnostics'].update(reference_trials=audits,selected_variant=variants[index]['label'],
        enumeration_count=sum(a.get('enumeration_count',0) for a in audits),valid_variant_count=len(variants),
        selection_rule='Robust training loss + explicit plane/gable complexity and virtual-area penalties; local gable evidence and geometry validation. Analytical cross sections never used.')
    selected['timing'].update(total_seconds=time.perf_counter()-tick,reference_seconds=reference_seconds,
        all_variant_fit_seconds=sum(r['fit_seconds'] for r in records),all_variant_geometry_seconds=sum(r['geometry_seconds'] for r in records),
        all_reference_skeleton_seconds=sum(r['timing']['skeleton_seconds'] for r in reference_results))
    selected['_variant_results']=variants
    return selected
