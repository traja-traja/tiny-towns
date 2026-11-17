"""Reproducible local roof batch: canonical results, inputs, times and HTML.

Example: python scripts/roof_batch.py --output <new-directory> --test
         --previous <previous-directory> --open
Every invocation is an analytical HTML report run, with point-profile ridge
diagnostics enabled. --test adds a previous/current comparison; it does not
control diagnostic computation. Map production uses night_roof_batch instead.
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
from roof_config import resolve_config, resolve_execution_config, ALGORITHM_VERSION
from roof_v2_report import render_report
from roof_candidate_telemetry import capture
from roof_candidate_summary import summarize_candidate_telemetry
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


def restore_checkpoint(output, expected_run, selected):
    """Resume a saved prefix only when geometry, settings and point caches agree."""
    run = read_json(output/'run.json')
    document = read_json(output/'results.json')
    packed = read_json(output/'inputs.json')
    for key in ('algorithm', 'input_manifest', 'previous', 'configuration', 'expected_buildings'):
        if run.get(key) != expected_run.get(key):
            raise ValueError(f'Resume mismatch: {key}')
    # The runner may gain recovery/reporting fixes; numerical modules must match.
    for name, digest in expected_run['source_code'].items():
        if name != 'roof_batch.py' and run.get('source_code', {}).get(name) != digest:
            raise ValueError(f'Resume algorithm changed: {name}')
    done = document['buildings']
    saved = packed['buildings']
    if len(done) != len(saved) or [b['id'] for b in done] != [b['id'] for b in selected[:len(done)]]:
        raise ValueError('Resume checkpoint is not a consistent input prefix')
    for source, building, frozen in zip(selected, done, saved):
        if source.get('roof_config_overrides')!=frozen.get('roof_config_overrides'):
            raise ValueError('Resume per-building configuration changed')
        if building['id'] != frozen['id'] or len(source['parts']) != len(frozen['parts']):
            raise ValueError('Resume checkpoint parts differ')
        for original, part in zip(source['parts'], frozen['parts']):
            for key in ('part_index', 'footprint', 'origin_xy', 'ground_z'):
                if original.get(key) != part.get(key):
                    raise ValueError(f'Resume input changed: {source["id"]} {key}')
            source_cache=part.get('source_cache',part['cache']) if part.get('footprint_support') else part['cache']
            if original['cache'].get('sha256') != source_cache.get('sha256'):
                raise ValueError('Resume point input changed')
            if original.get('context_cache',{}).get('sha256')!=part.get('context_cache',{}).get('sha256'):
                raise ValueError('Resume wider context changed')
            cache = output/part['cache']['path']
            if hashlib.sha256(cache.read_bytes()).hexdigest() != part['cache']['sha256']:
                raise ValueError('Resume saved point cache damaged')
    run.setdefault('resumes', []).append({
        'at_utc':datetime.now(timezone.utc).isoformat(), 'skipped_buildings':len(done),
        'runner_sha256':expected_run['source_code']['roof_batch.py']})
    return run, document, packed


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


def source_records(inputs_path, ids, city=None):
    saved = inputs_path.parent/'source_records.json'
    if saved.is_file():
        prior = read_json(saved)
        return {oid:prior.get(oid, {}) for oid in ids}
    records = {oid:{} for oid in ids}
    city = city or read_json(inputs_path).get('city', 'ceske-budejovice')
    if city not in ('ceske-budejovice', 'velesin'):
        raise ValueError(f'Unsupported roof input city: {city}')
    preview = ROOT/'.work/.preview'/city
    data = preview/('data_all' if city == 'velesin' else 'data')
    parquet = data/'building.parquet'
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
    parser.add_argument('--test', action='store_true', help='Add inputs archive and previous/current comparison; analytical ridge diagnostics run in all HTML reports')
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--id', action='append', dest='ids')
    parser.add_argument('--no-pyramidal', action='store_true', help='Disable the pyramidal candidate family')
    parser.add_argument('--config', type=Path, help='JSON overrides for module switches, thresholds and score weights')
    parser.add_argument('--no-annex', action='store_true', help='Disable annex detection and fit the whole footprint')
    parser.add_argument('--split-volumes', action='store_true', help='Split strict 2D connectors first; otherwise compare height-profile partitions; fit children without further splitting')
    parser.add_argument('--resume', action='store_true', help='Continue a matching interrupted batch without recalculating its saved prefix')
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
    roof_config = resolve_execution_config(roof_config, mode='report')
    if args.test and not args.previous:
        parser.error('--test requires --previous')
    if args.previous and not args.test:
        parser.error('--previous is used with --test')
    output, input_path = args.output.resolve(), args.inputs.resolve()
    if output == input_path.parent or output in input_path.parents:
        parser.error('Output must not replace the source inputs directory or its ancestors')
    if args.previous and (output == args.previous.resolve() or output in args.previous.resolve().parents):
        parser.error('Output must not replace the previous directory or its ancestors')
    if not args.resume and output.exists() and any(output.iterdir()):
        parser.error('Output directory is not empty; choose a new run directory')
    if args.resume and not (output/'run.json').is_file():
        parser.error('--resume requires an existing batch checkpoint')
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
    (output/'point-clouds').mkdir(exist_ok=args.resume)
    raw_sources = source_records(input_path, {b['id'] for b in selected}, inputs.get('city'))
    run = {'schema':'roof-batch-run/1', 'created_at_utc':datetime.now(timezone.utc).isoformat(),
           'algorithm':ALGORITHM_VERSION, 'input_manifest':str(input_path),
           'output':str(output), 'previous':str(args.previous.resolve()) if args.previous else None,
           'configuration':{'roof':roof_config, 'threads':1, 'test_mode':True,'comparison_mode':args.test,'execution_mode':'report',
                            'analytical_ridges':True,'candidate_telemetry':'detailed','split_volumes':args.split_volumes},
           'source_code':{}, 'errors':[], 'status':'running', 'expected_buildings':len(selected)}
    for name in ['roof_batch.py','roof_annex.py','roof_config.py','roof_eave_planes.py','roof_connected_wings.py','roof_parallel.py','roof_flat_majority.py','roof_flat_protrusions.py','roof_v2.py','roof_v2_geometry.py','roof_v2_report.py','roof_v2_viewer.js','roof_volume_pipeline.py','roof_footprint_connector.py','roof_longitudinal_experiment.py','roof_longitudinal_split.py','roof_sections.py','roof_footprint_regularization.py','roof_butterfly.py','roof_butterfly_support.py','roof_footprint_support.py','roof_input_refinement.py','roof_observed_ridges.py','roof_candidate_telemetry.py','roof_candidate_summary.py','roof_skeleton_candidate.py','roof_skeleton_gables.py','roof_skeleton_caps.py','roof_virtual_outline.py']:
        run['source_code'][name] = hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest()
    document = {k:inputs[k] for k in ('city','source','crs','vertical_datum')}
    document.update(schema='roof-v2/1', status='running', created_at_utc=run['created_at_utc'],
                    algorithm=run['algorithm'], configuration=run['configuration'], buildings=[])
    packed_inputs = {**inputs, 'buildings':[], 'cache_path_base':'manifest_directory',
                     'source_records':'source_records.json'}
    if args.resume:
        try:
            run, document, packed_inputs = restore_checkpoint(output, run, selected)
        except (ValueError, OSError, KeyError) as error:
            parser.error(str(error))
    else:
        write_json(output/'source_records.json', raw_sources)
        write_json(output/'config.json', roof_config)
    completed = len(document['buildings'])
    elapsed_before = run.get('checkpoint_wall_seconds', sum(b.get('timing', {}).get('wall_seconds', 0) for b in document['buildings']))
    cpu_before = run.get('checkpoint_cpu_seconds', 0)
    roof_times = [p['result']['timing']['total_seconds'] for b in document['buildings']
                  for p in b['parts'] if p.get('status') == 'inferred']
    if completed:
        print(json.dumps({'resuming_after_buildings':completed, 'remaining':len(selected)-completed}), flush=True)
    with guard.keep_awake():
        for number, source in enumerate(selected, 1):
            if number <= completed:
                continue
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
            effective_config=copy.deepcopy(roof_config)
            def merge_overrides(target,patch):
                for key,value in patch.items():
                    if isinstance(value,dict) and isinstance(target.get(key),dict):merge_overrides(target[key],value)
                    else:target[key]=copy.deepcopy(value)
            merge_overrides(effective_config,source.get('roof_config_overrides',{}))
            effective_config=resolve_execution_config(effective_config, mode='report')
            for input_part in source['parts']:
                io_started = time.perf_counter()
                part = copy.deepcopy(input_part)
                candidate_trace = None
                inference_started = None
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
                    support_metadata=None
                    if effective_config['modules']['footprint_support']:
                        from roof_input_refinement import refine_input_part
                        part,points,support_metadata=refine_input_part(part,base,output,filename,effective_config)
                        cache_hash=part['cache']['sha256']
                    part['input_read_seconds'] = time.perf_counter()-io_started-(support_metadata['timing']['total_seconds'] if support_metadata else 0.)
                    packed['parts'].append(copy.deepcopy(part))
                    fit_footprint=part.get('effective_footprint',part['footprint']) if support_metadata else part['footprint']
                    inference_started = time.perf_counter()
                    with capture(detailed=True) as candidate_trace:
                        if args.split_volumes:
                            from roof_volume_pipeline import infer_volume_roof
                            result=infer_volume_roof(fit_footprint,points,config=effective_config)
                            children=result.pop('_child_results',[])
                            if children:
                                (output/'volumes').mkdir(exist_ok=True)
                                for child_index,child in enumerate(children):
                                    name=f"volumes/{source['id']}-{input_part['part_index']}-{child_index+1}.json"
                                    body=result['model']['metadata']['bodies'][child_index]
                                    write_json(output/name,dict(parent_id=source['id'],footprint=body['footprint'],
                                        origin_xy=part.get('origin_xy'),ground_z=part.get('ground_z'),cache_sha256=cache_hash,result=child))
                                    body['model_file']=name
                        else:
                            result = infer_modular_roof(fit_footprint, points, config=effective_config)
                    result.setdefault('diagnostics',{})['candidate_telemetry']=candidate_trace.to_dict()
                    if support_metadata:
                        result.setdefault('diagnostics',{})['footprint_support']=support_metadata
                        result['model']['metadata'].update(source_footprint=part['footprint'],
                            effective_footprint=result['model']['metadata'].get('effective_footprint',fit_footprint),
                            footprint_modified=bool(support_metadata['changed'] or result['model']['metadata'].get('footprint_modified')))
                        result['timing']['footprint_support_seconds']=support_metadata['timing']['total_seconds']
                        result['timing']['roof_only_seconds']=result['timing']['total_seconds']
                        result['timing']['total_seconds']+=support_metadata['timing']['total_seconds']
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
                    if candidate_trace is not None:
                        part['candidate_telemetry']=candidate_trace.to_dict()
                        part['timing']={'total_seconds':time.perf_counter()-inference_started}
                    run['errors'].append({'building_id':source['id'], 'part_index':input_part.get('part_index'), **part['error']})
                building['parts'].append(part)
            building['status'] = 'complete' if all(p.get('status')=='inferred' for p in building['parts']) else 'incomplete'
            building['timing'] = {'wall_seconds':time.perf_counter()-building_started,
                'roof_compute_seconds':sum(p.get('result', {}).get('timing', {}).get('total_seconds', 0) for p in building['parts'])}
            document['buildings'].append(building); packed_inputs['buildings'].append(packed)
            run['checkpoint_wall_seconds'] = elapsed_before+time.perf_counter()-started
            run['checkpoint_cpu_seconds'] = cpu_before+time.process_time()-cpu_started
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
                   wall_seconds_before_report=elapsed_before+time.perf_counter()-started)
        analytical_seconds=sum(p.get('result',{}).get('timing',{}).get('observed_ridges_seconds',0.) for b in document['buildings'] for p in b.get('parts',[]))
        run['analytical_ridges_seconds']=analytical_seconds
        run['roof_seconds_excluding_analytical_ridges']=max(0.,sum(roof_times)-analytical_seconds)
        document['status'] = run['status']; document['run_summary'] = run
        candidate_summary=summarize_candidate_telemetry(document)
        write_json(output/'candidate-summary.json',candidate_summary)
        report_data = compare_documents(document, previous, args.previous.name) if args.test else copy.deepcopy(document)
        summary = f"{len(selected)} domů · výpočet střech celkem {sum(roof_times):.3f} s · úspěšných částí {len(roof_times)} · chyb {len(run['errors'])}"
        report_data['report'] = {'batch':True, 'title':'Porovnání střech · '+output.name if args.test else 'Střechy · '+output.name,
            'subtitle':('Při výchozím pohledu vlevo předchozí, vpravo nová verze. ' if args.test else '')+summary,
            'note':'Čas výpočtu střechy zahrnuje přípravu bodů, přizpůsobení kandidátů, tvorbu geometrie a analytické řezy. Analytické řezy mají vlastní čas; mapové dávky je nespouštějí. Načítání vstupů a sestavení HTML se měří zvlášť. Výšky jsou nad lokálním terénem. Vzhled posuzuje uživatel.',
            'links':[{'label':'Výsledky JSON', 'href':'results.json'}, {'label':'Časy celé dávky', 'href':'run.json'},
                     {'label':'Četnost a časy kandidátů', 'href':'candidate-summary.json'},
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
        if args.split_volumes:
            command += ' --split-volumes'
        if args.test:
            command += f' --test --previous "{args.previous.resolve()}"'
        (output/'RUN.txt').write_text(command+' --open\n\n'
            'results.json contains only the current models. comparison.json is for display only.\n'
            'The comparison baseline stays fixed to --previous when reproducing this run; it does not advance automatically.\n'
            'inputs.json and point-clouds contain the exact cropped inputs (train and withheld points); no complete LAZ downloads are duplicated.\n'
            'source_records.json preserves locally available provider records; it is not a fresh complete OSM API response.\n'
            'Floor count from source is preserved; a new floor estimate has not been calculated.\n'
            'All roof_batch runs are analytical HTML tests: point-profile ridge diagnostics are enabled. Map production disables them.\n'
            'Candidate telemetry includes nested volume/annex attempts once per input part; candidate-summary.json aggregates only current models.\n'
            'Use --id repeatedly for a subset. Choose a new output directory for each run.\n', encoding='utf-8')
        write_json(output/'run.json', run)
        if args.test:
            with zipfile.ZipFile(output/'input-bundle.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in [output/'inputs.json', output/'source_records.json', output/'config.json', output/'RUN.txt', output/'run.json', *sorted((output/'point-clouds').glob('*.npz')), *sorted((output/'context-clouds').glob('*.npz'))]:
                    archive.write(path, path.relative_to(output).as_posix())
        run['wall_seconds'] = elapsed_before+time.perf_counter()-started
        run['cpu_seconds'] = cpu_before+time.process_time()-cpu_started
        run['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        if args.resume:
            run['timing_note'] = 'Active batch time excludes stopped intervals; a legacy checkpoint contributes saved building wall times only.'
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
