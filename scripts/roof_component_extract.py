"""Training-only extraction, roof infill and restoration of compact protrusions.

The source is an existing roof height field, not semantic recognition of a
church or chimney. All thresholds are fixed before the seven-case experiment.
An unchanged source is returned when detection or safe infill is unsupported.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import time

import numpy as np
from scipy import ndimage
import shapely
from shapely.geometry import Polygon, box, shape, mapping
from shapely.ops import unary_union

try:
    from .roof_pilot_roofer import predict_roofer_z
    from .roof_pilot_methods import fit_roof_models, predict_roof_z
    from .roof_simplify_planes import extract_roof_regions, _mesh_regions, _polygons, simplify_roof
except ImportError:
    from roof_pilot_roofer import predict_roofer_z
    from roof_pilot_methods import fit_roof_models, predict_roof_z
    from roof_simplify_planes import extract_roof_regions, _mesh_regions, _polygons, simplify_roof


SETTINGS = {
    'cell_m': .25, 'max_grid_cells': 100000,
    'min_prominence_m': 1.25, 'min_component_area_m2': .35,
    'max_component_area_m2': 30., 'max_component_area_fraction': .08,
    'max_aspect_ratio': 3.5, 'min_compactness': .12,
    'min_train_support': 12, 'max_components': 8,
    'mask_buffer_m': .20, 'surround_ring_m': 2.,
    'max_patch_boundary_p95_m': .60, 'max_patch_boundary_error_m': 1.,
    'max_restored_train_p95_m': .75, 'max_restored_peak_loss_m': .75,
    'base_merge_angle_deg': 15., 'base_merge_vertical_m': .5,
    'max_template_fit_points': 1000,
}
PROFILES = {
    'compact15': dict(SETTINGS, opening_radius_m=1.5),
    'compact25': dict(SETTINGS, opening_radius_m=2.5),
}


def _source_regions(model):
    extracted = extract_roof_regions(model)
    return [{'id':i, 'geometry':shape(r['polygon']), 'plane':np.asarray(r['plane'])}
            for i,r in enumerate(extracted['regions'])]


def _grid(model, domain, cfg):
    xmin,ymin,xmax,ymax = domain.bounds
    cell = max(cfg['cell_m'], np.sqrt((xmax-xmin)*(ymax-ymin)/cfg['max_grid_cells']))
    nx,ny = int(np.ceil((xmax-xmin)/cell)),int(np.ceil((ymax-ymin)/cell))
    xx,yy = np.meshgrid(xmin+(np.arange(nx)+.5)*cell,ymin+(np.arange(ny)+.5)*cell)
    xy = np.column_stack((xx.ravel(),yy.ravel()))
    inside = shapely.contains_xy(domain,xy[:,0],xy[:,1]).reshape(ny,nx)
    zz = predict_roofer_z(model,xy).reshape(ny,nx)
    valid = inside & np.isfinite(zz)
    if not np.any(valid):
        raise ValueError('No valid roof pixels')
    nearest = ndimage.distance_transform_edt(~valid,return_distances=False,return_indices=True)
    filled = zz[tuple(nearest)]
    radius = max(1,int(np.ceil(cfg['opening_radius_m']/cell)))
    kx,ky = np.meshgrid(np.arange(-radius,radius+1),np.arange(-radius,radius+1))
    kernel = (kx*kx+ky*ky)*cell*cell <= cfg['opening_radius_m']**2
    opened = ndimage.grey_opening(filled, footprint=kernel, mode='nearest')
    relief = np.maximum(0,filled-opened)
    return {'xy':xy,'z':zz,'relief':relief,'valid':valid,'cell':cell,'xmin':xmin,'ymin':ymin}


def _shape_stats(poly):
    rectangle = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)[:-1]
    lengths = np.linalg.norm(np.roll(rectangle,-1,axis=0)-rectangle,axis=1)
    return {'area_m2':float(poly.area),
            'aspect_ratio':float(lengths.max()/max(lengths.min(),1e-9)),
            'compactness':float(4*np.pi*poly.area/max(poly.length**2,1e-9))}


def detect_components(model, train_relative, footprint, config):
    """Detect compact positive relief without building names or holdout data."""
    cfg=dict(config)
    regions = _source_regions(model)
    domain = unary_union([r['geometry'] for r in regions])
    grid = _grid(model,domain,cfg)
    active = grid['valid'] & (grid['relief'] >= cfg['min_prominence_m'])
    labels,count = ndimage.label(active,structure=np.ones((3,3),dtype=int))
    points = np.asarray(train_relative,dtype=float)
    points = points[np.isfinite(points).all(axis=1)]
    source_z = predict_roofer_z(model,points[:,:2])
    # Roof-surface support only; class6 can also contain wall points.
    roof_support = np.isfinite(source_z) & (np.abs(source_z-points[:,2])<=.75)
    max_area=min(cfg['max_component_area_m2'],domain.area*cfg['max_component_area_fraction'])
    candidates=[]
    for number in range(1,count+1):
        iy,ix=np.where(labels==number)
        cells=[box(grid['xmin']+x*grid['cell'],grid['ymin']+y*grid['cell'],
                   grid['xmin']+(x+1)*grid['cell'],grid['ymin']+(y+1)*grid['cell']) for y,x in zip(iy,ix)]
        seed=unary_union(cells).intersection(domain)
        record={'id':f'component-{number}', 'kind':'protrusion','status':'rejected',
                'label':f'Kompaktní výstupek {number}', 'polygon':mapping(seed),
                'seed_area_m2':seed.area,'seed_pixels':len(ix),
                'prominence_max_m':float(grid['relief'][iy,ix].max()),
                'prominence_median_m':float(np.median(grid['relief'][iy,ix])),
                'rejection_reasons':[]}
        if seed.is_empty or seed.geom_type!='Polygon':
            record['rejection_reasons'].append('disconnected_or_invalid_seed');candidates.append(record);continue
        stats=_shape_stats(seed);record.update(stats)
        if stats['area_m2'] < cfg['min_component_area_m2']:record['rejection_reasons'].append('too_small')
        if stats['area_m2'] > max_area:record['rejection_reasons'].append('major_roof_volume_not_small_feature')
        if stats['aspect_ratio'] > cfg['max_aspect_ratio']:record['rejection_reasons'].append('elongated_main_ridge_or_wing')
        if stats['compactness'] < cfg['min_compactness']:record['rejection_reasons'].append('insufficient_compactness')
        if any(r['geometry'].area>max_area and r['geometry'].intersection(seed).area>=seed.area*.5 for r in regions):
            record['rejection_reasons'].append('seed_is_corner_fragment_of_major_roof_plane')
        if record['rejection_reasons']:
            candidates.append(record);continue
        # Expand a raster cap to its complete nearby source roof patches. Do not
        # swallow a whole large roof plane merely because one pixel touches it.
        expanded=seed.buffer(cfg['mask_buffer_m']).intersection(domain)
        base_height=float(np.median(grid['z'][iy,ix]-grid['relief'][iy,ix]))
        joined=[r['geometry'] for r in regions if r['geometry'].area<=max_area
                and float(np.asarray([*r['geometry'].representative_point().coords[0],1.])@r['plane'])>=base_height+.6
                and r['geometry'].intersection(expanded).area/max(r['geometry'].area,1e-9)>=.35]
        joined_union=unary_union(joined) if joined else Polygon()
        if joined_union.intersection(seed).area>=seed.area*.75:
            mask=joined_union.intersection(domain)
        else:
            mask=unary_union([expanded,*joined]).intersection(domain).simplify(.08,preserve_topology=True).intersection(domain)
        if mask.geom_type!='Polygon' or not mask.is_valid or mask.area>max_area:
            record['rejection_reasons'].append('expanded_mask_exceeds_small_component_gate');candidates.append(record);continue
        support = roof_support & shapely.intersects_xy(mask,points[:,0],points[:,1]) & (points[:,2]>=base_height+.6)
        record.update({'polygon':mapping(mask),'area_m2':float(mask.area),
                       'train_roof_support_points':int(support.sum()),
                       'top_z_m':float(np.percentile(points[support,2],99)) if support.any() else None,
                       'base_z_m':base_height})
        if support.sum()<cfg['min_train_support']:
            record['rejection_reasons'].append('insufficient_roof_train_support')
        else:
            record['status']='detected'
        candidates.append(record)
    selected=[]
    for candidate in sorted((c for c in candidates if c['status']=='detected'),
                            key=lambda c:(-c['prominence_max_m'],c['id'])):
        mask=shape(candidate['polygon'])
        if len(selected)>=cfg['max_components']:
            candidate['status']='rejected';candidate['rejection_reasons'].append('bounded_component_budget')
        elif any(mask.intersection(shape(other['polygon'])).area>1e-7 for other in selected):
            candidate['status']='rejected';candidate['rejection_reasons'].append('overlapping_candidate')
        else:selected.append(candidate)
    return {'candidates':candidates,'domain':domain,'regions':regions,'grid_cell_m':grid['cell'],
            'grid_cells':int(grid['valid'].size),'detected_count':len(selected)}


def _boundary_samples(polygon, spacing=.20):
    points=[]
    for p in _polygons(polygon):
        for ring in [p.exterior,*p.interiors]:
            n=max(8,int(np.ceil(ring.length/spacing)))
            points.extend(ring.interpolate(i/n,normalized=True).coords[0] for i in range(n))
    return np.asarray(points,dtype=float)


def _clip_regions(regions, region):
    result=[]
    for r in regions:
        for polygon in _polygons(r['geometry'].intersection(region)):
            if polygon.area>1e-8:
                result.append({'id':len(result),'geometry':polygon,'plane':r['plane']})
    return result


def _build(regions, domain, source, label):
    regions=[dict(r,id=i) for i,r in enumerate(regions)]
    union=unary_union([r['geometry'] for r in regions])
    overlap=sum(r['geometry'].area for r in regions)-union.area
    if domain.symmetric_difference(union).area>max(1e-6,domain.area*1e-8) or overlap>max(1e-6,domain.area*1e-8):
        raise ValueError('Roof partition changed domain or overlaps')
    v,f,s,edges,steps,jump,ids=_mesh_regions(regions,domain,0.)
    return {'schema':'roof-component-model/1','status':'ok','method':label,'shape':'piecewise_planar_components',
            'vertices':v,'faces':f,'face_semantics':s,'face_region_ids':ids,
            'origin_epsg5514':source.get('origin_epsg5514'),'ground_z':source.get('ground_z',0.),
            'roof_regions':[{'id':i,'polygon':mapping(r['geometry']),'plane':list(r['plane'])} for i,r in enumerate(regions)],
            'structural_edges':edges,'metrics':{'roof_region_count_before_coplanar_cleanup':len(regions),
                'roof_partition_overlap_m2':float(overlap),'roof_domain_change_m2':float(domain.symmetric_difference(union).area),
                'step_wall_segment_count':steps,'max_interface_jump_m':jump},
            'mesh_note':'One roof height-field partition with perimeter and step walls; no interior walls down to ground.'}


def _fit_patch(source,train,mask,domain,cfg):
    surround=mask.buffer(cfg['surround_ring_m']).intersection(domain)
    outer=max(_polygons(surround),key=lambda p:p.area)
    ring=outer.difference(mask.buffer(.10))
    inside=shapely.intersects_xy(ring,train[:,0],train[:,1])
    sample=train[inside]
    if len(sample):
        z=predict_roofer_z(source,sample[:,:2]);sample=sample[np.isfinite(z)&(np.abs(z-sample[:,2])<=.75)]
    if len(sample)<18:raise ValueError('insufficient_surrounding_roof_train_points')
    fitted=fit_roof_models(outer,sample,0.,allow_barrel=False,max_fit_points=cfg['max_template_fit_points'],
                          max_orientations=2,penalty_m=.06,tolerance_m=.5,include_candidate_meshes=True)
    xy=_boundary_samples(mask.buffer(.10).intersection(domain))
    keep=shapely.intersects_xy(outer,xy[:,0],xy[:,1]) & ~shapely.contains_xy(mask,xy[:,0],xy[:,1])
    xy=xy[keep]
    expected=predict_roofer_z(source,xy);valid=np.isfinite(expected);xy=xy[valid];expected=expected[valid]
    if len(xy)<8:raise ValueError('insufficient_safe_patch_boundary')
    approved=[]
    for candidate in fitted.get('candidates',[]):
        if candidate['shape'] not in ('flat','shed','gabled'):continue
        error=np.abs(predict_roof_z(candidate,xy)-expected)
        if np.percentile(error,95)<=cfg['max_patch_boundary_p95_m'] and error.max()<=cfg['max_patch_boundary_error_m']:
            approved.append((candidate['metrics']['selection_score_m'],candidate,error))
    if not approved:raise ValueError('local_roof_infill_boundary_mismatch')
    _,chosen,error=min(approved,key=lambda x:x[0])
    return _clip_regions(_source_regions(chosen),mask), {'shape':chosen['shape'],'params':chosen['params'],
        'surrounding_train_points':len(sample),'boundary_sample_count':len(xy),
        'boundary_p95_m':float(np.percentile(error,95)),'boundary_max_m':float(error.max()),
        'selection':'training-only local flat/shed/gable, then source-boundary continuity gate'}


def _fit_component(source,base,train,mask,cfg):
    sample=train[shapely.intersects_xy(mask,train[:,0],train[:,1])]
    z=predict_roofer_z(source,sample[:,:2]);sample=sample[np.isfinite(z)&(np.abs(z-sample[:,2])<=.75)]
    if len(sample)<cfg['min_train_support']:raise ValueError('insufficient_component_roof_points')
    fitted=fit_roof_models(mask,sample,0.,allow_barrel=False,max_fit_points=cfg['max_template_fit_points'],
                          max_orientations=2,penalty_m=.08,tolerance_m=.5,include_candidate_meshes=True)
    peak=float(np.percentile(sample[:,2],99)); approved=[]
    for candidate in fitted.get('candidates',[]):
        prediction=predict_roof_z(candidate,sample[:,:2]);error=np.abs(prediction-sample[:,2])
        if np.percentile(error,95)>cfg['max_restored_train_p95_m']:continue
        if peak-float(np.percentile(prediction,99))>cfg['max_restored_peak_loss_m']:continue
        vertices=np.asarray(candidate['vertices'])
        base_z=predict_roofer_z(base,vertices[:,:2]);roof_ids={i for f,s in zip(candidate['faces'],candidate['face_semantics']) if s=='roof' for i in f}
        ids=np.asarray(sorted(roof_ids),dtype=int);valid=np.isfinite(base_z[ids])
        if np.any(vertices[ids[valid],2]<base_z[ids[valid]]-.05):continue
        approved.append((candidate['metrics']['selection_score_m'],candidate,error))
    if not approved:raise ValueError('no_simple_component_preserves_training_shape_and_height')
    _,chosen,error=min(approved,key=lambda x:x[0])
    return _clip_regions(_source_regions(chosen),mask), {'shape':chosen['shape'],'params':chosen['params'],
        'train_points':len(sample),'train_p95_m':float(np.percentile(error,95)),
        'reference_train_peak99_m':peak,'fitted_train_peak99_m':float(np.percentile(predict_roof_z(chosen,sample[:,:2]),99))}


def extract_components(model, train_relative, footprint, config):
    """Return independently reviewable patched base and simplified restoration."""
    started=time.perf_counter(); cfg=dict(config)
    train=np.asarray(train_relative,dtype=float)
    train=train[np.isfinite(train).all(axis=1)]
    detected=detect_components(model,train,footprint,cfg)
    detection_finished=time.perf_counter()
    candidates=detected['candidates'];domain=detected['domain'];regions=detected['regions']
    accepted=[]; patches=[]
    for record in candidates:
        if record['status']!='detected':continue
        mask=shape(record['polygon'])
        try:
            infill,audit=_fit_patch(model,train,mask,domain,cfg)
            record['patch']=audit;record['status']='accepted';accepted.append(record);patches.extend(infill)
        except (ValueError,shapely.errors.GEOSException) as error:
            record['status']='rejected';record['rejection_reasons'].append(str(error))
    removal=unary_union([shape(r['polygon']) for r in accepted]) if accepted else Polygon()
    base_regions=_clip_regions(regions,domain.difference(removal))+patches
    patched=_build(base_regions,domain,model,'component_patch') if accepted else deepcopy(model)
    patch_finished=time.perf_counter()
    before_simplify=time.perf_counter()
    # The same simplified base is used by both outputs. This avoids crediting
    # component restoration with an unrelated different main-roof fit.
    patched=simplify_roof(patched,None,footprint,max_vertical_change_m=cfg['base_merge_vertical_m'],
                         max_normal_angle_deg=cfg['base_merge_angle_deg'])
    merge_seconds=time.perf_counter()-before_simplify
    patched['method']='component_patch_simplified_base'
    restored_regions=_source_regions(patched); restored=[]
    for record in accepted:
        mask=shape(record['polygon'])
        try:
            component,audit=_fit_component(model,patched,train,mask,cfg)
            remaining=_clip_regions(restored_regions,domain.difference(mask))
            tentative=_build(remaining+component,domain,model,'component_restored')
            restored_regions=_source_regions(tentative)
            record['restoration']=audit;record['restored']=True;restored.append(record)
        except (ValueError,shapely.errors.GEOSException) as error:
            # Keep the original component when its simple surrogate is unsafe.
            # This protects identity rather than silently deleting a tower.
            original_component=_clip_regions(regions,mask)
            remaining=_clip_regions(restored_regions,domain.difference(mask))
            tentative=_build(remaining+original_component,domain,model,'component_restored_original_fallback')
            restored_regions=_source_regions(tentative)
            record['restored']=False;record['restoration_error']=str(error);record['retained_original_component']=True
    restored_model=_build(restored_regions,domain,model,'component_restored') if accepted else deepcopy(patched)
    restoration_finished=time.perf_counter()
    masks=[{k:r.get(k) for k in ['id','polygon','status','kind','label','base_z_m','top_z_m']} for r in candidates]
    count=len(accepted)
    for output,purpose in [(patched,'intentional_feature_removal_diagnostic'),(restored_model,'simple_features_returned_or_original_retained')]:
        output['component_masks']=masks;output['component_audit']=deepcopy(candidates)
        output['configuration']=cfg;output['purpose']=purpose
        output.setdefault('metrics',{}).update({'detected_component_count':detected['detected_count'],
            'accepted_patch_count':count,'restored_component_count':len(restored),
            'original_component_fallback_count':count-len(restored),
            'grid_cell_m':detected['grid_cell_m'],'grid_cells':detected['grid_cells'],
            'component_mask_area_m2':float(removal.area),'source_roof_region_count':len(regions),
            'patched_base_region_count':patched['metrics'].get('actual_roof_region_count')})
    return {'schema':'roof-component-extraction/1','status':'ok' if count else 'no_safe_component',
            'models':{'patched':patched,'restored':restored_model},'component_masks':masks,
            'candidates':candidates,'configuration':cfg,
            'timing':{'total_seconds':time.perf_counter()-started,'base_merge_seconds':merge_seconds,
                      'detection_seconds':detection_finished-started,
                      'patch_fit_and_build_seconds':patch_finished-detection_finished,
                      'restoration_seconds':restoration_finished-before_simplify-merge_seconds},
            'holdout_used':False,'notes':['Detections are geometric protrusions, not semantic identification of towers/chimneys.',
                'Patched output intentionally removes features; restored output uses the same simplified main roof.',
                'Unsafe simple replacements retain original component geometry rather than silently erase it.']}


def run_selected():
    import roof_simplification_common as common
    import resource_guard as guard
    dest=common.ROOT/'cities/ceske-budejovice/experiments/roof-components'
    if (dest/'extraction-results.json').exists():
        import shutil
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
        archive=common.ROOT/'.work/cb-roof-components/extraction-previous'/stamp
        archive.mkdir(parents=True,exist_ok=False)
        for name in ['extraction-results.json','extraction-protocol.json']:
            if (dest/name).exists():shutil.copyfile(dest/name,archive/name)
    provenance=common.snapshot([Path(__file__),common.ROOT/'scripts/roof_simplification_common.py',
        common.ROOT/'scripts/roof_simplify_planes.py',common.ROOT/'scripts/roof_pilot_methods.py',
        common.ROOT/'scripts/roof_pilot_roofer.py'],'components-extraction')
    started=time.perf_counter();cases=common.load_cases()
    originals={r['id']:r for r in common.baseline_rows() if r['variant']=='roofer_lod22_reference'}
    document={'schema':'roof-component-extraction-comparison/1','status':'running','runs':[],
        'created_at':datetime.now(timezone.utc).isoformat(),'source_code':provenance,
        'input_manifest_sha256':guard.sha256(common.MANIFEST),'profiles':PROFILES,
        'source':'dmpok','holdout_used_for_fitting':False,'comparison_repetitions':1}
    common.write(dest/'extraction-protocol.json',{'profiles':PROFILES,'source_code':provenance,
        'fitting':'Original c0.888 geometry plus roof-support TRAIN points only; holdout is evaluation-only.',
        'repetitions':1,'written_before_measured_comparison':True})
    for identifier,case in cases.items():
        for profile,cfg in PROFILES.items():
            print('Extracting',case['name'],profile,flush=True);guard.check_budget()
            original=originals[identifier]
            try:
                output=extract_components(original['model'],case['train_relative'],case['polygon'],cfg)
                for stage,model in output['models'].items():
                    metrics=dict(model.get('metrics',{}));metrics.update(common.evaluate_model(model,case))
                    row={'id':identifier,'pilot_id':case['pilot_id'],'name':case['name'],
                        'variant':f'extract_{profile}_{stage}','source':'dmpok','status':output['status'],
                        'model':model,'metrics':metrics,'component_masks':output['component_masks'],
                        'component_audit':output['candidates'],'configuration':cfg,
                        'parent_variant':'roofer_lod22_reference','parent_extrusion_mode':original['model'].get('attributes',{}).get('rf_extrusion_mode'),
                        'timing':{'seconds':output['timing']['total_seconds'],'repetitions':1,
                            'base_merge_seconds':output['timing']['base_merge_seconds'],
                            'stages_seconds':output['timing'],
                            'scope':'whole paired extraction+patch+base merge+restoration; shared by both outputs, do not add rows'},
                        'review':{'status':'review','note':('Nebyla nalezena bezpečná komponenta k vyčlenění; proběhlo pouze konzervativní sloučení původních rovin.' if not metrics['accepted_patch_count'] else
                            'Diagnostika: výstupky byly záměrně odstraněny a hlavní střecha zaplněna.' if stage=='patched' else
                            'Výstupky vráceny jako jednoduché díly; při nejistém náhradním tvaru se zachová původní komponenta.')},
                        'no_component_extracted':not metrics['accepted_patch_count'],
                        'base_simplification_still_applied':True}
                    document['runs'].append(row)
            except (ValueError,shapely.errors.GEOSException) as error:
                for stage in ['patched','restored']:
                    document['runs'].append({'id':identifier,'pilot_id':case['pilot_id'],'name':case['name'],
                        'variant':f'extract_{profile}_{stage}','source':'dmpok','status':'unsupported',
                        'error':str(error),'model':deepcopy(original['model']),
                        'metrics':common.evaluate_model(original['model'],case),
                        'configuration':cfg,'component_masks':[],
                        'review':{'status':'rejected','note':'Metoda nezvládla bezpečně sestavit geometrii; zobrazen původní model.'}})
            common.write(dest/'extraction-results.json',document)
    document['status']='complete';document['elapsed_seconds']=time.perf_counter()-started
    for relative,expected in provenance['sha256'].items():
        if guard.sha256(common.ROOT/relative)!=expected:raise ValueError('Implementation changed while measuring')
    common.write(dest/'extraction-results.json',document)
    print('Saved',len(document['runs']),'extraction rows',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.execute:run_selected()
    else:parser.print_help()
