"""Frozen seven-footprint inputs and shared evaluation for simplification round 2.

No production map is changed. XYZ in the per-building NPZ is local XY and Z
above the SAME ground reference used by the first pilot. Held-out points must
not be used to fit, split or tune a model.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import shapely
from shapely.geometry import shape, mapping, Polygon

import resource_guard as guard
from roof_pilot_roofer import predict_roofer_z, _safe

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'cities/ceske-budejovice/experiments/roof-simplification'
WORK = ROOT / '.work/cb-roof-simplification'
MANIFEST = DEST / 'manifest.json'
PILOT_IDS = ('CB-ROOF-01', 'CB-ROOF-02', 'CB-ROOF-04', 'CB-ROOF-09',
             'CB-ROOF-10', 'CB-ROOF-12', 'CB-ROOF-16')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_safe(value), ensure_ascii=False, indent=2,
                               allow_nan=False) + '\n', encoding='utf-8')


def snapshot(paths, label):
    """Immutable source copy made before the measured worker starts."""
    paths = [Path(p).resolve() for p in paths]
    hashes = {p.relative_to(ROOT).as_posix(): guard.sha256(p) for p in paths}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    target = WORK / 'implementation' / (label + '-' + digest[:16])
    for p in paths:
        dest = target / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copyfile(p, dest)
        if guard.sha256(dest) != hashes[p.relative_to(ROOT).as_posix()]:
            raise ValueError('Immutable source snapshot mismatch')
    result = {'path': target.relative_to(ROOT).as_posix(), 'sha256': hashes,
              'fingerprint': digest, 'captured_at': datetime.now(timezone.utc).isoformat()}
    write(target / 'manifest.json', result)
    return result


def prepare():
    if MANIFEST.exists():
        load_cases()
        print('Frozen input already exists and verifies.', flush=True)
        return
    import cb_roof_pilot
    shared = cb_roof_pilot.configure()
    cb_roof_pilot.verify_inputs()
    guard.check_budget(reserve_bytes=50_000_000, force=True)
    sample = read(shared.SAMPLE)
    selected = {f['id']: f for f in sample['features']
                if f['properties']['pilot_id'] in PILOT_IDS}
    if len(selected) != 7:
        raise ValueError('Expected exactly seven original footprints')
    details = read(ROOT / 'cities/ceske-budejovice/experiments/roofs/results.json')
    reference = read(details['inputs']['baseline_adapter_path'])
    features = read(reference['files']['footprints'])['features']
    features = {f['properties']['id']: f for f in features}
    train_path = Path(details['inputs']['train_path'])
    split_path = Path(details['inputs']['split_path'])
    if guard.sha256(train_path) != read(split_path)['input_cloud_sha256']:
        raise ValueError('Training LAZ changed')
    xyz, cls, held = shared.load_source('dmpok')
    cases = []
    for source_feature, poly in shared.samples():
        identifier = source_feature['id']
        if identifier not in selected:
            continue
        data = shared.building_data(poly, xyz, cls, held)
        feature = deepcopy(features[identifier])
        props = feature['properties']
        if not np.allclose([*data['centre'], data['ground_z']],
                           [props['centre_x'], props['centre_y'], props['ground_z']],
                           atol=1e-7, rtol=0):
            raise ValueError('Ground or centroid mismatch: ' + identifier)
        train = data['train'].copy(); test = data['test'].copy()
        train[:, 2] -= data['ground_z']; test[:, 2] -= data['ground_z']
        npz = WORK / 'input' / (identifier + '.npz')
        npz.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(npz, train_relative=train, test_relative=test)
        p = source_feature['properties']
        cases.append({'id': identifier, 'pilot_id': p['pilot_id'], 'name': p['name'],
                      'group_id': p['group_id'], 'category': p['category'],
                      'centre': data['centre'].tolist(), 'ground_z': data['ground_z'],
                      'feature': feature, 'polygon_local': mapping(data['poly']),
                      'points_path': npz.relative_to(ROOT).as_posix(),
                      'points_sha256': guard.sha256(npz),
                      'train_points': len(train), 'holdout_points': len(test),
                      'original_sample_properties': p})
        print(p['name'], len(train), len(test), flush=True)
    cases.sort(key=lambda x: PILOT_IDS.index(x['pilot_id']))
    footprint_path = WORK / 'input/footprints.geojson'
    write(footprint_path, {'type': 'FeatureCollection',
        'crs': {'type': 'name', 'properties': {'name': 'EPSG:5514'}},
        'features': [c['feature'] for c in cases]})
    inputs = [shared.SAMPLE, train_path, split_path,
              ROOT / 'cities/ceske-budejovice/experiments/roofs/results.json',
              ROOT / 'cities/ceske-budejovice/roof-pilot/results.json', footprint_path]
    value = {'schema': 'roof-simplification-inputs/1', 'created_at': datetime.now(timezone.utc).isoformat(),
             'city': 'ceske-budejovice', 'source': 'dmpok', 'requested_objects': 6,
             'footprints': 7, 'train_laz': str(train_path), 'footprints_path': str(footprint_path),
             'split_seed': 20261115, 'coordinate_system': 'local XY in EPSG:5514 axes; Z above shared ground',
             'input_sha256': {p.relative_to(ROOT).as_posix(): guard.sha256(p) for p in inputs},
             'buildings': cases,
             'protocol': {'no_holdout_used_for_fitting_or_partition': True,
                 'tolerance_m': 0.5,
                 'tolerance_note': 'User preference, not a guarantee. Report point error, baseline geometry change and silhouette separately.',
                 'same_source_holdout_not_independent_survey': True,
                 'production_map_modified': False}}
    write(MANIFEST, value)
    print('Saved frozen inputs:', MANIFEST, flush=True)


def load_cases():
    manifest = read(MANIFEST)
    cases = {}
    for record in manifest['buildings']:
        path = ROOT / record['points_path']
        if guard.sha256(path) != record['points_sha256']:
            raise ValueError('Frozen per-building points changed')
        with np.load(path) as points:
            case = dict(record, polygon=shape(record['polygon_local']),
                        train_relative=points['train_relative'],
                        test_relative=points['test_relative'])
        cases[record['id']] = case
    return cases


def baseline_rows():
    selected = {c['id'] for c in read(MANIFEST)['buildings']}
    rows = []
    for r in read(ROOT / 'cities/ceske-budejovice/experiments/roofs/results.json')['runs']:
        if r['id'] in selected and r['variant'] in ('roofer_lod22_reference', 'roofer_lod22_regularized'):
            rows.append(deepcopy(r))
    # Names of old profiles are read from configuration, not silently assumed.
    if len(rows) != 14:
        rows = [deepcopy(r) for r in read(ROOT / 'cities/ceske-budejovice/experiments/roofs/results.json')['runs']
                if r['id'] in selected and r.get('configuration', {}).get('lod') == '2.2'
                and r.get('configuration', {}).get('complexity_factor') in (0.888, 0.6)]
    if len(rows) != 14:
        raise ValueError('Expected two previous native profiles per footprint')
    for r in rows:
        r['reused_previous_run'] = True
    for r in read(ROOT / 'cities/ceske-budejovice/roof-pilot/results.json')['runs']:
        if r['id'] in selected and r['source'] == 'dmpok' and r['method'] == 'templates':
            rows.append({'id': r['id'], 'name': r['name'], 'variant': 'template_original',
                         'model': deepcopy(r['model']), 'metrics': {},
                         'timing': {'median_seconds': r['elapsed_seconds'],
                                    'scope': r['timing_scope']}, 'reused_previous_run': True})
    return rows


def evaluate_model(model, case):
    """Evaluate the actual displayed triangle mesh, never an analytic substitute."""
    test = case['test_relative']
    predicted = predict_roofer_z(model, test[:, :2])
    valid = np.isfinite(predicted)
    err = predicted[valid] - test[valid, 2]
    tri = []
    vertices = np.asarray(model.get('vertices', []), dtype=float)
    for face, sem in zip(model.get('faces', []), model.get('face_semantics', [])):
        if sem == 'roof' and len(face) == 3:
            p = Polygon(vertices[face, :2])
            if p.is_valid and p.area > 1e-9:
                tri.append(p)
    coverage = shapely.union_all(tri) if tri else Polygon()
    poly = case['polygon']
    return {'holdout_points': len(test), 'predicted_points': int(valid.sum()),
            'coverage_fraction': float(valid.mean()) if len(test) else None,
            'holdout_rmse_m': float(np.sqrt(np.mean(err**2))) if len(err) else None,
            'holdout_mae_m': float(np.mean(np.abs(err))) if len(err) else None,
            'holdout_p95_abs_m': float(np.percentile(np.abs(err), 95)) if len(err) else None,
            'holdout_bias_m': float(np.mean(err)) if len(err) else None,
            'within_0_5m_fraction': float(np.mean(np.abs(err) <= .5)) if len(err) else None,
            'within_0_5m_all_holdout_fraction': float(np.sum(np.abs(err) <= .5)/len(test)) if len(test) else None,
            'roof_footprint_coverage_fraction': coverage.intersection(poly).area/poly.area,
            'roof_area_outside_footprint_m2': coverage.difference(poly).area,
            'roof_triangle_count': len(tri), 'render_triangle_count': len(model.get('faces', [])),
            'vertex_count': len(vertices), 'evaluation_set': 'original frozen20% DMPOK holdout; displayed mesh',
            'error_scope': 'predicted points; missing points counted separately',
            'not_independent_survey_accuracy': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare'])
    parser.parse_args()
    prepare()
