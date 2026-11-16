"""Freeze the latest known model/input per building before a combined batch.

Pass --run from oldest to newest; later runs replace matching building IDs.
Does not fit models or alter source runs. Copies only small cropped NPZ files.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from roof_batch import ROOT, read_json, write_json, current_parts
import resource_guard as guard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='append', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    runs = [p.resolve() for p in args.run]
    if output.exists() and any(output.iterdir()):
        parser.error('Choose a new/empty output directory')
    if any(output==p or output in p.parents for p in runs):
        parser.error('Output must not replace source runs')
    guard.check_budget(reserve_bytes=30*1024**2, force=True)
    inputs_by_id, models_by_id, records, lineage = {}, {}, {}, []
    header = None
    for directory in runs:
        manifest = read_json(directory/'inputs.json')
        results = read_json(directory/'results.json')
        keys = ('city','source','crs','vertical_datum')
        identity = {k:manifest[k] for k in keys}
        if header is not None and identity!={k:header[k] for k in keys}:
            raise ValueError('Cannot combine different cities or coordinate references')
        header = header or copy.deepcopy(manifest)
        models = {b['id']:b for b in results['buildings']}
        raw = read_json(directory/'source_records.json')
        for building in manifest['buildings']:
            oid = building['id']
            model = copy.deepcopy(models[oid])
            model['parts'] = copy.deepcopy(current_parts(results, model))
            if any(not p.get('result') for p in model['parts']):
                raise ValueError('Previous model is incomplete: '+oid)
            origin = str(directory)
            model['previous_source_run'] = origin
            for part in model['parts']:
                part['previous_source_run'] = directory.name
            entry = copy.deepcopy(building)
            base = directory if manifest.get('cache_path_base')=='manifest_directory' else ROOT
            for part in entry['parts']:
                part['cache']['path'] = str((base/part['cache']['path']).resolve())
            inputs_by_id[oid] = entry
            models_by_id[oid] = model
            records[oid] = raw.get(oid, {})
        lineage.append({'run':str(directory), 'buildings':len(manifest['buildings']),
            'inputs_sha256':guard.sha256(directory/'inputs.json'),
            'results_sha256':guard.sha256(directory/'results.json')})
    output.mkdir(parents=True, exist_ok=True)
    (output/'point-clouds').mkdir()
    for oid, building in inputs_by_id.items():
        for part in building['parts']:
            source = Path(part['cache']['path'])
            digest = guard.sha256(source)
            if digest != part['cache']['sha256']:
                raise ValueError('Changed input crop: '+str(source))
            relative = f"point-clouds/{oid}-{part['part_index']}.npz"
            shutil.copyfile(source, output/relative)
            part['source_cache'] = copy.deepcopy(part['cache'])
            part['cache'] = {'path':relative, 'sha256':digest, 'bytes':(output/relative).stat().st_size}
    created = datetime.now(timezone.utc).isoformat()
    header.update(buildings=list(inputs_by_id.values()), cache_path_base='manifest_directory',
        merged_runs=lineage, created_at_utc=created, source_records='source_records.json')
    signature = [(b['id'],[(p['part_index'],p['cache']['sha256']) for p in b['parts']])
                 for b in header['buildings']]
    header['sample_sha256'] = hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    header['sample_sha256_scope'] = 'Merged ordered building IDs, part indices and point-cache checksums'
    header.pop('timing', None)
    header['output_cache_bytes'] = sum(p['cache']['bytes'] for b in header['buildings'] for p in b['parts'])
    previous = {k:header[k] for k in ('city','source','crs','vertical_datum')}
    previous.update(schema='roof-v2/1', algorithm='latest_previous_per_building', status='complete',
        created_at_utc=created, merged_runs=lineage, buildings=list(models_by_id.values()))
    write_json(output/'inputs.json',header)
    write_json(output/'results.json',previous)
    write_json(output/'source_records.json',records)
    write_json(output/'merge.json',{'order':'oldest to newest; last matching ID wins',
        'runs':lineage,'buildings':len(inputs_by_id)})
    last_config = runs[-1]/'config.json'
    if last_config.exists():
        shutil.copyfile(last_config,output/'config.json')
    guard.check_budget(force=True)
    print(json.dumps({'output':str(output),'unique_buildings':len(inputs_by_id),
                      'source_counts':[r['buildings'] for r in lineage]}),flush=True)


if __name__=='__main__':
    main()
