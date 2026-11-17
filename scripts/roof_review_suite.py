"""Prepare a frozen review suite and its last model per building.

Sources are ordered oldest to newest. Only explicit listed report folders are
merged; no scan of arbitrary experiments. The batch subsequently archives NPZ
inputs itself. This preparation does not fit or inspect any point cloud.
"""
from __future__ import annotations
import argparse,copy,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')

def prepare_suite(source_dirs,output):
    output=Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new preparation directory')
    by_id={};models={};records={};provenance=[];header=None
    for source_dir in source_dirs:
        folder=Path(source_dir).resolve()
        inputs=read(folder/'inputs.json');results=read(folder/'results.json')
        saved_records=read(folder/'source_records.json') if (folder/'source_records.json').is_file() else {}
        latest={b['id']:b for b in results.get('buildings',[])}
        base=folder if inputs.get('cache_path_base')=='manifest_directory' else ROOT
        if header is None:
            header={k:copy.deepcopy(inputs[k]) for k in ('source','crs','vertical_datum')}
        elif any(inputs[k]!=header[k] for k in ('crs','vertical_datum')):
            raise ValueError('Review sources have different spatial references')
        for source in inputs['buildings']:
            oid=source['id']
            if oid not in latest:
                raise ValueError('No previous model for '+oid)
            building=copy.deepcopy(source)
            for part in building['parts']:
                for field in ('cache','context_cache'):
                    if not part.get(field):continue
                    record=part[field];path=Path(record['path'])
                    path=path if path.is_absolute() else base/path
                    path=path.resolve()
                    if not path.is_file():raise ValueError('Missing frozen input: '+str(path))
                    digest=hashlib.sha256(path.read_bytes()).hexdigest()
                    if record.get('sha256') and record['sha256']!=digest:
                        raise ValueError('Frozen input checksum differs: '+str(path))
                    record.update(path=str(path),sha256=digest,bytes=path.stat().st_size)
            building['review_source']={'folder':str(folder),'algorithm':results.get('algorithm')}
            previous=copy.deepcopy(latest[oid])
            parts=previous.get('parts',[])
            if results.get('comparison_mode'):
                explicit=[p for p in parts if p.get('display_variant')=='current']
                if explicit:parts=explicit
                else:parts=list({p.get('part_index',0):p for p in parts}.values())
            previous['parts']=parts
            for part in parts:part['previous_source_run']=folder.name
            by_id[oid]=building;models[oid]=previous;records[oid]=saved_records.get(oid,{})
        provenance.append({'folder':str(folder),'building_count':len(inputs['buildings']),
            'inputs_sha256':hashlib.sha256((folder/'inputs.json').read_bytes()).hexdigest(),
            'results_sha256':hashlib.sha256((folder/'results.json').read_bytes()).hexdigest()})
    if not by_id:raise ValueError('No buildings in explicit sources')
    # Preparation writes only after every source/cache has passed validation.
    output.mkdir(parents=True)
    now=datetime.now(timezone.utc).isoformat()
    inputs={**header,'schema':'roof-review-inputs/1','city':'mixed',
        'created_at_utc':now,'cache_path_base':'absolute','source_records':'source_records.json',
        'selection':'Explicit review suite, latest listed source wins per building ID',
        'source_manifests':provenance,'buildings':list(by_id.values())}
    baseline={**header,'schema':'roof-v2/1','city':'mixed','status':'complete',
        'created_at_utc':now,'algorithm':'latest-saved-per-building',
        'buildings':list(models.values())}
    write(output/'inputs.json',inputs);write(output/'results.json',baseline)
    write(output/'source_records.json',records)
    write(output/'suite.json',{'building_count':len(by_id),'sources':provenance,
        'buildings':[{'id':b['id'],'address':b.get('address'),**b['review_source']} for b in by_id.values()]})
    return inputs,baseline

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run-output',type=Path,help='Optional new report folder; then execute the normal sequential batch')
    parser.add_argument('--url-base',default='http://127.0.0.1:8877')
    args=parser.parse_args(argv)
    inputs,_=prepare_suite(args.source,args.output)
    print(json.dumps({'prepared_buildings':len(inputs['buildings']),'folder':str(args.output.resolve())}),flush=True)
    if args.run_output:
        from roof_batch import main as run_batch
        run_batch(['--inputs',str(args.output/'inputs.json'),'--test','--previous',str(args.output),
            '--split-volumes','--output',str(args.run_output),'--url-base',args.url_base])

if __name__=='__main__':main()
