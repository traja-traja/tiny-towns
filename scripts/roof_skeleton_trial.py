"""Isolated straight-skeleton comparison; never changes production selection.

Requires py_straight_skeleton==0.1.0 (BSD-3-Clause). Reads an existing cached
model and its NPZ; all inference, geometry and reports run locally.
"""
from __future__ import annotations
import argparse, copy, json, math, time, os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key]='1'
from pathlib import Path
import numpy as np
import shapely
from shapely.geometry import Polygon, shape, mapping
from shapely.geometry.polygon import orient
from scipy.optimize import least_squares
from py_straight_skeleton import compute_skeleton, __version__
from roof_v2 import _cells, _lines, predict_regions, residual_stats
from roof_v2_geometry import build_mesh
from roof_batch import compare_documents, write_json
from roof_v2_report import render_report
import resource_guard as guard


def reference_footprint(original, simplify_m, opening_m, max_change=.03):
    # MODULE: bounded footprint generalization. Preserve components and holes.
    p = original
    if opening_m:
        p = p.buffer(-opening_m, join_style='mitre').buffer(opening_m, join_style='mitre')
    p = p.simplify(simplify_m, preserve_topology=True)
    change = original.symmetric_difference(p).area / original.area
    if (p.geom_type != 'Polygon' or not p.is_valid or p.is_empty
            or len(p.interiors) != len(original.interiors)
            or change > max_change or original.hausdorff_distance(p) > 2.5):
        raise ValueError('Reference simplification exceeded configured geometric limits')
    return orient(p, sign=1), dict(simplify_m=simplify_m, opening_m=opening_m,
        changed_area_fraction=change, hausdorff_m=original.hausdorff_distance(p),
        input_edges=len(original.exterior.coords)-1, reference_edges=len(p.exterior.coords)-1)


