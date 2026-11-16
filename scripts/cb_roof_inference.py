"""Run roof inference on the address sample in the České Budějovice preview."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import laspy
import numpy as np
import pyarrow.parquet as pq
from pyproj import Transformer
import shapely

from roof_pilot_sources import CHUNK_SIZE, deduplicate, header_metadata


ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / '.work/.preview/ceske-budejovice'
SAMPLE = ROOT / 'cities/ceske-budejovice/roof-inference-sample.json'
OUTPUT = ROOT / '.work/cb-roof-inference/roofs.json'
DMPOK = ROOT / '.work/cb-roof-pilot/sources/dmpok'
CRS = 'EPSG:5514'
TRANSFORMER = Transformer.from_crs('EPSG:4326', CRS, always_xy=True)
GROUND_BUFFER = 20


def address_key(row):
    return row['street'], row['number'], row['unit']


def address_label(row):
    street, number, unit = address_key(row)
    return f'{street} {number}/{unit}' if unit else f'{street} {number}'


def ruian_id(row):
    return next((source['record_id'] for source in row['sources'] or []
                 if source['provider'] == 'cuzk'), None)


def polygon_parts(geometry):
    if geometry.geom_type == 'Polygon' and geometry.area > 0:
        yield geometry
    elif geometry.geom_type in ('MultiPolygon', 'GeometryCollection'):
        for part in geometry.geoms:
            yield from polygon_parts(part)


def address_candidates(data_dir, sample):
    addresses = [row for row in pq.read_table(
        data_dir / 'address.parquet', columns=['id', 'street', 'number', 'unit', 'geometry', 'sources']
    ).to_pylist() if ruian_id(row)]
    address_geometries = shapely.from_wkb([row['geometry'] for row in addresses])
    address_index = shapely.STRtree(address_geometries)
    by_key = {}
    for index, row in enumerate(addresses):
        by_key.setdefault(address_key(row), {})[ruian_id(row)] = index

    footprints = pq.read_table(data_dir / 'building.parquet', columns=[
        'id', 'geometry', 'roof_shape', 'has_parts', 'is_underground',
    ]).to_pylist()
    footprints = [row for row in footprints if row['geometry'] and not row['is_underground']]
    geometries = shapely.make_valid(shapely.from_wkb([row['geometry'] for row in footprints]))
    footprint_index = shapely.STRtree(geometries)

    for target in sample:
        label = address_label(target)
        record = {'address': label, 'requested_address': target.get('requested', label),
                  'id': None, 'lon': None, 'lat': None, 'models': []}
        exact = by_key.get(address_key(target), {})
        if len(exact) != 1:
            record.update(status='address_not_found' if not exact else 'ambiguous_address',
                          ruian_address_candidates=sorted(exact))
            yield record, []
            continue
        official_id, a = next(iter(exact.items()))
        point = address_geometries[a]
        record.update(lon=point.x, lat=point.y, ruian_address_id=official_id)
        indices = footprint_index.query(point, predicate='covered_by')
        if len(indices) != 1:
            record.update(status='footprint_not_found' if not len(indices) else 'ambiguous_footprint',
                          footprint_candidates=sorted(footprints[i]['id'] for i in indices))
            yield record, []
            continue

        i = indices[0]
        footprint, geometry = footprints[i], geometries[i]
        projected = shapely.make_valid(shapely.transform(geometry, TRANSFORMER.transform, interleaved=False))
        parts = sorted(polygon_parts(projected), key=lambda g: (-g.area, g.bounds))
        matches = address_index.query(geometry, predicate='covers')
        co_addresses = sorted({address_label(addresses[j]) for j in matches if j != a})
        record.update(id=footprint['id'], status='matched' if parts else 'invalid_footprint',
                      matched_by='ruian_address_in_overture_footprint',
                      footprint_area_m2=round(projected.area, 2),
                      footprint_has_parts=bool(footprint['has_parts']),
                      footprint_other_addresses=co_addresses, source_roof_type=footprint['roof_shape'])
        yield record, parts


def read_points(files, region):
    """Read the relevant source sheets once and retain class 2/6 around the sample."""
    blocks, labels, tiles = [], [], []
    if region.is_empty:
        return np.empty((0, 3)), np.empty(0, dtype=np.uint8), tiles, 0
    xmin, ymin, xmax, ymax = region.bounds
    for path in files:
        header = header_metadata(path)
        lo, hi = header['bounds']
        if not region.intersects(shapely.box(lo[0], lo[1], hi[0], hi[1])):
            continue
        tiles.append({'file': path.name, 'point_count': header['point_count'],
                      'las_creation_date': header['creation_date']})
        with laspy.open(path) as reader:
            for chunk in reader.chunk_iterator(CHUNK_SIZE):
                x, y = np.asarray(chunk.x), np.asarray(chunk.y)
                cls = np.asarray(chunk.classification)
                selected = np.flatnonzero((x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)
                                          & ((cls == 2) | (cls == 6)))
                selected = selected[shapely.intersects_xy(region, x[selected], y[selected])]
                if len(selected):
                    z = np.asarray(chunk.z)
                    blocks.append(np.column_stack((x[selected], y[selected], z[selected])))
                    labels.append(cls[selected])
    if not blocks:
        return np.empty((0, 3)), np.empty(0, dtype=np.uint8), tiles, 0
    points, classes, removed = deduplicate(np.concatenate(blocks), np.concatenate(labels))
    return points, classes, tiles, removed


def building_points(polygon, points, classes):
    x, y = points[:, 0], points[:, 1]
    inside = shapely.contains_xy(polygon, x, y)
    roof = points[inside & (classes == 6)]
    ground = np.empty(0)
    for distance in (6, 12, GROUND_BUFFER):
        ring = polygon.buffer(distance).difference(polygon.buffer(1))
        ground = points[(classes == 2) & shapely.contains_xy(ring, x, y), 2]
        if len(ground) >= 5:
            break
    return roof, ground, distance


def run(args):
    sample = json.loads(args.sample.read_text(encoding='utf-8'))
    candidates = list(address_candidates(args.work / 'data', sample))
    region = shapely.union_all([p.buffer(GROUND_BUFFER) for _, parts in candidates for p in parts])
    point_dir = args.point_dir or (args.work / 'build/dmp' if args.source == 'dmp1g' else DMPOK)
    files = sorted(path for path in point_dir.rglob('*') if path.suffix.lower() in ('.las', '.laz'))
    if not files and not region.is_empty:
        raise FileNotFoundError(f'No LAS/LAZ tiles in {point_dir}')
    points, classes, tiles, removed = read_points(files, region)

    if not args.inspect_only and not region.is_empty:
        from roof_inference import infer_roof

    buildings = []
    for record, parts in candidates:
        for index, polygon in enumerate(parts, start=1):
            roof, ground, radius = building_points(polygon, points, classes)
            ground_z = float(np.median(ground)) if len(ground) >= 5 else None
            if args.inspect_only or not len(roof):
                model = {'status': 'points_available' if len(roof) else 'no_roof_points',
                         'type': None, 'vertices': [], 'roof_faces': [], 'wall_faces': [],
                         'ridge': [], 'diagnostics': {}}
            else:
                model = infer_roof(polygon, roof, ground_z)
            model['id'] = record['id'] if len(parts) == 1 else f"{record['id']}:{index}"
            model['scene_oid'] = record['id']
            model['measurement'] = {'roof_points': len(roof), 'ground_points': len(ground),
                                    'ground_z_m': ground_z, 'ground_outer_radius_m': radius,
                                    'footprint_area_m2': round(polygon.area, 2)}
            record['models'].append(model)
        if parts:
            statuses = {model['status'] for model in record['models']}
            record['status'] = statuses.pop() if len(statuses) == 1 else 'mixed'
        record['map_geometry'] = ('inferred_roof' if record['status'] == 'supported'
                                  else 'existing_renderer_fallback')
        buildings.append(record)
        print(f"{record['address']}: {record['status']} " + ', '.join(
            f"{model['type'] or '—'} ({model['measurement']['roof_points']} bodů)"
            for model in record['models']), flush=True)
    return {'schema': 'roof-inference/1', 'city': 'ceske-budejovice',
            'horizontal_crs': CRS, 'vertical_datum': 'Bpv', 'units': 'm',
            'source': {'address': 'ČÚZK RÚIAN via Overture Maps', 'footprint': 'Overture Maps',
                       'heights': 'ČÚZK ' + args.source.upper(), 'tiles': tiles,
                       'class6': 'inside original building footprint',
                       'class2': 'within exterior ring, 1 m from outline and up to 20 m away',
                       'exact_duplicates_removed': removed}, 'buildings': buildings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=PREVIEW, help='Local city preview with GeoParquet')
    parser.add_argument('--sample', type=Path, default=SAMPLE)
    parser.add_argument('--output', type=Path, help='Output JSON path')
    parser.add_argument('--source', choices=('dmp1g', 'dmpok'), default='dmp1g')
    parser.add_argument('--point-dir', type=Path, help='Override the directory of source LAS/LAZ tiles')
    parser.add_argument('--inspect-only', action='store_true', help='Only verify addresses and count points')
    args = parser.parse_args()
    result = run(args)
    suffix = ('-' + args.source if args.source != 'dmp1g' else '') + ('-inputs' if args.inspect_only else '')
    output = args.output or OUTPUT.with_name(OUTPUT.stem + suffix + OUTPUT.suffix)
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.close()
            temporary.replace(output)
        finally:
            if not handle.closed:
                handle.close()
            temporary.unlink(missing_ok=True)
    print(output)


if __name__ == '__main__':
    main()
