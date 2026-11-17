"""Unattended local roof queue; sequential fitting, atomic checkpoints and HTML.

MODULES: fingerprints/cache, one-building worker, paginated reports, guarded
process supervisor, city-stage scheduling. No AI/API calls or visual reviews.
Point-cloud extraction is a separate night_roof_inputs.py process.
"""
from __future__ import annotations
import argparse
import copy
import contextlib
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.venv/Lib/site-packages'))
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
            'NUMEXPR_NUM_THREADS', 'ARROW_NUM_THREADS'):
    os.environ[key] = '1'
import resource_guard as guard

VERSION = 'modular-roofs-4.9.1'
STOP_FILE = None
ALGORITHM_FILES = ('roof_annex.py', 'roof_config.py', 'roof_eave_planes.py',
                   'roof_connected_wings.py', 'roof_parallel.py',
                   'roof_flat_majority.py', 'roof_flat_protrusions.py',
                   'roof_v2.py', 'roof_v2_geometry.py')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    def scalar(item):
        if hasattr(item, 'tolist'): return item.tolist()
        if hasattr(item, 'item'): return item.item()
        raise TypeError(type(item).__name__)
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'), default=scalar)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(payload, encoding='utf-8')
    temp.replace(path)


def utc():
    return datetime.now(timezone.utc).isoformat()


def identity(config):
    return {'algorithm': VERSION, 'configuration': config,
            'code': {name: guard.sha256(ROOT / 'scripts' / name) for name in ALGORITHM_FILES}}


def fingerprint(building, engine):
    """Reuse only identical geometry, heights, point crops and algorithm settings."""
    parts = [{k: p.get(k) for k in ('part_index', 'footprint', 'origin_xy', 'ground_z')}
             | {'point_sha256': p.get('cache', {}).get('sha256')} for p in building['parts']]
    if any(not p['point_sha256'] for p in parts):
        raise ValueError('A frozen point checksum is required for cache reuse')
    value = {'id': building['id'], 'parts': parts, 'engine': engine}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def extra_allowed(initial_seconds, essential_complete):
    return bool(essential_complete and initial_seconds < 2 * 3600)


@contextlib.contextmanager
def singleton(output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    with (output / 'night.lock').open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1): stream.write(b'0'); stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt': msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def check_stop():
    if STOP_FILE and STOP_FILE.exists():
        raise guard.ResourceLimit('Stopped by user STOP file; checkpoints preserved')


def model_file(cache, oid, digest):
    # Provider IDs are data, never paths.
    key = hashlib.sha256(str(oid).encode()).hexdigest()[:24]
    return Path(cache) / (key + '-' + digest[:20] + '.json')


def cached_model(path, digest):
    if not path.is_file():
        return None
    value = read(path)
    if value.get('fingerprint') == digest and value.get('model', {}).get('status') == 'complete':
        return value['model']
    return None


def seed_prior(cache, engine, directories):
    """Small prior reports can seed matching cache entries, without refitting."""
    from roof_batch import current_parts
    for directory in directories:
        directory = Path(directory)
        if not all((directory / f).is_file() for f in ('run.json', 'inputs.json', 'results.json')):
            continue
        run = read(directory / 'run.json')
        if (run.get('algorithm') != VERSION or
                run.get('configuration', {}).get('roof') != engine['configuration'] or
                any(run.get('source_code', {}).get(k) != v for k, v in engine['code'].items())):
            continue
        inputs, results = read(directory / 'inputs.json'), read(directory / 'results.json')
        by_id = {b['id']: b for b in results['buildings']}
        for source in inputs['buildings']:
            model = by_id.get(source['id'])
            if not model or model.get('status') != 'complete':
                continue
            model = copy.deepcopy(model)
            model['parts'] = current_parts(results, model)
            digest = fingerprint(source, engine)
            path = model_file(cache, source['id'], digest)
            if not path.exists():
                model['reused_from'] = str(directory)
                write(path, {'fingerprint': digest, 'model': model, 'created_at_utc': utc()})


