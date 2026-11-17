"""Sequential, resumable 15-building roof-volume experiment using local inputs.

No network, model APIs or visual reviews. Existing cache splits are preserved.
Run --prepare-only to resolve input addresses without running roof inference.
"""
from __future__ import annotations
import argparse, copy, csv, hashlib, html, io, json, math, os, shutil, sys, time
from datetime import datetime, timezone
from pathlib import Path
for _name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_name]='1'
ROOT=Path(__file__).resolve().parents[1]
for _path in (ROOT/'.venv/Lib/site-packages',ROOT/'.work/roof-skeleton-test/vendor'):
    if _path.is_dir(): sys.path.insert(0,str(_path))
import numpy as np
import atomic_io
import resource_guard as guard
from roof_v2 import _cells, predict_regions, residual_stats
from roof_v2_report import render_report

VEL_INPUT='cities/velesin/experiments/roof-night-20261117-v491/inputs-streets/inputs.json'
CB_INPUT='cities/ceske-budejovice/experiments/roof-regularized-wings-v491-8/inputs.json'
CB_EXTRA='cities/ceske-budejovice/experiments/roof-flat-protrusions-v481-44/inputs.json'
VEL_NUMBERS=[5,13,4,94,70,72,69,54,1]
CB_ADDRESSES=['Husova tř. 1829/12','Kněžská 410/8','Široká 421/1','Hroznová 314/18','Jirsíkova 423/1','Jirsíkova 422/3']
LABELS={'baseline':'Předchozí 4.9.1','skeleton_shared':'Společný skeleton',
    'skeleton_sections':'Skeleton podle řezů','split_volumes':'Řezy u hran','split_scan':'Posuvné řezy',
    'lod_boxes':'Výškové krabice'}


def now():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(atomic_io.read_text(path))
def default(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,Path):return str(value)
    raise TypeError(type(value).__name__)
def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    atomic_io.write_text(path,json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False,default=default))


def select_inputs():
    """MODULE: address selection from frozen manifests, never geocode remotely."""
    manifests={p:read(ROOT/p) for p in (VEL_INPUT,CB_INPUT,CB_EXTRA)}
    stage=read(ROOT/'cities/velesin/experiments/roof-night-20261117-v491/streets/stage.json')
    old_by_id={e['id']:e for e in stage['entries']}
    requests=[('velesin','náměstí J. V. Kamarýta '+str(n)) for n in VEL_NUMBERS]
    requests += [('ceske-budejovice',a) for a in CB_ADDRESSES]
    result=[]
    for city,address in requests:
        sources=[VEL_INPUT] if city=='velesin' else [CB_INPUT,CB_EXTRA]
        found=None
        for path in sources:
            match=[b for b in manifests[path]['buildings'] if b.get('address')==address]
            if len(match)>1:raise ValueError('Ambiguous address: '+address)
            if match:found=(path,match[0]);break
        if found is None:raise ValueError('Missing frozen input: '+address)
        manifest_path,building=found;manifest=manifests[manifest_path]
        building=copy.deepcopy(building)
        base=(ROOT/manifest_path).parent if manifest.get('cache_path_base')=='manifest_directory' else ROOT
        for part in building['parts']:
            path=Path(part['cache']['path'])
            path=path if path.is_absolute() else base/path
            if not path.is_file():raise FileNotFoundError(path)
            part['cache']['path']=str(path.resolve())
        baseline=None
        if city=='velesin' and building['id'] in old_by_id:
            baseline=old_by_id[building['id']]['model_file']
        elif manifest_path==CB_INPUT:
            baseline=str((ROOT/CB_INPUT).with_name('results.json'))
        source_records=(ROOT/manifest_path).with_name('source_records.json')
        providers=read(source_records).get(building['id'],{}) if source_records.is_file() else {}
        result.append(dict(city=city,id=building['id'],address=address,building=building,
            input_manifest=manifest_path,baseline_file=baseline,provider_records=providers,
            input_provenance={k:manifest.get(k) for k in ('source','crs','vertical_datum','source_manifest','source_policy','source_tiles','split','ground_policy')}))
    return result


