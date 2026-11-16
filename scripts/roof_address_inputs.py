"""Prepare explicitly requested addresses from local data; never download tiles.

Example: --requests addresses.json --output cities/ceske-budejovice/experiments/new-inputs
Optional --reuse-inputs and repeated --reuse-id keep existing point crops unchanged.
"""
import argparse
import copy
import gc
import json
from pathlib import Path
import cb_roof_v2 as prep
import pyarrow.parquet as pq
import shapely
from shapely.geometry import mapping
from pyproj import Transformer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--city', choices=prep.SUPPORTED_CITIES, default='ceske-budejovice',
                        help='Select cached city inputs; default keeps the original CB experiment')
    parser.add_argument('--requests', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--reuse-inputs', type=Path)
    parser.add_argument('--reuse-id', action='append', default=[])
    parser.add_argument('--resume', action='store_true', help='Resume only an identical frozen address sample')
    args = parser.parse_args(argv)
    prep.configure_city(args.city)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()) and not args.resume:
        parser.error('Choose a new/empty output directory')
    if args.reuse_id and not args.reuse_inputs:
        parser.error('--reuse-id requires --reuse-inputs')
    old = None
    if args.reuse_inputs:
        old = json.loads(args.reuse_inputs.read_text(encoding='utf-8'))
        if old.get('city') != args.city:
            parser.error('Reused input manifest belongs to a different city')
    with prep.guard.keep_awake():
        prep.resource_check()
        requested = json.loads(args.requests.read_text(encoding='utf-8'))
        rows = pq.read_table(prep.DATA/'building.parquet').to_pylist()
        rows = [r for r in rows if r.get('geometry') and not r.get('is_underground')]
        shapes = shapely.make_valid(shapely.from_wkb([r['geometry'] for r in rows]))
        tree = shapely.STRtree(shapes)
        addresses = pq.read_table(prep.DATA/'address.parquet').to_pylist()
        _, source = prep.source_inventory()
        coverage = shapely.union_all([shapely.box(t['header']['bounds'][0][0], t['header']['bounds'][0][1],
            t['header']['bounds'][1][0], t['header']['bounds'][1][1]).buffer(.15) for t in source['tiles']])
        transform = Transformer.from_crs(4326, 5514, always_xy=True).transform
        features, seen, by_id = [], set(), {}
        for request in requested:
            matches = [a for a in addresses if a.get('geometry') and prep.address_key(a)==prep.address_key(request)]
            if not matches:
                raise ValueError('Missing local address: '+prep.address_label(request))
            indices = set()
            for address in matches:
                indices.update(map(int, tree.query(shapely.from_wkb(address['geometry']), predicate='covered_by')))
            if len(indices) != 1:
                raise ValueError('Ambiguous/missing footprint: '+prep.address_label(request))
            index = indices.pop()
            row, wgs = rows[index], shapes[index]
            poly = shapely.transform(wgs, transform, interleaved=False)
            if not coverage.covers(poly.buffer(prep.BUFFER)):
                raise ValueError('Address outside cached dense point coverage: '+prep.address_label(request))
            label = prep.address_label(request)
            if row['id'] in seen:
                by_id[row['id']]['properties']['requested_addresses'].append(label)
                continue
            seen.add(row['id'])
            features.append({'type':'Feature', 'id':row['id'], 'geometry':mapping(poly), 'properties':{
                'role':'user_address', 'category':'user_address', 'name':label, 'address':label,
                'requested_address':request.get('requested_address',label), 'requested_addresses':[request.get('requested_address',label)],
                'address_resolution_note':request.get('resolution_note'), 'lon':wgs.centroid.x, 'lat':wgs.centroid.y,
                'footprint_sources':row.get('sources'), 'coverage_complete':True,
                'source_attributes':{k:row.get(k) for k in ('class','subtype','height','num_floors',
                    'roof_shape','roof_height','roof_color','facade_color','roof_material','has_parts')}}})
            by_id[row['id']] = features[-1]
        print(json.dumps({'event':'resolved_addresses','requested':len(requested),
            'unique_buildings':len(features), 'addresses':[
                {'id':f['id'],'addresses':f['properties']['requested_addresses']} for f in features]},
            ensure_ascii=False),flush=True)
        del rows, shapes, tree, addresses, coverage
        gc.collect()
        sample = {'type':'FeatureCollection', 'schema':'roof-v2-sample/1', 'city':args.city,
            'crs':'EPSG:5514', 'created_at_utc':prep.utc(), 'features':features,
            'selection':'Explicit user addresses; roof type is not supplied to the fitter.'}
        if args.resume and (output/'sample.json').exists():
            saved = json.loads((output/'sample.json').read_text(encoding='utf-8'))
            if any(json.dumps(saved.get(k),sort_keys=True) != json.dumps(sample[k],sort_keys=True)
                   for k in ('features','city','crs')):
                raise ValueError('Cannot resume: selected addresses or footprints changed')
            sample = saved
        prep.atomic_json(output/'sample.json', sample)
        prep.CACHE = output/'point-clouds'
        inputs = prep.prepare(sample, output/'additional-inputs.json')
        if old is not None:
            lookup = {b['id']:b for b in old['buildings']}
            for oid in args.reuse_id:
                building = copy.deepcopy(lookup[oid])
                base = args.reuse_inputs.resolve().parent if old.get('cache_path_base')=='manifest_directory' else prep.ROOT
                for part in building['parts']:
                    if 'cache' in part:
                        part['cache']['path'] = prep.rel(base/part['cache']['path'])
                if oid not in seen:
                    inputs['buildings'].insert(0, building)
            inputs['reused_input_manifest'] = prep.rel(args.reuse_inputs)
            inputs['reused_building_ids'] = args.reuse_id
        inputs['sample_sha256_scope'] = 'New address sample; reused inputs retain their point-cache checksums.'
        prep.atomic_json(output/'inputs.json', inputs)
        print(json.dumps({'inputs':prep.rel(output/'inputs.json'), 'buildings':len(inputs['buildings'])}), flush=True)


if __name__ == '__main__':
    main()