def fit_trial(part, points, simplify_m, opening_m):
    total = time.perf_counter()
    original = shape(part['footprint'])
    p, generalization = reference_footprint(original, simplify_m, opening_m)
    pre_seconds = time.perf_counter()-total
    tick = time.perf_counter()
    sk = compute_skeleton(list(p.exterior.coords)[:-1], [list(r.coords)[:-1] for r in p.interiors])
    unit = []
    for face in sk.get_faces():
        nodes = [sk.nodes[i] for i in face]
        xy = np.array([[n.position.x,n.position.y] for n in nodes])
        t = np.array([n.time for n in nodes])
        plane = np.linalg.lstsq(np.c_[xy,np.ones(len(xy))], t, rcond=None)[0]
        if np.max(np.abs(np.c_[xy,np.ones(len(xy))]@plane-t)) > 1e-5:
            raise ValueError('Nonplanar skeleton face')
        face_poly = Polygon(xy)
        if not face_poly.is_valid:
            raise ValueError('Invalid skeleton face')
        unit.append(dict(polygon=mapping(face_poly),plane=plane.tolist()))
    skeleton_seconds = time.perf_counter()-tick
    tick = time.perf_counter()
    cells = _cells(points,.6)
    distance = predict_regions(unit,cells[:,:2])
    ok = np.isfinite(distance)
    if ok.sum()<20: raise ValueError('Insufficient roof cells')
    z = cells[ok,2]; d = distance[ok]
    initial = [max(.6,float(np.quantile(z,.1))-.3),.7]
    fit = least_squares(lambda x:x[0]+x[1]*d-z, initial,
        bounds=([.5,.12],[max(initial[0]+.1,float(np.quantile(z,.9))),2.5]),
        loss='soft_l1', f_scale=.35, max_nfev=65)
    eave,pitch = map(float,fit.x)
    regions = [dict(polygon=r['polygon'],plane=(np.array(r['plane'])*pitch+[0,0,eave]).tolist()) for r in unit]
    fit_seconds=time.perf_counter()-tick
    tick=time.perf_counter()
    mesh=build_mesh(p,regions)
    if not mesh['diagnostics']['valid']: raise ValueError('Invalid output mesh')
    roof_z = np.asarray(mesh['vertices'])[:,2]
    metadata=dict(eave_height_m=eave,ridge_height_m=float(roof_z.max()),
        roof_height_m=float(roof_z.max()-eave),ridge_kind='straight_skeleton',
        nominal_roof_plane_count=len(regions),pitch_degrees=math.degrees(math.atan(pitch)),
        common_eave=True,common_pitch=True,footprint_modified=not p.equals(original),
        generalization=generalization,library='py_straight_skeleton',library_version=__version__,
        note='Isolated all-hipped candidate, no gable classification. Generalized footprint applies to this trial only.')
    model=dict(type='compound',mesh=mesh,regions=regions,metadata=metadata,
        height_range_m=[eave,float(roof_z.max())])
    model['ridge_lines'],model['eave_lines'],model['roof_boundary_lines']=_lines(model,p)
    # Evaluation uses the SAME intersection of supported cells for both models.
    baseline=predict_regions(part['result']['model']['regions'],cells[:,:2])
    prediction=predict_regions(regions,cells[:,:2])
    common=np.isfinite(baseline)&np.isfinite(prediction)
    diagnostics=dict(mesh=mesh['diagnostics'],comparison_cells=int(common.sum()),
        excluded_cells=int((~common).sum()),
        baseline_residual=residual_stats(baseline[common]-cells[common,2]),
        trial_residual=residual_stats(prediction[common]-cells[common,2]))
    mesh_seconds=time.perf_counter()-tick
    out=copy.deepcopy(part)
    out['footprint']=mapping(p)
    out['original_footprint']=mapping(original)
    out['result']=dict(algorithm='straight-skeleton-trial-1',model=model,candidates=[],
        diagnostics=diagnostics,configuration=generalization,
        timing=dict(total_seconds=time.perf_counter()-total,footprint_seconds=pre_seconds,
            skeleton_seconds=skeleton_seconds,fit_seconds=fit_seconds,mesh_evaluation_seconds=mesh_seconds))
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model-cache',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--city',default='velesin')
    args=ap.parse_args()
    if args.output.exists(): raise ValueError('Choose a new output folder')
    print('Checking resources',flush=True)
    guard.check_budget(force=True)
    print('Loading cached model',flush=True)
    record=json.loads(args.model_cache.read_text(encoding='utf-8'))
    baseline=record.get('model',record)
    if len(baseline['parts'])!=1: raise ValueError('Trial currently supports a single footprint part')
    part=baseline['parts'][0]
    with np.load(part['cache']['path']) as npz: points=npz['train']
    config=[('raw',0.,0.),('simplified',.65,0.),('minor-features',.15,1.8)]
    summaries=[]
    args.output.mkdir(parents=True)
    for label,tolerance,opening in config:
        print('Computing '+label,flush=True)
        newpart=fit_trial(part,points,tolerance,opening)
        building=copy.deepcopy(baseline);building['parts']=[newpart]
        building['timing']={'roof_compute_seconds':newpart['result']['timing']['total_seconds']}
        current=dict(schema='roof-v2/1',city=args.city,status='complete',buildings=[building])
        previous=dict(schema='roof-v2/1',buildings=[baseline])
        folder=args.output/label;folder.mkdir()
        write_json(folder/'results.json',current)
        comparison=compare_documents(current,previous,'modular-roofs-4.9.1')
        comparison['report']=dict(batch=True,title='Straight skeleton · '+label,
            subtitle='Vlevo dosavadní model, vpravo knihovna. Jeden dům, původní model zachován.',
            note='Zkušební valbová střecha. Sklon a okap se přizpůsobují bodům. Všechny strany mají valbu; štíty zatím nevybíráme. Zjednodušený půdorys platí jen pro tento pokus.',
            links=[dict(label='Všechny varianty',href='../index.html'),dict(label='Výsledky a metadata',href='results.json')])
        write_json(folder/'comparison.json',comparison)
        render_report(folder/'comparison.json',folder/'report.html')
        r=newpart['result']
        summaries.append(dict(variant=label,timing=r['timing'],metadata=r['model']['metadata'],diagnostics=r['diagnostics']))
    write_json(args.output/'summary.json',summaries)
    write_json(args.output/'baseline.json',baseline)
    links=''.join('<li><a href="'+s['variant']+'/report.html">'+s['variant']+'</a> — '+str(s['metadata']['nominal_roof_plane_count'])+' ploch, '+format(s['timing']['total_seconds'],'.3f')+' s</li>' for s in summaries)
    (args.output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Straight skeleton – pokus</title><style>body{font:18px system-ui;max-width:850px;margin:40px auto;line-height:1.7}</style><h1>Straight skeleton · '+baseline['address']+'</h1><p>V každé variantě je vlevo původní model a vpravo test knihovny. Město nebylo přegenerováno. Drobné úpravy půdorysu jsou pouze experiment.</p><ul>'+links+'</ul><a href="summary.json">Časy, odchylky a metadata JSON</a>',encoding='utf-8')
    print(json.dumps(summaries,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
