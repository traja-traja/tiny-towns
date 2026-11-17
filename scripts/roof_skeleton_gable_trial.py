"""Isolated skeleton/gable trial from frozen local inputs.

All inference is delegated to roof_skeleton_gables. Existing production models
and reports are never edited. Holdout statistics are added only after selection.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile

for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_key]='1'
ROOT=Path(__file__).resolve().parents[1]
VENDOR=ROOT/'.work/roof-skeleton-test/vendor'
if VENDOR.is_dir():
    sys.path.insert(0,str(VENDOR))

import numpy as np
from roof_batch import read_json,write_json,compare_documents,current_parts,source_records
from roof_v2 import _cells,predict_regions,residual_stats
from roof_v2_report import render_report
import resource_guard as guard


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _clean_result(result):
    # The selected result may also occur in _variant_results. Never serialize
    # that private collection recursively into each candidate.
    return copy.deepcopy({key:value for key,value in result.items() if not key.startswith('_')})


def _copy_cache(record,base,output,folder,filename):
    source=(base/record['path']).resolve()
    if not source.is_file():
        raise ValueError('Missing frozen input cache: '+str(source))
    digest=guard.sha256(source)
    if record.get('sha256') and digest!=record['sha256']:
        raise ValueError('Frozen input cache checksum changed: '+str(source))
    destination=output/folder/filename
    destination.parent.mkdir(parents=True,exist_ok=True)
    guard.check_budget(reserve_bytes=source.stat().st_size)
    shutil.copyfile(source,destination)
    return {'path':destination.relative_to(output).as_posix(),'sha256':digest,
            'bytes':destination.stat().st_size}


def _add_holdout(result,cells):
    tick=time.perf_counter()
    if len(cells):
        predicted=predict_regions(result['model']['regions'],cells[:,:2])
        covered=np.isfinite(predicted)
        statistics=residual_stats(predicted[covered]-cells[covered,2]) if covered.any() else None
    else:
        covered=np.zeros(0,dtype=bool)
        statistics=None
    result.setdefault('diagnostics',{})['holdout_evaluation']={
        'policy':'Computed after training-only selection; not used to choose a variant.',
        'input_cells':len(cells),'covered_cells':int(covered.sum()),
        'uncovered_cells':int((~covered).sum()),'residual':statistics,
        'seconds':time.perf_counter()-tick}


def _building(source,part,result,point_preview=None):
    building=copy.deepcopy(source)
    outpart=copy.deepcopy(part)
    outpart.update(status='inferred',result=result)
    if point_preview is not None:
        outpart['point_preview']=copy.deepcopy(point_preview)
    building.update(parts=[outpart],status='complete',
        timing={'roof_compute_seconds':result.get('timing',{}).get('total_seconds',0.)})
    return building


def _document(header,building,result):
    return {key:copy.deepcopy(header[key]) for key in ('city','source','crs','vertical_datum') if key in header} | {
        'schema':'roof-v2/1','created_at_utc':_utc(),'algorithm':result.get('algorithm'),
        'status':'complete','buildings':[building]}


def _report_header(title,subtitle,links):
    return {'batch':True,'title':title,'subtitle':subtitle,
        'note':'Vlevo předchozí model, vpravo zkušební konstrukce. Volba používá trénovací body; kontrolní body se hodnotí až následně. Vše počítá místní Python. Vzhled posuzuje uživatel.',
        'links':links}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--id',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--settings',type=Path,help='Optional JSON overrides for the isolated inference module')
    parser.add_argument('--url-base',default='http://127.0.0.1:8877')
    args=parser.parse_args(argv)
    input_path=args.inputs.resolve();previous_dir=args.previous.resolve();output=args.output.resolve()
    if output==input_path.parent or output in input_path.parents or output==previous_dir or output in previous_dir.parents:
        parser.error('Choose a new output outside source directories and their ancestors')
    if output.exists():
        parser.error('Choose a new output directory')
    inputs=read_json(input_path)
    matched=[b for b in inputs['buildings'] if b['id']==args.id]
    if len(matched)!=1 or len(matched[0]['parts'])!=1:
        parser.error('This isolated trial requires one selected building with one footprint part')
    source=matched[0]
    previous=read_json(previous_dir/'results.json')
    baseline=next((b for b in previous.get('buildings',[]) if b['id']==args.id),None)
    if baseline is None:
        parser.error('Selected building has no previous model')
    prior_parts=current_parts(previous,baseline)
    if len(prior_parts)!=1:
        parser.error('Previous model must contain one footprint part')
    settings=read_json(args.settings) if args.settings else None
    base=input_path.parent if inputs.get('cache_path_base')=='manifest_directory' else ROOT
    started=time.perf_counter();cpu=time.process_time()
    guard.check_budget(reserve_bytes=30*1024**2,force=True)
    output.mkdir(parents=True)
    run={'schema':'roof-skeleton-gable-trial-run/1','status':'running','created_at_utc':_utc(),
        'input_manifest':str(input_path),'previous':str(previous_dir),'building_id':args.id,
        'expected_buildings':1,'source_code':{},'settings_overrides':settings,'errors':[]}
    for name in ('roof_skeleton_gable_trial.py','roof_skeleton_gables.py','roof_v2.py',
                 'roof_v2_geometry.py','roof_v2_report.py','roof_v2_viewer.js','roof_observed_ridges.py','roof_skeleton_caps.py','roof_virtual_outline.py'):
        path=ROOT/'scripts'/name
        if path.is_file():run['source_code'][name]=guard.sha256(path)
    write_json(output/'run.json',run)
    try:
      with guard.keep_awake():
        packed_source=copy.deepcopy(source)
        part=packed_source['parts'][0]
        original_cache=copy.deepcopy(part['cache'])
        part['source_cache']=original_cache
        part['cache']=_copy_cache(original_cache,base,output,'point-clouds',args.id+'-0.npz')
        if part.get('context_cache'):
            part['context_cache']=_copy_cache(part['context_cache'],base,output,'context-clouds',args.id+'-0.npz')
        packed_inputs=copy.deepcopy(inputs)
        packed_inputs.update(buildings=[packed_source],cache_path_base='manifest_directory',
            source_records='source_records.json',input_manifest_origin=str(input_path))
        write_json(output/'inputs.json',packed_inputs)
        records=source_records(input_path,{args.id},inputs.get('city'))
        write_json(output/'source_records.json',records)
        write_json(output/'baseline.json',baseline)
        input_started=time.perf_counter()
        with np.load(output/part['cache']['path'],allow_pickle=False) as data:
            train=np.asarray(data['train'],dtype=float)
            holdout=np.asarray(data['holdout'],dtype=float)
        run['input_read_seconds']=time.perf_counter()-input_started
        print(json.dumps({'stage':'infer_skeleton_gables','address':source.get('address'),
            'train_points':len(train),'holdout_points':len(holdout)},ensure_ascii=False),flush=True)
        from roof_skeleton_gables import infer_skeleton_gables
        inferred=infer_skeleton_gables(part.get('effective_footprint',part['footprint']),train,settings=settings)
        from roof_observed_ridges import attach_observed_ridges,compare_with_model
        attach_observed_ridges(inferred,part.get('effective_footprint',part['footprint']),train)
        measured=copy.deepcopy(inferred['diagnostics']['observed_ridges'])
        inferred['timing']['total_seconds']+=measured['seconds']
        variants=list(inferred.get('_variant_results',[]))
        for entry in variants:
            diagnostic=entry['result'].setdefault('diagnostics',{})
            diagnostic['observed_ridges']=compare_with_model(copy.deepcopy(measured),entry['result']['model'])
            for key in ('end_edge_audit','candidate_end_edges','cap_rejections'):
                diagnostic.setdefault(key,copy.deepcopy(inferred['diagnostics'].get(key,[])))
        for prior in prior_parts:
            prior['result'].setdefault('diagnostics',{})['observed_ridges']=compare_with_model(copy.deepcopy(measured),prior['result']['model'])
        selected=_clean_result(inferred)
        if not selected.get('model'):
            raise ValueError('Inference returned no selected model')
        selected.setdefault('model',{}).setdefault('metadata',{}).update(
            source_floor_count=source.get('source_attributes',{}).get('num_floors'),
            estimated_floor_count=None,height_reference='metres above ground_z; ground_z is Bpv')
        holdout_cells=_cells(holdout,.6) if len(holdout) else np.empty((0,3))
        _add_holdout(selected,holdout_cells)
        preview=prior_parts[0].get('point_preview')
        current_building=_building(packed_source,part,selected,preview)
        current=_document(inputs,current_building,selected)
        write_json(output/'results.json',current)
        write_json(output/'config.json',selected.get('configuration',settings or {}))
        links=[{'label':'Všechny varianty','href':'variants.html'},
               {'label':'Přehled pokusu','href':'index.html'},
               {'label':'Metadata výsledku','href':'results.json'},
               {'label':'Časy a rozhodnutí','href':'summary.json'},
               {'label':'Zabalené vstupy','href':'input-bundle.zip'}]
        comparison=compare_documents(current,previous,previous_dir.name)
        comparison['report']=_report_header('Skeleton a kandidátní štíty · '+source.get('address',args.id),
            'Předchozí model a automaticky vybraná zkušební varianta.',links)
        write_json(output/'comparison.json',comparison)
        report_started=time.perf_counter()
        render_report(output/'comparison.json',output/'report.html')
        report_seconds=time.perf_counter()-report_started
        variant_doc={key:copy.deepcopy(value) for key,value in current.items() if key!='buildings'}
        variant_doc.update(buildings=[],comparison_mode='batch')
        variant_summaries=[]
        variant_folder=output/'variants';variant_folder.mkdir()
        for index,entry in enumerate(variants):
            result=_clean_result(entry['result'])
            if not result.get('model'):
                continue
            _add_holdout(result,holdout_cells)
            label=str(entry.get('label','Varianta '+str(index+1)))
            meta=result['model'].get('metadata',{})
            state='VYBRANÁ' if meta.get('selected') else ('přijatá' if meta.get('evidence_accepted') else 'zamítnutá podle bodů')
            label=label+' · '+state
            variant_building=_building(packed_source,part,result,preview)
            doc=_document(inputs,variant_building,result)
            filename=f'{index:02d}.json'
            write_json(variant_folder/filename,doc)
            compared=compare_documents(doc,previous,previous_dir.name)
            item=compared['buildings'][0]
            item['source_building_id']=args.id
            item['id']=args.id+'-variant-'+str(index)
            item['name']=source.get('address',args.id)+' · '+label
            item['address']=source.get('address',args.id)+' · '+label
            for new_part in item['parts']:
                if new_part.get('display_variant')=='current':
                    new_part['display_label']=label
            variant_doc['buildings'].append(item)
            variant_summaries.append({'index':index,'label':label,'report_anchor':item['id'],
                'result_file':'variants/'+filename,'timing':result.get('timing',{}),
                'metadata':result['model'].get('metadata',{}),'diagnostics':result.get('diagnostics',{})})
        variant_doc['report']=_report_header('Všechny varianty štítů · '+source.get('address',args.id),
            'Každá varianta vedle původního modelu. Výběr varianty je v seznamu budov.',
            [{'label':'Vybraný výsledek','href':'report.html'},{'label':'Přehled','href':'index.html'},
             {'label':'Metadata všech variant','href':'variants.json'}])
        write_json(output/'variants.json',variant_doc)
        report_started=time.perf_counter()
        render_report(output/'variants.json',output/'variants.html')
        report_seconds+=time.perf_counter()-report_started
        summary={'schema':'roof-skeleton-gable-trial-summary/1','building_id':args.id,
            'address':source.get('address'),'variant_count':len(variant_summaries),
            'timing':selected.get('timing',{}),'metadata':selected['model'].get('metadata',{}),
            'diagnostics':selected.get('diagnostics',{}),'candidates':selected.get('candidates',[]),
            'original_footprint':part['footprint'],
            'input_footprint':part.get('effective_footprint',part['footprint']),
            'variant_summaries':variant_summaries,'holdout_not_used_for_selection':True,
            'note':'All models generated automatically; no visual architecture assessment.'}
        write_json(output/'summary.json',summary)
        items=''.join('<li><a href="variants.html#'+html.escape(v['report_anchor'],quote=True)+'">'+
            html.escape(v['label'])+'</a> · <a href="'+html.escape(v['result_file'],quote=True)+'">JSON</a></li>'
            for v in variant_summaries)
        (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Skeleton a štíty</title>'
            '<style>body{font:17px system-ui;max-width:950px;margin:40px auto;padding:0 20px;line-height:1.6}a{color:#28614f}li{margin:6px 0}</style>'
            '<h1>'+html.escape(source.get('address',args.id))+'</h1>'
            '<p>Samostatný pokus: virtuální zjednodušený půdorys, skeleton a kandidátní štíty. Původní model zůstává zachován.</p>'
            '<p><a href="report.html">Vybraný výsledek proti předchozímu modelu</a> · '
            '<a href="variants.html">Všechny varianty ve 3D</a> · <a href="summary.json">Časy a metadata</a> · '
            '<a href="input-bundle.zip">Zmrazené vstupy</a></p><ul>'+items+'</ul>',encoding='utf-8')
        command='python scripts/roof_skeleton_gable_trial.py --inputs "'+str(output/'inputs.json')+'" --previous "'+str(previous_dir)+'" --id "'+args.id+'" --settings "'+str(output/'config.json')+'" --output "<nova-slozka>"'
        (output/'RUN.txt').write_text(command+'\n\nInput caches are preserved byte-for-byte. Training and withheld points remain separate.\n'
            'Holdout evaluation follows candidate selection and does not influence it.\n'
            'The selected model is in results.json. Every generated variant is available in variants/ and variants.html.\n',encoding='utf-8')
        run.update(status='complete',completed_buildings=1,algorithm=selected.get('algorithm'),
            variant_count=len(variant_summaries),roof_compute_seconds=selected.get('timing',{}).get('total_seconds'),
            report_seconds=report_seconds,finished_at_utc=_utc(),
            wall_seconds=time.perf_counter()-started,cpu_seconds=time.process_time()-cpu)
        write_json(output/'run.json',run)
        with zipfile.ZipFile(output/'input-bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
            files=[output/name for name in ('inputs.json','source_records.json','baseline.json','config.json','RUN.txt','run.json')]
            files+=sorted((output/'point-clouds').glob('*.npz'))
            files+=sorted((output/'context-clouds').glob('*.npz'))
            for file in files:archive.write(file,file.relative_to(output).as_posix())
        guard.check_budget(force=True)
    except Exception as error:
        run.update(status='failed',errors=[{'type':type(error).__name__,'message':str(error)}],
            finished_at_utc=_utc(),wall_seconds=time.perf_counter()-started)
        write_json(output/'run.json',run)
        raise
    try:
        report_url=args.url_base.rstrip('/')+'/'+(output/'report.html').relative_to(ROOT).as_posix()
    except ValueError:
        report_url=(output/'report.html').as_uri()
    print(json.dumps({'status':'complete','buildings':1,'address':source.get('address'),
        'model_type':selected['model'].get('type'),'variants':len(variant_summaries),
        'roof_compute_seconds':run['roof_compute_seconds'],'wall_seconds':run['wall_seconds'],
        'report_url':report_url,'variants_url':report_url.replace('report.html','variants.html')},ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
