"""Prepare and run the isolated DMPOK roof-v2 experiment; never download data.

The sample is frozen before point extraction or fitting. Holdout points are from
the same photogrammetric survey and are not independent architectural truth.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS', 'ARROW_NUM_THREADS'):
    os.environ[_key] = '1'

import laspy
import numpy as np
import pyarrow.parquet as pq
from pyproj import Transformer
import shapely
from shapely.geometry import mapping, shape
from shapely.affinity import translate

import resource_guard as guard

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / '.work/.preview/ceske-budejovice'
OUT = ROOT / 'cities/ceske-budejovice/experiments/roof-v2'
CACHE = ROOT / '.work/cb-roof-v2'
SOURCE_MANIFEST = ROOT / '.work/cb-roof-pilot/sources/sources.json'
PILOT_SAMPLE = ROOT / 'cities/ceske-budejovice/roof-pilot/sample.json'
USER_SAMPLE = ROOT / 'cities/ceske-budejovice/roof-inference-sample.json'
WORTNER = '98192926-2e4d-4667-b3e9-9998dd4ea22a'
SEED = 'cb-roof-v2-20261116'
BUFFER = 20.0
CHUNK = 100_000
STREAM_RECOVERY = None


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    guard.check_budget(reserve_bytes=len(payload))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_bytes(payload)
    temp.replace(path)


def resource_check():
    status = guard.check_budget()
    status['memory'] = guard.memory_status()
    if status['memory']['available'] < 350_000_000:
        raise guard.ResourceLimit('STOP: available system RAM below 350 MB')
    return status


def file_record(path, digest=False):
    path = Path(path)
    result = {'path': rel(path), 'bytes': path.stat().st_size,
              'mtime_ns': path.stat().st_mtime_ns}
    if digest:
        result['sha256'] = guard.sha256(path)
    return result


def polygon_parts(geometry):
    if geometry.geom_type == 'Polygon' and not geometry.is_empty and geometry.area > 0:
        yield geometry
    elif geometry.geom_type in ('MultiPolygon', 'GeometryCollection'):
        for part in geometry.geoms:
            yield from polygon_parts(part)


def address_key(row):
    return tuple(str(row.get(key) or '') for key in ('street', 'number', 'unit'))


def address_label(row):
    street, number, unit = address_key(row)
    return f'{street} {number}' + (f'/{unit}' if unit else '')


def source_inventory():
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding='utf-8'))
    source = manifest['sources']['dmpok']
    for tile in source['tiles']:
        path = ROOT / tile['file']['path']
        if not path.is_file() or path.stat().st_size != tile['file']['bytes']:
            raise ValueError(f'Existing DMPOK tile missing or changed: {path}')
    return manifest, source


def make_sample(path=OUT / 'sample.json'):
    """Freeze stratified random buildings independently of fitted roof results."""
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    start, cpu = time.perf_counter(), time.process_time()
    resource_check()
    _, source = source_inventory()
    coverage = shapely.union_all([shapely.box(t['header']['bounds'][0][0], t['header']['bounds'][0][1],
                    t['header']['bounds'][1][0], t['header']['bounds'][1][1]).buffer(.15)
                    for t in source['tiles']])
    rows = pq.read_table(PREVIEW / 'data/building.parquet').to_pylist()
    rows = [r for r in rows if r.get('geometry') and not r.get('is_underground')]
    wgs = shapely.make_valid(shapely.from_wkb([r['geometry'] for r in rows]))
    transform = Transformer.from_crs(4326, 5514, always_xy=True).transform
    projected = shapely.transform(wgs, transform, interleaved=False)
    tree = shapely.STRtree(wgs)
    metric_tree = shapely.STRtree(projected)
    info = json.loads((PREVIEW / 'build/info_src.json').read_text(encoding='utf-8'))
    scene_rows = info.get('buildings', []) if isinstance(info, dict) else info
    preview_ids = {str(r['oid']) for r in scene_rows if r.get('oid')}
    if not preview_ids:
        raise ValueError('Actual preview has no building OIDs; refusing to select outside the preview')
    addresses = pq.read_table(PREVIEW / 'data/address.parquet', columns=[
        'id', 'street', 'number', 'unit', 'geometry', 'sources']).to_pylist()
    addresses = [a for a in addresses if a['geometry']]
    address_geoms = shapely.from_wkb([a['geometry'] for a in addresses])
    address_tree = shapely.STRtree(address_geoms)
    address_lookup = {}
    for index, row in enumerate(addresses):
        ruian = next((s['record_id'] for s in row.get('sources') or [] if s['provider'] == 'cuzk'), None)
        if ruian:
            address_lookup.setdefault(address_key(row), {})[str(ruian)] = index
    requested = json.loads(USER_SAMPLE.read_text(encoding='utf-8')) if USER_SAMPLE.exists() else []
    selected, unresolved = {}, []
    for item in requested[:5]:
        matches = address_lookup.get(address_key(item), {})
        candidates = tree.query(address_geoms[next(iter(matches.values()))], predicate='covered_by') if len(matches) == 1 else []
        if len(candidates) != 1:
            unresolved.append({'address': address_label(item), 'requested': item,
                'status': 'ambiguous_or_missing_address' if len(matches) != 1 else 'ambiguous_or_missing_footprint'})
            continue
        index = int(candidates[0])
        selected[index] = {'role': 'user_address', 'category': 'user_address',
                           'requested_address': address_label(item)}
    wortner = next((i for i, r in enumerate(rows) if r['id'] == WORTNER), None)
    if wortner is not None:
        selected[wortner] = {'role': 'control', 'category': 'wortner_control'}
    previous = {f['id'] for f in json.loads(PILOT_SAMPLE.read_text(encoding='utf-8'))['features']}
    pools = {'corner_candidate': [], 'row_candidate': [], 'detached_candidate': [], 'source_flat': []}
    excluded_classes = {'church', 'cathedral', 'stadium', 'sports_centre', 'school', 'hospital', 'civic', 'industrial'}
    for i, (row, poly) in enumerate(zip(rows, projected)):
        if i in selected or row['id'] in previous or row['id'] not in preview_ids:
            continue
        if poly.geom_type != 'Polygon' or not poly.is_valid or not 70 <= poly.area <= 1100:
            continue
        if row.get('class') in excluded_classes or not coverage.covers(poly.buffer(BUFFER)):
            continue
        if not len(address_tree.query(wgs[i], predicate='covers')):
            continue
        near = [int(j) for j in metric_tree.query(poly.buffer(1.5), predicate='intersects')
                if j != i and projected[j].area > 35 and poly.intersection(projected[j]).area < .1 * poly.area]
        center = np.array([poly.centroid.x, poly.centroid.y])
        angles = []
        for j in near:
            delta = np.array([projected[j].centroid.x, projected[j].centroid.y]) - center
            angles.append(float(np.arctan2(delta[1], delta[0])))
        gaps = [abs((a-b+np.pi) % (2*np.pi)-np.pi)*180/np.pi
                for k, a in enumerate(angles) for b in angles[k+1:]]
        if row.get('roof_shape') == 'flat':
            group = 'source_flat'
        elif len(near) >= 2 and any(g >= 135 for g in gaps):
            group = 'row_candidate'
        elif len(near) >= 2 and any(55 <= g <= 125 for g in gaps):
            group = 'corner_candidate'
        elif len(near) == 0:
            group = 'detached_candidate'
        else:
            continue
        pools[group].append((i, {'role': 'random_stratified', 'category': group,
            'neighbor_count_within_1_5m': len(near), 'neighbor_centroid_angles_deg': np.round(gaps, 2).tolist()}))
    for group, candidates in pools.items():
        candidates.sort(key=lambda entry: hashlib.sha256((SEED + group + rows[entry[0]]['id']).encode()).hexdigest())
        if len(candidates) < 6:
            raise ValueError(f'Only {len(candidates)} eligible buildings in {group}; inspect selection before changing it')
        selected.update(candidates[:6])
    features = []
    for i, selection in selected.items():
        row, poly = rows[i], projected[i]
        labels = sorted({address_label(addresses[int(j)]) for j in address_tree.query(wgs[i], predicate='covers')})
        name = (row.get('names') or {}).get('primary') or (labels[0] if labels else row['id'])
        if row['id'] == WORTNER:
            name = 'Wortnerův dům — kontrola'
        properties = {**selection, 'name': name, 'address': labels[0] if labels else None,
            'other_addresses': labels[1:], 'lon': wgs[i].centroid.x, 'lat': wgs[i].centroid.y,
            'footprint_area_m2': poly.area, 'source_attributes': {key: row.get(key) for key in
                ('class', 'subtype', 'height', 'num_floors', 'roof_shape', 'roof_height', 'roof_color',
                 'facade_color', 'roof_material', 'has_parts')}, 'footprint_sources': row.get('sources'),
            'coverage_complete': coverage.covers(poly.buffer(BUFFER))}
        features.append({'type': 'Feature', 'id': row['id'], 'geometry': mapping(poly), 'properties': properties})
    result = {'type': 'FeatureCollection', 'schema': 'roof-v2-sample/1', 'city': 'ceske-budejovice',
        'crs': 'EPSG:5514', 'created_at_utc': utc(), 'seed': SEED, 'features': features,
        'strata_pool_counts': {k: len(v) for k,v in pools.items()}, 'unresolved_user_addresses': unresolved,
        'queued_user_addresses': requested[5:],
        'selection': 'Six SHA256-seeded random buildings in each of four disjoint heuristic groups; 24 new buildings, first five user addresses and Wortner control (maximum 30).',
        'limitations': ['Corner/row labels are footprint-neighbor heuristics, not visually verified street position.',
            'source_flat means an existing source tag, not measured roof truth.',
            'All selected buildings must fall inside actual existing preview and cached DMPOK extent.',
            'Source colors are preserved as input metadata; no new appearance is inferred.'],
        'source_files': [file_record(PREVIEW / 'data/building.parquet', True),
                         file_record(PREVIEW / 'data/address.parquet', True)],
        'timing': {'wall_seconds': time.perf_counter()-start, 'cpu_seconds': time.process_time()-cpu}}
    atomic_json(path, result)
    return result


def split_points(xyz):
    """Stable 80/20 XY-hash split: repeated XY observations never cross the split."""
    if not len(xyz):
        return np.zeros(0, dtype=bool)
    xy = np.rint(np.asarray(xyz[:, :2]) * 100).astype(np.int64).view(np.uint64)
    with np.errstate(over='ignore'):
        hashed = (xy[:, 0] * np.uint64(0x9E3779B185EBCA87)) ^ (xy[:, 1] * np.uint64(0xC2B2AE3D27D4EB4F))
        hashed ^= hashed >> np.uint64(33)
        hashed *= np.uint64(0xff51afd7ed558ccd)
        hashed ^= hashed >> np.uint64(33)
    return hashed % np.uint64(5) == 0


def unique_points(xyz, classes):
    if not len(xyz):
        return xyz, classes, 0
    key = np.column_stack((xyz, classes))
    _, indices = np.unique(key, axis=0, return_index=True)
    indices.sort()
    return xyz[indices], classes[indices], len(xyz)-len(indices)


def extract_stream(source, region):
    """Serial 100k-point chunks; persist the tiny crop and cursor for resuming."""
    global STREAM_RECOVERY
    blocks, labels, visited = [], [], []
    checkpoint = CACHE / 'stream-checkpoint.npz'
    tiles = [t for t in source['tiles'] if region.intersects(shapely.box(
        t['header']['bounds'][0][0], t['header']['bounds'][0][1],
        t['header']['bounds'][1][0], t['header']['bounds'][1][1]))]
    identity = hashlib.sha256(region.wkb + json.dumps([
        file_record(ROOT/t['file']['path']) for t in tiles],sort_keys=True).encode()).hexdigest()
    tile_index, processed, elapsed_before, attempts = 0, 0, 0., 0
    if checkpoint.exists():
        with np.load(checkpoint, allow_pickle=False) as saved:
            meta = json.loads(str(saved['metadata']))
            if meta['identity'] != identity:
                raise ValueError('Stream checkpoint belongs to different source files or selected region')
            blocks, labels = [saved['xyz']], [saved['classes']]
        tile_index, processed = meta['tile_index'],meta['processed']
        visited, elapsed_before, attempts = meta['visited'],meta['active_seconds'],meta['attempts']
        print(json.dumps({'event':'resume_point_stream','tile_index':tile_index,
            'points_in_tile':processed,'previous_active_seconds':elapsed_before}),flush=True)
    resumed_points = sum(t['header']['point_count'] for t in tiles[:tile_index])+processed
    started = time.perf_counter()
    def save_checkpoint():
        xyz = np.concatenate(blocks) if blocks else np.empty((0,3))
        classes = np.concatenate(labels) if labels else np.empty(0,dtype=np.uint8)
        guard.check_budget(reserve_bytes=xyz.nbytes+classes.nbytes+1_000_000)
        meta = {'identity':identity,'tile_index':tile_index,'processed':processed,'visited':visited,
                'active_seconds':elapsed_before+time.perf_counter()-started,'attempts':attempts+1}
        temporary = checkpoint.with_suffix('.npz.tmp')
        with temporary.open('wb') as handle:
            np.savez_compressed(handle,xyz=xyz,classes=classes,metadata=json.dumps(meta))
        temporary.replace(checkpoint)
    xmin, ymin, xmax, ymax = region.bounds
    shapely.prepare(region)
    try:
      while tile_index < len(tiles):
        tile = tiles[tile_index]
        resource_check()
        path = ROOT / tile['file']['path']
        print(json.dumps({'event': 'read_cached_tile', 'file': rel(path)}, ensure_ascii=False), flush=True)
        if rel(path) not in visited:
            visited.append(rel(path))
        next_report = (processed//10_000_000+1)*10_000_000
        with laspy.open(path, laz_backend=laspy.LazBackend.Lazrs) as reader:
            if processed:
                reader.seek(processed)
            for chunk in reader.chunk_iterator(CHUNK):
                resource_check()
                processed += len(chunk)
                x, y, cls = np.asarray(chunk.x), np.asarray(chunk.y), np.asarray(chunk.classification)
                keep = np.flatnonzero((x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)
                                      & ((cls == 2) | (cls == 6)))
                keep = keep[shapely.intersects_xy(region, x[keep], y[keep])]
                if len(keep):
                    z = np.asarray(chunk.z)
                    blocks.append(np.column_stack((x[keep], y[keep], z[keep])))
                    labels.append(cls[keep].copy())
                if sum(a.nbytes for a in blocks) > 300_000_000:
                    raise guard.ResourceLimit('Selected crop exceeded 300 MB; reduce sample before retrying')
                if processed >= next_report:
                    print(json.dumps({'event':'tile_progress','file':rel(path),'points_read':processed,
                                      'total_points':tile['header']['point_count']},ensure_ascii=False),flush=True)
                    save_checkpoint()
                    next_report += 10_000_000
        tile_index += 1
        processed = 0
        save_checkpoint()
    except guard.ResourceLimit:
        try:
            save_checkpoint()
        except guard.ResourceLimit:
            pass  # Disk stop takes precedence over persisting the last chunk.
        raise
    STREAM_RECOVERY = {'resumed_points':resumed_points, 'attempts':attempts+1,
        'active_read_seconds_all_attempts':elapsed_before+time.perf_counter()-started,
        'checkpoint':rel(checkpoint)}
    if not blocks:
        return np.empty((0, 3)), np.empty(0, dtype=np.uint8), visited
    return np.concatenate(blocks), np.concatenate(labels), visited


def prepare(sample, output=OUT / 'inputs.json'):
    start, cpu = time.perf_counter(), time.process_time()
    resource_check()
    old_manifest, source = source_inventory()
    sample_hash = hashlib.sha256(json.dumps(sample, sort_keys=True).encode()).hexdigest()
    if output.exists():
        saved = json.loads(output.read_text(encoding='utf-8'))
        if saved.get('sample_sha256') == sample_hash and all('cache' not in p or
                ((ROOT / p['cache']['path']).is_file() and (ROOT / p['cache']['path']).stat().st_size == p['cache']['bytes'])
                for b in saved.get('buildings', []) for p in b.get('parts', [])):
            print('Input cache reused unchanged.', flush=True)
            return saved
        raise ValueError('Existing inputs do not match the frozen sample; inspect before replacing')
    pilot = json.loads(PILOT_SAMPLE.read_text(encoding='utf-8'))
    transform = Transformer.from_crs(4326, 5514, always_xy=True).transform
    pilot_region = shapely.union_all([shapely.transform(shape(f['geometry']), transform,
        interleaved=False).buffer(BUFFER) for f in pilot['features']])
    crops, new = {}, []
    for feature in sample['features']:
        region = shape(feature['geometry']).buffer(BUFFER)
        if pilot_region.buffer(.001).covers(region):
            crops[feature['id']] = 'existing_pilot_crop'
        else:
            crops[feature['id']] = 'existing_full_laz'
            new.append(region)
    # Existing 68 MB crop is read first, released before streaming new source sheets.
    groups = [('existing_pilot_crop', None), ('existing_full_laz', shapely.union_all(new))]
    buildings, read_files = [], []
    CACHE.mkdir(parents=True, exist_ok=True)
    for mode, region in groups:
        features = [f for f in sample['features'] if crops[f['id']] == mode]
        if not features:
            continue
        if mode == 'existing_pilot_crop':
            crop_path = ROOT / source['crop_path']
            with np.load(crop_path) as data:
                xyz, classes = data['xyz'], data['classification']
            read_files.append(rel(crop_path))
        else:
            xyz, classes, visited = extract_stream(source, region)
            read_files.extend(visited)
        for feature in features:
            resource_check()
            properties = feature['properties']
            building = {'id': feature['id'], 'name': properties['name'], 'address': properties['address'],
                'lon': properties['lon'], 'lat': properties['lat'], 'source': 'dmpok',
                'selection': {k: properties[k] for k in ('role', 'category')},
                'requested_address':properties.get('requested_address'),
                'requested_addresses':properties.get('requested_addresses', [properties.get('requested_address')]),
                'address_resolution_note':properties.get('address_resolution_note'),
                'source_attributes': properties['source_attributes'],
                'footprint_sources': properties.get('footprint_sources', []), 'parts': []}
            polygons = sorted(polygon_parts(shape(feature['geometry'])), key=lambda poly: (-poly.area, poly.bounds))
            for part_index, poly in enumerate(polygons):
                xmin,ymin,xmax,ymax = poly.buffer(BUFFER).bounds
                nearby = np.flatnonzero((xyz[:,0]>=xmin)&(xyz[:,0]<=xmax)&(xyz[:,1]>=ymin)&(xyz[:,1]<=ymax))
                pts, cls = xyz[nearby], classes[nearby]
                roof = pts[(cls == 6) & shapely.contains_xy(poly, pts[:,0], pts[:,1])]
                roof, _, removed = unique_points(roof, np.full(len(roof),6,dtype=np.uint8))
                ground = np.empty((0,3))
                for radius in (6,12,20):
                    ring = poly.buffer(radius).difference(poly.buffer(1))
                    ground = pts[(cls == 2) & shapely.contains_xy(ring,pts[:,0],pts[:,1])]
                    if len(ground) >= 5:
                        break
                if len(ground) < 5:
                    building['parts'].append({'status': 'missing_ground_reference', 'part_index': part_index,
                        'ground_source': {'method':'class2_median_external_annulus','points':len(ground)}})
                    continue
                ground_z = float(np.median(ground[:,2]))
                origin = np.array([poly.centroid.x,poly.centroid.y])
                relative = roof - np.array([*origin, ground_z])
                held = split_points(roof)
                cache_path = CACHE / f"{feature['id']}-{part_index}.npz"
                temp = cache_path.with_suffix('.npz.tmp')
                guard.check_budget(reserve_bytes=relative.nbytes+1_000_000)
                with temp.open('wb') as handle:
                    np.savez_compressed(handle, train=relative[~held], holdout=relative[held])
                temp.replace(cache_path)
                building['parts'].append({'part_index':part_index, 'status':'prepared' if len(roof) else 'no_roof_points',
                    'origin_xy':origin.tolist(),'ground_z':ground_z,
                    'footprint':mapping(translate(poly,-origin[0],-origin[1])), 'cache':file_record(cache_path,True),
                    'ground_source': {'method':'class2_median_external_annulus','points':len(ground),'radius_m':radius,
                        'inner_exclusion_m':1,'p10_m':float(np.quantile(ground[:,2],.1)),
                        'p90_m':float(np.quantile(ground[:,2],.9))},
                    'measurement': {'roof_points':len(roof),'train_points':int((~held).sum()),'holdout_points':int(held.sum()),
                        'footprint_area_m2':poly.area,'roof_points_per_m2':len(roof)/poly.area,
                        'exact_duplicate_points_removed':removed},'input_mode':mode})
            buildings.append(building)
            print(json.dumps({'event':'prepared','id':building['id'],'address':building['address'],
                              'roof_points':sum(p.get('measurement',{}).get('roof_points',0) for p in building['parts'])},ensure_ascii=False),flush=True)
        del xyz, classes
    order = {f['id']:i for i,f in enumerate(sample['features'])}
    buildings.sort(key=lambda b:order[b['id']])
    result = {'schema':'roof-v2-inputs/1','city':'ceske-budejovice','crs':'EPSG:5514','vertical_datum':'Bpv',
        'created_at_utc':utc(),'sample_sha256':sample_hash,'source':'dmpok','buildings':buildings,
        'source_tiles':source['tiles'],'input_files_read':read_files,
        'split':{'method':'centimetre world XY uint64 hash modulo 5; bin0 holdout','heldout_fraction_target':.2,
                 'independent_of_model':True,'same_xy_kept_together':True,
                 'limitation':'Same correlated photogrammetric survey, not independent surveyed geometry.'},
        'ground_policy':'Median unchanged class2 samples within exterior 1–6/12/20m annulus; no guessed elevation.',
        'timing':{'wall_seconds':time.perf_counter()-start,'cpu_seconds':time.process_time()-cpu},
        'stream_recovery':STREAM_RECOVERY,
        'resources_after':resource_check(),'output_cache_bytes':sum(p.get('cache',{}).get('bytes',0) for b in buildings for p in b['parts'])}
    atomic_json(output,result)
    return result


def point_preview(points, limit):
    if len(points) <= limit:
        return np.round(points,3).tolist()
    return np.round(points[np.linspace(0,len(points)-1,limit,dtype=int)],3).tolist()


def external_metrics(result, points):
    """Evaluate held-out XY against roofs; a shared edge may use either roof plane."""
    if not len(points):
        return {'n':0,'status':'no_holdout_points'}
    prediction = np.full(len(points),np.nan)
    for region in result.get('model',{}).get('regions',[]):
        polygon = shape(region['polygon'])
        covered = shapely.intersects_xy(polygon.buffer(1e-7),points[:,0],points[:,1])
        a,b,c = region['plane']
        z = a*points[covered,0]+b*points[covered,1]+c
        prediction[covered] = np.fmax(prediction[covered],z)
    valid = np.isfinite(prediction)
    errors = points[valid,2]-prediction[valid]
    if not len(errors):
        return {'n':len(points),'evaluated':0,'coverage_fraction':0,'status':'no_region_coverage'}
    absolute = np.abs(errors)
    return {'n':len(points),'evaluated':len(errors),'coverage_fraction':float(valid.mean()),
        'mae_m':float(absolute.mean()),'rmse_m':float(np.sqrt(np.mean(errors**2))),
        'median_abs_m':float(np.median(absolute)),'p90_abs_m':float(np.quantile(absolute,.9)),
        'p95_abs_m':float(np.quantile(absolute,.95)),'p99_abs_m':float(np.quantile(absolute,.99)),
        'within_05m':float(np.mean(absolute<=.5)),'within_1m':float(np.mean(absolute<=1)),
        'positive_over_1m':float(np.mean(errors>1)), 'negative_below_minus_1m':float(np.mean(errors < -1)),
        'positive_over_1m_count':int(np.sum(errors>1)), 'negative_below_minus_1m_count':int(np.sum(errors < -1)),
        'signed_bias_m':float(errors.mean()),'status':'same_source_holdout',
        'interpretation':'Vertical residual over all fixed heldout class6 points, including rooftop protrusions; not architectural ground truth.'}


def run(inputs, output=OUT/'results.json', config=None, limit=None):
    from roof_v2 import infer_roof_v2
    start,cpu = time.perf_counter(),time.process_time()
    doc = {'schema':'roof-v2/1','city':'ceske-budejovice','source':'dmpok','crs':'EPSG:5514',
        'vertical_datum':'Bpv','created_at_utc':utc(),'status':'running','sample_sha256':inputs['sample_sha256'],
        'split':inputs['split'],'buildings':[],'configuration':config or {}}
    diagnostics = {'schema':'roof-v2-diagnostics/1','sample_sha256':inputs['sample_sha256'],'buildings':[]}
    for source_building in inputs['buildings'][:limit]:
        resource_check()
        wall, proc = time.perf_counter(),time.process_time()
        building = {k:v for k,v in source_building.items() if k!='parts'}
        building['parts'] = []
        for source_part in source_building['parts']:
            part = dict(source_part)
            if part.get('status') != 'prepared':
                building['parts'].append(part)
                continue
            try:
                with np.load(ROOT/part['cache']['path']) as data:
                    train,holdout = data['train'],data['holdout']
                result = infer_roof_v2(shape(part['footprint']),train,
                    source_type=building['source_attributes'].get('roof_shape'), config=config)
                part.update(result=result, external_metrics=external_metrics(result,holdout),
                    point_preview=point_preview(train,2000),holdout_preview=point_preview(holdout,500), status='inferred')
            except Exception as exc:
                if isinstance(exc,(MemoryError,guard.ResourceLimit)):
                    raise
                part.update(status='failed',error={'type':type(exc).__name__,'reason':str(exc)})
                print(json.dumps({'event':'part_failed','id':building['id'],'part_index':part['part_index'],
                                  'error':part['error']},ensure_ascii=False),flush=True)
            finally:
                train=holdout=None
            building['parts'].append(part)
        building['status']='inferred' if all(p['status']=='inferred' for p in building['parts']) else 'incomplete'
        building['timing'] = {'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-proc}
        doc['buildings'].append(building)
        diagnostics['buildings'].append({'id':building['id'],'address':building['address'],'timing':building['timing'],
            'parts':[{'part_index':p['part_index'],'diagnostics':p.get('result',{}).get('diagnostics'),
                      'external_metrics':p.get('external_metrics'),'status':p['status'],
                      'error':p.get('error')} for p in building['parts']]})
        doc['timing'] = {'wall_seconds':time.perf_counter()-start,'cpu_seconds':time.process_time()-cpu}
        atomic_json(output,doc)
        atomic_json(output.with_name('diagnostics.json'),diagnostics)
        print(json.dumps({'event':'inferred','id':building['id'],'address':building['address'],
                          'seconds':building['timing']['wall_seconds']},ensure_ascii=False),flush=True)
    doc['status'] = 'complete' if limit is None or limit >= len(inputs['buildings']) else 'limited_run'
    if any(b['status']!='inferred' for b in doc['buildings']):
        doc['status'] += '_with_incomplete_buildings'
    doc['resources_after'] = resource_check()
    atomic_json(output,doc)
    return doc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare-only',action='store_true')
    action.add_argument('--run',action='store_true')
    action.add_argument('--sample-only',action='store_true')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    if not args.worker:
        bootstrap = ('import sys,runpy;sys.path[:0]=' + repr(sys.path) +
                     ';sys.argv=' + repr([str(Path(__file__).resolve()),*sys.argv[1:],'--worker']) +
                     ';runpy.run_path(' + repr(str(Path(__file__).resolve())) + ',run_name="__main__")')
        guard.run_guarded([sys.executable,'-S','-X','utf8','-c',bootstrap], ROOT,
            CACHE/('run.log' if args.run else 'prepare.log'), min_available_gb=.75,max_ram_gb=1.5,
            wait_memory_seconds=0)
        return
    with guard.keep_awake():
        sample=make_sample()
        if args.sample_only:
            print(json.dumps({'sample':rel(OUT/'sample.json'),'buildings':len(sample['features']),
                              'groups':dict(Counter(f['properties']['category'] for f in sample['features']))},ensure_ascii=False),flush=True)
            return
        inputs=prepare(sample)
        if args.run:
            config=json.loads(args.config.read_text(encoding='utf-8')) if args.config else None
            run(inputs,config=config,limit=args.limit)


if __name__=='__main__':
    main()
