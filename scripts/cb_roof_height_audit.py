"""Trace actual preview roof/wall decisions for a fixed, separate 12-case audit.

Reads only existing source tables and generated scene; no renderer mutations.
Run under resource_guard. The selected cases are not a new city-wide sample.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
import io
from pathlib import Path
import sys
import time
import unittest
from collections import Counter
import numpy as np
from pyproj import Transformer
import pyarrow.parquet as pq
import shapely
from shapely.geometry import mapping, Polygon, Point
import resource_guard as guard

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work/.preview/ceske-budejovice'
DEST = ROOT / 'cities/ceske-budejovice/experiments/roof-heights'
AUDIT = ROOT / '.work/cb-roof-heights'
sys.path.insert(0, str(ROOT))
CASES = [
 ('9e12c98b-650e-42cb-be78-330800d0130a','marianske','five_levels_forced_flat'),
 ('703989e7-ed6e-4fe0-af7f-2e333d74f71f','marianske','five_levels_forced_flat'),
 ('6ce5e9b9-c892-42db-8a47-4c9f2d05ad8b','marianske','apartments_forced_flat'),
 ('e397e532-bd55-406e-bb91-450db3305934','marianske','large_compound_footprint'),
 ('4360399b-b4fe-442c-aebf-299791112d22','nearby_regression_control','explicit_gabled_overwritten_by_floors'),
 ('478f9384-0414-4c4d-99af-fa0c89f059fc','premysla','retail_forced_flat'),
 ('02e3ff25-6457-45de-9102-f37f158751ec','premysla','retail_forced_flat'),
 ('e3c6d4cb-3381-4a3b-8e04-20840916fa8e','premysla','apartments_forced_flat'),
 ('8f1c02d0-e10d-4a71-9332-840a68b6d75b','premysla','large_compound_footprint'),
 ('0ba58b9f-b4cc-41a1-857b-005b6227282d','premysla','existing_pitched_control'),
 ('e8ed1629-4536-4975-9f07-c129bc7b0d6a','premysla','bank_flat_control'),
 ('099a5e53-02a4-4b93-a6a7-0123062e381f','high_flat_control','explicit_flat_control'),
]
FLAT_CLASSES = {'garage','garages','apartments','industrial','warehouse','commercial','retail',
 'school','university','hospital','office','carport','parking','service','transportation',
 'sports_hall','sports_centre','greenhouse','roof'}
ROOF_MAP = {'gabled':'gabled','hipped':'hipped','half_hipped':'hipped','pyramidal':'pyramidal',
 'saltbox':'gabled','gambrel':'gabled','skillion':'gabled','mansard':'hipped','flat':'flat',
 'round':'flat','dome':'pyramidal'}

def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 part=p.with_suffix(p.suffix+'.partial')
 part.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');part.replace(p)
def fingerprint(p):
 p=Path(p);return {'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,
                    'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

def wall_window_rows(height,style):
 """Count shader bands that intersect the positive-height wall; not real floors."""
 spacing,lo,hi={0:(2.9,.9,2.2),1:(2.8,.8,2.2),3:(4.2,2.4,3.6),11:(3.2,.95,2.5)}.get(style,(None,None,None))
 if spacing is None:return None
 return sum(1 for i in range(max(0,math.ceil(height/spacing))) if i*spacing+lo<height and i*spacing+hi>0)

def execute():
 start=time.perf_counter();guard.check_budget(force=True)
 wanted={x[0] for x in CASES}
 columns=['id','geometry','names','sources','class','num_floors','height','roof_shape','roof_height',
          'roof_direction','roof_orientation','has_parts','min_height','min_floor']
 rows=pq.read_table(WORK/'data/building.parquet',columns=columns).to_pylist()
 raw={r['id']:r for r in rows};info=read(WORK/'build/info_src.json')['buildings']
 infos={r['oid']:r for r in info};scene=read(WORK/'build/scene.json')
 objects={b['id']:b for b in scene['buildings']};dmp=read(WORK/'assets/dmp_vysky.json');diagnostic=read(WORK/'build/dmp_vysky.json')
 project=Transformer.from_crs(4326,5514,always_xy=True).transform
 features=[];traces=[]
 for index,(bid,area_name,case) in enumerate(CASES,1):
  r=raw[bid];i=infos[bid];b=objects[i['id']];p=Polygon(b['p']);measured=dmp.get(bid);mapped=ROOF_MAP.get(r['roof_shape'])
  height=round(b['e']-b['g'],3);floors=r['num_floors'];hgt=r['height'];cls=r['class'] or ''
  flags={
   'source_roof_recognized':mapped,
   'high_or_apartments_rule':bool(cls=='apartments' or (floors and floors>=5) or (hgt and hgt>=14)),
   'urban_tenement_branch_enabled':False,
   'urban_reason':'All selected centroids are in chunk(0,0); legacy URBAN := chunk != (0,0).',
   'dmp_flat_04_rule':bool(measured and p.area>80 and measured[0]>=6 and measured[1]-measured[0]<.4),
   'dmp_flat_035_rule':bool(measured and p.area>=25 and measured[0]>=2.2 and measured[1]-measured[0]<.35),
   'fallback_flat_class':cls in FLAT_CLASSES,
   'fallback_area_over650':p.area>650,
   'explicit_pitched_attribute_lost':mapped not in (None,'flat') and b['r']=='flat',
   'flat_wall_uses_roof_median':bool(measured and b['r']=='flat' and abs(height-measured[0])<=.02),
  }
  attrs={k:v for k,v in r.items() if k not in ('geometry','id')}
  feature={'type':'Feature','id':bid,'geometry':mapping(shapely.from_wkb(r['geometry'])),
   'properties':{'id':bid,'pilot_id':f'CB-HEIGHT-{index:02d}','name':'; '.join(i['addr']) or i.get('name') or bid,
    'area':area_name,'case':case,'category':case,'source_attributes':attrs,'scene_id':i['id'],'addresses':i['addr'],
    'longitude':i['lon'],'latitude':i['lat'],'not_part_of_fixed_roof_pilot':True}}
  features.append(feature)
  traces.append({'id':bid,'pilot_id':feature['properties']['pilot_id'],'name':feature['properties']['name'],
    'area':area_name,'case':case,'source_attributes':attrs,
    'source_geometry_area_m2':round(shapely.transform(shapely.from_wkb(r['geometry']),project,interleaved=False).area,2),
    'source_geometry_area_crs':'EPSG:5514','baseline_scene_footprint_area_m2':round(p.area,2),
    'dmp':{'accepted_median_p90_m':measured,'diagnostic_row':diagnostic.get(bid),
           'percentile_spread_m':round(measured[1]-measured[0],3) if measured else None,
           'interpretation':'Median and P90 of all class6 roof points above ground; median is not an eave measurement.'},
    'rule_flags':flags,'baseline_scene':b,'baseline':{'roof':b['r'],'wall_height_m':height,
       'roof_height_m':b['rh'],'total_m':round(height+b['rh'],3),'style':b['s'],
       'shader_window_bands':wall_window_rows(height,b['s']),'parts':len(b['parts']),
       'not_true_floor_count':True}})
 square=[i for i in info if any('Přemysla Otakara' in a for a in i.get('addr',[]))]
 lost=[i for i in info if ROOF_MAP.get(raw[i['oid']]['roof_shape']) not in (None,'flat') and objects[i['id']]['r']=='flat']
 sample={'type':'FeatureCollection','schema':'roof-height-audit-sample/1','city':'ceske-budejovice',
         'features':features,'scope':'Separate diagnostic sample; fixed30 benchmark and18 detail candidates unchanged.'}
 write(DEST/'sample.json',sample)
 result={'schema':'roof-height-audit/1','city':'ceske-budejovice','created_at':datetime.now(timezone.utc).isoformat(),
   'status':'baseline_trace_complete_correction_pending','sample_count':len(traces),'traces':traces,
   'summary':{'square_address_footprints':len({i['oid'] for i in square}),
     'square_flat_footprints':len({i['oid'] for i in square if objects[i['id']]['r']=='flat'}),
     'city_explicit_pitched_mapped_to_flat':len({i['oid'] for i in lost}),
     'audit_explicit_pitched_lost':sum(t['rule_flags']['explicit_pitched_attribute_lost'] for t in traces),
     'audit_flat_walls_using_roof_median':sum(t['rule_flags']['flat_wall_uses_roof_median'] for t in traces)},
   'code_findings':[
    {'file':'prep.py','line':1180,'issue':'class apartments / floors>=5 / height>=14 overwrites an explicit pitched roof attribute.'},
    {'file':'prep.py','line':1155,'issue':'URBAN depends on tile index; historical tenement rescue is disabled in centre tile(0,0).'},
    {'file':'prep.py','line':1212,'issue':'Missing roof type defaults to flat for retail/office and footprints over650m2.'},
    {'file':'prep.py','line':1253,'issue':'For a chosen flat roof, class6 roof median becomes wall height; not a measured eave.'},
    {'file':'render.html','line':261,'issue':'Style1 repeats window bands every2.8m irrespective of actual source floor count or attic levels.'}],
   'source_files':[fingerprint(WORK/p) for p in ['data/building.parquet','build/info_src.json','build/scene.json','assets/dmp_vysky.json','build/dmp_vysky.json']],
   'code_files':[fingerprint(ROOT/p) for p in ['prep.py','render.html','dmp_vysky.py']],
   'references':[
    {'url':'https://www.encyklopedie.c-budejovice.cz/clanek/namesti-premysla-otakara-ii','supports':'Historic roofscape, later longitudinal roofs and functionalist bank exception; not per-building dimensions.'},
    {'url':'https://www.npu.cz/uop/ceske-budejovice/vystavy/moderni-architektura/vystava_moderna_web.pdf','supports':'Bank at U Černé věže čp69 is Českobudějovická záložna1934–1936.'},
    {'url':'https://www.marianska.org/o-pasazi','supports':'Former Mariánská barracks with modern parking addition; complex footprint must not be forced to one roof.'}],
   'notes':['User3+2 floors is a diagnostic hypothesis, not substituted as ground truth.',
    'P90-minus-median spread alone cannot distinguish a pitched roof from multiple flat roof levels.',
    'Historical rows and modern flat controls require spatial roof fitting and/or independent photograph evidence.',
    'No shared renderer code, city assets or generated preview were changed by this audit.'],
   'elapsed_seconds':time.perf_counter()-start}
 write(DEST/'results.json',result)
 print(json.dumps(result['summary'],ensure_ascii=False),flush=True)

def policy_preview():
 """Execute the actual geometry/height blocks on frozen baseline footprints."""
 from nastroje.roof_policy import resolve_roof_shape
 from tests.test_roof_policy import HEIGHT
 start=time.perf_counter();guard.check_budget(force=True)
 result=read(DEST/'results.json');tree=ast.parse((ROOT/'prep.py').read_text(encoding='utf8'))
 defs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('max_rect','roof_parts')]
 globals_={'np':np,'shapely':shapely,'math':math,'Point':Point}
 exec(compile(ast.Module(body=defs,type_ignores=[]),'prep.py:roof-functions','exec'),globals_)
 def assigned(n,name):
  return isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets)
 for node in ast.walk(tree):
  body=getattr(node,'body',None)
  if isinstance(body,list) and any(assigned(n,'source_roof') for n in body):
   first=next(i for i,n in enumerate(body) if assigned(n,'obb'))
   last=next(i for i,n in enumerate(body[first:],first) if assigned(n,'roofh'))
   geometry_code=compile(ast.Module(body=body[first:last+1],type_ignores=[]),'prep.py:roof-geometry','exec')
   break
 from types import SimpleNamespace
 predictions=[]
 for trace in result['traces']:
  baseline=trace['baseline'];flags=trace['rule_flags'];scene=trace['baseline_scene']
  shape=resolve_roof_shape(flags['source_roof_recognized'],baseline['roof'],
      flat_surface_evidence=flags['dmp_flat_04_rule'] or flags['dmp_flat_035_rule'])
  after=dict(baseline);parts=scene['parts']
  if shape!=baseline['roof']:
   polygon=Polygon(scene['p']);context=dict(globals_,p=polygon,area=polygon.area,rs=shape,
      r=SimpleNamespace(id=trace['id']),HREBENY=read(WORK/'assets/hrebeny.json') if (WORK/'assets/hrebeny.json').exists() else {})
   exec(geometry_code,context)
   context.update(DMP={trace['id']:trace['dmp']['accepted_median_p90_m']},dsp=None,lm=None,
     c=trace['source_attributes']['class'],panel=False,total=0,eave=0)
   exec(HEIGHT,context)
   after.update(roof=context['rs'],wall_height_m=round(context['eave'],3),roof_height_m=round(context['roofh'],3),
     total_m=round(context['eave']+context['roofh'],3),parts=len(context['parts']),
     shader_window_bands=wall_window_rows(context['eave'],baseline['style']))
   parts=context['parts']
  predictions.append({'id':trace['id'],'name':trace['name'],'before':baseline,'after':after,'parts':parts,
    'changed':after!=baseline,'status':'isolated_policy_preview_not_rendered',
    'precision_note':'Uses baseline scene footprint rounded to centimetres; full prep result may differ slightly.'})
 stream=io.StringIO();test_start=time.perf_counter()
 suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_roof_policy')
 check=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
 AUDIT.mkdir(parents=True,exist_ok=True);(AUDIT/'policy-tests.txt').write_text(stream.getvalue(),encoding='utf8')
 result['policy_preview']={'status':'isolated_blocks_passed_full_render_pending','rows':predictions,
  'changed_count':sum(r['changed'] for r in predictions),'elapsed_seconds':time.perf_counter()-start,
  'tests':{'run':check.testsRun,'failures':len(check.failures),'errors':len(check.errors),'passed':check.wasSuccessful(),
    'elapsed_seconds':time.perf_counter()-test_start,'log':'.work/cb-roof-heights/policy-tests.txt'},
  'code_files':[fingerprint(ROOT/f) for f in ['prep.py','nastroje/roof_policy.py','tests/test_roof_policy.py']],
  'priority':'Manual DOM/SAT after policy > existing near-horizontal DMP evidence > explicit mapped source shape > legacy heuristic.',
  'limits':['Unknown shapes remain under existing fallbacks; no mass replacement with gabled.',
    'The existing DMP flat priority may conflict with source tags; it is not external ground truth.',
    'Source-shape resolution is tile independent; the legacy unknown-shape heuristic still depends on URBAN.',
    'Geometric40degree/max7m roof remains a fallback, not fitted eave/ridge measurements.']}
 result['status']='policy_fixed_and_unit_tested_full_render_and_fits_pending'
 write(DEST/'results.json',result)
 print(json.dumps({'changed':result['policy_preview']['changed_count'],'tests':result['policy_preview']['tests']},ensure_ascii=False))
 if not check.wasSuccessful():raise RuntimeError('Roof policy regressions failed')

def crop_sources():
 """Read existing LAZ tiles once per source; never download or alter them."""
 import roof_pilot_sources as sources
 start=time.perf_counter();guard.check_budget(force=True)
 source_manifest=read(ROOT/'.work/cb-roof-pilot/sources/sources.json')
 sample=read(DEST/'sample.json')
 for feature in sample['features']:
  feature['properties']['category']=feature['properties']['case']
 write(DEST/'sample.json',sample)
 manifest_path=AUDIT/'sources.json';sample_hash=fingerprint(DEST/'sample.json')
 if manifest_path.exists():
  manifest=read(manifest_path)
  if manifest['sample_file']!=sample_hash:raise ValueError('Audit crop sample changed')
 else:
  manifest={'schema_version':1,'scope':'Separate12 roof-height diagnostics; no original30 IDs changed.',
    'sample_file':sample_hash,'sources':{},'crs':'EPSG:5514','vertical_datum':'Bpv',
    'parent_manifest':fingerprint(ROOT/'.work/cb-roof-pilot/sources/sources.json')}
 sources.CROP_DIR=AUDIT/'crops'
 buildings,union=sources.sample_geometry(DEST/'sample.json')
 for name in ('dmp1g','dmpok'):
  if name in manifest['sources']:
   existing=manifest['sources'][name]
   if fingerprint(ROOT/existing['crop_path'])!=existing['crop_file']:raise ValueError('Changed audit crop')
   continue
  tiles=json.loads(json.dumps(source_manifest['sources'][name]['tiles']))
  for tile in tiles:
   path=ROOT/tile['file']['path']
   if path.stat().st_size!=tile['file']['bytes']:raise ValueError('Changed original LAZ size: '+str(path))
  crop=sources.crop_source(name,tiles,buildings,union)
  manifest['sources'][name]={'tiles':tiles,**crop,'downloaded_for_audit':False}
  manifest['elapsed_seconds']=time.perf_counter()-start
  write(manifest_path,manifest)
 print(json.dumps({'event':'audit_crops_complete','sources':list(manifest['sources']),
   'seconds':time.perf_counter()-start}),flush=True)

def fit_sources():
 """Run existing bounded algorithms on the separate12 diagnostic sample."""
 import roof_pilot as shared
 shared.WORK=AUDIT;shared.DEST=DEST;shared.SAMPLE=DEST/'sample.json';shared.MANIFEST=AUDIT/'sources.json'
 start=time.perf_counter();guard.check_budget(force=True)
 manifest=read(shared.MANIFEST)
 if manifest['sample_file']!=fingerprint(shared.SAMPLE):raise ValueError('Crop sample mismatch')
 all_runs=[];batches={};observations=[]
 frozen={t['id']:t for t in read(DEST/'results.json')['traces']}
 href=read(ROOT/'cities/ceske-budejovice/mesto.json')['href']
 for source in ('dmp1g','dmpok'):
  xyz,classes,holdout=shared.load_source(source)
  for feature,poly in shared.samples():
   guard.check_budget()
   roof=xyz[(classes==6)&shapely.contains_xy(poly,xyz[:,0],xyz[:,1]),2]
   ring14=shapely.difference(shapely.buffer(poly,14),shapely.buffer(poly,1));ring20=poly.buffer(20).difference(poly)
   ground14=xyz[(classes==2)&shapely.contains_xy(ring14,xyz[:,0],xyz[:,1]),2]
   ground20=xyz[(classes==2)&shapely.contains_xy(ring20,xyz[:,0],xyz[:,1]),2]
   g14=float(np.median(ground14)) if len(ground14) else None
   g20=float(np.median(ground20)) if len(ground20) else None
   scene_ground=frozen[feature['id']]['baseline_scene']['g']+href
   observations.append({'source':source,'id':feature['id'],'roof_class6_points':len(roof),
    'roof_absolute_bpv_percentiles':dict(zip(['p05','p10','p50','p90','p95','p99'],map(float,np.percentile(roof,[5,10,50,90,95,99])))) if len(roof) else {},
    'ground14_bpv_m':g14,'ground14_points':len(ground14),'ground20_bpv_m':g20,'ground20_points':len(ground20),
    'scene_ground_plus_href_m':round(scene_ground,3),
    'scene_minus_ground14_m':round(scene_ground-g14,3) if g14 is not None else None,
    'note':'Scene terrain comes from Terrarium; the numerical offset is not a surveyed vertical-datum correction.'})
  del xyz,classes,holdout
  for method in ('baseline','templates','roofer'):
   guard.check_budget(force=True)
   if method=='roofer':shared.roofer_worker(source)
   else:shared.template_worker(source,method,repetitions=3)
   output=read(AUDIT/f'{source}-{method}.json')
   for run in output['runs']:
    model=run.get('model') or {};vertices=np.asarray(model.get('vertices',[]),dtype=float)
    if vertices.size:
     roof_indices=set()
     for face,semantic in zip(model.get('faces',[]),model.get('face_semantics',[])):
      if semantic=='roof':roof_indices.update(face)
     heights=vertices[list(roof_indices),2] if roof_indices else np.empty(0)
     run['height_diagnostics']={'ground_z_bpv':run['ground_z'],
       'roof_vertex_min_above_ground_m':float(heights.min()) if len(heights) else None,
       'roof_vertex_max_above_ground_m':float(heights.max()) if len(heights) else None,
       'interpretation':'Roof vertex minimum is model geometry, not independently surveyed eave; compound roofs have several eaves.'}
    all_runs.append(run)
   if output.get('batch_metrics'):batches[source]=output['batch_metrics']
 result=read(DEST/'results.json')
 result['fits']={'status':'measured_candidates_pending_spatial_review','runs':all_runs,'source_metrics':manifest,
  'height_observations':observations,
  'roofer_batch_metrics':batches,'elapsed_seconds':time.perf_counter()-start,
  'summary':shared.summarise({'runs':all_runs}),
  'notes':['Twenty percent same-source class6 points held out before all reconstruction, seed20261115.',
   'The fit-gallery baseline is an approximate generic method, not the frozen actual city renderer; actual map before/after is kept separately in traces/rendered_comparison.',
   'Templates fit at most3500 points and4 orientations; baseline/templates median of3 repeats; Roofer one batch per source.',
   'Class6 building points within a footprint are roof candidates, not a separately verified roof-only classification.',
   'Good heldout absolute-height agreement does not verify ground estimate, relative eave or true floor counts.',
   'No fitted result is automatically added to the main city map.']}
 result['status']='policy_tested_and_point_cloud_candidates_ready_for_review'
 write(DEST/'results.json',result)
 report={'schema':'roof-pilot/1','city':'ceske-budejovice','created_at':datetime.now(timezone.utc).isoformat(),
   'samples':[dict(f['properties'],id=f['id']) for f in read(shared.SAMPLE)['features']],
   'runs':all_runs,'summary':result['fits']['summary'],'notes':result['fits']['notes'],
   'source_metrics':manifest,'process_metrics':batches}
 write(DEST/'fit-results.json',report)
 import roof_pilot_report
 html=roof_pilot_report.build_report(report).replace('Velešín','České Budějovice — audit12')
 (DEST/'fit-report.html').write_text(html,encoding='utf8')
 print(json.dumps({'event':'audit_fits_complete','seconds':time.perf_counter()-start,'runs':len(all_runs)},ensure_ascii=False),flush=True)

def scene_index():
 """Match stable Overture IDs and canonical centimetre-rounded footprint parts."""
 infos={x['id']:x for x in read(WORK/'build/info_src.json')['buildings']}
 rows=[];seen=Counter();unmapped=[]
 for b in read(WORK/'build/scene.json')['buildings']:
  i=infos.get(b['id'])
  if not i or not i.get('oid'):
   unmapped.append(b['id']);continue
  ring=[tuple(round(float(v),2) for v in pt) for pt in b['p']]
  if len(ring)>1 and ring[-1]==ring[0]:ring.pop()
  variants=[]
  for sequence in (ring,list(reversed(ring))):
   first=min(range(len(sequence)),key=lambda k:sequence[k:]+sequence[:k])
   variants.append(sequence[first:]+sequence[:first])
  canonical=min(variants)
  gh=hashlib.sha256(json.dumps(canonical,separators=(',',':')).encode()).hexdigest()
  pair=(i['oid'],gh);number=seen[pair];seen[pair]+=1
  wall=round(b['e']-b['g'],3)
  rows.append({'key':f'{i["oid"]}:{gh}:{number}','id':i['oid'],'scene_id':b['id'],
   'footprint_sha256':gh,'addresses':i.get('addr',[]),'name':i.get('name'),
   'roof':b['r'],'wall_height_m':wall,'roof_height_m':b['rh'],'total_m':round(wall+b['rh'],3),
   'parts':b['parts'],'style':b['s'],'ground_relative_m':b['g'],
   'lm':b.get('lm'),'dn':b.get('dn')})
 return {'rows':rows,'matched_parts':len(rows),'unique_overture_ids':len({r['id'] for r in rows}),
   'scene_buildings_count':len(rows)+len(unmapped),'unmapped_scene_ids':unmapped,
   'source_files':[fingerprint(WORK/'build'/p) for p in ('scene.json','info_src.json')]}

def review_fits():
 """Light review of saved models and the small sparse crop; no LAZ scan/refit."""
 import roof_pilot as shared
 import laspy
 import importlib.metadata
 guard.check_budget(force=True);start=time.perf_counter();result=read(DEST/'results.json')
 shared.SAMPLE=DEST/'sample.json';shared.MANIFEST=AUDIT/'sources.json'
 xyz,classes,holdout=shared.load_source('dmp1g');low_rows=[]
 for feature,poly in shared.samples():
  data=shared.building_data(poly,xyz,classes,holdout)
  roof=xyz[(classes==6)&shapely.contains_xy(poly,xyz[:,0],xyz[:,1])]
  low=roof[roof[:,2]<data['ground_z']+2]
  distances=shapely.distance(poly.boundary,shapely.points(low[:,:2])) if len(low) else np.empty(0)
  low_rows.append({'id':feature['id'],'pilot_id':feature['properties']['pilot_id'],'roof_candidates':len(roof),
   'class6_within2m_above_ground20':len(low),'low_fraction':len(low)/len(roof),
   'low_distance_to_footprint_boundary_median_m':float(np.median(distances)) if len(distances) else None,
   'low_within1m_boundary':int((distances<=1).sum()),'example_low_xyz_class6':low[:3].tolist(),
   'all_candidates_strictly_inside_original_footprint':True})
 result['fits']['class6_source_audit']={'source':'dmp1g','classification_read':'Native laspy chunk.classification copied unchanged to NPZ; no synthetic classification in this reader.',
  'laspy_module':str(Path(laspy.__file__)),'laspy_version':importlib.metadata.version('laspy'),
  'source_code':[{'file':'scripts/roof_pilot_sources.py','line':253,'role':'Read native LAS class'},
   {'file':'scripts/roof_pilot_sources.py','line':263,'role':'Copy selected class unchanged'},
   {'file':'scripts/roof_pilot.py','line':71,'role':'Roof candidates restricted to original footprint, not buffer'},
   {'file':'dmp_fetch.py','line':25,'role':'Download and unzip; no point editing'}],
  'observations':low_rows,'dense_source_rescanned':False,
  'interpretation':'Class6 means building, not verified roof. Low points near edges may be facades/arcades/footprint or epoch mismatch/classification error; no unique cause is established. Published holdout points and metrics are unchanged.'}
 observed={(o['source'],o['id']):o for o in result['fits']['height_observations']}
 lows={r['id']:r for r in low_rows};quality_counts=Counter()
 face_audits=[]
 import roof_pilot_roofer as roofer
 for run in result['fits']['runs']:
  model=run.get('model') or {};hd=run.get('height_diagnostics') or {};flags=[]
  o=observed[(run['source'],run['id'])];top99=o['roof_absolute_bpv_percentiles'].get('p99')
  excess=None
  if run['status']!='ok':flags.append('missing_geometry')
  if hd.get('roof_vertex_min_above_ground_m',0)<-1:flags.append('roof_below_ground')
  if top99 is not None and hd.get('roof_vertex_max_above_ground_m') is not None:
   excess=hd['roof_vertex_max_above_ground_m']-(top99-run['ground_z'])
   if excess>3:flags.append('peak_over_source_p99_plus3m')
  if 'invalid_faces_skipped' in model.get('warnings',[]):flags.append('skipped_faces_require_semantic_audit')
  if 'lod11_fallback' in str(model.get('warnings',[])):flags.append('lod11_fallback_not_detailed_roof')
  if run['source']=='dmp1g' and lows[run['id']]['low_fraction']>.05:flags.append('low_class6_points_in_evaluation')
  status=('unavailable' if run['status']!='ok' else 'reject_geometric_envelope' if any(f in flags for f in ['roof_below_ground','peak_over_source_p99_plus3m'])
          else 'fallback_only' if 'lod11_fallback_not_detailed_roof' in flags else 'review_not_ground_truth')
  run['audit_quality']={'status':status,'flags':flags,'peak_excess_above_source_p99_m':round(excess,3) if excess is not None else None,
   'rule_note':'Conservative review gate, not calibrated probability; source P99 may omit rare real features. No model geometry or holdout score changed.'}
  quality_counts[status]+=1
  if 'invalid_faces_skipped' in model.get('warnings',[]):
   for raw_path in sorted((AUDIT/run['source']/'roofer').rglob('*.city.jsonl'),reverse=True):
    header={};feature=None
    for line in raw_path.read_text(encoding='utf8').splitlines():
     value=json.loads(line)
     if value.get('type')=='CityJSON':header=value
     if value.get('id')==run['id']:feature=value;break
    if feature is None:continue
    tr=feature.get('transform',header.get('transform',{}))
    vertices=(np.asarray(feature['vertices'],dtype=float)*np.asarray(tr.get('scale',[1,1,1]))+
      np.asarray(tr.get('translate',[0,0,0]))-np.asarray(model['origin_epsg5514'])).tolist()
    invalid=[];passed=Counter()
    for obj in roofer._object_group(feature['CityObjects'],run['id']):
     for geometry in obj.get('geometry',[]):
      if str(geometry.get('lod'))!='2.2':continue
      for index,(rings,semantic) in enumerate(roofer._surface_records(geometry)):
       try:roofer._triangulate_surface(rings,vertices);passed[semantic]+=1
       except (ValueError,TypeError,IndexError,shapely.errors.GEOSException) as exc:
        invalid.append({'surface_index':index,'semantic':semantic,'reason':str(exc),'rings':rings})
    face_audits.append({'id':run['id'],'source':run['source'],'raw_file':fingerprint(raw_path),
      'invalid_surfaces':invalid,'passed_surfaces_by_semantic':dict(passed),
      'method':'Re-execute the unchanged adapter triangulation on raw LoD2.2 semantic surfaces; no reconstruction or mesh repair.'})
    if invalid and all(s['semantic']=='WallSurface' and s['reason']=='Degenerate face' for s in invalid):
     run['audit_quality']['flags']=[('degenerate_wall_surfaces_skipped_roofs_preserved' if flag=='skipped_faces_require_semantic_audit' else flag)
       for flag in run['audit_quality']['flags']]
     run['audit_quality']['face_audit_status']='Only degenerate WallSurface polygons skipped; semantic roof polygons all passed.'
    break
 decisions=[
  ('component_roofs_review','Členitý objekt. DMPOK Roofer má výrazně nižší RMSE než jediná šablona; nejnižší střešní vrchol není římsa uliční fasády. Tři řady oken mohou být tři vysoká podlaží, nikoli ověřené 3 + 2.'),
  ('simple_gable_candidate','DMPOK gabled i Roofer souhlasí v hlavní geometrii; zhruba 14,94 → 18,91 m. Kandidát k ověření průčelí a orientace, nikoli automaticky 3 + 2.'),
  ('template_candidate_roofer_failed','DMPOK šablona gabled je použitelný kandidát; Roofer nevytvořil geometrii. Vyžaduje kontrolu menšího půdorysu a okolních částí.'),
  ('split_complex_before_refit','Areál kasáren a novějších částí vyžaduje rozdělení. DMPOK Roofer použil LoD1.1 fallback; jednoduchý model střechy není schválen.'),
  ('explicit_gable_supported','Explicitní gabled podporují zejména obě DMPOK metody. DMPOK šablona zhruba 12,77 → 19,43 m souhlasí s konzervativní opravou mapy 12,2 + 7 m.'),
  ('component_roofs_review','DMPOK Roofer zachycuje více výšek lépe než jediný pult. Nevynucovat jednu střechu ani jednu společnou římsu celého dlouhého půdorysu.'),
  ('roofer_candidate_template_ambiguous','DMPOK Roofer je dobrý kandidát; volba barrel u šablon není důkazem valené střechy. DMP1G Roofer špička 38,8 m se odmítá.'),
  ('gable_with_complexity_review','V obou zdrojích vyšla gabled šablona, ale DMPOK RMSE 1,80 m a malé nižší části vyžadují kontrolu. Neurčovat počet podlaží z modelu.'),
  ('component_roofs_and_faces_review','Složený půdorys, DMPOK Roofer je kandidát. Audit prokázal dvě degenerované stěny, všech 43 střešních ploch prošlo. DMP1G Roofer má části pod terénem a špičku 51,7 m: odmítnuto.'),
  ('keep_existing_pitched_control','Dosavadní valbová kontrola má přibližně správný rozsah výšky; modely typu gabled/slanted nejsou samy důvodem změnit ověřování typu střechy.'),
  ('preserve_flat_bank_control','Fotografie potvrzuje horizontální atiky a více výškových částí. Šablony gabled jsou špatný fit; Roofer slanted neznamená jednu sedlovou střechu celé banky.'),
  ('preserve_explicit_flat_control','DMPOK flat šablona potvrzuje hlavní plochou střechu. DMP1G class 6 obsahuje nízké body a může nesprávně zvýhodnit gabled; explicitní flat zachovat.'),
 ]
 pairs=[]
 for trace,(decision,note) in zip(result['traces'],decisions):
  selected=[r for r in result['fits']['runs'] if r['id']==trace['id'] and r['method']!='baseline']
  pairs.append({'id':trace['id'],'pilot_id':trace['pilot_id'],'name':trace['name'],'decision':decision,'note_cs':note,
   'methods':[{'source':r['source'],'method':r['method'],'status':r['status'],'shape':(r.get('model')or{}).get('shape'),
     'holdout_rmse_m':r['metrics']['holdout_rmse_m'],'height_diagnostics':r.get('height_diagnostics'),
     'audit_quality':r['audit_quality']} for r in selected], 'automatically_applied_to_main_map':False})
 result['fits']['paired_review']=pairs;result['fits']['quality_summary']=dict(quality_counts)
 result['fits']['face_audits']=face_audits
 result['fits']['review_seconds']=time.perf_counter()-start
 extra_notes=[
  'Model vytvořen means file/geometry exists, not approved geometry. Inspect audit_quality and paired_review.',
  'DMP1G low class6 points remain in all published scores. No roof-only or filtered RMSE was substituted.',
  'Scene terrain plus href differs numerically from local laser ground; relative roof heights must be anchored consistently. No datum correction is inferred.']
 for note in extra_notes:
  if note not in result['fits']['notes']:result['fits']['notes'].append(note)
 write(DEST/'results.json',result)
 report=read(DEST/'fit-results.json');report['runs']=result['fits']['runs'];report['notes']=result['fits']['notes']
 write(DEST/'fit-results.json',report)
 import roof_pilot_report
 html=roof_pilot_report.build_report(report).replace('Velešín','České Budějovice — audit 12')
 marker='modelDetails(card,r);'
 audit_ui="""modelDetails(card,r);const aq=r.audit_quality||{};
