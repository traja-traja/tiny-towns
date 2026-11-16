"""Split main roof volumes at persistent vertical steps, then fit simple roofs.

The geometry graph deliberately does not split continuous gable ridges. Small
or sparsely sampled components retain their source geometry. This experimental
method uses TRAIN points only; it never uses holdout to partition or fit.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import shapely
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

import roof_pilot_methods as templates
from roof_pilot_roofer import predict_roofer_z
from roof_simplify_planes import extract_roof_regions, _mesh_regions, _polygons, _line_segments, _z


SETTINGS = {
    'step_thresholds_m': [0.75, 1.50],
    'minimum_step_fraction': 0.60,
    'edge_samples_per_segment': 9,
    'minimum_main_area_m2': 6.0,
    'minimum_main_area_fraction': 0.02,
    'minimum_fit_points': 30,
    'maximum_main_volumes': 8,
    'maximum_total_components': 64,
    'maximum_fit_points': 1500,
    'maximum_orientations': 2,
    'maximum_scoring_points_per_part': 6000,
    'template_penalty_m': 0.04,
    'template_tolerance_m': 0.50,
    'allow_barrel': True,
    'maximum_source_gap_area_fraction': 0.001,
    'maximum_source_gap_area_m2': 1.0,
    'maximum_source_gap_distance_m': 0.05,
    'source_plane_tolerance_m': 0.003,
    'source_plane_angle_deg': 0.25,
}


def _roof_domain(model):
    vertices = np.asarray(model['vertices'], float)
    return unary_union([Polygon(vertices[f, :2]) for f, semantic in
                        zip(model['faces'], model['face_semantics']) if semantic == 'roof'])


def _normalised_regions(model, footprint):
    """Clip millimetre-quantised source roofs to the frozen footprint.

    Only tiny source-domain gaps (<=0.1% and <=1m2, <=5cm reach) may be filled
    with the nearest source plane. Courtyard holes always remain excluded.
    """
    raw = extract_roof_regions(model,
        tolerance_m=SETTINGS['source_plane_tolerance_m'], angle_deg=SETTINGS['source_plane_angle_deg'])
    regions = []
    for record in raw['regions']:
        clipped = shape(record['polygon']).intersection(footprint)
        for polygon in _polygons(clipped):
            if polygon.area > 1e-8:
                regions.append({'id':len(regions),'geometry':polygon,
                                'plane':np.asarray(record['plane'],float),
                                'source_region_id':record['id']})
    domain = unary_union([r['geometry'] for r in regions])
    gap = footprint.difference(domain)
    maximum_area = min(SETTINGS['maximum_source_gap_area_m2'],
                       footprint.area * SETTINGS['maximum_source_gap_area_fraction'])
    if gap.area > maximum_area + 1e-8:
        raise ValueError('Source roof has a material footprint gap; no invented infill')
    fill_records = []
    for polygon in _polygons(gap):
        if polygon.area < 1e-9:
            continue
        vertices = np.asarray(polygon.exterior.coords)
        reach = max(shapely.Point(p).distance(domain) for p in vertices)
        if reach > SETTINGS['maximum_source_gap_distance_m']:
            raise ValueError('Source roof gap exceeds the declared spatial bound')
        nearest = min(regions, key=lambda r:(r['geometry'].distance(polygon.representative_point()),r['id']))
        regions.append({'id':len(regions),'geometry':polygon,
                        'plane':nearest['plane'].copy(),'source_region_id':nearest['source_region_id']})
        fill_records.append({'area_m2':polygon.area,'reach_m':reach,'plane_from_region':nearest['id']})
    union = unary_union([r['geometry'] for r in regions])
    if union.symmetric_difference(footprint).area > max(1e-7,footprint.area*1e-9):
        raise ValueError('Normalised source partition does not cover the frozen footprint')
    overlap = sum(r['geometry'].area for r in regions)-union.area
    if overlap > max(1e-7,footprint.area*1e-9):
        raise ValueError('Source roof regions overlap')
    return regions, {'source_region_count':raw['region_count'],
                     'source_roof_outside_footprint_m2':_roof_domain(model).difference(footprint).area,
                     'tiny_gap_fills':fill_records,'normalised_region_count':len(regions)}


def partition_roof(model, footprint, *, step_threshold_m=0.75):
    if step_threshold_m not in SETTINGS['step_thresholds_m']:
        raise ValueError('Use one of the two frozen step thresholds')
    regions, normalisation = _normalised_regions(model,footprint)
    parents = list(range(len(regions)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    def join(a,b):
        a,b=find(a),find(b)
        if a!=b:
            parents[max(a,b)]=min(a,b)
    polygons=[r['geometry'] for r in regions]
    tree=STRtree(polygons)
    edges=[]
    for i,p in enumerate(polygons):
        for j0 in tree.query(p):
            j=int(j0)
            if j<=i:
                continue
            shared=p.boundary.intersection(polygons[j].boundary)
            if shared.length <= 1e-6:
                continue
            gaps,weights=[],[]
            for a,b in _line_segments(shared):
                length=float(np.linalg.norm(b-a))
                # Interior sample locations make each sample's represented length equal.
                fractions=(np.arange(SETTINGS['edge_samples_per_segment'])+.5)/SETTINGS['edge_samples_per_segment']
                xy=a[None,:]+fractions[:,None]*(b-a)[None,:]
                gaps.extend(np.abs(_z(regions[i]['plane'],xy)-_z(regions[j]['plane'],xy)).tolist())
                weights.extend([length/len(xy)]*len(xy))
            gaps=np.asarray(gaps); weights=np.asarray(weights)
            fraction=float(weights[gaps>=step_threshold_m].sum()/weights.sum())
            cut=fraction>=SETTINGS['minimum_step_fraction']
            if not cut:
                join(i,j)
            edges.append({'left_region':i,'right_region':j,'shared_boundary_m':float(shared.length),
                          'length_fraction_above_threshold':fraction,
                          'maximum_height_gap_m':float(gaps.max()),
                          'mean_height_gap_m':float(np.average(gaps,weights=weights)),
                          'decision':'vertical_step_barrier' if cut else 'continuous_or_weak_boundary'})
    groups={}
    for i in range(len(regions)):
        groups.setdefault(find(i),[]).append(i)
    components=[]
    for indices in groups.values():
        union=unary_union([polygons[i] for i in indices]).simplify(1e-8,preserve_topology=True)
        for polygon in _polygons(union):
            related=[i for i in indices if polygons[i].intersection(polygon).area>1e-8]
            components.append({'geometry':polygon,'source_region_indices':related})
    components.sort(key=lambda c:(-c['geometry'].area,c['geometry'].centroid.x,c['geometry'].centroid.y))
    for i,c in enumerate(components):
        c['id']=i
    # A barrier can have an alternate continuous graph path; disclose that case.
    for edge in edges:
        edge['separates_components']=find(edge['left_region'])!=find(edge['right_region'])
    return {'regions':regions,'components':components,
            'audit':{'normalisation':normalisation,'edges':edges,
                     'component_count':len(components),'step_threshold_m':step_threshold_m,
                     'partition_reason':'Connected source roof regions after removing persistent vertical-step adjacencies; continuous ridges remain joined.',
                     'barriers_with_alternate_path':sum(e['decision']=='vertical_step_barrier' and not e['separates_components'] for e in edges)}}


def _train_points(poly,points):
    points=np.asarray(points,float)
    if points.ndim!=2 or points.shape[1]!=3:
        raise ValueError('Expected training XYZ')
    points=points[np.isfinite(points).all(axis=1)]
    points=points[shapely.intersects_xy(poly,points[:,0],points[:,1])]
    order=np.lexsort((points[:,2],points[:,1],points[:,0]))
    return points[order]


def _source_component_regions(partition,component):
    result=[]
    for index in component['source_region_indices']:
        source=partition['regions'][index]
        for polygon in _polygons(source['geometry'].intersection(component['geometry'])):
            if polygon.area>1e-8:
                result.append({'geometry':polygon,'plane':source['plane'].copy(),'volume_id':component['id']})
    return result


def _serial_component(component,source_regions):
    heights=np.concatenate([_z(r['plane'],np.asarray(r['geometry'].exterior.coords)) for r in source_regions])
    return {'id':component['id'],'polygon':mapping(component['geometry']),
            'area_m2':component['geometry'].area,'source_region_indices':component['source_region_indices'],
            'base_z_m':float(heights.min()),'top_z_m':float(heights.max())}


def fit_volume_candidate(case,baseline_model,*,step_threshold_m=0.75):
    started=time.perf_counter()
    footprint=case['polygon']
    if not isinstance(footprint,Polygon) or not footprint.is_valid:
        raise ValueError('Expected valid frozen Polygon')
    partition=partition_roof(baseline_model,footprint,step_threshold_m=step_threshold_m)
    train=_train_points(footprint,case['train_relative'])
    minimum_area=max(SETTINGS['minimum_main_area_m2'],footprint.area*SETTINGS['minimum_main_area_fraction'])
    parts=[]
    for component in partition['components']:
        points=_train_points(component['geometry'],train)
        source_regions=_source_component_regions(partition,component)
        record=_serial_component(component,source_regions)
        record['is_main_volume']=component['geometry'].area>=minimum_area
        reason=('small_component' if component['geometry'].area<minimum_area else
                'sparse_training_points' if len(points)<SETTINGS['minimum_fit_points'] else None)
        parts.append({'component':component,'points':points,'source_regions':source_regions,
                      'record':record,'preserve_reason':reason})
    mains=sum(p['record']['is_main_volume'] for p in parts)
    fit_eligible=sum(p['preserve_reason'] is None for p in parts)
    budget_ok=mains<=SETTINGS['maximum_main_volumes'] and len(parts)<=SETTINGS['maximum_total_components']
    if not budget_ok:
        for p in parts:
            p['preserve_reason']='component_budget_exceeded'
    new_regions=[]
    masks=[]
    fit_seconds=0.0
    for part in parts:
        component,points,record=part['component'],part['points'],part['record']
        model=None
        record['training_points']=len(points)
        if part['preserve_reason'] is None:
            scoring=points
            if len(scoring)>SETTINGS['maximum_scoring_points_per_part']:
                ids=np.sort(np.random.default_rng(37).choice(len(scoring),SETTINGS['maximum_scoring_points_per_part'],replace=False))
                scoring=scoring[ids]
            fitted=templates.fit_roof_models(component['geometry'],scoring,0.0,
                allow_barrel=SETTINGS['allow_barrel'],max_fit_points=SETTINGS['maximum_fit_points'],
                max_orientations=SETTINGS['maximum_orientations'],penalty_m=SETTINGS['template_penalty_m'],
                tolerance_m=SETTINGS['template_tolerance_m'])
            fit_seconds+=fitted['timing']['total_seconds']
            model=fitted.get('best')
            record['fit_seconds']=fitted['timing']['total_seconds']
            record['scoring_points']=len(scoring)
            if model is None or not model.get('faces'):
                part['preserve_reason']='no_valid_template'
            else:
                fitted_regions=extract_roof_regions(model)
                local=[{'geometry':shape(r['polygon']),'plane':np.asarray(r['plane']),
                        'volume_id':component['id']} for r in fitted_regions['regions']]
                if unary_union([r['geometry'] for r in local]).symmetric_difference(component['geometry']).area>max(1e-6,footprint.area*1e-9):
                    part['preserve_reason']='template_domain_mismatch'
                else:
                    predicted=predict_roofer_z(model,points[:,:2])
                    valid=np.isfinite(predicted)
                    errors=predicted[valid]-points[valid,2]
                    record['training_actual_mesh_rmse_m']=float(np.sqrt(np.mean(errors**2))) if len(errors) else None
                    record['training_actual_mesh_within_05_fraction']=float(np.sum(np.abs(errors)<=.5)/len(points)) if len(points) else None
                    record['shape']=model['shape']
                    record['params']=deepcopy(model['params'])
                    record['template_regions']=len(local)
                    new_regions.extend(local)
        if part['preserve_reason'] is not None:
            new_regions.extend(part['source_regions'])
            record['shape']='preserved_source_regions'
        record['decision']='preserved_source' if part['preserve_reason'] is not None else 'fitted_template'
        record['preserve_reason']=part['preserve_reason']
        masks.append({'id':component['id'],'polygon':record['polygon'],'status':'accepted',
                      'kind':'volume','label':f"Objem {component['id']+1}: "+record['shape'],
                      'base_z_m':record['base_z_m'],'top_z_m':record['top_z_m'],
                      'decision':record['decision']})
    for i,region in enumerate(new_regions):
        region['id']=i
    domain=unary_union([r['geometry'] for r in new_regions])
    missing=footprint.difference(domain).area
    outside=domain.difference(footprint).area
    overlap=sum(r['geometry'].area for r in new_regions)-domain.area
    if max(missing,outside,overlap)>max(1e-6,footprint.area*1e-9):
        raise ValueError('Final roof partition does not preserve footprint and holes')
    vertices,faces,semantics,edges,steps,max_jump,face_region_ids=_mesh_regions(new_regions,domain,0.0)
    parent_fallback=baseline_model.get('attributes',{}).get('rf_extrusion_mode')=='lod11_fallback'
    model={'schema':'roof-component-volumes/1','id':case.get('id'),'method':'height_step_volume_templates',
           'status':'ok','shape':'partitioned_templates_with_protected_small_parts',
           'vertices':vertices,'faces':faces,'face_semantics':semantics,
           'face_region_ids':face_region_ids,'structural_edges':edges,
           'face_component_ids':[new_regions[i]['volume_id'] if i>=0 else -1 for i in face_region_ids],
           'roof_regions':[{'id':r['id'],'polygon':mapping(r['geometry']),'plane':r['plane'].tolist(),
                            'volume_id':r['volume_id']} for r in new_regions],
           'component_masks':masks,'volume_components':[p['record'] for p in parts],
           'configuration':dict(SETTINGS,step_threshold_m=step_threshold_m),
           'metrics':{'main_volume_count':mains,'fit_eligible_main_volume_count':fit_eligible,'component_count':len(parts),
                      'fitted_volume_count':sum(p['record']['decision']=='fitted_template' for p in parts),
                      'preserved_small_component_count':sum(p['preserve_reason']=='small_component' for p in parts),
                      'preserved_component_count':sum(p['record']['decision']=='preserved_source' for p in parts),
                      'actual_roof_region_count':len(new_regions),'step_wall_segment_count':steps,
                      'max_interface_jump_m':max_jump,'roof_missing_area_m2':missing,
                      'roof_outside_area_m2':outside,'roof_overlap_area_m2':overlap},
           'partition_audit':partition['audit'],
           'partition_source_fallback':parent_fallback,
           'warnings':['Volume boundaries come from the original reconstruction, not independent observation.',
                       'Simple template fits are experimental candidates; training error is recorded but no holdout-based acceptance is used.',
                       'Continuous intersections of different building wings may remain one graph component.'],
           'mesh_note':'Single non-overlapping roof partition with outer walls and local vertical step walls; no full-height duplicate internal volume walls.',
           'fitting_inputs':'Original roof mesh for partition; frozen TRAIN points only for template fitting.'}
    if parent_fallback:
        model['warnings'].append('Source reconstruction is a LoD1.1 fallback; volume partition is uninformative. A new whole-footprint template was fit to TRAIN points.')
    for key in ['origin_epsg5514','ground_z','coordinates']:
        if key in baseline_model:
            model[key]=deepcopy(baseline_model[key])
    return {'model':model,'status':'ok' if budget_ok else 'preserved_budget_exceeded',
            'timing':{'seconds':time.perf_counter()-started,'template_solver_seconds':fit_seconds,
                      'scope':'partition graph, fitting and unified mesh construction; excludes original Roofer and common holdout evaluation',
                      'repetitions':1}}


def fit_volume_candidates(case,baseline_model):
    return [fit_volume_candidate(case,baseline_model,step_threshold_m=t) for t in SETTINGS['step_thresholds_m']]


def run_selected():
    import roof_simplification_common as common
    import resource_guard as guard
    destination=common.ROOT/'cities/ceske-budejovice/experiments/roof-components'
    destination.mkdir(parents=True,exist_ok=True)
    provenance=common.snapshot([Path(__file__),common.ROOT/'scripts/roof_simplify_planes.py',
        common.ROOT/'scripts/roof_pilot_methods.py',common.ROOT/'scripts/roof_pilot_roofer.py',
        common.ROOT/'scripts/roof_simplification_common.py',common.ROOT/'scripts/resource_guard.py'],'volume-components')
    started=time.perf_counter()
    cases=common.load_cases()
    source_path=common.ROOT/'cities/ceske-budejovice/experiments/roof-simplification/results.json'
    reference={r['id']:r for r in common.read(source_path)['runs'] if r['variant']=='roofer_lod22_reference'}
    document={'schema':'roof-component-volumes-comparison/1','status':'running',
              'created_at':datetime.now(timezone.utc).isoformat(),'source':'dmpok',
              'settings':SETTINGS,'runs':[],'source_code':provenance,
              'input_manifest_sha256':guard.sha256(common.MANIFEST),
              'baseline_results_sha256':guard.sha256(source_path),
              'holdout_used_for_fitting':False,'production_map_modified':False,
              'resource_before':guard.check_budget(force=True)}
    for case in cases.values():
        for threshold in SETTINGS['step_thresholds_m']:
            variant='volume_steps_'+('075' if threshold==.75 else '150')
            print(case['name'],variant,flush=True)
            try:
                output=fit_volume_candidate(case,reference[case['id']]['model'],step_threshold_m=threshold)
                model=output['model']
                metrics=dict(model['metrics'])
                metrics.update(common.evaluate_model(model,case))
                row={'id':case['id'],'pilot_id':case['pilot_id'],'name':case['name'],'variant':variant,
                     'source':'dmpok','model':model,'status':output['status'],'metrics':metrics,
                     'timing':output['timing'],'component_masks':model['component_masks'],
                     'partition_audit':model['partition_audit'],'configuration':model['configuration']}
                print('  components',metrics['component_count'],'main',metrics['main_volume_count'],
                      'fitted',metrics['fitted_volume_count'],'RMSE',metrics['holdout_rmse_m'],flush=True)
            except (ValueError,shapely.errors.GEOSException,np.linalg.LinAlgError) as error:
                row={'id':case['id'],'pilot_id':case['pilot_id'],'name':case['name'],'variant':variant,
                     'source':'dmpok','model':None,'status':'unsupported','error':str(error),'metrics':{},
                     'timing':{'repetitions':1,'scope':'failed experiment; no measured method time claimed'}}
                print('  unsupported',error,flush=True)
            document['runs'].append(row)
            common.write(destination/'volumes-results.json',document)
    for rel,expected in provenance['sha256'].items():
        if guard.sha256(common.ROOT/rel)!=expected:
            raise ValueError('Source changed during measured run: '+rel)
    document.update({'status':'complete','elapsed_seconds':time.perf_counter()-started,
                     'resource_after':guard.check_budget(force=True)})
    common.write(destination/'volumes-results.json',document)
    print('Saved',destination/'volumes-results.json',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.execute:
        run_selected()
    else:
        parser.print_help()
