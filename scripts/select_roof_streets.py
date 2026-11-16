"""Select roof requests by street from cached addresses, without downloading data.

Address points must lie in exactly one existing footprint. Missing/ambiguous
matches are reported for review, never assigned to the nearest house silently.
"""
import argparse
import json
import time
from pathlib import Path

import resource_guard as guard

# Check before importing the numerical libraries when this is a CLI worker.
if __name__ == '__main__' and guard.memory_status()['available'] < 1_000_000_000:
    raise guard.ResourceLimit('STOP: street selection needs at least 1 GB available RAM')

import pyarrow.parquet as pq
import shapely

ROOT = Path(__file__).resolve().parents[1]


def select(streets, addresses, buildings):
    """MODULE street selection: exact normalized names and spatial containment."""
    wanted = {s.strip().casefold() for s in streets}
    rows = [b for b in buildings if b.get('geometry') and not b.get('is_underground')]
    shapes = shapely.make_valid(shapely.from_wkb([b['geometry'] for b in rows]))
    tree = shapely.STRtree(shapes)
    requests, resolved, unresolved, seen_addresses = [], [], [], set()
    counts = {s: {'addresses': 0, 'building_ids': set()} for s in streets}
    names = {s.strip().casefold(): s for s in streets}
    for address in addresses:
        street = (address.get('street') or '').strip().casefold()
        if street not in wanted:
            continue
        name = names[street]
        counts[name]['addresses'] += 1
        request = {k: address.get(k) for k in ('street', 'number', 'unit')}
        point = shapely.from_wkb(address['geometry']) if address.get('geometry') else None
        indices = list(map(int, tree.query(point, predicate='covered_by'))) if point is not None else []
        if len(indices) != 1:
            unresolved.append({'address': request, 'address_id': address.get('id'),
                               'reason': 'missing_footprint' if not indices else 'ambiguous_footprint',
                               'candidate_ids': [rows[i]['id'] for i in indices]})
            continue
        building_id = rows[indices[0]]['id']
        counts[name]['building_ids'].add(building_id)
        key = tuple(request.values())
        if key not in seen_addresses:
            requests.append(request)
            resolved.append({'address': request, 'building_id': building_id})
            seen_addresses.add(key)
    requests.sort(key=lambda r: (r['street'], str(r['number']), str(r.get('unit') or '')))
    return requests, {'streets': {s: {'addresses': c['addresses'],
                                      'unique_buildings': len(c['building_ids'])} for s, c in counts.items()},
                      'unique_buildings': len({r['building_id'] for r in resolved}),
                      'resolved': resolved, 'unresolved': unresolved,
                      'selection': 'Addressed buildings only; exact street name and point-in-footprint.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--city', required=True)
    parser.add_argument('--street', action='append', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not (ROOT / 'cities' / args.city).is_dir() or Path(args.city).name != args.city:
        parser.error('Unknown city slug')
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error('Choose a new/empty output directory')
    preview = ROOT / '.work' / '.preview' / args.city
    data = next((preview / p for p in ('data_all', 'data')
                 if all((preview / p / (n + '.parquet')).is_file() for n in ('address', 'building'))), None)
    if data is None:
        raise FileNotFoundError('No local address/building Parquet pair for ' + args.city)
    guard.check_budget(force=True)
    start = time.perf_counter()
    requests, report = select(args.street,
        pq.read_table(data / 'address.parquet', columns=['id', 'street', 'number', 'unit', 'geometry']).to_pylist(),
        pq.read_table(data / 'building.parquet', columns=['id', 'geometry', 'is_underground']).to_pylist())
    report.update(city=args.city, source_directory=str(data.relative_to(ROOT)),
                  elapsed_seconds=time.perf_counter() - start)
    output.mkdir(parents=True, exist_ok=True)
    for filename, payload in [('requests.json', requests), ('selection.json', report)]:
        (output / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'city': args.city, 'streets': report['streets'],
                     'unique_buildings': report['unique_buildings'], 'unresolved': report['unresolved'],
                     'elapsed_seconds': report['elapsed_seconds'], 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
