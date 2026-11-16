"""Reproducible 30-footprint roof benchmark; no generative models or rendering calls.

Sources are prepared by roof_pilot_sources.py. This runner reserves 20% of all
building points BEFORE any reconstruction, including the Roofer input cloud.
Agreement with these held-out points is not surveyed geometric accuracy.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import statistics
import sys
import time

import numpy as np
import shapely
from shapely.geometry import shape, mapping
from shapely.ops import transform
from shapely.affinity import translate
from pyproj import Transformer, CRS

import resource_guard as guard

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work/roof-pilot'
DEST = ROOT / 'cities/velesin/roof-pilot'
SAMPLE = DEST / 'sample.json'
MANIFEST = WORK / 'sources/sources.json'
SOURCES = ('dmp1g', 'dmpok')
METHODS = ('baseline', 'templates', 'roofer')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + '.partial')
    part.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    part.replace(path)


def samples():
    project = Transformer.from_crs(4326, 5514, always_xy=True).transform
    return [(f, transform(project, shape(f['geometry']))) for f in read(SAMPLE)['features']]


def load_source(name):
    manifest = read(MANIFEST)
    path = Path(manifest['sources'][name]['crop_path'])
    if not path.is_absolute(): path = ROOT / path
    with np.load(path) as data:
        xyz, cls = data['xyz'], data['classification']
    finite = np.isfinite(xyz).all(axis=1)
    xyz, cls = xyz[finite], cls[finite]
    # One global split prevents a point on overlapping footprints leaking from
    # a neighbour's training subset into another building's holdout.
    order = np.lexsort((xyz[:, 2], xyz[:, 1], xyz[:, 0]))
    xyz, cls = xyz[order], cls[order]
    holdout = (np.random.default_rng(20261115).random(len(xyz)) < .2) & (cls == 6)
    return xyz, cls, holdout


def building_data(poly, xyz, cls, heldout):
    inside = shapely.contains_xy(poly, xyz[:, 0], xyz[:, 1])
    ring = shapely.contains_xy(poly.buffer(20).difference(poly), xyz[:, 0], xyz[:, 1])
    ground_points = xyz[ring & (cls == 2)]
    ground = float(np.median(ground_points[:, 2])) if len(ground_points) else None
    roof = inside & (cls == 6)
    centre = np.array([poly.centroid.x, poly.centroid.y])
    offset = np.r_[centre, 0.]
    return {'ground_z': ground, 'ground_points': len(ground_points),
            'centre': centre, 'poly': translate(poly, -centre[0], -centre[1]),
            'train': xyz[roof & ~heldout] - offset,
            'test': xyz[roof & heldout] - offset,
            'roof_points': int(roof.sum())}


def evaluate(prediction, observed, training):
    prediction = np.asarray(prediction, dtype=float)
    observed = np.asarray(observed, dtype=float)
    ok = np.isfinite(prediction) & np.isfinite(observed)
    error = prediction[ok] - observed[ok]
    return {'holdout_rmse_m': float(np.sqrt(np.mean(error**2))) if len(error) else None,
            'holdout_mae_m': float(np.mean(np.abs(error))) if len(error) else None,
            'holdout_p90_abs_m': float(np.percentile(np.abs(error), 90)) if len(error) else None,
            'holdout_coverage': float(ok.mean()) if len(ok) else 0.,
            'train_points': int(training), 'test_points': len(observed),
            'evaluated_points': len(error),
            'evaluation_set': '20_percent_same_source_held_out_before_reconstruction',
            'not_surveyed_ground_truth': True}


def base_run(source, method, feature, data):
    p = feature['properties']
    return {'source': source, 'method': method, 'id': feature['id'],
            'pilot_id': p['pilot_id'], 'name': p['name'], 'category': p['category'],
            'status': 'insufficient', 'elapsed_seconds': None, 'model': None,
            'ground_z': data['ground_z'], 'ground_points': data['ground_points'],
            'roof_points': data['roof_points'],
            'metrics': evaluate(np.full(len(data['test']), np.nan), data['test'][:, 2], len(data['train']))}


def report_mesh(model, ground):
    result = deepcopy(model)
    vertices = np.asarray(result.get('vertices', []), dtype=float)
    if vertices.size:
        vertices[:, 2] -= ground
        result['vertices'] = vertices.tolist()
    result['coordinate_system'] = 'metres; local XY relative footprint centroid, Z relative median ground'
    return result


def template_worker(source, method, repetitions=3):
    from roof_pilot_methods import baseline_roof_model, fit_roof_models, predict_roof_z
    xyz, cls, heldout = load_source(source)
    runs = []
    for feature, poly in samples():
        guard.check_budget()
        data = building_data(poly, xyz, cls, heldout)
        run = base_run(source, method, feature, data)
        if data['ground_z'] is None:
            run['error'] = 'No class-2 ground points within 20 m'
        else:
            attrs = feature['properties']['source_attributes']
            measured = []
            failure = None
            for _ in range(repetitions):
                start = time.perf_counter()
                try:
                    if method == 'baseline':
                        model = baseline_roof_model(data['poly'], data['train'], data['ground_z'],
                            roof_shape=attrs.get('roof_shape'), source_height=attrs.get('height'),
                            source_levels=attrs.get('num_floors'))
                        result = None
                    else:
                        result = fit_roof_models(data['poly'], data['train'], data['ground_z'], allow_barrel=True)
                        model = result['best']
                except (ValueError, np.linalg.LinAlgError, shapely.errors.GEOSException) as exc:
                    failure = f'{type(exc).__name__}: {exc}'
                    model, result = None, None
                    measured.append(time.perf_counter() - start)
                    break
                measured.append(time.perf_counter() - start)
            run.update(elapsed_seconds=statistics.median(measured), repetition_seconds=measured,
                       timing_scope=f'median of {len(measured)} in-process model+mesh attempts; excludes source crop and process startup')
            if model and model.get('vertices') and model.get('faces'):
                prediction = predict_roof_z(model, data['test'][:, :2])
                run.update(status='ok', model=report_mesh(model, data['ground_z']),
                           metrics=evaluate(prediction, data['test'][:, 2], len(data['train'])))
                if result:
                    run['candidates'] = [{k: v for k, v in m.items() if k not in ('vertices', 'faces', 'face_semantics')}
                                         for m in result['candidates']]
            else:
                run['error'] = failure or (result or model or {}).get('reason', 'No usable model')
                if failure: run['status'] = 'failed'
        runs.append(run)
        print(source, method, run['pilot_id'], run['status'], run['elapsed_seconds'], flush=True)
    write(WORK / f'{source}-{method}.json', {'runs': runs})


def prepare_roofer_input(source):
    import laspy
    xyz, cls, heldout = load_source(source)
    folder = WORK / source
    folder.mkdir(parents=True, exist_ok=True)
    features = []
    data_by_id = {}
    for feature, poly in samples():
        data = building_data(poly, xyz, cls, heldout)
        data_by_id[feature['id']] = data
        if data['ground_z'] is None: continue
        features.append({'type': 'Feature', 'id': feature['id'], 'geometry': mapping(poly),
                         'properties': {'id': feature['id'], 'ground_z': data['ground_z'],
                                        'centre_x': float(data['centre'][0]), 'centre_y': float(data['centre'][1])}})
    keep = ((cls == 2) | (cls == 6)) & ~heldout
    header = laspy.LasHeader(point_format=6, version='1.4')
    header.scales = np.array([.001, .001, .001]); header.offsets = np.floor(xyz.min(axis=0))
    header.add_crs(CRS.from_epsg(5514))
    cloud = laspy.LasData(header)
    cloud.x, cloud.y, cloud.z = xyz[keep].T
    cloud.classification = cls[keep]
    cloud.write(folder / 'train.laz')
    write(folder / 'split.json', {'seed': 20261115, 'heldout_points': int(heldout.sum()),
                               'training_points': int(keep.sum()), 'input_cloud_sha256': guard.sha256(folder / 'train.laz')})
    return features, data_by_id, folder


def roofer_worker(source):
    from roof_pilot_roofer import run_roofer, predict_roofer_z
    features, data_by_id, folder = prepare_roofer_input(source)
    result = run_roofer(source, features, folder / 'train.laz', folder / 'roofer')
    runs = []
    for feature, poly in samples():
        data = data_by_id[feature['id']]
        run = base_run(source, 'roofer', feature, data)
        entry = result['buildings'].get(feature['id'])
        if (entry and entry.get('model') and entry['model'].get('status') == 'ok'
                and entry['model'].get('vertices') and entry['model'].get('faces')
                and 'roof' in entry['model'].get('face_semantics', [])):
            model = entry['model']
            prediction = predict_roofer_z(model, data['test'][:, :2]) + data['ground_z']
            run.update(status='ok', model=model,
                       elapsed_seconds=entry.get('elapsed_seconds'),
                       timing_scope=entry.get('timing_scope', 'Roofer per-building reported time'),
                       metrics=evaluate(prediction, data['test'][:, 2], len(data['train'])),
                       attributes=entry.get('attributes', {}))
        else:
            run.update(status='failed', error=(entry or {}).get('error', 'Roofer did not produce this building'),
                       attributes=(entry or {}).get('attributes', {}))
        runs.append(run)
    write(WORK / f'{source}-roofer.json', {'runs': runs, 'batch_metrics': result.get('metrics', {})})


def summarise(results):
    rows = []
    for source in SOURCES:
        for method in METHODS:
            runs = [r for r in results['runs'] if r['source'] == source and r['method'] == method]
            ok = [r for r in runs if r['status'] == 'ok']
            errors = [r['metrics']['holdout_rmse_m'] for r in ok if r['metrics']['holdout_rmse_m'] is not None]
            times = [r['elapsed_seconds'] for r in runs if r['elapsed_seconds'] is not None]
            rows.append({'source': source, 'method': method, 'success': len(ok), 'total': len(runs),
                         'model_seconds_sum': sum(times) if times else None,
                         'median_building_seconds': statistics.median(times) if times else None,
                         'median_building_holdout_rmse_m': statistics.median(errors) if errors else None,
                         'mean_holdout_coverage': statistics.mean(r['metrics']['holdout_coverage'] for r in ok) if ok else None})
    return rows


def compile_results():
    result = {'schema': 'roof-pilot/1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'samples': [f['properties'] for f, _ in samples()], 'runs': [],
              'source_metrics': read(MANIFEST), 'process_metrics': {}, 'notes': [
        '30 půdorysů představuje 27 skupin; radnice má 2 a bývalý kostel Jakub 3 půdorysy.',
        'Baseline je aproximace stávající heuristiky, nikoli přesný běh městského rendereru; neobsahuje jeho všechny výjimky ani ručně upravené modely.',
        'Šablony hledají flat/shed/gabled/hipped/barrel; maximálně 3500 bodů pro optimalizaci, maximálně 4 výchozí orientace. Zdrojový typ střechy se při jejich výběru nepoužívá.',
        '20 % bodů třídy 6 je odděleno před výpočtem a není v trénovací LAZ ani v šablonách. Sousední fotogrammetrické body jsou korelované; nejde o nezávislé zaměření skutečného stavu.',
        'RMSE popisuje shodu výšky se zadrženými body téhož zdroje, nikoli správnost typu střechy, fasády, vikýřů či průchodů.',
        'DMP1G a DMPOK pocházejí z odlišných metod a období. Starší data mohou postrádat novější stavby. Hustota není přesnost.',
        'Ground je medián bodů třídy 2 v prstenci do 20 m od půdorysu. Šikmý terén není v tomto objemovém pilotu samostatně modelován.',
        'Časy šablon a baseline jsou medián 3 opakování včetně tvorby mesh; celý běh Rooferu a jeho vnitřní časy jsou vedeny odděleně.',
        'Paměťový údaj peak_job_commit_bytes je špička rezervované/commitované paměti celého procesu a jeho potomků, nikoli pouze fyzická RAM.',
        'Podloubí a průchody nelze spolehlivě odvodit z těchto 2.5D podkladů; vyžadují samostatnou geometrii a další zdroje.'
    ]}
    for source in SOURCES:
        for method in METHODS:
            path = WORK / f'{source}-{method}.json'
            value = read(path)
            if method == 'roofer' and value.get('batch_metrics', {}).get('log'):
                adapter = Path(value['batch_metrics']['log']).parent / 'adapter-result.json'
                if adapter.exists():
                    raw_models = read(adapter).get('models', {})
                    for run in value['runs']:
                        run.setdefault('attributes', raw_models.get(run['id'], {}).get('attributes', {}))
            result['runs'].extend(value['runs'])
            if 'batch_metrics' in value:
                result['process_metrics'][f'{source}-{method}-batch'] = value['batch_metrics']
            log = WORK / 'logs' / f'{source}-{method}.log.metrics.json'
            if log.exists(): result['process_metrics'][f'{source}-{method}'] = read(log)
    result['summary'] = summarise(result)
    result['source_metrics']['process_metrics'] = {
        source: read(WORK / 'sources' / f'prepare-{source}.log.metrics.json')
        for source in SOURCES if (WORK / 'sources' / f'prepare-{source}.log.metrics.json').exists()}
    result['software'] = {
        'python': sys.version,
        'packages': {name: importlib.metadata.version(name) for name in ('numpy','scipy','shapely','laspy','pyproj')},
        'roofer_provenance': read(WORK / 'tools/source.json') if (WORK / 'tools/source.json').exists() else None,
        'script_sha256': {path.name: guard.sha256(path) for path in [Path(__file__),
            ROOT/'scripts/roof_pilot_methods.py', ROOT/'scripts/roof_pilot_roofer.py', ROOT/'scripts/roof_pilot_sources.py']}}
    # Observations remain tied to measured output when this pilot is repeated.
    def run(source, method, pilot_id):
        return next((r for r in result['runs'] if (r['source'],r['method'],r['pilot_id']) == (source,method,pilot_id)), {})
    sports = run('dmpok','templates','VEL-ROOF-11')
    if sports.get('model') and sports['model'].get('shape') != 'barrel':
        result['notes'].append('Zjištění pilotu: u Sportcentra jediná šablona přes celý složený půdorys neobnovila známou válcovou střechu. Pro takové objekty je třeba nejprve rozdělit objem na části; ručně ověřený model zůstává vhodnější.')
    if any('invalid_faces_skipped' in (r.get('model') or {}).get('warnings', []) for r in result['runs']):
        result['notes'].append('U některých výstupů jsou označeny plochy vynechané při převodu mesh. Toto upozornění samo nerozlišuje závažnou vadu a nulovou plochu po zaokrouhlení; podrobný audit je uveden níže, pokud odpovídá aktuálním souborům. Shoda výšek sama neposuzuje složitost ani vizuální vhodnost modelu.')
    jakub = run('dmpok','roofer','VEL-ROOF-05')
    if jakub and jakub['status'] != 'ok':
        attrs = jakub.get('attributes', {})
        reason = f"; Roofer hlásí {attrs['rf_nodata_frac']:.1%} nodata" if attrs.get('rf_nodata_frac') is not None else ''
        result['notes'].append('Roofer u čp. 88 v bývalém kostele Jakub nevyrobil geometrii' + reason + '. Model se v porovnání nenahrazuje jinou metodou.')
    tower = run('dmp1g','baseline','VEL-ROOF-07')
    if tower.get('model') and tower.get('roof_points') == 0:
        result['notes'].append('Starší data postrádají body vodojemu. Jeho základní objem DMP1G je pouze odhad ze zdrojových atributů; není to rekonstrukce z bodů.')
    review_path = DEST / 'review.json'
    if review_path.exists():
        review = read(review_path)
        basis = review.get('basis', [])
        if basis and all((ROOT / f['path']).is_file() and guard.sha256(ROOT / f['path']) == f['sha256'] for f in basis):
            result['review'] = review
            result['notes'].extend(review.get('notes', []))
    result['budweis_decision'] = {
        'roof_method': 'existing_basic_model',
        'reason': 'No verified full-pipeline improvement within the +20–30% runtime budget; isolated baseline is an approximation. Keep the approved basic renderer for the first ČB preview.',
        'no_ai_processing': True, 'preview_size_m': [2300, 2300]}
    result['resource_status'] = guard.check_budget(force=True)
    write(DEST / 'results.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--worker', choices=METHODS)
    p.add_argument('--source', choices=SOURCES)
    p.add_argument('--report-only', action='store_true')
    args = p.parse_args()
    if args.worker:
        if args.worker == 'roofer': roofer_worker(args.source)
        else: template_worker(args.source, args.worker)
        return
    if not args.execute and not args.report_only:
        print('Prepare sources, then run --execute. Outputs: cities/velesin/roof-pilot/results.json and report.html')
        return
    with guard.keep_awake():
        if not args.report_only:
            # A content fingerprint prevents old results surviving a changed split,
            # source crop, footprint or implementation.
            files = [SAMPLE, MANIFEST, Path(__file__), ROOT/'scripts/roof_pilot_methods.py', ROOT/'scripts/roof_pilot_roofer.py']
            fingerprint = hashlib.sha256(b''.join(f.read_bytes() for f in files)).hexdigest()
            checkpoint_path = WORK / 'benchmark-checkpoint.json'
            state = read(checkpoint_path) if checkpoint_path.exists() else {}
            if state.get('fingerprint') != fingerprint: state = {'fingerprint': fingerprint, 'completed': []}
            for source in SOURCES:
                for method in METHODS:
                    key = f'{source}-{method}'
                    path = WORK / f'{key}.json'
                    if key in state['completed'] and path.exists() and len(read(path).get('runs', [])) == 30:
                        print('Verified checkpoint', key, flush=True); continue
                    print('Starting', key, flush=True)
                    guard.run_guarded([sys.executable, '-X', 'utf8', __file__, '--worker', method, '--source', source],
                                      ROOT, WORK / 'logs' / f'{key}.log', min_available_gb=1, max_ram_gb=3)
                    state['completed'].append(key); write(checkpoint_path, state)
        result = compile_results()
        import roof_pilot_report
        roof_pilot_report.generate_report(DEST / 'results.json', DEST / 'report.html')
        print(json.dumps(result['summary'], indent=2), flush=True)


if __name__ == '__main__':
    main()
