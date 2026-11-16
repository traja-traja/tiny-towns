"""Rebuild the CB preview after a reviewed roof policy change, preserving baseline.

Runs only local prepare/render/packaging stages; never downloads source data.
The original site, scene and checkpoint are retained for before/after review.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import build_preview_guarded as build
import resource_guard as guard
import towns

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work/.preview/ceske-budejovice'
REPORT = ROOT / 'cities/ceske-budejovice/experiments/roof-heights/map-rebuild.json'
STEPS = build.STEPS[build.STEPS.index('prepare'):]


def fingerprint():
    return hashlib.sha256((ROOT/'scripts/build_preview_guarded.py').read_bytes() +
        (ROOT/'scripts/overture_stac_subset.py').read_bytes() +
        (WORK/towns.MANIFEST).read_bytes()).hexdigest()


def snapshot_baseline():
    dest = towns.local_path(WORK, 'revisions', 'baseline')
    marker = dest/'snapshot.json'
    if marker.exists():
        value = build.read_json(marker)
        if guard.sha256(dest/'scene.json') != value['scene_sha256']:
            raise ValueError('Baseline scene snapshot changed')
        return dest, value
    checkpoint = build.read_json(WORK/'build/preview-checkpoint.json')
    if not all(s in checkpoint['completed'] for s in build.STEPS):
        raise ValueError('Basic preview must be complete before roof revision')
    site = WORK/'site'
    files = [p for p in site.rglob('*') if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    guard.check_budget(reserve_bytes=size + 30_000_000, force=True)
    dest.mkdir(parents=True, exist_ok=True)
    # Copies are resumable. No source or destination directory is removed.
    for source in files:
        relative = source.relative_to(site)
        target = towns.local_path(dest, 'site', *relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        guard.check_budget()
        shutil.copy2(source, target)
    shutil.copy2(WORK/'build/scene.json', dest/'scene.json')
    shutil.copy2(WORK/'build/preview-checkpoint.json', dest/'preview-checkpoint.json')
    shutil.copy2(WORK/towns.MANIFEST, dest/'towns-inputs.json')
    old_code = {}
    for name in ('prep.py', 'render.html', 'geo.py', 'mesto.json'):
        source = WORK/name
        if source.is_file():
            target = dest/'source-code'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            old_code[name] = guard.sha256(target)
    qa = WORK/'qa'
    if qa.is_dir():
        for source in qa.iterdir():
            if source.is_file():
                target = dest/'qa'/source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    value = {'created_utc': datetime.now(timezone.utc).isoformat(), 'site_bytes': size,
             'site_files': len(files), 'scene_sha256': guard.sha256(dest/'scene.json'),
             'checkpoint_sha256': guard.sha256(dest/'preview-checkpoint.json'),
             'selected_original_code_sha256': old_code,
             'reason': 'Preserved unchanged basic preview before roof policy correction'}
    build.write_json(marker, value)
    return dest, value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--stop-after', choices=STEPS)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'steps': STEPS, 'baseline': str(WORK/'revisions/baseline'),
                          'no_downloads': True, 'status': 'plan_only'}, indent=2))
        return
    guard.check_budget(force=True)
    with towns.workspace_lock(WORK), guard.keep_awake():
        baseline, snapshot = snapshot_baseline()
        towns.stage(ROOT, towns.city_path(ROOT, 'ceske-budejovice'), WORK, 'preview')
        towns.prepare_dependencies(ROOT, WORK)
        current = fingerprint()
        checkpoint = WORK/'build/roof-fix-checkpoint.json'
        state = build.read_json(checkpoint) if checkpoint.exists() else {}
        if state.get('inputs') != current:
            state = {'inputs': current, 'completed': {}, 'baseline': str(baseline),
                     'baseline_snapshot': snapshot, 'no_downloads': True}
        env = towns.command_env(ROOT)
        env.update({k: '2' for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
            'NUMEXPR_NUM_THREADS', 'ARROW_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
            'IZO_DZI_VLAKNA', 'TINY_TOWNS_WORKERS')})
        env.update(NODE_OPTIONS='--max-old-space-size=2048', PYTHONUNBUFFERED='1')
        invalidated = False
        with build.in_workspace(WORK):
            # Validate unchanged upstream inputs in the correct city context.
            upstream = build.STEPS[:build.STEPS.index('prepare')]
            if not all(build.checked(s, WORK) for s in upstream):
                raise ValueError('Upstream source data is incomplete; roof-only rebuild refused')
            for index, step in enumerate(STEPS):
                guard.check_budget()
                if not invalidated and step in state['completed'] and build.checked(step, WORK):
                    print('Verified roof revision checkpoint:', step, flush=True)
                else:
                    invalidated = True
                    for later in STEPS[index:]: state['completed'].pop(later, None)
                    state['current_step'] = step
                    build.write_json(checkpoint, state)
                    print('Roof revision:', step, flush=True)
                    metrics = guard.run_guarded([sys.executable, '-X', 'utf8',
                        ROOT/'scripts/build_preview_guarded.py', '--internal-step', step],
                        WORK, WORK/'build/roof-fix-logs'/f'{step}.log',
                        min_available_gb=3 if step.startswith(('render-', 'trees-', 'dzi-')) else 1,
                        max_ram_gb=4, env=env)
                    if not build.checked(step, WORK): raise ValueError('Invalid output: '+step)
                    state['completed'][step] = {'finished_utc': datetime.now(timezone.utc).isoformat(),
                                                'metrics': metrics}
                    state.pop('current_step', None)
                    build.write_json(checkpoint, state)
                if step == args.stop_after: return
        overall = build.read_json(baseline/'preview-checkpoint.json')
        previous = overall['inputs']
        overall['inputs'] = current
        overall['completed'].update(state['completed'])
        overall.setdefault('checkpoint_migrations', []).append({
            'from': previous, 'to': current, 'reason': 'Roof policy revision; source inputs retained and revalidated',
            'baseline': str(baseline), 'time_utc': datetime.now(timezone.utc).isoformat()})
        build.write_json(WORK/'build/preview-checkpoint.json', overall)
        state.update(status='complete', resource_status=guard.check_budget(force=True),
                     current_scene_sha256=guard.sha256(WORK/'build/scene.json'))
        metadata = build.read_json(WORK/'site/preview-build.json')
        metadata.update(roof_policy_revision={
            'name': 'explicit_source_shape_before_height_and_use_heuristics',
            'policy_sha256': guard.sha256(WORK/'nastroje/roof_policy.py'),
            'scene_sha256': state['current_scene_sha256'],
            'baseline_relative_to_site': '../revisions/baseline/site',
            'experimental_roofer_arcades_facades_applied': False,
        })
        build.write_json(WORK/'site/preview-build.json', metadata)
        build.write_json(checkpoint, state)
        build.write_json(REPORT, state)
        print('Completed local roof revision; baseline retained:', baseline, flush=True)


if __name__ == '__main__':
    main()
