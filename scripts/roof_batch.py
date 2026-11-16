"""Reproducible local roof batch: canonical results, inputs, times and HTML.

Example: python scripts/roof_batch.py --output <new-directory> --test
         --previous <previous-directory> --open
No downloads, AI calls, screenshots, or architectural quality judgments.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import webbrowser
import zipfile
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','ARROW_NUM_THREADS'):
    os.environ[_key] = '1'
ROOT = Path(__file__).resolve().parents[1]
LOCAL_PACKAGES = ROOT/'.venv/Lib/site-packages'
if LOCAL_PACKAGES.is_dir():
    sys.path.insert(0, str(LOCAL_PACKAGES))
import numpy as np
import shapely
from shapely.geometry import mapping
from roof_annex import infer_modular_roof
from roof_config import resolve_config
from roof_v2_report import render_report
import resource_guard as guard

DEFAULT_INPUTS = ROOT/'cities/ceske-budejovice/experiments/roof-v2/inputs.json'


def json_default(value):
    if isinstance(value, (datetime,)) or hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, bytes):
        try:
            return mapping(shapely.from_wkb(value))
        except Exception:
            return {'encoding':'hex', 'value':value.hex()}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def write_json(path, data):
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
    guard.check_budget(reserve_bytes=len(payload.encode('utf-8')))
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(payload, encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def current_parts(document, building):
    parts = building.get('parts', [])
    if document.get('comparison_mode'):
        explicit = [p for p in parts if p.get('display_variant') == 'current']
        if explicit:
            return explicit
        # Compatibility with earlier comparison reports: current version last.
        latest = {}
        for part in parts:
            latest[part.get('part_index', 0)] = part
        return list(latest.values())
    return parts


def compare_documents(current, previous, previous_label):
    output = copy.deepcopy(current)
    output['comparison_mode'] = 'batch'
    previous_by_id = {b['id']:b for b in previous.get('buildings', [])}
    for building in output['buildings']:
        earlier = previous_by_id.get(building['id'])
        old = copy.deepcopy(current_parts(previous, earlier)) if earlier else []
        new = building['parts']
        for part in old:
            part['display_variant'] = 'previous'
            part['display_label'] = 'Předchozí · '+part.get('previous_source_run', previous_label)
        for part in new:
            part['display_variant'] = 'current'
            part['display_label'] = 'Nová · '+part.get('result', {}).get('algorithm', 'chyba')
        ref = next((p.get('origin_xy') for p in old+new if p.get('origin_xy')), [0.,0.])
        right = np.array([np.cos(-.8), np.sin(-.8)])
        projected = []
        for part in old+new:
            vertices = part.get('result', {}).get('model', {}).get('mesh', {}).get('vertices', [])
            if vertices:
                xy = np.asarray(vertices)[:, :2]+np.asarray(part.get('origin_xy', ref))-ref
                projected.extend((xy@right).tolist())
        spacing = float(np.ptp(projected)+8) if projected else 25.
        for group, direction in ((old,-1), (new,1)):
            for part in group:
                part['display_offset_m'] = [*map(float, right*spacing*.5*direction), 0.] if old else [0.,0.,0.]
        building['parts'] = old+new
        building['comparison'] = {'matched_by':'building id + part_index', 'previous_available':bool(old)}
    return output


def source_records(inputs_path, ids):
    saved = inputs_path.parent/'source_records.json'
    if saved.is_file():
        prior = read_json(saved)
        return {oid:prior.get(oid, {}) for oid in ids}
    records = {oid:{} for oid in ids}
    preview = ROOT/'.work/.preview/ceske-budejovice'
    parquet = preview/'data/building.parquet'
    if parquet.is_file():
        import pyarrow.parquet as pq
        for row in pq.read_table(parquet, filters=[('id','in',list(ids))]).to_pylist():
            records[row['id']]['overture_building'] = row
        for record in records.values():
            record['building_record_origin'] = str(parquet)
            record['building_record_note'] = 'Locally available Overture record including provider provenance; not a newly fetched complete OSM tag history.'
    scene = preview/'build/info_src.json'
    if scene.is_file():
        data = read_json(scene)
        for row in data.get('buildings', []) if isinstance(data, dict) else data:
            if row.get('oid') in records:
                records[row['oid']]['existing_map_record'] = row
                records[row['oid']]['map_record_origin'] = str(scene)
    return json.loads(json.dumps(records, ensure_ascii=False, default=json_default, allow_nan=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--inputs', type=Path, default=DEFAULT_INPUTS)
    parser.add_argument('--test', action='store_true', help='Include inputs archive and previous/current comparison')
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--id', action='append', dest='ids')
    parser.add_argument('--no-pyramidal', action='store_true', help='Disable the pyramidal candidate family')
    parser.add_argument('--config', type=Path, help='JSON overrides for module switches, thresholds and score weights')
    parser.add_argument('--no-annex', action='store_true', help='Disable annex detection and fit the whole footprint')
    parser.add_argument('--open', action='store_true', help='Open the generated HTML after completion')
    parser.add_argument('--url-base', help='Existing HTTP server URL serving the project root; otherwise open local HTML')
    args = parser.parse_args(argv)
    try:
        roof_config = resolve_config(read_json(args.config) if args.config else None)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.no_annex:
        roof_config['modules']['annex_detection'] = False
    if args.no_pyramidal:
        roof_config['modules']['pyramidal'] = False
    roof_config = resolve_config(roof_config)
    if args.test and not args.previous:
        parser.error('--test requires --previous')
    if args.previous and not args.test:
        parser.error('--previous is used with --test')
    output, input_path = args.output.resolve(), args.inputs.resolve()
    if output == input_path.parent or output in input_path.parents:
        parser.error('Output must not replace the source inputs directory or its ancestors')
    if args.previous and (output == args.previous.resolve() or output in args.previous.resolve().parents):
        parser.error('Output must not replace the previous directory or its ancestors')
    if output.exists() and any(output.iterdir()):
        parser.error('Output directory is not empty; choose a new run directory')
    guard.check_budget(reserve_bytes=30*1024**2, force=True)
    started = time.perf_counter(); cpu_started = time.process_time()
    inputs = read_json(input_path)
    selected = [b for b in inputs['buildings'] if not args.ids or b['id'] in args.ids]
    if not selected:
        parser.error('No input buildings selected')
    if args.ids and set(args.ids)-{b['id'] for b in selected}:
        parser.error('Some requested IDs are missing from the input manifest')
    previous = read_json(args.previous/'results.json') if args.test else None
    output.mkdir(parents=True, exist_ok=True)
    (output/'point-clouds').mkdir()
    raw_sources = source_records(input_path, {b['id'] for b in selected})
    write_json(output/'source_records.json', raw_sources)
    write_json(output/'config.json', roof_config)
    run = {'schema':'roof-batch-run/1', 'created_at_utc':datetime.now(timezone.utc).isoformat(),
           'algorithm':'modular-roofs-4.5', 'input_manifest':str(input_path),
           'output':str(output), 'previous':str(args.previous.resolve()) if args.previous else None,
           'configuration':{'roof':roof_config, 'threads':1, 'test_mode':args.test},
           'source_code':{}, 'errors':[], 'status':'running', 'expected_buildings':len(selected)}
    for name in ['roof_batch.py','roof_annex.py','roof_config.py','roof_eave_planes.py','roof_parallel.py','roof_v2.py','roof_v2_geometry.py','roof_v2_report.py','roof_v2_viewer.js']:
        run['source_code'][name] = hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest()
    document = {k:inputs[k] for k in ('city','source','crs','vertical_datum')}
    document.update(schema='roof-v2/1', status='running', created_at_utc=run['created_at_utc'],
                    algorithm=run['algorithm'], configuration=run['configuration'], buildings=[])
    packed_inputs = {**inputs, 'buildings':[], 'cache_path_base':'manifest_directory',
                     'source_records':'source_records.json'}
    roof_times = []
    with guard.keep_awake():
        for number, source in enumerate(selected, 1):
            guard.check_budget()
            if guard.memory_status()['available'] < 350_000_000:
                raise guard.ResourceLimit('STOP: less than 350 MB available RAM')
            building_started = time.perf_counter()
            building = {k:copy.deepcopy(v) for k,v in source.items() if k!='parts'}
            building['input_data'] = {'source_attributes':source.get('source_attributes', {}),
                'footprint_sources':source.get('footprint_sources', []), 'provider_records':raw_sources[source['id']],
                'floor_count':{'source_value':source.get('source_attributes', {}).get('num_floors'),
                               'estimate':None, 'estimate_method':None}}
            building['parts'] = []
            packed = copy.deepcopy(source)
            packed['parts'] = []
            for input_part in source['parts']:
                io_started = time.perf_counter()
                part = copy.deepcopy(input_part)
                try:
                    original_cache = Path(input_part['cache']['path'])
                    base = input_path.parent if inputs.get('cache_path_base')=='manifest_directory' else ROOT
                    cache = original_cache if original_cache.is_absolute() else base/original_cache
                    filename = f"{source['id']}-{input_part['part_index']}.npz"
                    destination = output/'point-clouds'/filename
                    shutil.copyfile(cache, destination)
                    cache_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
                    if input_part['cache'].get('sha256') and cache_hash != input_part['cache']['sha256']:
                        raise ValueError('Point cache differs from the frozen input checksum')
                    part['source_cache'] = copy.deepcopy(input_part['cache'])
                    part['cache'] = {'path':'point-clouds/'+filename, 'bytes':destination.stat().st_size, 'sha256':cache_hash}
                    with np.load(destination) as data:
                        points = data['train']
                    part['input_read_seconds'] = time.perf_counter()-io_started
                    packed['parts'].append(copy.deepcopy(part))
                    result = infer_modular_roof(part['footprint'], points, config=roof_config)
                    roof_times.append(result['timing']['total_seconds'])
                    result['timing']['input_read_seconds'] = part['input_read_seconds']
                    part.update(result=result, status='inferred',
                        point_preview=points[::max(1, int(np.ceil(len(points)/1500)))].tolist())
                    meta = result['model']['metadata']
                    meta['source_floor_count'] = source.get('source_attributes', {}).get('num_floors')
                    meta['estimated_floor_count'] = None
                    meta['height_reference'] = 'metres above ground_z; ground_z is Bpv'
                except guard.ResourceLimit:
                    raise
                except Exception as error:
                    part.update(status='failed', error={'type':type(error).__name__, 'message':str(error)})
                    run['errors'].append({'building_id':source['id'], 'part_index':input_part.get('part_index'), **part['error']})
                building['parts'].append(part)
            building['status'] = 'complete' if all(p.get('status')=='inferred' for p in building['parts']) else 'incomplete'
            building['timing'] = {'wall_seconds':time.perf_counter()-building_started,
                'roof_compute_seconds':sum(p.get('result', {}).get('timing', {}).get('total_seconds', 0) for p in building['parts'])}
            document['buildings'].append(building); packed_inputs['buildings'].append(packed)
            write_json(output/'results.json', document)
            write_json(output/'inputs.json', packed_inputs)
            write_json(output/'run.json', run)
            event = {'completed':number, 'total':len(selected), 'address':building.get('address'),
                     'status':building['status'], **building['timing']}
            with (output/'progress.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=False)+'\n')
            print(json.dumps(event, ensure_ascii=False), flush=True)
        run.update(status='complete' if not run['errors'] else 'complete_with_errors',
                   completed_buildings=len(document['buildings']),
                   successful_parts=len(roof_times),
                   roof_compute_seconds=sum(roof_times),
                   median_roof_seconds=float(np.median(roof_times)) if roof_times else None,
                   max_roof_seconds=max(roof_times, default=None),
                   wall_seconds_before_report=time.perf_counter()-started)
        document['status'] = run['status']; document['run_summary'] = run
        report_data = compare_documents(document, previous, args.previous.name) if args.test else copy.deepcopy(document)
        summary = f"{len(selected)} domů · výpočet střech celkem {sum(roof_times):.3f} s · úspěšných částí {len(roof_times)} · chyb {len(run['errors'])}"
        report_data['report'] = {'batch':True, 'title':'Porovnání střech · '+output.name if args.test else 'Střechy · '+output.name,
            'subtitle':('Při výchozím pohledu vlevo předchozí, vpravo nová verze. ' if args.test else '')+summary,
            'note':'Čas výpočtu střechy zahrnuje přípravu bodů, přizpůsobení kandidátů a tvorbu geometrie. Načítání vstupů a sestavení HTML se měří zvlášť. Výšky jsou nad lokálním terénem. Vzhled posuzuje uživatel.',
            'links':[{'label':'Výsledky JSON', 'href':'results.json'}, {'label':'Časy celé dávky', 'href':'run.json'},
                     {'label':'Konfigurace modulů', 'href':'config.json'},
                     {'label':'Vstupy JSON', 'href':'inputs.json'}, {'label':'Spuštění', 'href':'RUN.txt'}]}
        if args.test:
            report_data['report']['links'].append({'label':'Zabalené vstupy ZIP', 'href':'input-bundle.zip'})
        write_json(output/'results.json', document)
        report_input = output/('comparison.json' if args.test else 'viewer.json')
        write_json(report_input, report_data)
        report_started = time.perf_counter()
        render_report(report_input, output/'report.html')
        run['report_seconds'] = time.perf_counter()-report_started
        command = f'python scripts/roof_batch.py --inputs "{output / "inputs.json"}" --config "{output / "config.json"}" --output "<nova-slozka>"'
        if args.no_pyramidal:
            command += ' --no-pyramidal'
        if args.test:
            command += f' --test --previous "{output}"'
        (output/'RUN.txt').write_text(command+' --open\n\n'
            'results.json contains only the current models. comparison.json is for display only.\n'
            'inputs.json and point-clouds contain the exact cropped inputs (train and withheld points); no complete LAZ downloads are duplicated.\n'
            'source_records.json preserves locally available provider records; it is not a fresh complete OSM API response.\n'
            'Floor count from source is preserved; a new floor estimate has not been calculated.\n'
            'Use --id repeatedly for a subset. Choose a new output directory for each run.\n', encoding='utf-8')
        write_json(output/'run.json', run)
        if args.test:
            with zipfile.ZipFile(output/'input-bundle.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in [output/'inputs.json', output/'source_records.json', output/'config.json', output/'RUN.txt', output/'run.json', *sorted((output/'point-clouds').glob('*.npz'))]:
                    archive.write(path, path.relative_to(output).as_posix())
        run['wall_seconds'] = time.perf_counter()-started
        run['cpu_seconds'] = time.process_time()-cpu_started
        write_json(output/'run.json', run)
        guard.check_budget(force=True)
    url = output.joinpath('report.html').as_uri()
    if args.url_base:
        url = args.url_base.rstrip('/')+'/'+(output/'report.html').relative_to(ROOT).as_posix()
    if args.open:
        run['browser_open_requested'] = True
        run['browser_open_returned'] = webbrowser.open(url)
        write_json(output/'run.json', run)
    print(json.dumps({'report_url':url, 'status':run['status'], 'buildings':len(selected),
                      'roof_compute_seconds':sum(roof_times), 'wall_seconds':run['wall_seconds'],
                      'errors':run['errors']}, ensure_ascii=False), flush=True)
    return 0 if not run['errors'] else 1


if __name__ == '__main__':
    sys.exit(main())
