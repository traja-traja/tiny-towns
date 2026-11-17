"""Standalone, resumable city point preparation; no roof fitting or AI services.

plan freezes the footprint queue. prepare reads each relevant LAZ once per stage,
spools small per-building crops, then writes normal roof_batch input manifests.
Roof class 6 is unchanged; class 2 uses a deterministic 1/16 XY sample for ground.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import unicodedata
import urllib.error

for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'ARROW_NUM_THREADS'):
    os.environ[_key] = '1'

import laspy
import numpy as np
import pyarrow.parquet as pq
from pyproj import Transformer
import shapely
from shapely.geometry import shape, mapping
from shapely.affinity import translate
import cb_roof_v2 as prep
import resource_guard as guard
import atomic_io

ROOT = Path(__file__).resolve().parents[1]
VELESIN_STREETS = ['Náměstí J. V. Kamarýta', 'Družstevní', 'Školní', 'U Přehrady']
CB_STREETS = ['nám. Přemysla Otakara II.', 'Hroznová', 'Krajinská', 'Česká', 'Kněžská',
              'Dr. Stejskala', 'Radniční', 'Biskupská', 'Karla IV.', 'Široká']
SPORTCENTRUM = '78e32d1e-ecfa-4e1b-a00f-db417ea5af1b'
RAW_DTYPE = np.dtype([('x', '<f8'), ('y', '<f8'), ('z', '<f8'), ('c', 'u1')])
POLICY = 'night-inputs-1; class6 unchanged; ground class2 centimetre-XY hash modulo16'


def normal(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value)).casefold() if c.isalnum())


def stage_for(city, streets):
    names = [normal(s) for s in streets]
    priorities = VELESIN_STREETS if city == 'velesin' else CB_STREETS
    hits = [i for i, name in enumerate(priorities) if normal(name) in names]
    return (('streets' if city == 'velesin' else 'centre'), min(hits)) if hits else (
        'city' if city == 'velesin' else 'extra', len(priorities))


def write(path, document):
    payload = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    guard.check_budget(reserve_bytes=len(payload.encode('utf-8')))
    atomic_io.write_text(path, payload)


def read(path):
    return json.loads(atomic_io.read_text(path))


def expired(deadline):
    return deadline is not None and time.time() >= deadline


def transient_download_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return error.code in (408, 429) or 500 <= error.code <= 599
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))


def tile_polygon(tile):
    lo, hi = tile['header']['bounds']
    return shapely.box(lo[0], lo[1], hi[0], hi[1])


def coverage(tiles):
    return shapely.union_all([tile_polygon(t).buffer(.15) for t in tiles])


def plan(city, output):
    output = Path(output).resolve()
    if (output / 'queue.json').exists():
        saved = read(output / 'queue.json')
        if saved['city'] != city:
            raise ValueError('Existing queue belongs to another city')
        return saved
    prep.configure_city(city)
    data = prep.PREVIEW / 'data_all'
    if not (data / 'building.parquet').exists():
        data = prep.DATA
    rows = pq.read_table(data / 'building.parquet').to_pylist()
    rows = [r for r in rows if r.get('geometry') and not r.get('is_underground')]
    polygons = shapely.make_valid(shapely.from_wkb([r['geometry'] for r in rows]))
    tree = shapely.STRtree(polygons)
    addresses = pq.read_table(data / 'address.parquet', columns=['id','street','number','unit','geometry']).to_pylist()
    per_building = {}
    unresolved = 0
    for address in addresses:
        if not address.get('geometry'):
            continue
        found = tree.query(shapely.from_wkb(address['geometry']), predicate='covered_by')
        if len(found) == 1:
            per_building.setdefault(int(found[0]), []).append(address)
        else:
            unresolved += 1
    boundary_file = ROOT / 'cities' / city / 'boundary.geojson'
    boundary = None
    if city == 'velesin' and boundary_file.exists():
        boundary = shapely.union_all([shape(f['geometry']) for f in read(boundary_file)['features']])
    transform = Transformer.from_crs(4326,5514,always_xy=True).transform
    _, source = prep.source_inventory()
    available = coverage(source['tiles'])
    features, protected, excluded = [], [], []
    for i, (row, wgs) in enumerate(zip(rows, polygons)):
        if boundary is not None and not boundary.intersects(wgs):
            excluded.append({'id':row['id'],'reason':'outside_municipality_boundary'})
            continue
        if city == 'velesin' and row['id'] == SPORTCENTRUM:
            protected.append({'id':row['id'],'reason':'signature_model_preserved',
                'model':'cities/velesin/assets/models/sportcentrum-velesin.json'})
            continue
        poly = shapely.transform(wgs, transform, interleaved=False)
        if not list(prep.polygon_parts(poly)):
            excluded.append({'id':row['id'],'reason':'no_polygonal_footprint'})
            continue
        address_rows = per_building.get(i, [])
        labels = sorted({prep.address_label(a) for a in address_rows})
        streets = sorted({a.get('street') or '' for a in address_rows})
        stage, priority = stage_for(city, streets)
        label = labels[0] if labels else (row.get('names') or {}).get('primary') or row['id']
        properties = {'name':label,'address':labels[0] if labels else None,'other_addresses':labels[1:],
            'requested_addresses':labels,'streets':streets,'stage':stage,'street_priority':priority,
            'role':'city_queue','category':stage,'lon':wgs.centroid.x,'lat':wgs.centroid.y,
            'footprint_area_m2':poly.area,'coverage_complete':available.covers(poly.buffer(prep.BUFFER)),
            'source_attributes':{k:row.get(k) for k in ('class','subtype','height','num_floors','roof_shape',
                'roof_height','roof_color','facade_color','roof_material','has_parts')},
            'footprint_sources':row.get('sources')}
        features.append({'type':'Feature','id':row['id'],'geometry':mapping(poly),'properties':properties})
    # Priority street order is stable; extra CB houses follow a reproducible hash.
    features.sort(key=lambda f:(f['properties']['street_priority'],
        hashlib.sha256(('night-roofs-20261117'+f['id']).encode()).hexdigest()))
    counts = {stage:sum(f['properties']['stage']==stage for f in features)
              for stage in ('streets','city','centre','extra')}
    result={'schema':'night-roof-queue/1','type':'FeatureCollection','city':city,'crs':'EPSG:5514',
        'created_at_utc':prep.utc(),'data_directory':prep.rel(data),'source_manifest':prep.rel(prep.SOURCE_MANIFEST),
        'features':features,'counts':counts,'protected':protected,'excluded':excluded,
        'cached_dense_coverage':sum(f['properties']['coverage_complete'] for f in features),
        'unresolved_address_points':unresolved,'source_policy':POLICY,
        'scope':'All cached municipality footprints' if boundary is not None else 'All locally cached city footprints',
        'source_files':[prep.file_record(data/'building.parquet',True),prep.file_record(data/'address.parquet',True)]}
    write(output/'queue.json',result)
    write(output/'sample.json',result)
    return result


def compatible_crop(feature, building):
    """Compare actual global footprints, never just an ID or address."""
    try:
        if not building.get('parts') or any(p.get('status') != 'prepared' for p in building['parts']):
            return False
        stored = shapely.union_all([translate(shape(p['footprint']),*p['origin_xy']) for p in building['parts']])
        current = shape(feature['geometry'])
        return stored.hausdorff_distance(current) < 1e-5 and stored.symmetric_difference(current).area < 1e-4
    except (KeyError, ValueError):
        return False


def reusable_inputs(city, features):
    wanted={f['id']:f for f in features}
    found={}
    directory=ROOT/'cities'/city/'experiments'
    paths=sorted(directory.glob('*/inputs.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in paths:
        try:
            doc=read(path)
            if doc.get('city')!=city or doc.get('source')!='dmpok':
                continue
            base=path.parent if doc.get('cache_path_base')=='manifest_directory' else ROOT
            for building in doc.get('buildings',[]):
                oid=building['id']
                if oid not in wanted or oid in found or not compatible_crop(wanted[oid],building):
                    continue
                item=copy.deepcopy(building)
                valid=True
                for part in item['parts']:
                    cache=part['cache'];p=(base/cache['path']).resolve()
                    if not p.is_file() or p.stat().st_size!=cache['bytes'] or guard.sha256(p)!=cache['sha256']:
                        valid=False;break
                    cache['path']=prep.rel(p)
                if valid:
                    item['reused_from_manifest']=prep.rel(path)
                    found[oid]=item
        except (OSError,ValueError,KeyError):
            continue
    return found


def restore_spool(directory, committed):
    """Truncate uncommitted bytes after interruption; makes stream resume exact."""
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    for path in directory.glob('*.bin'):
        size=committed.get(path.name,0)
        if path.stat().st_size<size:
            raise ValueError('Point spool is shorter than its committed checkpoint: '+str(path))
        with path.open('r+b') as stream:
            stream.truncate(size)


def stream_crops(features, tiles, folder, deadline=None):
    """MODULE extraction: one serial LAZ pass, bounded chunks and per-house files."""
    folder=Path(folder);spool=folder/'spool';spool.mkdir(parents=True,exist_ok=True)
    checkpoint=folder/'stream.json'
    polys=[shape(f['geometry']) for f in features]
    buffers=[p.buffer(20) for p in polys]
    index=shapely.STRtree(buffers)
    identity=hashlib.sha256(json.dumps({'ids':[f['id'] for f in features],
        'geometry':[f['geometry'] for f in features],'tiles':[t['file'] for t in tiles],
        'policy':POLICY},sort_keys=True).encode()).hexdigest()
    state=read(checkpoint) if checkpoint.exists() else {'identity':identity,'tile':0,'processed':0,'sizes':{},'active_seconds':0}
    if state['identity']!=identity:
        raise ValueError('Frozen stream inputs changed; choose another output folder')
    restore_spool(spool,state['sizes'])
    started=time.perf_counter();prior=state['active_seconds']
    def save():
        state['active_seconds']=prior+time.perf_counter()-started
        write(checkpoint,state)
    for ti in range(state['tile'],len(tiles)):
        tile=tiles[ti];tile_region=tile_polygon(tile)
        if not len(index.query(tile_region)):
            state.update(tile=ti+1,processed=0);save();continue
        print(json.dumps({'event':'point_tile','sheet':tile.get('sheet'),'resume':state['processed'] if ti==state['tile'] else 0}),flush=True)
        processed=state['processed'] if ti==state['tile'] else 0
        with laspy.open(ROOT/tile['file']['path'],laz_backend=laspy.LazBackend.Lazrs) as reader:
            if processed:reader.seek(processed)
            last_save=processed
            for chunk in reader.chunk_iterator(prep.CHUNK):
                if expired(deadline):
                    save();return False,state
                prep.resource_check()
                x,y,c=np.asarray(chunk.x),np.asarray(chunk.y),np.asarray(chunk.classification)
                # Stable world-XY sampling bounds duplicated ground-ring storage.
                xi=np.rint(x*100).astype(np.int64);yi=np.rint(y*100).astype(np.int64)
                ground=(c==2)&(((xi*73856093)^(yi*19349663))%16==0)
                chosen=np.flatnonzero((c==6)|ground)
                if len(chosen):
                    x,y,c=x[chosen],y[chosen],c[chosen];z=np.asarray(chunk.z)[chosen]
                    block_box=shapely.box(float(x.min()),float(y.min()),float(x.max()),float(y.max()))
                    for raw_i in index.query(block_box):
                        i=int(raw_i);poly=polys[i];buf=buffers[i]
                        lo_x,lo_y,hi_x,hi_y=buf.bounds
                        near=np.flatnonzero((x>=lo_x)&(x<=hi_x)&(y>=lo_y)&(y<=hi_y))
                        if not len(near):continue
                        xx,yy,cc=x[near],y[near],c[near]
                        keep=((cc==6)&shapely.contains_xy(poly,xx,yy))|((cc==2)&shapely.contains_xy(buf,xx,yy))
                        near=near[keep]
                        if not len(near):continue
                        values=np.empty(len(near),dtype=RAW_DTYPE)
                        for name,arr in [('x',x),('y',y),('z',z),('c',c)]:values[name]=arr[near]
                        path=spool/(features[i]['id']+'.bin')
                        new_size=state['sizes'].get(path.name,0)+values.nbytes
                        if new_size>150_000_000:
                            raise guard.ResourceLimit('Single-building raw crop exceeds 150 MB: '+features[i]['id'])
                        guard.check_budget(reserve_bytes=values.nbytes)
                        with path.open('ab') as out:values.tofile(out)
                        state['sizes'][path.name]=new_size
                processed+=len(chunk);state.update(tile=ti,processed=processed)
                if processed-last_save>=1_000_000:
                    save();last_save=processed
            state.update(tile=ti+1,processed=0);save()
    state['complete']=True;save()
    return True,state


def finish_building(feature, spool, cache):
    """MODULE normalization: original roof points, ground datum and stable holdout."""
    path=Path(spool)/(feature['id']+'.bin')
    raw=np.fromfile(path,dtype=RAW_DTYPE) if path.exists() else np.empty(0,dtype=RAW_DTYPE)
    xyz=np.column_stack((raw['x'],raw['y'],raw['z']));cls=raw['c']
    props=feature['properties']
    building={k:props.get(k) for k in ('name','address','lon','lat','source_attributes','footprint_sources','requested_addresses')}
    building.update(id=feature['id'],source='dmpok',selection={'role':'city_queue','category':props['stage']},parts=[])
    for pi,poly in enumerate(sorted(prep.polygon_parts(shape(feature['geometry'])),key=lambda p:(-p.area,p.bounds))):
        roof=xyz[(cls==6)&shapely.contains_xy(poly,xyz[:,0],xyz[:,1])]
        roof,_,removed=prep.unique_points(roof,np.full(len(roof),6,dtype=np.uint8))
        ground=np.empty((0,3))
        for radius in (6,12,20):
            ring=poly.buffer(radius).difference(poly.buffer(1))
            ground=xyz[(cls==2)&shapely.contains_xy(ring,xyz[:,0],xyz[:,1])]
            if len(ground)>=5:break
        if len(ground)<5:
            building['parts'].append({'part_index':pi,'status':'missing_ground_reference',
                'ground_source':{'method':'class2_median_external_annulus_hash16','points':len(ground)}})
            continue
        ground_z=float(np.median(ground[:,2]));origin=np.array([poly.centroid.x,poly.centroid.y])
        relative=roof-np.array([*origin,ground_z]);held=prep.split_points(roof)
        dest=Path(cache)/(feature['id']+'-'+str(pi)+'.npz');dest.parent.mkdir(parents=True,exist_ok=True)
        temp=dest.with_suffix('.npz.tmp');guard.check_budget(reserve_bytes=relative.nbytes+1_000_000)
        with temp.open('wb') as handle:np.savez_compressed(handle,train=relative[~held],holdout=relative[held])
        temp.replace(dest)
        building['parts'].append({'part_index':pi,'status':'prepared' if len(roof) else 'no_roof_points',
            'origin_xy':origin.tolist(),'ground_z':ground_z,'footprint':mapping(translate(poly,-origin[0],-origin[1])),
            'cache':prep.file_record(dest,True),'ground_source':{'method':'class2_median_external_annulus_hash16',
                'points':len(ground),'radius_m':radius,'inner_exclusion_m':1,'sampling_fraction':1/16,
                'p10_m':float(np.quantile(ground[:,2],.1)),'p90_m':float(np.quantile(ground[:,2],.9))},
            'measurement':{'roof_points':len(roof),'train_points':int((~held).sum()),'holdout_points':int(held.sum()),
                'footprint_area_m2':poly.area,'roof_points_per_m2':len(roof)/poly.area,'exact_duplicate_points_removed':removed},
            'input_mode':'night_serial_full_laz'})
    return building


def prepare(queue_path, output, stage='all', download_missing=False, deadline=None):
    queue=read(queue_path);city=queue['city'];prep.configure_city(city)
    folder=Path(output).resolve();folder.mkdir(parents=True,exist_ok=True)
    selected=[f for f in queue['features'] if stage=='all' or f['properties']['stage']==stage]
    signature=hashlib.sha256(json.dumps({'features':selected,'policy':POLICY},sort_keys=True).encode()).hexdigest()
    if (folder/'inputs.json').exists():
        saved=read(folder/'inputs.json')
        if saved.get('sample_sha256')!=signature:raise ValueError('Input selection changed')
        if saved.get('preparation_status')=='complete':return saved
    start=time.perf_counter();_,source=prep.source_inventory();tiles=copy.deepcopy(source['tiles'])
    source_extra=folder/'additional-source-tiles.json'
    shared_tiles=ROOT/'.work'/'night-roof-sources'/city/'tiles.json'
    for registry in (shared_tiles, source_extra):
        if registry.exists():
            known={t['file']['path'] for t in tiles}
            for tile in read(registry)['tiles']:
                path=ROOT/tile['file']['path']
                if tile['file']['path'] not in known and path.is_file() and path.stat().st_size==tile['file']['bytes']:
                    tiles.append(tile);known.add(tile['file']['path'])
    cov=coverage(tiles);missing=[f for f in selected if not cov.covers(shape(f['geometry']).buffer(20))]
    download_error=None
    if missing and download_missing and not expired(deadline):
        try:
            import roof_pilot_sources as sources
            # Existing bounded downloader preserves cache and enforces project/disk limits.
            sources.SOURCE_DIR=ROOT/'.work'/'night-roof-sources'/city
            sources.MASTER_FEED=ROOT/'.work'/'roof-pilot'/'sources'/'dmpok-atom.xml'
            region=shapely.union_all([shape(f['geometry']).buffer(20) for f in missing])
            # Exclude cached sheets so existing source LAZ are not duplicated.
            old_select=sources.selected_dmpok_entries
            cached_sheets={t.get('sheet') for t in tiles}
            sources.selected_dmpok_entries=lambda union:[e for e in old_select(union) if e['sheet'] not in cached_sheets]
            try:
                # Retry only transient network failures, at most twice. Disk/RAM
                # limits, corrupt files and permanent HTTP errors never retry.
                for attempt in range(3):
                    try:
                        extra,timing=sources.prepare_dmpok(region)
                        break
                    except guard.ResourceLimit:
                        raise
                    except Exception as exc:
                        if attempt>=2 or not transient_download_error(exc) or expired(deadline):
                            raise
                        print(json.dumps({'event':'download_retry','attempt':attempt+1,
                            'error_type':type(exc).__name__,'message':str(exc)}),flush=True)
                        time.sleep(2*(attempt+1))
            finally:sources.selected_dmpok_entries=old_select
            write(source_extra,{'tiles':extra,'timing':timing});tiles+=extra;cov=coverage(tiles)
            write(shared_tiles,{'tiles':tiles,'updated_at_utc':prep.utc()})
        except guard.ResourceLimit:raise
        except Exception as exc:download_error={'type':type(exc).__name__,'message':str(exc)}
    excluded=[{'id':f['id'],'address':f['properties']['address'],'reason':'dense_coverage_unavailable'}
              for f in selected if not cov.covers(shape(f['geometry']).buffer(20))]
    excluded_ids={x['id'] for x in excluded};eligible=[f for f in selected if f['id'] not in excluded_ids]
    reuse_file=folder/'reused-inputs.json'
    if reuse_file.exists():reused=read(reuse_file)
    else:
        reused=reusable_inputs(city,eligible);write(reuse_file,reused)
    pending=[f for f in eligible if f['id'] not in reused]
    complete,stream=(True,{'active_seconds':0}) if not pending else stream_crops(pending,tiles,folder,deadline)
    buildings=[]
    item_dir=folder/'prepared';item_dir.mkdir(exist_ok=True)
    if complete:
        for feature in eligible:
            if expired(deadline):complete=False;break
            prep.resource_check();oid=feature['id'];record=item_dir/(oid+'.json')
            if record.exists():building=read(record)
            elif oid in reused:building=reused[oid];write(record,building)
            else:building=finish_building(feature,folder/'spool',folder/'point-clouds');write(record,building)
            buildings.append(building)
    else:
        for feature in eligible:
            record=item_dir/(feature['id']+'.json')
            if record.exists():buildings.append(read(record))
    result={'schema':'roof-v2-inputs/1','city':city,'source':'dmpok','crs':'EPSG:5514','vertical_datum':'Bpv',
        'created_at_utc':prep.utc(),'sample_sha256':signature,'source_manifest':queue['source_manifest'],
        'input_data_directory':queue['data_directory'],'source_tiles':tiles,'buildings':buildings,
        'preparation_status':'complete' if complete else 'paused','stage':stage,'source_policy':POLICY,
        'requested_count':len(selected),'excluded':excluded,'protected':queue.get('protected',[]),
        'reused_count':sum(b['id'] in reused for b in buildings),'download_error':download_error,
        'split':{'method':'centimetre world XY uint64 hash modulo5; bin0 holdout','heldout_fraction_target':.2},
        'ground_policy':'Class2 deterministic centimetre-XY hash modulo16 then median exterior1-6/12/20m annulus; reused crops retain their recorded policy.',
        'timing':{'wall_seconds':time.perf_counter()-start,'point_stream_seconds':stream.get('active_seconds',0)}}
    write(folder/'inputs.json',result)
    write(folder/'preparation.json',{k:v for k,v in result.items() if k not in ('buildings','source_tiles')})
    # The committed NPZ files replace this worker's reproducible intermediate
    # spool. Delete only exact generated files after the complete manifest exists.
    if complete:
        spool_root=(folder/'spool').resolve()
        for feature in pending:
            temporary=(spool_root/(feature['id']+'.bin')).resolve()
            if temporary.parent != spool_root:
                raise ValueError('Invalid source identifier for point spool')
            if temporary.is_file():temporary.unlink()
    print(json.dumps({'event':'inputs_finished','status':result['preparation_status'],'city':city,'stage':stage,
        'prepared':len(buildings),'excluded':len(excluded),'reused':result['reused_count'],'seconds':result['timing']['wall_seconds']}),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);actions=parser.add_subparsers(dest='action',required=True)
    planning=actions.add_parser('plan');planning.add_argument('--city',choices=prep.SUPPORTED_CITIES,required=True);planning.add_argument('--output',type=Path,required=True)
    preparing=actions.add_parser('prepare');preparing.add_argument('--plan',type=Path,required=True);preparing.add_argument('--output',type=Path,required=True)
    preparing.add_argument('--stage',choices=['all','streets','city','centre','extra'],default='all');preparing.add_argument('--download-missing',action='store_true');preparing.add_argument('--deadline-utc')
    args=parser.parse_args()
    with guard.keep_awake():
        prep.resource_check()
        if args.action=='plan':
            result=plan(args.city,args.output);print(json.dumps({'city':args.city,'counts':result['counts'],'cached_dense_coverage':result['cached_dense_coverage'],'protected':len(result['protected'])}),flush=True)
        else:
            deadline=datetime.fromisoformat(args.deadline_utc.replace('Z','+00:00')).timestamp() if args.deadline_utc else None
            prepare(args.plan,args.output,args.stage,args.download_missing,deadline)


if __name__=='__main__':main()
