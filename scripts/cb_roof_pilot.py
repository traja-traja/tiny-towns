"""Isolated ČB roof benchmark using the measured Velešín algorithms unchanged.

Three repetitions for baseline/templates; one real Roofer batch per source,
matching the first pilot. No city renderer input is altered by this runner.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

import resource_guard as guard
import roof_pilot as shared
from cb_roof_sources import require_basic_preview

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work/cb-roof-pilot'
DEST = ROOT / 'cities/ceske-budejovice/roof-pilot'
SAMPLE = DEST / 'sample.json'
MANIFEST = WORK / 'sources/sources.json'
SOURCES = ('dmp1g', 'dmpok')
METHODS = ('baseline', 'templates', 'roofer')
IMPLEMENTATIONS = ('cb_roof_pilot.py', 'cb_roof_sources.py', 'roof_pilot.py',
                   'roof_pilot_methods.py', 'roof_pilot_roofer.py',
                   'roof_pilot_sources.py', 'roof_pilot_report.py', 'resource_guard.py')


def configure():
    shared.WORK, shared.DEST, shared.SAMPLE, shared.MANIFEST = WORK, DEST, SAMPLE, MANIFEST
    return shared


def snapshot():
    files = [ROOT / 'scripts' / name for name in IMPLEMENTATIONS]
    hashes = {p.name: guard.sha256(p) for p in files}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    target = WORK / 'implementation' / digest[:16]
    target.mkdir(parents=True, exist_ok=True)
    for path in files:
        destination = target / path.name
        if not destination.exists():
            shutil.copyfile(path, destination)
        if guard.sha256(destination) != hashes[path.name]:
            raise ValueError('Changed immutable implementation snapshot: ' + str(destination))
    shared.write(target / 'manifest.json', {'sha256': hashes, 'fingerprint': digest,
                  'note': 'Provenance snapshot. Original project paths remain required when executing.'})
    return {'path': target.relative_to(ROOT).as_posix(), 'fingerprint': digest, 'sha256': hashes}


def verify_inputs():
    manifest = shared.read(MANIFEST)
    if manifest['sample_file']['sha256'] != guard.sha256(SAMPLE):
        raise ValueError('Source crops were prepared for a different footprint sample')
    for source in SOURCES:
        info = manifest['sources'][source]
        path = ROOT / info['crop_path']
        if path.stat().st_size != info['crop_file']['bytes'] or guard.sha256(path) != info['crop_file']['sha256']:
            raise ValueError('Changed source crop: ' + source)


def compile_results(provenance):
    configure()
    features = [f for f, _ in shared.samples()]
    samples = [dict(f['properties'], id=f['id']) for f in features]
    groups = len({p.get('group_id', p['pilot_id']) for p in samples})
    result = {'schema': 'roof-pilot/1', 'city': 'ceske-budejovice',
              'created_at': datetime.now(timezone.utc).isoformat(), 'samples': samples,
              'runs': [], 'source_metrics': shared.read(MANIFEST), 'process_metrics': {},
              'notes': [
        f'{len(samples)} půdorysů představuje {groups} skupin v centru Českých Budějovic; složené stavby mohou mít více půdorysů.',
        'Baseline je aproximace stávající heuristiky, nikoli přesný běh městského rendereru; nezahrnuje všechny jeho výjimky ani ručně upravené modely.',
        'Šablony hledají flat/shed/gabled/hipped/barrel; nejvýše 3500 bodů pro optimalizaci a 4 výchozí orientace. Zdrojový typ střechy se při výběru nepoužívá.',
        'Globálních 20 % bodů třídy 6 je odděleno před rekonstrukcí (seed 20261115); nejsou v trénovací LAZ ani šablonách. Sousední fotogrammetrické body jsou korelované.',
        'RMSE je shoda výšek se zadrženými body téhož zdroje, nikoli nezávisle zaměřená přesnost ani správnost typu střechy, fasády nebo průchodů.',
        'DMP1G a DMPOK mají odlišný původ a období. Větší hustota neznamená automaticky vyšší přesnost; datum vytvoření souboru není datum snímkování.',
        'DMP1G se znovu nestahuje: používá cache základního městského preview. Jeho dřívější stažení není započítáno do tohoto pilotu. DMPOK má nově měřené stažení dvou listů.',
        'Ground je medián bodů třídy 2 v prstenci do 20 m od půdorysu. Šikmý terén se v tomto objemovém pilotu samostatně nemodeluje.',
        'Baseline a šablony: medián 3 opakování včetně tvorby mesh. Roofer: jeden skutečný batch na zdroj; vnitřní časy budov a čas celého procesu jsou odděleny.',
        'Roofer batch je potomkem pracovního procesu. Jeho čas a paměť se k metrikám celého procesového stromu znovu nepřičítají.',
        'peak_job_commit_bytes je špička commitované paměti celého procesového stromu; nejde o rezidentní fyzickou RAM.',
        'Podloubí, průchody a barvy fasád vyžadují samostatné zdroje a experimenty. Tento pilot je neodvozuje z výškového mračna.',
        'Výběr obsahuje záměrně obtížné a atypické budovy. Souhrn nelze bez dalšího považovat za reprezentativní rychlost nebo úspěšnost pro celé město.'
    ]}
    for source in SOURCES:
        for method in METHODS:
            key = f'{source}-{method}'
            value = shared.read(WORK / f'{key}.json')
            for run in value['runs']:
                model = run.get('model') or {}
                run['complexity'] = {'vertices': len(model.get('vertices', [])),
                    'triangles': len(model.get('faces', [])),
                    'roof_triangles': model.get('face_semantics', []).count('roof'),
                    'model_json_bytes': len(json.dumps(model, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))}
                if model.get('warnings'):
                    run['quality_warnings'] = model['warnings']
            result['runs'].extend(value['runs'])
            if 'batch_metrics' in value:
                result['process_metrics'][key + '-batch'] = value['batch_metrics']
            metrics = WORK / 'logs' / f'{key}.log.metrics.json'
            if metrics.exists():
                result['process_metrics'][key] = shared.read(metrics)
    result['summary'] = shared.summarise(result)
    result['source_metrics']['process_metrics'] = {
        s: shared.read(WORK / 'sources' / f'prepare-{s}.log.metrics.json')
        for s in SOURCES if (WORK / 'sources' / f'prepare-{s}.log.metrics.json').exists()}
    tool_source = ROOT / '.work/roof-pilot/tools/source.json'
    result['software'] = {'python': sys.version, 'implementation_snapshot': provenance,
        'packages': {p: importlib.metadata.version(p) for p in ('numpy', 'scipy', 'shapely', 'laspy', 'pyproj')},
        'roofer_provenance': shared.read(tool_source),
        'roofer_executable_sha256': guard.sha256(ROOT / '.work/roof-pilot/tools/roofer/bin/roofer.exe')}
    result['resource_status'] = guard.check_budget(force=True)
    shared.write(DEST / 'results.json', result)
    import roof_pilot_report
    # Change only the report's fixed city label, leaving the shared renderer
    # and previously generated Velešín report byte-for-byte untouched.
    html = roof_pilot_report.build_report(result).replace('Velešín', 'České Budějovice')
    (DEST / 'report.html').write_text(html, encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--worker', choices=METHODS)
    parser.add_argument('--source', choices=SOURCES)
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    configure()
    if args.worker:
        require_basic_preview()
        if args.worker == 'roofer':
            shared.roofer_worker(args.source)
        else:
            shared.template_worker(args.source, args.worker)
        return
    if not args.execute and not args.report_only:
        print('Prepare cb_roof_sources.py, then --execute. No city renderer inputs will change.')
        return
    require_basic_preview()
    guard.check_budget(reserve_bytes=5_000_000, force=True)
    verify_inputs()
    checkpoint = WORK / 'benchmark-checkpoint.json'
    state = shared.read(checkpoint) if checkpoint.exists() else {}
    with guard.keep_awake():
        if not args.report_only:
            provenance = snapshot()
            files = [SAMPLE, MANIFEST] + [ROOT / 'scripts' / name for name in IMPLEMENTATIONS]
            fingerprint = hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()
            if state.get('fingerprint') != fingerprint:
                state = {'fingerprint': fingerprint, 'completed': [], 'implementation_snapshot': provenance}
            expected_ids = {f['id'] for f in shared.read(SAMPLE)['features']}
            if len(expected_ids) != 30:
                raise ValueError('Expected exactly 30 distinct pilot footprints')
            for source in SOURCES:
                for method in METHODS:
                    key = f'{source}-{method}'
                    output = WORK / f'{key}.json'
                    if key in state['completed'] and output.exists():
                        ids = {r['id'] for r in shared.read(output).get('runs', [])}
                        if ids == expected_ids:
                            print('Verified checkpoint', key, flush=True)
                            continue
                    print('Starting', key, flush=True)
                    guard.run_guarded([sys.executable, '-X', 'utf8', __file__, '--worker', method, '--source', source],
                        ROOT, WORK / 'logs' / f'{key}.log', min_available_gb=1, max_ram_gb=2)
                    ids = {r['id'] for r in shared.read(output).get('runs', [])}
                    if ids != expected_ids:
                        raise ValueError('Incomplete benchmark output: ' + key)
                    state['completed'].append(key)
                    shared.write(checkpoint, state)
        else:
            provenance = state['implementation_snapshot']
            if len(state.get('completed', [])) != len(SOURCES) * len(METHODS):
                raise ValueError('Cannot report an incomplete benchmark')
        result = compile_results(provenance)
        print(json.dumps(result['summary'], indent=2), flush=True)


if __name__ == '__main__':
    main()