def page_report(output, entries, header, page_number, page_size=40):
    """Generate only the affected page; never embed a whole city's mesh in one HTML."""
    from roof_v2_report import render_report
    selected = entries[(page_number - 1) * page_size:page_number * page_size]
    models = [read(e['model_file'])['model'] for e in selected if e.get('model_file')]
    if not models:
        return
    payload = dict(header, schema='roof-v2/1', buildings=models, algorithm=VERSION,
                   report={'batch': True, 'title': 'Střechy · ' + header['city'],
                           'subtitle': 'Noční dávka · strana ' + str(page_number),
                           'note': 'Automatický lokální výpočet. Vzhled nebyl kontrolován. '
                                   'Časy a rozhodování jsou v metadatech jednotlivých modelů.',
                           'links': [{'label': 'Seznam domů a stav dávky', 'href': 'report.html'},
                                     {'label': 'Data této strany', 'href': f'page-{page_number:04}.json'}]})
    target = Path(output) / f'page-{page_number:04}.json'
    write(target, payload)
    render_report(target, target.with_suffix('.html'))


def stage_index(output, state):
    entries = state['entries']
    rows = []
    for i, entry in enumerate(entries):
        label = html.escape(entry.get('address') or entry['id'])
        href = f'page-{i // 40 + 1:04}.html#{entry["id"]}'
        name = f'<a href="{html.escape(href, quote=True)}">{label}</a>' if entry.get('model_file') else label
        rows.append(f'<tr><td>{name}</td><td>{html.escape(entry["status"])}</td>'
                    f'<td>{entry.get("roof_seconds", 0):.3f}</td></tr>')
    completed = sum(e['status'] in ('complete', 'reused') for e in entries)
    content = ('<!doctype html><html lang="cs"><meta charset="utf-8"><meta name="viewport" '
               'content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="90">'
               '<title>Noční střechy</title><style>body{font:16px/1.5 system-ui;max-width:1050px;'
               'margin:32px auto;padding:0 20px;color:#243a31;background:#f5f6f2}table{width:100%;'
               'border-collapse:collapse}td,th{padding:7px;text-align:left;border-bottom:1px solid #ddd}'
               'a{color:#06645f}</style><h1>Noční generování · ' + html.escape(state['city']) + '</h1>'
               f'<p>Stav: {html.escape(state["status"])} · hotovo {completed} / {state["expected"]} · '
               f'nový výpočet střech {state.get("roof_seconds", 0):.2f} s</p>'
               '<p>Samostatné 3D modely; mapové dlaždice a vlastní Sportcentrum zůstávají zachované. '
               'Bez vizuálního posuzování. Opětovné spuštění přeskočí shodné hotové modely.</p>'
               '<p><a href="stage.json">Stav a časy JSON</a> · <a href="inputs.json">Vstupní manifest</a>'
               ' · <a href="config.json">Nastavení</a></p><table><tr><th>Dům</th><th>Stav</th>'
               '<th>Střecha (s)</th></tr>' + ''.join(rows) + '</table></html>')
    path = Path(output) / 'report.html'
    temp = path.with_suffix('.html.tmp'); temp.write_text(content, encoding='utf-8'); temp.replace(path)


