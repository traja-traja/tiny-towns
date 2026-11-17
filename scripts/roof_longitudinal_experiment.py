"""Local single-building comparison: longitudinal partition + original roofs.

No straight skeleton, network calls, manual cut coordinates or AI evaluation.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, math, os, time
from pathlib import Path
from datetime import datetime, timezone
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[k]='1'
import numpy as np
import shapely
from shapely.geometry import shape
from shapely.geometry.polygon import orient
import atomic_io
import resource_guard as guard
from roof_longitudinal_split import detect_longitudinal_split
from roof_annex import infer_modular_roof
from roof_config import ALGORITHM_VERSION
from roof_v2 import _cells, _lines, predict_regions, residual_stats
from roof_v2_geometry import build_mesh
from roof_v2_report import render_report

VERSION='longitudinal-split-original-roofs-0.3'
CHILD_ROOF_CONFIG={'modules':{'annex_detection':False,'annex_profiles':False,'footprint_regularization':False,'footprint_connector':False}}
CHILD_POLICY={'split_depth':1,'max_split_depth':1,'volume_splitting_enabled':False,'footprint_connector_enabled':False,
              'annex_detection_enabled':False,'roof_generator':ALGORITHM_VERSION}

def write(path,data):
    def convert(v):
        if isinstance(v,np.generic):return v.item()
        if isinstance(v,np.ndarray):return v.tolist()
        raise TypeError(type(v).__name__)
    atomic_io.write_text(path,json.dumps(data,ensure_ascii=False,allow_nan=False,default=convert,separators=(',',':')))

def boundary_diagnostics(footprint,result):
    """Measured model boundary heights; sloping gable ends are not called eaves."""
    poly=orient(shape(footprint) if isinstance(footprint,dict) else footprint,sign=1)
    records=[]
    for ring_index,ring in enumerate([poly.exterior,*poly.interiors]):
        q=np.asarray(ring.coords)
        for edge_index,(a,b) in enumerate(zip(q[:-1],q[1:])):
            length=float(np.linalg.norm(b-a))
            if length<8:continue
            u=(b-a)/length;inside=np.array([-u[1],u[0]])
            xy=a+np.linspace(.05,.95,31)[:,None]*(b-a)+inside*.0001
            z=predict_regions(result['model']['regions'],xy);z=z[np.isfinite(z)]
            if not len(z):continue
            records.append(dict(ring_index=ring_index,edge_index=edge_index,length_m=length,
                direction_deg=float(math.degrees(math.atan2(u[1],u[0]))%180),
                min_height_m=float(z.min()),max_height_m=float(z.max()),height_span_m=float(np.ptp(z))))
    return dict(note='Actual roof heights along long footprint edges; some are gable ends, not eaves.',edges=records)

def fit_partition(poly,train,proposal,config=None):
    start=time.perf_counter();regions=[];bodies=[];children=[]
    child_config=copy.deepcopy(config or {})
    child_config.setdefault('modules',{}).update(CHILD_ROOF_CONFIG['modules'])
    for i,footprint in enumerate(proposal['footprints']):
        body=shape(footprint);mask=shapely.intersects_xy(body,train[:,0],train[:,1])
        print(json.dumps({'stage':'fit_body','index':i,'area_m2':body.area}),flush=True)
        # One-way call into the original fitter: it never calls this detector.
        # Also disable its small-annex divider for every already separated body.
        result=infer_modular_roof(footprint,train[mask],config=child_config)
        result['model'].setdefault('metadata',{})['child_volume_policy']=CHILD_POLICY
        result['model']['metadata']['long_boundary_diagnostics']=boundary_diagnostics(footprint,result)
        children.append(result)
        print(json.dumps({'stage':'body_done','index':i,'seconds':result['timing']['total_seconds']}),flush=True)
        if not result['model']['mesh']['diagnostics']['valid']:raise ValueError('Invalid body mesh')
        fitted=copy.deepcopy(result['model']['regions'])
        for r in fitted:r['volume_index']=i
        regions.extend(fitted)
        bodies.append(dict(index=i,area_m2=body.area,footprint=footprint,train_points=int(mask.sum()),
            roof_type=result['model']['type'],algorithm=result['algorithm'],
            metadata=result['model'].get('metadata'),timing=result['timing'],configuration=result['configuration']))
    mesh=build_mesh(poly,regions)
    if not mesh['diagnostics']['valid']:raise ValueError('Invalid combined mesh')
    heights=[]
    for r in regions:
        xy=shapely.get_coordinates(shape(r['polygon']));heights.extend((np.c_[xy,np.ones(len(xy))]@r['plane']).tolist())
    floor,top=min(heights),max(heights)
    model=dict(type='compound',mesh=mesh,regions=regions,height_range_m=[floor,top],
        metadata=dict(volume_count=len(bodies),bodies=bodies,footprint_modified=False,child_volume_policy=CHILD_POLICY,
            ridge_kind='independent_height_volumes',ridge_height_m=top,eave_height_m=floor,
            roof_height_m=top-floor,split_proposal=proposal))
    model['ridge_lines'],model['eave_lines'],model['roof_boundary_lines']=_lines(model,poly)
    model['valley_lines']=[copy.deepcopy(line) for child in children for line in child['model'].get('valley_lines',[])]
    return dict(algorithm=VERSION,model=model,candidates=[],diagnostics={},timing={'total_seconds':time.perf_counter()-start},_child_results=children)

def compare_metrics(variants,points):
    cells=_cells(points,.6)
    preds={k:predict_regions(v['model']['regions'],cells[:,:2]) for k,v in variants.items()}
    common=np.logical_and.reduce([np.isfinite(p) for p in preds.values()])
    return dict(total_cells=len(cells),shared_cells=int(common.sum()),variants={k:dict(
        supported_cells=int(np.isfinite(p).sum()),**residual_stats(p[common]-cells[common,2])) for k,p in preds.items()})

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',required=True,type=Path,help='Frozen wrapper JSON with baseline part')
    ap.add_argument('--cache',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--config',type=Path)
    ap.add_argument('--previous',type=Path,help='Previous comparison.json; display selected old split unchanged')
    ap.add_argument('--extra-volume-penalty',type=float,default=.10)
    args=ap.parse_args();output=args.output.resolve()
    if args.extra_volume_penalty<0:raise ValueError('Volume penalty must be nonnegative')
    if output.exists() and any(output.iterdir()):raise ValueError('Use an empty versioned output directory')
    resources=guard.check_budget(force=True)
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('roof_*.py')}
    output.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    source=json.loads(args.source.read_text(encoding='utf-8'));building=copy.deepcopy(source.get('building',source))
    baseline=next(p for p in building['parts'] if p.get('display_variant')=='baseline')
    if baseline['result']['algorithm']!='modular-roofs-4.9.1':raise ValueError('Expected original 4.9.1 baseline')
    cache_bytes=args.cache.read_bytes();digest=hashlib.sha256(cache_bytes).hexdigest()
    expected=baseline.get('cache',{}).get('sha256')
    if expected and digest!=expected:raise ValueError('Input cache checksum mismatch')
    (output/'input.npz').write_bytes(cache_bytes)
    with np.load(args.cache) as data:train=data['train'];holdout=data['holdout']
    config=json.loads(args.config.read_text(encoding='utf-8')) if args.config else None
    poly=shape(baseline['footprint'])
    detection=detect_longitudinal_split(poly,train,config)
    write(output/'profiles.json',detection)
    variants={'baseline':copy.deepcopy(baseline['result'])};errors={}
    if args.previous:
        previous=json.loads(args.previous.read_text(encoding='utf-8'))
        old_building=next(b for b in previous['buildings'] if b['id']==building['id'])
        old_selected=old_building['parts'][0]['result']['model']['metadata']['experiment_decision']['selected_variant']
        old_part=next(p for p in old_building['parts'] if p['display_variant']==old_selected)
        if old_part.get('cache',{}).get('sha256')!=digest:raise ValueError('Previous model uses different frozen points')
        variants['previous']=copy.deepcopy(old_part['result'])
    for i,proposal in enumerate(detection['candidates']):
        key='split_'+str(i+1)
        try:
            fitted=fit_partition(poly,train,proposal)
            child_results=fitted.pop('_child_results')
            (output/'volumes').mkdir(exist_ok=True)
            for index,result in enumerate(child_results):
                model_file='volumes/'+key+'-'+str(index+1)+'.json'
                write(output/model_file,dict(schema='independent-roof-volume/1',id=building['id']+'/'+key+'/'+str(index+1),
                    parent_id=building['id'],footprint=proposal['footprints'][index],
                    origin_xy=baseline.get('origin_xy'),ground_z=baseline.get('ground_z'),
                    cache_sha256=digest,result=result))
                fitted['model']['metadata']['bodies'][index]['model_file']=model_file
            variants[key]=fitted
        except (ValueError,RuntimeError,shapely.errors.GEOSException) as e:errors[key]=str(e)
    # Select on training cells only. Holdout is untouched until after selection.
    cells=_cells(train,.6);scores={}
    for key,result in variants.items():
        if key=='previous':continue  # Historical display only, no new model selection.
        p=predict_regions(result['model']['regions'],cells[:,:2]);ok=np.isfinite(p)
        loss=float(np.mean(np.minimum(abs(p[ok]-cells[ok,2]),2.))) if ok.all() else 100.
        penalty=0. if key=='baseline' else args.extra_volume_penalty
        scores[key]=dict(data_loss_m=loss,volume_penalty_m=penalty,
            score=loss+penalty,plane_count=len(result['model']['regions']))
    selected=min(scores,key=lambda k:scores[k]['score'])
    compute_seconds=time.perf_counter()-started
    # Report-only diagnostics; fit_partition remains production-safe by default.
    from roof_observed_ridges import attach_observed_ridges
    for result in variants.values():
        attach_observed_ridges(result,poly,train)
    validation=compare_metrics(variants,holdout)
    decision=dict(selected_variant=selected,scores=scores,errors=errors,
        reason='Training fit with configurable penalty for one extra volume; holdout not used for selection.',production_changed=False)
    counts={**detection.get('counts',{}),'selected_volume_count':variants[selected]['model'].get('metadata',{}).get('volume_count',1),
        'geometry_cuts_applied':0 if selected=='baseline' else 1,'child_split_calls':0,
        'child_roof_fits':2*sum(k.startswith('split_') for k in variants)}
    decision['counts']=counts
    write(output/'volumes.json',dict(selected_variant=selected,counts=counts,
        child_volume_policy=CHILD_POLICY,bodies=variants[selected]['model'].get('metadata',{}).get('bodies',[])))
    labels={'baseline':'Původní 4.9.1','previous':'Předchozí dělení','split_1':'Dělení podle půdorysu · 2 objemy','split_2':'Alternativní rozdělení · 2 objemy'}
    building['parts']=[];direction=np.array([math.cos(-.8),math.sin(-.8)])
    span=np.ptp(shapely.get_coordinates(poly)@direction)+12
    for index,(key,result) in enumerate(variants.items()):
        part=copy.deepcopy(baseline);part.update(result=result,display_variant=key,
            display_label=labels.get(key,key)+(' · vybraná' if key==selected else ''),
            display_offset_m=[*map(float,direction*span*(index-(len(variants)-1)/2)),0.])
        part['cache']={'path':'input.npz','sha256':digest,'bytes':len(cache_bytes)}
        meta=part['result']['model'].setdefault('metadata',{})
        meta['experiment_decision']=decision;meta['holdout_validation']=validation['variants'][key]
        meta['validation_shared_cells']=validation['shared_cells']
        building['parts'].append(part)
    summary=dict(algorithm=VERSION,id=building['id'],address=source.get('address'),created_at_utc=datetime.now(timezone.utc).isoformat(),
        source=str(args.source.resolve()),cache_sha256=digest,train_points=len(train),holdout_points=len(holdout),
        decision=decision,validation=validation,detector_seconds=detection['timing']['total_seconds'],
        fitting_seconds=sum(v['timing']['total_seconds'] for k,v in variants.items() if k.startswith('split_')),
        compute_seconds=compute_seconds,resources=resources,configuration=detection['settings'],
        extra_volume_penalty_m=args.extra_volume_penalty,source_hashes=hashes,counts=counts,child_volume_policy=CHILD_POLICY,
        eligibility=detection.get('eligibility'),previous_file=str(args.previous.resolve()) if args.previous else None)
    write(output/'summary.json',summary);write(output/'source.json',source)
    doc=dict(schema='roof-v2/1',city='ceske-budejovice',buildings=[building],
        report=dict(batch=True,title=str(source.get('address') or building.get('name') or building['id'])+' · podélné řezy',
            subtitle=f"{counts['selected_volume_count']} výsledné hmoty · {counts['geometry_cuts_applied']} dělení půdorysu · {counts.get('longitudinal_bands_evaluated',0)} vyhodnocených podélných pásů, {counts.get('supporting_bands',0)} potvrzuje hranici. Každá hmota má vlastní výpočet střechy {ALGORITHM_VERSION}; další dělení je vypnuté.",
            note='Výšky nad lokálním terénem. Geometrická hypotéza, nikoli hranice samostatných staveb. Stejné uložené DMP OK; kontrolní body nevstupují do výběru. Produkční mapa není změněna.',
            links=[dict(label='Rozhodnutí a časy',href='summary.json'),dict(label='Podélné řezy',href='profiles.json'),
                dict(label='Samostatné hmoty',href='volumes.json'),dict(label='Vstupy',href='source.json')]))
    write(output/'comparison.json',doc)
    tick=time.perf_counter();render_report(output/'comparison.json',output/'report.html')
    summary['report_seconds']=time.perf_counter()-tick;write(output/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('decision','validation','detector_seconds','fitting_seconds','compute_seconds','report_seconds')},ensure_ascii=False))

if __name__=='__main__':main()