def load_baseline(entry):
    if not entry.get('baseline_file'):return None
    data=read(entry['baseline_file'])
    building=data.get('model') if 'model' in data else next((b for b in data.get('buildings',[]) if b['id']==entry['id']),None)
    if not building:return None
    # Old shapes are re-used only from the intended baseline version.
    if not all(p.get('result',{}).get('algorithm')=='modular-roofs-4.9.1' for p in building.get('parts',[])):return None
    return building


def evaluate(results,points):
    """MODULE: identical cached holdout cell population for every candidate."""
    if not len(points):return {'available':False,'reason':'No held-out points in frozen NPZ'}
    cells=_cells(points,.6)
    predictions={key:predict_regions(result['model']['regions'],cells[:,:2]) for key,result in results.items()}
    shared=np.ones(len(cells),dtype=bool)
    for prediction in predictions.values():shared &= np.isfinite(prediction)
    rows={}
    for key,prediction in predictions.items():
        ok=np.isfinite(prediction)
        rows[key]=dict(supported_cell_count=int(ok.sum()),excluded_cell_count=int((~ok).sum()),
            supported_cells=residual_stats(prediction[ok]-cells[ok,2]),
            shared_cells=residual_stats(prediction[shared]-cells[shared,2]))
    return dict(available=True,cell_m=.6,total_cell_count=len(cells),shared_cell_count=int(shared.sum()),
        note='Untouched cached holdout; same photogrammetric survey, not independent surveyed truth. All variants share the same evaluation cells.',variants=rows)


def layout_variants(building):
    """MODULE: display offsets only, model coordinates remain unchanged."""
    parts=building['parts'];keys=list(dict.fromkeys(p['display_variant'] for p in parts))
    direction=np.array([math.cos(-.8),math.sin(-.8)])
    extents=[]
    origin=np.array(parts[0].get('origin_xy',[0.,0.]))
    for part in parts:
        vertices=part.get('result',{}).get('model',{}).get('mesh',{}).get('vertices',[])
        if vertices:
            xy=np.asarray(vertices)[:,:2]+np.array(part.get('origin_xy',origin))-origin
            extents.extend((xy@direction).tolist())
    spacing=float(np.ptp(extents)+10.) if extents else 30.
    for part in parts:
        slot=keys.index(part['display_variant'])-(len(keys)-1)/2
        part['display_offset_m']=[*map(float,direction*spacing*slot),0.]
    return building


def check_limits(initial,output):
    free=shutil.disk_usage(ROOT).free
    if free<guard.MIN_FREE_BYTES:raise guard.ResourceLimit('STOP: fewer than 25 GB free')
    # Only our tiny output grows in this process; initial whole-project scan is
    # done once, then bounded output growth and disk space are checked per house.
    used=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    if initial['project_bytes']+used+guard.SIZE_MARGIN>guard.MAX_PROJECT_BYTES:
        raise guard.ResourceLimit('STOP: conservative project/output budget exceeds 20 GB')
    if used>250_000_000:raise guard.ResourceLimit('STOP: experimental output exceeds 250 MB cap')
    if guard.memory_status()['available']<350_000_000:raise guard.ResourceLimit('STOP: less than 350 MB available memory')


