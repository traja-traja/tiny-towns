"""Small CPU-only benchmark of evaluating already fitted roof templates.
No roof fitting, point-cloud download, Roofer, or production changes.
Run: .venv/Scripts/python.exe -X utf8 scripts/roof_residual_microbench.py
"""
import os
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
            'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'

import argparse
import hashlib
import json
import math
import platform
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from roof_pilot_methods import predict_roof_z

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'cities/ceske-budejovice/roof-pilot/results.json'
INPUTS = ROOT / '.work/cb-roof-simplification/input'
CASES = [
    '98192926-2e4d-4667-b3e9-9998dd4ea22a',
    '2ea0e62e-9a14-4d65-bfef-7036d91bffa0',
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bench(fn):
    # Warm the implementation and caches. Each timing batch is at least ~20ms.
    for _ in range(3):
        fn()
    t0 = time.perf_counter_ns()
    for _ in range(5):
        fn()
    trial_s = max((time.perf_counter_ns() - t0) / 5e9, 1e-7)
    n = max(1, min(1000, math.ceil(0.020 / trial_s)))
    timings = []
    for _ in range(7):
        t0 = time.perf_counter_ns()
        for _ in range(n):
            fn()
        timings.append((time.perf_counter_ns() - t0) / n / 1e6)
    return {'unit': 'milliseconds_per_call', 'calls_per_batch': n,
            'batches': len(timings), 'min_ms': min(timings),
            'median_ms': statistics.median(timings), 'max_ms': max(timings),
            'batch_average_ms_per_call': timings}


def cpu_name():
    if sys.platform == 'win32':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            return winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
    return platform.processor()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'cities/ceske-budejovice/experiments/roof-archetypes/residual-cost.json')
    args = parser.parse_args()
    if shutil.disk_usage(ROOT).free < 25e9:
        raise RuntimeError('C: free space below user limit of 25 GB')
    if args.output.exists():
        raise FileExistsError(f'Refusing to replace an existing result: {args.output}')
    payload = json.loads(RESULTS.read_text(encoding='utf-8'))
    runs = {r['id']: r for r in payload['runs']
            if r['source'] == 'dmpok' and r['method'] == 'templates'}
    report = {'schema': 'roof-residual-microbench/1',
              'created_at': datetime.now(timezone.utc).isoformat(),
              'cpu': cpu_name(), 'os': platform.platform(),
              'python': platform.python_version(), 'numpy': np.__version__,
              'thread_environment': {k: os.environ[k] for k in (
                  'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')},
              'source_results': {'path': str(RESULTS.relative_to(ROOT)), 'sha256': sha256(RESULTS)},
              'implementation': {'path': 'scripts/roof_pilot_methods.py',
                                 'sha256': sha256(ROOT / 'scripts/roof_pilot_methods.py')},
              'metric': 'Vertical residual dz = predicted_z(x,y) - observed_z; not nearest-triangle Euclidean distance.',
              'timing_scope': 'In-memory warmed CPU evaluation of existing fitted templates; fitting, I/O, imports, classification, masks, spatial indexes, meshes and rendering excluded.',
              'gpu_measured': False, 'new_roof_fit_performed': False,
              'cases': []}
    started = time.perf_counter()
    for bid in CASES:
        run = runs[bid]
        path = INPUTS / (bid + '.npz')
        with np.load(path) as archive:
            xyz = archive['train_relative'].copy()
        # XY is centred on the same footprint; model heights use absolute Bpv.
        xyz[:, 2] += float(run['ground_z'])
        assert len(xyz) == run['metrics']['train_points']
        model = run['model']
        xy, z = xyz[:, :2], xyz[:, 2]
        residual = predict_roof_z(model, xy) - z
        rmse = float(np.sqrt(np.mean(residual * residual)))
        expected = float(model['metrics']['rmse_m'])
        if not np.isclose(rmse, expected, rtol=1e-9, atol=1e-9):
            raise ValueError(f'Coordinate/input check failed: {rmse} versus {expected}')

        def prediction_rmse():
            err = predict_roof_z(model, xy) - z
            return float(np.sqrt(np.mean(err * err)))

        def percentile_only():
            return float(np.percentile(np.abs(residual), 95))

        def prediction_rmse_p95():
            err = predict_roof_z(model, xy) - z
            return float(np.sqrt(np.mean(err * err))), float(np.percentile(np.abs(err), 95))

        report['cases'].append({
            'id': bid, 'name': run['name'], 'shape': model['shape'],
            'points': len(xyz), 'input_array_bytes': xyz.nbytes,
            'input': {'path': str(path.relative_to(ROOT)), 'sha256': sha256(path)},
            'coordinate_check': {'computed_training_rmse_m': rmse,
                                 'stored_training_rmse_m': expected,
                                 'passed': True},
            'prediction_and_rmse': bench(prediction_rmse),
            'p95_of_precomputed_residuals': bench(percentile_only),
            'prediction_rmse_and_p95': bench(prediction_rmse_p95)})
    report['measurement_section_wall_seconds'] = time.perf_counter() - started
    try:
        from threadpoolctl import threadpool_info
        report['loaded_threadpools'] = threadpool_info()
    except ImportError:
        report['loaded_threadpools'] = 'threadpoolctl unavailable; environment limits set before numerical imports'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({'output': str(args.output), 'cpu': report['cpu'],
                      'wall_s': report['measurement_section_wall_seconds'],
                      'cases': [{k: r[k] for k in ('name', 'points', 'prediction_and_rmse',
                               'p95_of_precomputed_residuals', 'prediction_rmse_and_p95')}
                                for r in report['cases']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