def worker(args):
    import numpy as np
    from roof_annex import infer_modular_roof
    from roof_config import resolve_config
    from roof_batch import source_records
    output, cache, manifest_path = args.output.resolve(), args.cache.resolve(), args.inputs.resolve()
    inputs = read(manifest_path)
    config = resolve_config(read(args.config) if args.config else None)
    engine = identity(config)
    cache.mkdir(parents=True, exist_ok=True); output.mkdir(parents=True, exist_ok=True)
    frozen = output / 'engine.json'
    if frozen.exists() and read(frozen) != engine:
        raise ValueError('Code/configuration changed: choose a new output version')
    write(frozen, engine); write(output / 'config.json', config)
    # Reference exact source NPZ rather than duplicate large city caches.
    packed = copy.deepcopy(inputs)
    base = manifest_path.parent if inputs.get('cache_path_base') == 'manifest_directory' else ROOT
    for b in packed['buildings']:
        for p in b['parts']:
            if p.get('cache', {}).get('path'):
                p['cache']['path'] = str((base / p['cache']['path']).resolve())
    packed['cache_path_base'] = 'absolute'
    write(output / 'inputs.json', packed)
    raw = source_records(manifest_path, {b['id'] for b in inputs['buildings']}, inputs['city'])
    data_dir = inputs.get('input_data_directory')
    if data_dir and (ROOT / data_dir / 'building.parquet').is_file():
        import pyarrow.parquet as pq
        from roof_batch import json_default
        parquet = ROOT / data_dir / 'building.parquet'
        records = pq.read_table(parquet, filters=[('id', 'in', [b['id'] for b in inputs['buildings']])]).to_pylist() if inputs['buildings'] else []
        for row in records:
            raw[row['id']] = {'overture_building': json.loads(json.dumps(row, default=json_default)),
                              'building_record_origin': str(parquet)}
    write(output / 'source_records.json', raw)
    seed_prior(cache, engine, args.reuse)
    state_path = output / 'stage.json'
    state = read(state_path) if state_path.exists() else {
        'schema': 'night-roof-stage/1', 'city': inputs['city'], 'entries': [],
        'started_at_utc': utc(), 'roof_seconds': 0., 'active_seconds': 0.}
    done = {e['id']: e for e in state['entries']}
    state.update(status='running', expected=len(inputs['buildings']))
    header = {k: inputs.get(k) for k in ('city', 'source', 'crs', 'vertical_datum')}
    start = time.monotonic()
    active_before = state['active_seconds']
    with guard.keep_awake():
        for source in packed['buildings']:
            if args.deadline and time.time() >= args.deadline:
                state['status'] = 'time_budget_reached'; break
            if source['id'] in done:
                continue
            guard.check_budget()
            if guard.memory_status()['available'] < 350_000_000:
                raise guard.ResourceLimit('STOP: less than 350 MB available RAM')
            ready = bool(source['parts']) and all(p.get('status') == 'prepared' and p.get('cache') for p in source['parts'])
            digest = fingerprint(source, engine) if ready else None
            target = model_file(cache, source['id'], digest) if ready else None
            write(output / 'active.json', {'id': source['id'], 'address': source.get('address'),
                                          'started_epoch': time.time(), 'model_file': str(target) if target else None})
            existing = cached_model(target, digest) if ready else None
            begin = time.perf_counter()
            entry = {'id': source['id'], 'address': source.get('address') or source.get('name'),
                     'fingerprint': digest, 'roof_seconds': 0.}
            try:
                if not ready:
                    entry.update(status='incomplete_inputs', error={'type': 'MissingPreparedParts',
                        'message': 'Unavailable point or ground reference; no invented model',
                        'part_statuses': [p.get('status') for p in source['parts']]})
                elif existing:
                    entry.update(status='reused', model_file=str(target))
                else:
                    building = {k: copy.deepcopy(v) for k, v in source.items() if k != 'parts'}
                    building.update(parts=[], input_data={'provider_records': raw.get(source['id'], {}),
                        'source_attributes': source.get('source_attributes', {}),
                        'floor_count': {'source_value': source.get('source_attributes', {}).get('num_floors'),
                                        'estimate': None, 'estimate_method': None}})
                    for ip in source['parts']:
                        part = copy.deepcopy(ip)
                        path = Path(ip['cache']['path'])
                        if guard.sha256(path) != ip['cache']['sha256']:
                            raise ValueError('Point cache checksum mismatch')
                        io_start = time.perf_counter()
                        with np.load(path) as data:
                            points = data['train']
                        io_seconds = time.perf_counter() - io_start
                        result = infer_modular_roof(part['footprint'], points, config=config)
                        result['timing']['input_read_seconds'] = io_seconds
                        meta = result['model']['metadata']
                        meta.update(source_floor_count=source.get('source_attributes', {}).get('num_floors'),
                                    estimated_floor_count=None,
                                    height_reference='metres above ground_z; ground_z is Bpv')
                        part.update(result=result, status='inferred',
                                    point_preview=points[::max(1, int(np.ceil(len(points) / 300)))].tolist())
                        building['parts'].append(part)
                        entry['roof_seconds'] += result['timing']['total_seconds']
                    if not building['parts']:
                        raise ValueError('No prepared polygon parts')
                    building.update(status='complete', timing={'roof_compute_seconds': entry['roof_seconds'],
                                    'wall_seconds': time.perf_counter() - begin})
                    write(target, {'fingerprint': digest, 'model': building, 'created_at_utc': utc()})
                    entry.update(status='complete', model_file=str(target))
            except guard.ResourceLimit:
                raise
            except Exception as error:
                entry.update(status='failed', error={'type': type(error).__name__, 'message': str(error)})
            entry['wall_seconds'] = time.perf_counter() - begin
            state['entries'].append(entry); done[source['id']] = entry
            state['roof_seconds'] += entry['roof_seconds']
            state['active_seconds'] = active_before + time.monotonic() - start
            state['updated_at_utc'] = utc()
            write(state_path, state)
            write(output / 'active.json', {'idle': True})
            with (output / 'progress.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
            print(json.dumps({'completed': len(done), 'expected': state['expected'], **entry},
                             ensure_ascii=False), flush=True)
            if len(done) % 10 == 0:
                page_report(output, state['entries'], header, (len(done) - 1) // 40 + 1)
                stage_index(output, state)
        else:
            state['status'] = 'complete' if all(e['status'] in ('complete', 'reused') for e in state['entries']) else 'complete_with_errors'
        state['active_seconds'] = active_before + time.monotonic() - start
        state['updated_at_utc'] = utc(); write(state_path, state)
        for p in range(1, (len(state['entries']) + 39) // 40 + 1):
            page_report(output, state['entries'], header, p)
        stage_index(output, state)
    return 0


def python_command(script, arguments):
    boot = ('import sys,runpy;sys.path[:0]=' + repr([str(ROOT / '.venv/Lib/site-packages'), str(ROOT / 'scripts')]) +
            ';sys.argv=' + repr([str(script), *map(str, arguments)]) + ';runpy.run_path(' + repr(str(script)) + ',run_name="__main__")')
    return [sys.executable, '-S', '-u', '-X', 'utf8', '-c', boot]


def supervise(command, log_path, deadline=None, active_path=None, house_timeout=180):
    """Bound child tree and individual fitting; no overnight AI supervision."""
    check_stop(); guard.check_budget(force=True)
    wait_start = time.monotonic()
    while guard.memory_status()['available'] < 1_000_000_000:
        check_stop()
        if deadline and time.time() >= deadline:
            return {'status': 'time_budget_reached'}
        if time.monotonic() - wait_start > 3600:
            raise guard.ResourceLimit('RAM remained below 1 GB for an hour')
        guard.check_budget(); time.sleep(3)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic(); job = None; peak = 0; stop = None
    with log_path.open('a', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=0x08000000 if os.name == 'nt' else 0)
        try:
            if os.name == 'nt':
                job = guard._WindowsJob(process, 1_500_000_000)
            while process.poll() is None:
                check_stop()
                guard.check_budget()
                if guard.memory_status()['available'] < 250_000_000:
                    raise guard.ResourceLimit('STOP: available system RAM below 250 MB')
                if job:
                    peak = max(peak, job.peak() or 0)
                if deadline and time.time() >= deadline:
                    stop = {'status': 'time_budget_reached'}; break
                if active_path and active_path.is_file():
                    active = read(active_path)
                    if active.get('started_epoch') and time.time() - active['started_epoch'] > house_timeout:
                        stop = {'status': 'building_timeout', 'active': active}; break
                time.sleep(.5)
            if stop:
                if job: job.terminate()
                else: process.kill()
                process.wait(timeout=15)
            result = dict(stop or {'status': 'complete' if process.returncode == 0 else 'failed'},
                          exit_code=process.returncode, elapsed_seconds=time.monotonic() - start,
                          peak_job_commit_bytes=peak)
            if job: result.update(job.accounting())
            write(log_path.with_suffix('.metrics.json'), result)
            return result
        except BaseException:
            if job: job.terminate()
            else: process.kill()
            process.wait(timeout=15)
            raise
        finally:
            if job: job.close()


def dashboard(output, state):
    rows = []
    for stage in state.get('stages', []):
        href = os.path.relpath(Path(stage['output']) / 'report.html', output).replace('\\', '/')
        label = html.escape(stage['name'])
        if (Path(stage['output']) / 'report.html').exists():
            label = '<a href="' + html.escape(href, quote=True) + '">' + label + '</a>'
        counts = str(stage.get('completed', 0)) + ' / ' + str(stage.get('expected', '?'))
        if stage.get('input_excluded'):
            counts += ' (mimo dostupné podklady: ' + str(stage['input_excluded']) + ')'
        rows.append('<tr><td>' + label + '</td><td>' + html.escape(stage['status']) +
                    '</td><td>' + counts + '</td></tr>')
    content = ('<!doctype html><html lang="cs"><meta charset="utf-8"><meta name="viewport" '
               'content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60">'
               '<title>Noční generování střech</title><style>body{font:17px/1.6 system-ui;max-width:950px;'
               'margin:40px auto;padding:0 20px;background:#f5f6f2;color:#243a31}td,th{padding:12px;'
               'text-align:left;border-bottom:1px solid #ccc}a{color:#06645f}</style>'
               '<h1>Noční generování střech · Velešín a ČB</h1><p>Algoritmus 4.9.1 · '
               + html.escape(state['status']) + '</p><p>Pořadí: čtyři velešínské ulice → celý Velešín '
               '→ náměstí a navazující ulice ČB. Pokud tyto kroky skončí do 2 hodin, další ČB nejvýše 4 hodiny.</p>'
               '<p>Lokální Python, jeden dům za druhým. Samostatné čtení mračen. Hotové shodné modely se '
               'přebírají. Bez vizuálního hodnocení; vlastní Sportcentrum i staré mapové dlaždice se nemění.</p>'
               '<table><tr><th>Etapa / výsledky</th><th>Stav</th><th>Hotové modely</th></tr>' + ''.join(rows) +
               '</table><p><a href="night.json">Průběh, časy a případné chyby JSON</a></p>'
               '<p>Limity: C: alespoň 25 GB volných, projekt nejvýše 20 GB, procesní paměť 1,5 GB; '
               'ochrana před automatickým uspáním po dobu běhu. Nedostupné podklady jsou zaznamenané v plánu.</p></html>')
    tmp = output / 'report.html.tmp'; tmp.write_text(content, encoding='utf-8'); tmp.replace(output / 'report.html')


def run(args):
    global STOP_FILE
    from roof_config import resolve_config
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    STOP_FILE = output / 'STOP'
    state_path = output / 'night.json'
    state = read(state_path) if state_path.exists() else {
        'schema': 'night-roof-run/1', 'started_epoch': time.time(), 'started_at_utc': utc(),
        'stages': [], 'status': 'starting', 'algorithm': VERSION}
    config = resolve_config(read(args.config) if args.config else None)
    engine = identity(config)
    if 'engine' in state and state['engine'] != engine:
        raise ValueError('Algorithm changed; start a new version directory')
    state['engine'] = engine
    write(output / 'config.json', config)
    city_roots = {'velesin': output, 'ceske-budejovice': ROOT / 'cities/ceske-budejovice/experiments' / output.name}
    schedule = [('velesin', 'streets', 'Velešín · čtyři zadané ulice'),
                ('velesin', 'city', 'Velešín · všechny budovy'),
                ('ceske-budejovice', 'centre', 'ČB · náměstí a navazující ulice'),
                ('ceske-budejovice', 'extra', 'ČB · další budovy, nejvýše 4 hodiny')]
    try:
        with guard.keep_awake():
            for city, stage_name, label in schedule:
                stage = next((s for s in state['stages'] if s['city'] == city and s['stage'] == stage_name), None)
                if stage and stage['status'] in ('complete', 'complete_with_errors', 'complete_with_missing_inputs', 'time_budget_reached', 'not_scheduled'):
                    continue
                stage_dir = city_roots[city] / stage_name
                if stage is None:
                    stage = {'city': city, 'stage': stage_name, 'name': label, 'output': str(stage_dir), 'status': 'pending'}
                    state['stages'].append(stage)
                deadline = None
                if stage_name == 'extra':
                    elapsed = state.setdefault('initial_elapsed_seconds', time.time() - state['started_epoch'])
                    essentials = all(s['status'] in ('complete', 'complete_with_errors') for s in state['stages'] if s is not stage)
                    if not extra_allowed(elapsed, essentials):
                        stage['status'] = 'not_scheduled'; stage['reason'] = 'Initial stages exceeded two hours or did not complete'
                        continue
                    deadline = state.setdefault('extra_deadline_epoch', time.time() + 4 * 3600)
                state['status'] = 'running'; stage['status'] = 'preparing_inputs'
                write(state_path, state); dashboard(output, state)
                plan_dir = city_roots[city] / 'plan'
                plan_file = plan_dir / 'queue.json'
                if not plan_file.exists():
                    result = supervise(python_command(ROOT / 'scripts/night_roof_inputs.py',
                        ['plan', '--city', city, '--output', plan_dir]), output / 'logs' / (city + '-plan.log'), deadline)
                    if result['status'] != 'complete':
                        raise RuntimeError('Planning failed: ' + city + ' ' + str(result))
                input_dir = city_roots[city] / ('inputs-' + stage_name)
                prepare_args = ['prepare', '--plan', plan_file, '--output', input_dir, '--stage', stage_name]
                if stage_name != 'extra': prepare_args += ['--download-missing']
                if deadline: prepare_args += ['--deadline-utc', datetime.fromtimestamp(deadline, timezone.utc).isoformat()]
                result = supervise(python_command(ROOT / 'scripts/night_roof_inputs.py', prepare_args),
                                   output / 'logs' / (city + '-' + stage_name + '-inputs.log'), deadline)
                stage['input_process'] = result
                if result['status'] == 'time_budget_reached':
                    stage['status'] = 'time_budget_reached'; break
                if result['status'] != 'complete':
                    raise RuntimeError('Input preparation failed: ' + str(result))
                manifest = input_dir / 'inputs.json'
                # Whole-city version includes street objects; immutable cache avoids refitting them.
                if city == 'velesin' and stage_name == 'city':
                    previous = city_roots[city] / 'inputs-streets/inputs.json'
                    if previous.exists():
                        combined = read(manifest); earlier = read(previous)
                        combined['buildings'] = list({b['id']: b for b in earlier['buildings'] + combined['buildings']}.values())
                        manifest = input_dir / 'inputs-all.json'; write(manifest, combined)
                prepared = read(manifest)
                if prepared.get('preparation_status') != 'complete':
                    stage['status'] = 'time_budget_reached'; break
                stage['expected'] = len(prepared['buildings'])
                stage['input_excluded'] = len(prepared.get('excluded', []))
                stage['status'] = 'fitting'; write(state_path, state); dashboard(output, state)
                worker_args = ['worker', '--inputs', manifest, '--output', stage_dir,
                               '--cache', city_roots[city] / 'models', '--config', output / 'config.json']
                if city == 'ceske-budejovice':
                    worker_args += ['--reuse', ROOT / 'cities/ceske-budejovice/experiments/roof-regularized-wings-v491-8']
                if deadline: worker_args += ['--deadline', str(deadline)]
                while True:
                    # Clear stale active marker from a stopped worker before starting its successor.
                    stage_dir.mkdir(parents=True, exist_ok=True); write(stage_dir / 'active.json', {'idle': True})
                    result = supervise(python_command(Path(__file__).resolve(), worker_args),
                        output / 'logs' / (city + '-' + stage_name + '-models.log'), deadline,
                        stage_dir / 'active.json', args.house_timeout)
                    if result['status'] == 'building_timeout':
                        sp = stage_dir / 'stage.json'
                        ss = read(sp) if sp.exists() else {'schema': 'night-roof-stage/1', 'city': city,
                            'entries': [], 'roof_seconds': 0., 'active_seconds': 0., 'expected': stage['expected']}
                        active = result['active']
                        if not any(e['id'] == active['id'] for e in ss['entries']):
                            ss['entries'].append({'id': active['id'], 'address': active.get('address'),
                                'status': 'timeout', 'roof_seconds': 0., 'error': 'Exceeded per-building time budget'})
                        write(sp, ss); continue
                    stage['model_process'] = result
                    if (stage_dir / 'stage.json').exists():
                        ss = read(stage_dir / 'stage.json')
                        stage.update(completed=sum(e['status'] in ('complete', 'reused') for e in ss['entries']),
                                     roof_seconds=ss['roof_seconds'], model_active_seconds=ss['active_seconds'])
                    if result['status'] == 'failed':
                        raise RuntimeError('Model worker failed: ' + str(result))
                    stage['status'] = result['status'] if result['status'] != 'complete' else ss['status']
                    if stage['status'] == 'time_budget_reached' and (stage_dir / 'stage.json').exists():
                        # Publish completed checkpoints after the fitting deadline; no more inference.
                        ss['status'] = 'time_budget_reached'; write(stage_dir / 'stage.json', ss)
                        hd = {k: prepared.get(k) for k in ('city', 'source', 'crs', 'vertical_datum')}
                        for page in range(1, (len(ss['entries']) + 39) // 40 + 1):
                            page_report(stage_dir, ss['entries'], hd, page)
                        stage_index(stage_dir, ss)
                    elif stage['input_excluded']:
                        stage['status'] = 'complete_with_missing_inputs'
                    break
                write(state_path, state); dashboard(output, state)
            state['status'] = 'finished'
    except BaseException as error:
        state.update(status='stopped', error={'type': type(error).__name__, 'message': str(error)})
        if state.get('stages') and state['stages'][-1]['status'] in ('preparing_inputs', 'fitting'):
            state['stages'][-1]['status'] = 'stopped'
        raise
    finally:
        state['updated_at_utc'] = utc(); state['elapsed_seconds'] = time.time() - state['started_epoch']
        write(state_path, state); dashboard(output, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    runner = commands.add_parser('run')
    runner.add_argument('--output', type=Path, required=True)
    runner.add_argument('--config', type=Path)
    runner.add_argument('--house-timeout', type=float, default=180)
    work = commands.add_parser('worker')
    work.add_argument('--inputs', type=Path, required=True)
    work.add_argument('--output', type=Path, required=True)
    work.add_argument('--cache', type=Path, required=True)
    work.add_argument('--config', type=Path)
    work.add_argument('--reuse', type=Path, action='append', default=[])
    work.add_argument('--deadline', type=float)
    args = parser.parse_args()
    if args.action == 'run':
        with singleton(args.output):
            return run(args)
    return worker(args)


if __name__ == '__main__':
    sys.exit(main())