def run_one(entry,output,config):
    from roof_volume_candidates import run_variants
    started=time.perf_counter(); baseline=load_baseline(entry)
    baseline_parts={p.get('part_index',0):p for p in baseline.get('parts',[])} if baseline else {}
    building={k:copy.deepcopy(v) for k,v in entry['building'].items() if k!='parts'}
    building['city']=entry['city'];building['parts']=[]
    building['name']=building.get('name',entry['address'])+' · '+('Velešín' if entry['city']=='velesin' else 'ČB')
    building['input_data']={'input_manifest':entry['input_manifest'],'provider_records':entry['provider_records'],
        'source_attributes':building.get('source_attributes',{}),'provenance':entry['input_provenance']}
    details=[]; fresh_seconds=0.; read_seconds=0.; baseline_compute=0.
    for source_part in entry['building']['parts']:
        part_started=time.perf_counter();part=copy.deepcopy(source_part)
        source_cache=Path(part['cache']['path'])
        packed=output/'point-clouds'/f"{entry['city']}-{entry['id']}-{part.get('part_index',0)}.npz"
        packed.parent.mkdir(exist_ok=True)
        shutil.copyfile(source_cache,packed)
        digest=hashlib.sha256(packed.read_bytes()).hexdigest()
        expected=part['cache'].get('sha256')
        if expected and digest!=expected:raise ValueError('Frozen NPZ checksum changed')
        part['source_cache']=copy.deepcopy(part['cache'])
        part['cache']={'path':str(packed.resolve()),'bytes':packed.stat().st_size,'sha256':digest}
        with np.load(packed) as data:
            train=data['train'];holdout=data['holdout'] if 'holdout' in data.files else np.empty((0,3))
        read_seconds+=time.perf_counter()-part_started
        previous=baseline_parts.get(part.get('part_index',0))
        if previous:
            previous_sha=previous.get('cache',{}).get('sha256') or previous.get('source_cache',{}).get('sha256')
            if previous_sha and previous_sha!=digest:previous=None
        if previous:
            baseline_result=copy.deepcopy(previous['result']);baseline_origin='reused frozen 4.9.1 model'
        else:
            from roof_annex import infer_modular_roof
            tick=time.perf_counter();baseline_result=infer_modular_roof(part['footprint'],train)
            baseline_compute+=time.perf_counter()-tick;baseline_origin='fresh 4.9.1 on same frozen points'
        tick=time.perf_counter()
        outcomes=run_variants(part['footprint'],train,config=config,baseline=baseline_result)
        compute_seconds=time.perf_counter()-tick;fresh_seconds+=compute_seconds
        variants={'baseline':baseline_result}
        variants.update({k:v for k,v in outcomes['variants'].items() if k not in ('selected','baseline') and isinstance(v,dict) and v.get('model')})
        evaluation_started=time.perf_counter();validation=evaluate(variants,holdout)
        detail=dict(part_index=part.get('part_index',0),decision=outcomes.get('decision'),profiles=outcomes.get('profiles'),
            errors=outcomes.get('errors',{}),module_timing=outcomes.get('timing'),validation=validation,
            compute_seconds=compute_seconds,evaluation_seconds=time.perf_counter()-evaluation_started,
            baseline_origin=baseline_origin,train_points=len(train),holdout_points=len(holdout),
            source_cache=part['source_cache'],packed_cache=part['cache'])
        details.append(detail)
        for key,result in variants.items():
            view=copy.deepcopy(part);view.update(status='inferred',display_variant=key,display_label=LABELS.get(key,key))
            view['result']=copy.deepcopy(result)
            if key in ('split_volumes','split_scan','lod_boxes'):
                count=result['model'].get('metadata',{}).get('volume_count',1)
                view['display_label']+=' · '+str(count)+' objemů'
            decision=outcomes.get('decision') or {}
            if decision.get('selected_variant')==key:view['display_label']+=' · doporučená'
            meta=view['result']['model'].setdefault('metadata',{})
            meta['experiment_decision']=outcomes.get('decision');meta['holdout_validation']=validation.get('variants',{}).get(key)
            meta['validation_shared_cells']=validation.get('shared_cell_count')
            meta['experiment_variant']=key
            view['result'].setdefault('diagnostics',{})['experiment_errors']=outcomes.get('errors',{})
            if key=='baseline':meta['baseline_origin']=baseline_origin
            view['point_preview']=train[::max(1,int(np.ceil(len(train)/500)))].tolist()
            view['holdout_preview']=holdout[::max(1,int(np.ceil(len(holdout)/250)))].tolist()
            building['parts'].append(view)
    building['status']='complete'
    building['timing']={'experiment_compute_seconds':fresh_seconds,'baseline_fresh_compute_seconds':baseline_compute,
        'input_read_seconds':read_seconds,'wall_seconds':time.perf_counter()-started}
    building['input_data']['analysis_file']='buildings/'+entry['id']+'.json'
    layout_variants(building)
    return dict(schema='roof-volume-building/1',id=entry['id'],city=entry['city'],address=entry['address'],
        status='complete',building=building,details=details,timing=building['timing'],
        variant_error_count=sum(len(d.get('errors') or {}) for d in details),created_at_utc=now())


