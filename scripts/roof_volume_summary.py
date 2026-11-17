"""Read-only summary of roof-volume checkpoints. Does not run inference."""
from __future__ import annotations
import argparse, json
from collections import Counter
from pathlib import Path


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def summarize(output):
    output=Path(output)
    run=read(output/'run.json') if (output/'run.json').is_file() else {}
    records=[read(p) for p in sorted((output/'buildings').glob('*.json'))]
    totals=Counter();choices=Counter();rows=[]
    for r in records:
        totals['buildings']+=1
        totals['complete_buildings']+=r.get('status')=='complete'
        totals['failed_buildings']+=r.get('status')!='complete'
        timing=r.get('timing') or {}
        for key in ('experiment_compute_seconds','baseline_fresh_compute_seconds','input_read_seconds','wall_seconds'):
            totals[key]+=timing.get(key,0.)
        details=r.get('details') or []
        totals['split_proposed_buildings']+=any((d.get('decision') or {}).get('split_proposed') for d in details)
        totals['split_selected_buildings']+=any((d.get('decision') or {}).get('split_accepted') for d in details)
        display_parts=r.get('building',{}).get('parts',[])
        for d in details:
            decision=d.get('decision') or {};selected=decision.get('selected_variant');choices[selected or 'unknown']+=1
            totals['parts']+=1;totals['variant_errors']+=len(d.get('errors') or {})
            totals['evaluation_seconds']+=d.get('evaluation_seconds',0.)
            module=d.get('module_timing') or {}
            for key in ('section_seconds','partition_seconds'):totals[key]+=module.get(key,0.)
            validation=d.get('validation') or {};metrics=validation.get('variants') or {}
            for key,m in metrics.items():
                stats=m.get('shared_cells') or {};score=(decision.get('scores') or {}).get(key) or {}
                displayed=next((p for p in display_parts if p.get('part_index',0)==d.get('part_index',0) and p.get('display_variant')==key),{})
                result=displayed.get('result') or {};meta=result.get('model',{}).get('metadata',{})
                rows.append(dict(city=r['city'],id=r['id'],address=r['address'],part_index=d.get('part_index',0),variant=key,
                    selected=key==selected,split_proposed=bool(decision.get('split_proposed')),split_selected=bool(decision.get('split_accepted')),
                    proposed_volume_count=decision.get('proposed_volume_count',1),selected_volume_count=decision.get('selected_volume_count',1),
                    volume_count=meta.get('volume_count',score.get('volume_count',1)),plane_count=meta.get('nominal_roof_plane_count',score.get('plane_count')),
                    shared_holdout_cells=validation.get('shared_cell_count',0),holdout_p50_m=stats.get('p50_m'),holdout_p90_m=stats.get('p90_m'),
                    holdout_rmse_m=stats.get('rmse_m'),holdout_within_05_fraction=stats.get('within_05_fraction'),
                    supported_cells=m.get('supported_cell_count'),excluded_cells=m.get('excluded_cell_count'),
                    variant_seconds=result.get('timing',{}).get('total_seconds'),
                    timing_note='historical baseline time, not newly computed' if key=='baseline' and d.get('baseline_origin','').startswith('reused') else 'candidate time; shared preprocessing may be excluded'))
    return dict(schema='roof-volume-overview/1',status=run.get('status'),totals=dict(totals),selected_variant_counts=dict(choices),
        report_seconds=run.get('report_seconds'),rows=rows,
        notes=['Validation is the same cached holdout cell intersection for every variant within one part.',
            'Box geometry is diagnostic and excluded from candidate selection.',
            'Variant times are not additive: some methods share profiles or skeleton data; experiment_compute_seconds is the complete measured pass.'])


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--json',action='store_true')
    args=ap.parse_args();summary=summarize(args.output)
    if args.json:print(json.dumps(summary,ensure_ascii=False,indent=2));return
    t=summary['totals']
    print('Stav:',summary['status'])
    print('Domy:',t.get('complete_buildings',0),'/',t.get('buildings',0),'Chyby variant:',t.get('variant_errors',0))
    print('Dělení navrženo:',t.get('split_proposed_buildings',0),'Vybráno:',t.get('split_selected_buildings',0))
    print('Výpočet experimentu:',round(t.get('experiment_compute_seconds',0),3),'s')
    for r in summary['rows']:
        if r['selected']:print(r['address'],'|',r['variant'],'| objemů',r['selected_volume_count'],'| P50',r['holdout_p50_m'],'| P90',r['holdout_p90_m'])

if __name__=='__main__':main()
