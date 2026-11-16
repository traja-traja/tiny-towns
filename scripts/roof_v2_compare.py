"""Compare existing dense-DMPOK roof meshes on the frozen roof-v2 holdout.

No model fitting, source download, nearest-plane extrapolation, or visual model
assessment is performed. The previous model may have seen these same points.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import time

for _key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_key]='1'

import numpy as np
import shapely
from shapely.geometry import shape

import resource_guard as guard

ROOT=Path(__file__).resolve().parents[1]
DIRECTORY=ROOT/'cities/ceske-budejovice/experiments/roof-v2'
OLD=ROOT/'.work/cb-roof-inference/roofs-dmpok.json'
EPSILON=1e-9
CAVEAT=('The previous fit may have used the new holdout points. This compares two existing '
        'geometries with the same photogrammetric samples; it is not an independent test of both fits. '
        'Neither dataset is independent surveyed architectural ground truth. Small residuals alone '
        'do not establish the desired level of roof simplification.')


def fingerprint(path):
    path=Path(path).resolve()
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):
            digest.update(block)
    try:
        name=path.relative_to(ROOT).as_posix()
    except ValueError:
        name=str(path)
    return {'path':name,'bytes':path.stat().st_size,'sha256':digest.hexdigest()}


def atomic_write(path,payload):
    path=Path(path)
    guard.check_budget(reserve_bytes=len(payload))
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(payload)
    temporary.replace(path)


def triangle_heights(vertices,faces,xy):
    """Barycentric interpolation strictly inside projected roof triangles.

    XY is local to the evaluated building part to avoid cancellation at the
    EPSG:5514 world origin. Shared boundaries are included. Where triangles
    overlap, the upper surface is returned and conflicting heights are counted.
    Degenerate XY triangles provide no height (vertical faces are not roofs).
    """
    vertices=np.asarray(vertices,dtype=float)
    xy=np.asarray(xy,dtype=float).reshape((-1,2))
    maximum=np.full(len(xy),np.nan)
    minimum=np.full(len(xy),np.nan)
    hit_count=np.zeros(len(xy),dtype=np.uint32)
    if not len(faces):
        return maximum,{'roof_face_count':0,'usable_triangle_count':0,'degenerate_xy_triangles':0,
                        'conflicting_overlap_points':0}
    if vertices.ndim!=2 or vertices.shape[1]!=3 or not np.isfinite(vertices).all():
        raise ValueError('Mesh vertices must be finite XYZ triples')
    skipped=0
    for face in faces:
        if len(face)!=3 or any(not isinstance(i,(int,np.integer)) or i<0 or i>=len(vertices) for i in face):
            raise ValueError('Only valid indexed triangular roof faces are accepted')
        a,b,c=vertices[np.asarray(face,dtype=int)]
        u=b[:2]-a[:2]
        v=c[:2]-a[:2]
        determinant=u[0]*v[1]-u[1]*v[0]
        if abs(determinant)<=1e-12:
            skipped+=1
            continue
        lo=np.minimum(np.minimum(a[:2],b[:2]),c[:2])-EPSILON
        hi=np.maximum(np.maximum(a[:2],b[:2]),c[:2])+EPSILON
        indices=np.flatnonzero(np.all((xy>=lo)&(xy<=hi),axis=1))
        if not len(indices):
            continue
        q=xy[indices]-a[:2]
        beta=(q[:,0]*v[1]-q[:,1]*v[0])/determinant
        gamma=(u[0]*q[:,1]-u[1]*q[:,0])/determinant
        inside=(beta>=-EPSILON)&(gamma>=-EPSILON)&(beta+gamma<=1+EPSILON)
        indices=indices[inside]
        z=a[2]+beta[inside]*(b[2]-a[2])+gamma[inside]*(c[2]-a[2])
        maximum[indices]=np.fmax(maximum[indices],z)
        minimum[indices]=np.fmin(minimum[indices],z)
        hit_count[indices]+=1
    conflicts=(hit_count>1)&((maximum-minimum)>.02)
    return maximum,{'roof_face_count':len(faces),'usable_triangle_count':len(faces)-skipped,
                    'degenerate_xy_triangles':skipped,'conflicting_overlap_points':int(conflicts.sum()),
                    'overlap_policy':'upper roof surface; disagreement above 0.02 m is reported'}


def combine_meshes(meshes):
    vertices,faces=[],[]
    for mesh in meshes:
        offset=len(vertices)
        vertices.extend(mesh.get('vertices',[]))
        faces.extend([[int(i)+offset for i in face] for face in mesh.get('roof_faces',[])])
    return np.asarray(vertices,dtype=float).reshape((-1,3)),faces


def residual_metrics(observed,predicted,mask=None):
    observed=np.asarray(observed,dtype=float)
    predicted=np.asarray(predicted,dtype=float)
    covered=np.isfinite(observed)&np.isfinite(predicted)
    if mask is not None:
        covered &= np.asarray(mask,dtype=bool)
    n=int(covered.sum())
    result={'total_points':len(observed),'evaluated_points':n,
            'coverage_fraction':n/len(observed) if len(observed) else None}
    if not n:
        return {**result,'p50_abs_m':None,'p90_abs_m':None,'rmse_m':None,
                'mae_m':None,'inlier_05_fraction':None,'inlier_05_all_points_fraction':0.0}
    signed=observed[covered]-predicted[covered]
    absolute=np.abs(signed)
    inliers=int(np.sum(absolute<=.5))
    return {**result,'p50_abs_m':float(np.quantile(absolute,.5)),
            'p90_abs_m':float(np.quantile(absolute,.9)),
            'rmse_m':float(np.sqrt(np.mean(signed**2))), 'mae_m':float(absolute.mean()),
            'inlier_05_fraction':inliers/n,'inlier_05_all_points_fraction':inliers/len(observed),
            'signed_bias_m':float(signed.mean())}


def compare(new_path,old_path):
    started,cpu=time.perf_counter(),time.process_time()
    guard.check_budget(force=True)
    new=json.loads(Path(new_path).read_text(encoding='utf-8'))
    old=json.loads(Path(old_path).read_text(encoding='utf-8'))
    if new.get('schema')!='roof-v2/1' or new.get('source')!='dmpok':
        raise ValueError('New results must be roof-v2/1 from dense DMPOK')
    if not new.get('status','').startswith('complete'):
        raise ValueError('Wait for complete final roof-v2 results before comparing')
    if 'dmpok' not in str(old.get('source',{}).get('heights','')).lower():
        raise ValueError('Old comparison file must be dense DMPOK, never roofs.json / sparse DMP1G')
    if new.get('crs')!='EPSG:5514' or old.get('horizontal_crs')!='EPSG:5514':
        raise ValueError('Both models must use EPSG:5514')
    if new.get('vertical_datum')!='Bpv' or old.get('vertical_datum')!='Bpv':
        raise ValueError('Both models must use the same Bpv vertical datum')
    previous={}
    for building in old['buildings']:
        oid=building.get('id')
        if not oid:
            continue
        if oid in previous:
            raise ValueError(f'Duplicate old building OID: {oid}')
        previous[oid]=building
    output=[]
    cache_files={}
    combined_observed,combined_old,combined_new=[],[],[]
    for building in new['buildings']:
        if building['id'] not in previous:
            continue
        guard.check_budget()
        prior=previous[building['id']]
        old_vertices,old_faces=combine_meshes(prior.get('models',[]))
        observed,old_heights,new_heights,parts=[],[],[],[]
        new_face_count=0
        for part in building['parts']:
            if part.get('status')!='inferred':
                raise ValueError(f"New shared building part incomplete: {building['id']}/{part.get('part_index')}")
            cache=ROOT/part['cache']['path']
            record=fingerprint(cache)
            if record['sha256']!=part['cache']['sha256']:
                raise ValueError(f'Frozen holdout cache checksum changed: {cache}')
            cache_files[record['path']]=record
            with np.load(cache) as data:
                points=data['holdout']
            origin=np.array([*part['origin_xy'],part['ground_z']],dtype=float)
            footprint=shape(part['footprint'])
            interior=shapely.intersects_xy(footprint,points[:,0],points[:,1])
            old_prediction,old_info=triangle_heights(old_vertices-origin,old_faces,points[:,:2])
            mesh=part['result']['model']['mesh']
            new_prediction,new_info=triangle_heights(mesh['vertices'],mesh['roof_faces'],points[:,:2])
            old_prediction[~interior]=np.nan
            new_prediction[~interior]=np.nan
            common=np.isfinite(old_prediction)&np.isfinite(new_prediction)&interior
            observed.append(points[:,2]);old_heights.append(old_prediction);new_heights.append(new_prediction)
            new_face_count+=new_info['roof_face_count']
            parts.append({'part_index':part['part_index'],'origin_xy':part['origin_xy'],'ground_z':part['ground_z'],
                'holdout_points':len(points),'outside_footprint_points':int((~interior).sum()),
                'common_covered_points':int(common.sum()),'old_mesh':old_info,'new_mesh':new_info,
                'cache':record})
        z=np.concatenate(observed);a=np.concatenate(old_heights);b=np.concatenate(new_heights)
        common=np.isfinite(a)&np.isfinite(b)
        item={'id':building['id'],'address':building.get('address'),'name':building.get('name'),
            'holdout_points':len(z),'common_covered_points':int(common.sum()),'parts':parts,
            'old':{'types':[m.get('type') for m in prior.get('models',[])],'status':prior.get('status'),
                   'roof_face_count':len(old_faces),'metrics':residual_metrics(z,a),
                   'paired_metrics':residual_metrics(z,a,common)},
            'new':{'types':[p['result']['model'].get('type') for p in building['parts']],
                   'status':building.get('status'),'roof_face_count':new_face_count,
                   'metrics':residual_metrics(z,b),'paired_metrics':residual_metrics(z,b,common)}}
        output.append(item)
        combined_observed.append(z);combined_old.append(a);combined_new.append(b)
    if not output:
        raise ValueError('No shared building OIDs between the two existing results')
    z=np.concatenate(combined_observed);a=np.concatenate(combined_old);b=np.concatenate(combined_new)
    common=np.isfinite(a)&np.isfinite(b)
    source_records={'new_results':fingerprint(new_path),'old_dense_results':fingerprint(old_path),
                    'comparison_script':fingerprint(__file__),'holdout_caches':list(cache_files.values())}
    inputs_path=Path(new_path).with_name('inputs.json')
    source_tiles=[]
    if inputs_path.is_file():
        source_records['input_manifest']=fingerprint(inputs_path)
        inputs=json.loads(inputs_path.read_text(encoding='utf-8'))
        source_tiles=[{'file':tile['file'],'point_count':tile['header']['point_count'],
                       'hash_basis':'Previously recorded input-source checksum; not rehashed during geometric comparison.'}
                      for tile in inputs.get('source_tiles',[])]
    return {'schema':'roof-v2-comparison/1','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'city':'ceske-budejovice','source':'dmpok','crs':'EPSG:5514','vertical_datum':'Bpv',
        'method':'Vertical barycentric intersection with existing roof triangles, clipped to original new footprint; no nearest-plane extrapolation.',
        'comparison_scope':'Existing old dense DMPOK geometry versus final roof-v2 geometry on exactly the same frozen new holdout points.',
        'old_models_refitted':False,'new_models_refitted':False,'caveat':CAVEAT,
        'coverage_policy':'Uncovered points remain unpredicted; individual coverage and paired common-support metrics are both reported.',
        'residual_sign':'observed point elevation minus roof mesh elevation',
        'sample_sha256':new.get('sample_sha256'),'split':new.get('split'), 'files':source_records,
        'old_source':old.get('source'),'new_source':new.get('source'),
        'dense_source_tiles':source_tiles,'triangle_boundary_tolerance':EPSILON,
        'new_configuration':new.get('configuration'),'new_run_created_at_utc':new.get('created_at_utc'),
        'common_building_count':len(output),'buildings':output,
        'aggregate':{'point_weighted':True,'holdout_points':len(z),'common_covered_points':int(common.sum()),
            'old':{'metrics':residual_metrics(z,a),'paired_metrics':residual_metrics(z,a,common),
                   'roof_face_count':sum(x['old']['roof_face_count'] for x in output)},
            'new':{'metrics':residual_metrics(z,b),'paired_metrics':residual_metrics(z,b,common),
                   'roof_face_count':sum(x['new']['roof_face_count'] for x in output)}},
        'timing':{'wall_seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-cpu},
        'resources_after':guard.check_budget()}


def report_html(document):
    def escaped(value):
        return html.escape(str(value))
    def number(value,percent=False):
        return '—' if value is None else f'{value*100:.1f} %' if percent else f'{value:.3f}'
    rows=[]
    for building in document['buildings']:
        for key,label in [('old','Původní DMPOK'),('new','Nový v2')]:
            model=building[key];metric=model['paired_metrics']
            cells=[escaped(building['address'] or building['id']),label,escaped(', '.join(str(t or 'unknown') for t in model['types'])),
                number(model['metrics']['coverage_fraction'],True),str(building['common_covered_points']),
                number(metric['p50_abs_m']),number(metric['p90_abs_m']),number(metric['rmse_m']),
                number(metric['inlier_05_fraction'],True),str(model['roof_face_count'])]
            rows.append('<tr>'+''.join('<td>'+value+'</td>' for value in cells)+'</tr>')
    aggregate_rows=[]
    for key,label in [('old','Původní DMPOK'),('new','Nový v2')]:
        item=document['aggregate'][key];metric=item['paired_metrics']
        aggregate_rows.append('<tr><th>'+label+'</th>'+''.join('<td>'+value+'</td>' for value in [
            number(item['metrics']['coverage_fraction'],True),number(metric['p50_abs_m']),
            number(metric['p90_abs_m']),number(metric['rmse_m']),number(metric['inlier_05_fraction'],True),
            str(item['roof_face_count'])])+'</tr>')
    files=''.join('<li><code>'+escaped(item['path'])+'</code><br><small>SHA256 '+escaped(item['sha256'])+'</small></li>'
                  for key,item in document['files'].items() if isinstance(item,dict))
    return f'''<!doctype html><html lang="cs"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ČB — numerické porovnání střech</title><style>
body{{font:15px/1.55 system-ui,sans-serif;margin:28px auto;max-width:1400px;padding:0 22px;color:#20303b;background:#f6f8f7}}
h1{{font-size:27px}}h2{{font-size:20px;margin-top:28px}}a{{color:#176452}}p{{max-width:1100px}}
.note{{padding:16px;background:#fff3d9;border-left:4px solid #ab7429}}.scroll{{overflow:auto}}
table{{width:100%;border-collapse:collapse;background:white;margin:16px 0}}th,td{{padding:9px 10px;border-bottom:1px solid #dbe2df;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}tbody tr:nth-child(4n+3),tbody tr:nth-child(4n+4){{background:#f0f5f2}}small{{color:#53665c}}code{{overflow-wrap:anywhere}}li{{margin:12px 0}}
</style><main><h1>České Budějovice: původní DMPOK × nový v2</h1>
<p><a href="report.html">Otevřít 3D report</a> · <a href="comparison.json">Úplná číselná data a kontrolní součty</a></p>
<p class="note"><strong>Toto není nezávislý test obou algoritmů.</strong> Původní výpočet mohl použít body, které jsou nyní v holdoutu nové verze. Porovnáváme dvě již vytvořené geometrie se stejnými body hustého fotogrammetrického DMPOK. Nejde o nezávislé zaměření architektury ani o optické hodnocení modelů. Menší bodová odchylka sama neurčuje vhodnou jednoduchost střechy.</p>
<p>Shodných budov: <strong>{document['common_building_count']}</strong>. Odložených bodů: <strong>{document['aggregate']['holdout_points']}</strong>; pokrytých oběma modely: <strong>{document['aggregate']['common_covered_points']}</strong>. Žádná střecha nebyla pro toto porovnání znovu fitována. Řídký DMP1G se nepoužívá.</p>
<p>Výška je určena průsečíkem s půdorysným průmětem skutečných střešních trojúhelníků. Mimo jejich pokrytí výšku nedopočítáváme. Pokrytí se vztahuje ke všem odloženým bodům; p50, p90, RMSE a podíl do 0,5 m v tabulkách se vztahují ke <strong>stejnému průniku bodů pokrytých oběma modely</strong>. Odchylka je svislá, výšky jsou v metrech. Počet ploch znamená počet střešních trojúhelníků, nikoli počet architektonických střešních rovin.</p>
<h2>Součet za společné budovy</h2><p>Odchylky jsou vážené počtem bodů, nikoli počtem budov.</p><div class="scroll"><table><thead><tr><th>Verze</th><th>Pokrytí</th><th>p50 [m]</th><th>p90 [m]</th><th>RMSE [m]</th><th>Do 0,5 m</th><th>Trojúhelníky</th></tr></thead><tbody>{''.join(aggregate_rows)}</tbody></table></div>
<h2>Jednotlivé budovy</h2><div class="scroll"><table><thead><tr><th>Adresa</th><th>Verze</th><th>Typ</th><th>Pokrytí</th><th>Společné body</th><th>p50 [m]</th><th>p90 [m]</th><th>RMSE [m]</th><th>Do 0,5 m</th><th>Trojúhelníky</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Reprodukovatelnost</h2><p>Shoda podle zdrojového Overture OID. Staré vrcholy EPSG:5514 + Bpv převedeny pomocí origin_xy a ground_z do stejného místního systému jako nový mesh a holdout. Individuální metriky pokrytí i metriky na společných bodech jsou uloženy v JSON.</p><ul>{files}</ul>
<p><small>Vytvořeno {escaped(document['created_at_utc'])}. Čas porovnání {document['timing']['wall_seconds']:.3f} s, CPU {document['timing']['cpu_seconds']:.3f} s.</small></p></main></html>'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--new',type=Path,default=DIRECTORY/'results.json')
    parser.add_argument('--old',type=Path,default=OLD)
    parser.add_argument('--output',type=Path,default=DIRECTORY/'comparison.json')
    parser.add_argument('--html',type=Path,default=DIRECTORY/'comparison.html')
    args=parser.parse_args()
    with guard.keep_awake():
        result=compare(args.new,args.old)
        atomic_write(args.output,(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))
        atomic_write(args.html,report_html(result).encode('utf-8'))
    print(json.dumps({'output':str(args.output),'html':str(args.html),
                      'buildings':result['common_building_count'],'timing':result['timing']},ensure_ascii=False))


if __name__=='__main__':
    main()