def make_reports(output,selection,state):
    documents=[];summaries=[]
    for entry in selection:
        path=output/'buildings'/f"{entry['id']}.json"
        if not path.is_file():continue
        record=read(path)
        if record.get('building'):documents.append(record['building'])
        summaries.append({k:record.get(k) for k in ('id','city','address','status','details','timing','error','variant_error_count')})
    write(output/'summary.json',{'run':state,'buildings':summaries})
    if documents:
        document=dict(schema='roof-v2/1',city='mixed',comparison_mode='volume-candidates',buildings=documents,
            report=dict(batch=True,title='Řezy a samostatné objemy · Velešín a ČB',
                subtitle='Předchozí model a nové varianty vedle sebe. Pro detail vyberte jednu variantu v nabídce Část.',
                note='Výšky jsou nad lokálním terénem. Rozdělení je geometrická hypotéza, nikoli zjištěná hranice samostatné stavby. Holdout pochází ze stejného mračna; nebyl použit k výběru modelu. Produkční mapa není změněna.',
                links=[dict(label='Přehled a časy',href='index.html'),dict(label='Všechna metadata',href='summary.json'),dict(label='Vstupy',href='selection.json')]))
        write(output/'comparison.json',document)
        render_report(output/'comparison.json',output/'report.html')
        rendered=atomic_io.read_text(output/'report.html').replace('Obě verze vedle sebe','Všechny varianty vedle sebe').replace('Izomapa · České Budějovice','Izomapa · Velešín a České Budějovice')
        atomic_io.write_text(output/'report.html',rendered)
    from roof_volume_summary import summarize
    overview=summarize(output)
    write(output/'overview.json',overview)
    if overview['rows']:
        stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(overview['rows'][0]))
        writer.writeheader();writer.writerows(overview['rows'])
        atomic_io.write_text(output/'metrics.csv',stream.getvalue())
    def fmt(value,digits=2):return '—' if value is None else format(value,'.'+str(digits)+'f')
    def esc(value):return html.escape(str(value))
    rows=[]
    for record in summaries:
        link='report.html#'+record['id'];details=record.get('details') or []
        timings=record.get('timing') or {};decisions=[d.get('decision') or {} for d in details]
        proposed=sum(d.get('proposed_volume_count',1) for d in decisions)
        selected=sum(d.get('selected_volume_count',1) for d in decisions)
        winners=[d.get('selected_variant','unknown') for d in decisions]
        method=' / '.join(LABELS.get(w,w) for w in winners)
        stats=[r for r in overview['rows'] if r['id']==record['id']]
        base=next((r for r in stats if r['variant']=='baseline'),{})
        win=next((r for r in stats if r['selected']),{})
        metric_rows=[]
        for r in stats:
            metric_rows.append('<tr><td>'+esc(LABELS.get(r['variant'],r['variant']))+(' ✓' if r['selected'] else '')+'</td><td>'+esc(r['volume_count'])+'</td><td>'+esc(r['plane_count'])+'</td><td>'+fmt(r['holdout_p50_m'])+'</td><td>'+fmt(r['holdout_p90_m'])+'</td><td>'+fmt(r['holdout_rmse_m'])+'</td><td>'+fmt(None if r['holdout_within_05_fraction'] is None else 100*r['holdout_within_05_fraction'],1)+' %</td><td>'+fmt(r['variant_seconds'],3)+'</td></tr>')
        metric_table='<table><thead><tr><th>Varianta</th><th>Objemy</th><th>Plochy</th><th>P50 m</th><th>P90 m</th><th>RMSE m</th><th>Do 0,5 m</th><th>Čas s</th></tr></thead><tbody>'+''.join(metric_rows)+'</tbody></table>'
        reasons=[{k:d.get(k) for k in ('selected_variant','split_proposed','split_accepted','proposed_volume_count','selected_volume_count','reason','partition_variants')} for d in decisions]
        errors=[d.get('errors') for d in details if d.get('errors')]
        info='<details><summary>Varianty, odchylky a důvod</summary>'+metric_table+'<p>Společných validačních buněk: '+esc(win.get('shared_holdout_cells','—'))+'. Čas předchozího modelu může být historický; časy variant nejsou součtem celé dávky.</p><pre>'+esc(json.dumps({'decision':reasons,'errors':errors},ensure_ascii=False,indent=2,default=default))+'</pre><a href="buildings/'+esc(record['id'])+'.json">Úplné řezy, vstupy a metadata JSON</a></details>'
        rows.append('<tr><td><a href="'+esc(link)+'">'+esc(record['address'])+'</a><small>'+esc(record['city'])+'</small></td><td>'+str(proposed)+' → '+str(selected)+'</td><td>'+esc(method)+'</td><td>'+fmt(base.get('holdout_p50_m'))+' → '+fmt(win.get('holdout_p50_m'))+'</td><td>'+fmt(base.get('holdout_p90_m'))+' → '+fmt(win.get('holdout_p90_m'))+'</td><td>'+fmt(timings.get('experiment_compute_seconds'),3)+' s</td><td>'+info+'</td></tr>')
    total=overview['totals']
    stat_text=f"{total.get('complete_buildings',0)} hotových domů · dělení navrženo u {total.get('split_proposed_buildings',0)}, vybráno u {total.get('split_selected_buildings',0)} · chyb variant {total.get('variant_errors',0)}"
    time_text=f"Výpočet experimentu {total.get('experiment_compute_seconds',0):.3f} s; z toho profily {total.get('section_seconds',0):.3f} s a hledání hranic {total.get('partition_seconds',0):.3f} s. Samostatně načítání {total.get('input_read_seconds',0):.3f} s, validace {total.get('evaluation_seconds',0):.3f} s a dopočet předchozích modelů {total.get('baseline_fresh_compute_seconds',0):.3f} s."
    page='<!doctype html><meta charset="utf-8"><title>Řezy a objemy – test</title><style>body{font:15px system-ui;max-width:1500px;margin:32px auto;padding:0 16px;color:#243a31;background:#f7f8f4}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #d5ded5;text-align:left;vertical-align:top}a{color:#21664c}small{display:block;color:#68786e;font-size:10px}pre{white-space:pre-wrap;max-height:360px;overflow:auto;font-size:11px}summary{cursor:pointer}details{max-width:650px}details table{font-size:11px}details td,details th{padding:5px}.stats{background:white;border:1px solid #d5ded5;padding:14px;border-radius:9px}</style><h1>Řezy a samostatné objemy · '+str(len(documents))+' domů</h1><p><a href="report.html">Otevřít 3D porovnání všech variant</a> · <a href="metrics.csv">Tabulka CSV</a> · <a href="overview.json">Souhrn JSON</a> · <a href="summary.json">Úplná metadata</a> · <a href="config.json">Nastavení</a> · <a href="RUN.txt">Spuštění</a></p><div class="stats"><strong>'+esc(stat_text)+'</strong><p>'+esc(time_text)+'</p></div><p>Sloupec objemů znamená nejvyšší navržený počet → počet skutečně zvolené varianty. Výběr vychází z trénovacích bodů a ceny složitosti; validační body do něj nevstupují. P50/P90 v hlavní tabulce: předchozí → vybraná varianta, svislá odchylka v metrech na stejných buňkách. Nižší je lepší.</p><p>Posuvné řezy jsou druhá metoda hledání hranic uvnitř jednoduchého půdorysu. Výškové krabice jsou pomocná reprezentace a nesoutěží jako výsledná střecha. Rozdělení na objemy neprokazuje hranice samostatných staveb. Původní modely a produkční mapa jsou zachovány.</p><table><thead><tr><th>Dům</th><th>Objemy návrh → výběr</th><th>Zvolená metoda</th><th>P50 m</th><th>P90 m</th><th>Výpočet</th><th>Podrobnosti</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'
    atomic_io.write_text(output/'index.html',page)