if(aq.status==='reject_geometric_envelope'){card.badge.textContent='Odmítnuto · výška';card.badge.className='badge bad';card.body.append(el('p','Geometrie neprošla kontrolou výškového rozsahu. Zůstává zobrazena pro diagnostiku.','error'));}
if(aq.status==='fallback_only')card.body.append(el('p','Pouze náhradní základní objem; detailní střecha není ověřena.','error'));
const auditNames={roof_below_ground:'Část střechy pod místním terénem',peak_over_source_p99_plus3m:'Špička více než 3 m nad P99 bodů zdroje',low_class6_points_in_evaluation:'Hodnocení obsahuje nízké body třídy Building',degenerate_wall_surfaces_skipped_roofs_preserved:'Přeskočeny dvě degenerované stěny; střešní plochy zachovány'};
for(const flag of aq.flags||[])if(auditNames[flag])card.body.append(el('p',auditNames[flag],aq.status==='reject_geometric_envelope'?'error':'small'));
"""
 if html.count(marker)!=1:raise ValueError('Audit report hook changed; refusing an incomplete quality display')
 html=html.replace(marker,audit_ui)
 notice='<div class="notice"><strong>Diagnostika, nikoli schválené modely.</strong> Zelený stav znamená vznik geometrie. Některé sparse DMP1G výsledky mají odmítnuté výškové špičky; typy střech a počty podlaží vyžadují samostatnou kontrolu. <a href="README.md">Párované závěry a omezení</a>.</div>'
 html=html.replace('<div id="warnings"></div>','<div id="warnings"></div>'+notice)
 (DEST/'fit-report.html').write_text(html,encoding='utf8')
 print(json.dumps({'event':'fit_review_complete','quality':dict(quality_counts),'seconds':time.perf_counter()-start},ensure_ascii=False),flush=True)

def freeze_all():
 guard.check_budget(force=True);p=AUDIT/'baseline-all-buildings.json'
 result=read(DEST/'results.json')
 original=next(f for f in result['source_files'] if f['path'].endswith('/build/scene.json'))
 if fingerprint(WORK/'build/scene.json')['sha256']!=original['sha256']:
  raise ValueError('Current scene is no longer the frozen baseline; use original archive')
 if p.exists():raise ValueError('Whole-scene baseline already exists; refusing to overwrite')
 index=scene_index();write(p,index)
 result['global_baseline']={k:v for k,v in index.items() if k!='rows'}
 result['global_baseline']['index_file']=fingerprint(p)
 result['global_baseline']['matching']='Overture UUID + canonical centimetre footprint ring hash + duplicate occurrence'
 write(DEST/'results.json',result)
 print(json.dumps({'event':'whole_scene_baseline_frozen',**{k:v for k,v in index.items() if k not in ('rows','source_files')}},ensure_ascii=False),flush=True)

def capture_rendered():
 """Capture the rebuilt real scene without changing the frozen baseline."""
 guard.check_budget(force=True);start=time.perf_counter();result=read(DEST/'results.json')
 info={x['oid']:x for x in read(WORK/'build/info_src.json')['buildings']}
 scene={x['id']:x for x in read(WORK/'build/scene.json')['buildings']};rows=[]
 for trace in result['traces']:
  b=scene[info[trace['id']]['id']];wall=round(b['e']-b['g'],3)
  after={'roof':b['r'],'wall_height_m':wall,'roof_height_m':b['rh'],'total_m':round(wall+b['rh'],3),
    'style':b['s'],'shader_window_bands':wall_window_rows(wall,b['s']),'parts':len(b['parts']),'not_true_floor_count':True}
  rows.append({'id':trace['id'],'name':trace['name'],'before':trace['baseline'],'after':after,
   'changed':trace['baseline']!=after,'scene':b})
 by_id={r['id']:r for r in rows}
 checks={'known_gabled_restored':by_id['4360399b-b4fe-442c-aebf-299791112d22']['after']['roof']=='gabled',
  'bank_remains_flat':by_id['e8ed1629-4536-4975-9f07-c129bc7b0d6a']['after']['roof']=='flat',
  'explicit_flat_remains_flat':by_id['099a5e53-02a4-4b93-a6a7-0123062e381f']['after']['roof']=='flat'}
 result['rendered_comparison']={'status':'captured_actual_scene','rows':rows,'checks':checks,
  'all_checks_passed':all(checks.values()),'changed_count':sum(r['changed'] for r in rows),
  'source_files':[fingerprint(WORK/'build'/p) for p in ('scene.json','info_src.json')],
  'elapsed_seconds':time.perf_counter()-start}
 original=read(AUDIT/'baseline-all-buildings.json');current=scene_index()
 old={r['key']:r for r in original['rows']};new={r['key']:r for r in current['rows']}
 transitions=Counter();transition_ids={};changed=[];height_counts=Counter();sets={k:set() for k in ('roof_shape','wall_height','roof_height','total_height','roof_parts','ground','style')}
 for key in sorted(old.keys()&new.keys()):
  before,after=old[key],new[key];changes=[]
  for label,field in [('roof_shape','roof'),('roof_parts','parts'),('style','style')]:
   if before[field]!=after[field]:changes.append(label)
  for label,field in [('wall_height','wall_height_m'),('roof_height','roof_height_m'),('total_height','total_m'),('ground','ground_relative_m')]:
   if abs(before[field]-after[field])>.02:changes.append(label)
  if changes:
   changed.append({'id':after['id'],'addresses':after['addresses'],'part_key':key,'changes':changes,
    'before':before,'after':after})
   for label in changes:height_counts[label]+=1;sets[label].add(after['id'])
   if 'roof_shape' in changes:
    transition=f'{before["roof"]}->{after["roof"]}';transitions[transition]+=1
    transition_ids.setdefault(transition,set()).add(after['id'])
 result['whole_scene_diff']={'matching':result['global_baseline']['matching'],'height_tolerance_m':.02,
  'before_parts':len(old),'after_parts':len(new),'matched_parts':len(old.keys()&new.keys()),
  'before_unique_overture_ids':original['unique_overture_ids'],'after_unique_overture_ids':current['unique_overture_ids'],
  'changed_parts':len(changed),'changed_unique_overture_ids':len({r['id'] for r in changed}),
  'changed_part_counts':dict(height_counts),'changed_unique_overture_counts':{k:len(v) for k,v in sets.items()},
  'roof_shape_transitions_by_part':dict(transitions),
  'roof_shape_transitions_unique_overture_ids':{k:len(v) for k,v in transition_ids.items()},
  'added_parts':[new[k] for k in sorted(new.keys()-old.keys())],
  'removed_parts':[old[k] for k in sorted(old.keys()-new.keys())],
  'unmapped_before_scene_ids':original['unmapped_scene_ids'],'unmapped_after_scene_ids':current['unmapped_scene_ids'],
  'changes':changed,'note':'Pure map-scene diff, independent of the16 source-attribute suspects. Added/removed footprint parts are not silently paired by centroid.'}
 result['status']='main_map_scene_rebuilt_and_captured'
 write(DEST/'results.json',result)
 print(json.dumps({'event':'rebuilt_scene_captured','checks':checks,'changed_count':sum(r['changed'] for r in rows)}),flush=True)
 if not all(checks.values()):raise RuntimeError('Rebuilt roof controls failed')

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--worker',action='store_true')
 p.add_argument('--phase',choices=['baseline','policy','crop','fit','review','freeze','capture'],default='baseline');a=p.parse_args()
 if a.worker:
  {'baseline':execute,'policy':policy_preview,'crop':crop_sources,'fit':fit_sources,'review':review_fits,'freeze':freeze_all,'capture':capture_rendered}[a.phase]();return
 m=guard.run_guarded([sys.executable,'-X','utf8',__file__,'--worker','--phase',a.phase],ROOT,AUDIT/(a.phase+'.log'),max_ram_gb=2 if a.phase in ('crop','fit') else 1,min_available_gb=1)
 d=read(DEST/'results.json')
 if a.phase=='baseline':d['process_metrics']=m
 elif a.phase=='policy':d['policy_preview']['process_metrics']=m
 elif a.phase=='crop':d['crop_process_metrics']=m
 elif a.phase=='capture':d['rendered_comparison']['process_metrics']=m
 elif a.phase=='freeze':d['global_baseline']['process_metrics']=m
 elif a.phase=='review':d['fits']['review_process_metrics']=m
 else:d['fits']['process_metrics']=m
 write(DEST/'results.json',d)

if __name__=='__main__':main()