def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--config',type=Path)
    ap.add_argument('--id',action='append',default=[])
    ap.add_argument('--prepare-only',action='store_true')
    ap.add_argument('--resume',action='store_true')
    ap.add_argument('--rebuild-report',action='store_true')
    args=ap.parse_args(argv);output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    config=read(args.config) if args.config else None
    selection=select_inputs()
    if args.id:selection=[s for s in selection if s['id'] in args.id]
    if not selection:raise ValueError('Empty selection')
    engine_files=['roof_volume_experiment.py','roof_volume_summary.py','roof_volume_candidates.py','roof_sections.py','roof_skeleton_trial.py']
    hashes={name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in engine_files if (ROOT/'scripts'/name).is_file()}
    identity=hashlib.sha256(json.dumps({'files':hashes,'config':config,'ids':[s['id'] for s in selection]},sort_keys=True).encode()).hexdigest()
    state_path=output/'run.json'
    if state_path.is_file():
        state=read(state_path)
        if args.rebuild_report:
            make_reports(output,selection,state);return 0
        if not args.resume:raise ValueError('Output already has run.json; use a new directory or --resume')
        if state.get('identity')!=identity:raise ValueError('Algorithm/config changed; choose a new output version')
    else:state=dict(schema='roof-volume-run/1',identity=identity,source_hashes=hashes,configuration=config,started_at_utc=now(),entries=[])
    write(output/'selection.json',selection)
    if args.prepare_only:
        print(json.dumps({'selected':len(selection),'input_bytes':sum(Path(p['cache']['path']).stat().st_size for s in selection for p in s['building']['parts']),'selection':str(output/'selection.json')},ensure_ascii=False),flush=True);return 0
    from roof_volume_candidates import DEFAULTS
    resolved_config={**DEFAULTS,**(config or {})}
    write(output/'config.json',resolved_config)
    command='python scripts/roof_volume_experiment.py --output '+chr(34)+str(output)+chr(34)
    atomic_io.write_text(output/'RUN.txt',command+'\n\nResume unchanged code: '+command+' --resume\nRebuild HTML only: '+command+' --rebuild-report\nRead-only summary: python scripts/roof_volume_summary.py --output '+chr(34)+str(output)+chr(34)+'\n\nFor another version use a new output directory and optionally --config '+chr(34)+str(output/'config.json')+chr(34)+'\n')
    initial=guard.check_budget(force=True)
    state['resources_initial']=initial;state['status']='running';write(state_path,state)
    try:
        with guard.keep_awake():
            for index,entry in enumerate(selection,1):
                check_limits(initial,output)
                target=output/'buildings'/f"{entry['id']}.json"
                if target.is_file() and read(target).get('status')=='complete':continue
                write(output/'active.json',dict(number=index,total=len(selection),address=entry['address'],started_at_utc=now()))
                print(json.dumps({'number':index,'total':len(selection),'address':entry['address'],'status':'computing'},ensure_ascii=False),flush=True)
                try:record=run_one(entry,output,config)
                except guard.ResourceLimit:raise
                except Exception as error:
                    record=dict(id=entry['id'],city=entry['city'],address=entry['address'],status='failed',error={'type':type(error).__name__,'message':str(error)})
                write(target,record)
                state['entries']=[e for e in state['entries'] if e['id']!=entry['id']]+[{k:record.get(k) for k in ('id','address','status','timing','error','variant_error_count')}]
                state['updated_at_utc']=now();write(state_path,state)
                print(json.dumps(state['entries'][-1],ensure_ascii=False),flush=True)
            state['status']='complete' if all(e['status']=='complete' for e in state['entries']) else 'complete_with_errors'
            if state['status']=='complete' and any(e.get('variant_error_count',0)>0 for e in state['entries']):
                state['status']='complete_with_variant_errors'
    except Exception as error:
        state['status']='stopped';state['error']={'type':type(error).__name__,'message':str(error)}
    state['finished_at_utc']=now();write(state_path,state)
    report_started=time.perf_counter();make_reports(output,selection,state)
    state['report_seconds']=time.perf_counter()-report_started;write(state_path,state)
    print(json.dumps({'status':state['status'],'report':str(output/'report.html'),'buildings':len(state['entries'])},ensure_ascii=False),flush=True)
    return 0 if state['status']=='complete' else 1

if __name__=='__main__':sys.exit(main())
