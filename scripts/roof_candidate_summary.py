"""MODULE report_telemetry: aggregate saved attempts, never run roof inference.

Only current top-level parts are counted. Parent captures already include all
annex/volume attempts; traversing child models would count their work twice.
"""
from __future__ import annotations
import html
import math
from collections import Counter
from urllib.parse import quote

FAMILY_NAMES = {'flat':'Plochá','gabled':'Sedlová','hipped':'Valbová',
 'straight':'Přímý hřeben (sedlová / valbová)','skillion':'Pultová',
 'pyramidal':'Stanová','butterfly':'Korytová','connected_wings':'Spojená křídla',
 'parallel_gables':'Souběžné hřebeny','u_shaped':'Hřebeny U','ring':'Uzavřený hřeben',
 'bent':'Starší pravoúhlé L','straight_skeleton':'Straight skeleton'}


def _number(value):
    return float(value) if isinstance(value,(int,float)) and math.isfinite(value) and value>=0 else None


def _current_parts(document,building):
    parts=building.get('parts',[])
    if not document.get('comparison_mode'):
        return parts
    explicit=[p for p in parts if p.get('display_variant')=='current']
    if explicit:return explicit
    # Legacy comparison reports stored current parts last for each part_index.
    latest={}
    for part in parts:latest[part.get('part_index',0)]=part
    return list(latest.values())


def summarize_candidate_telemetry(document):
    families={};buildings=[];missing_parts=0;recorded_parts=0;reason_rows={}
    totals={'fitting_seconds':0.,'geometry_seconds':0.,'overhead_seconds':0.}
    skeleton={'eligible_calls':0,'skipped_calls':0,'eligible_buildings':0,
              'skipped_buildings':0,'attempted_buildings':0,'gate_recorded_parts':0,'gate_missing_parts':0}
    for building in document.get('buildings',[]):
        parts=_current_parts(document,building)
        measured=0;missing=0;house_families={};reason_counts=Counter()
        total=0.;analytic=0.;time_known=True;analytic_known=True
        eligible=0;skipped=0;detailed_parts=0
        for part in parts:
            result=part.get('result',{})
            timing=result.get('timing',{}) or part.get('timing',{})
            seconds=_number(timing.get('total_seconds'))
            if seconds is None:time_known=False
            else:total+=seconds
            observed=_number(timing.get('observed_ridges_seconds'))
            if observed is None:
                # An explicitly disabled module establishes a real zero.
                cfg=result.get('configuration',{})
                if cfg.get('modules',{}).get('observed_ridges') is False:observed=0.
                else:analytic_known=False
            if observed is not None:analytic+=observed
            trace=result.get('diagnostics',{}).get('candidate_telemetry',part.get('candidate_telemetry'))
            if not isinstance(trace,dict) or not isinstance(trace.get('families'),list):
                missing+=1;missing_parts+=1;skeleton['gate_missing_parts']+=1;continue
            measured+=1;recorded_parts+=1
            for entry in trace['families']:
                name=str(entry.get('family','unknown'))
                base=house_families.setdefault(name,dict(family=name,considered=0,skipped=0,failed=0,rejected=0,selected=0,
                    fitting_seconds=0.,geometry_seconds=0.,overhead_seconds=0.))
                for key in ('considered','skipped','failed','rejected','selected'):
                    base[key]+=int(_number(entry.get(key)) or 0)
                for key in totals:base[key]+=_number(entry.get(key)) or 0.
            if not trace.get('detailed'):skeleton['gate_missing_parts']+=1
            if trace.get('detailed'):
                detailed_parts+=1;skeleton['gate_recorded_parts']+=1
                for attempt in trace.get('attempts',[]):
                    if attempt.get('family')!='straight_skeleton' or attempt.get('stage')!='eligibility':continue
                    status=attempt.get('status')
                    if status=='eligible':eligible+=1
                    elif status=='skipped':skipped+=1
                    else:continue
                    reason=str(attempt.get('reason') or status)
                    reason_counts[(status,reason)]+=1
        for family,row in house_families.items():
            row['total_seconds']=sum(row[key] for key in totals)
            combined=families.setdefault(family,dict(family=family,buildings_considered=0,
                considered=0,skipped=0,failed=0,rejected=0,selected=0,
                fitting_seconds=0.,geometry_seconds=0.,overhead_seconds=0.,total_seconds=0.))
            if row['considered']:combined['buildings_considered']+=1
            for key in ('considered','skipped','failed','rejected','selected',*totals,'total_seconds'):
                combined[key]+=row[key]
        skeleton['eligible_calls']+=eligible;skeleton['skipped_calls']+=skipped
        skeleton['eligible_buildings']+=bool(eligible);skeleton['skipped_buildings']+=bool(skipped)
        sk_count=house_families.get('straight_skeleton',{}).get('considered',0)
        skeleton['attempted_buildings']+=bool(sk_count)
        for (status,reason),count in reason_counts.items():
            key=(status,reason)
            record=reason_rows.setdefault(key,dict(status=status,reason=reason,calls=0,buildings=0))
            record['calls']+=count;record['buildings']+=1
        ordered=sorted(house_families.values(),key=lambda row:row['total_seconds'],reverse=True)
        buildings.append(dict(id=building.get('id'),address=building.get('address') or building.get('name') or building.get('id'),
            status=building.get('status'),parts=len(parts),recorded_parts=measured,missing_parts=missing,
            telemetry_complete=bool(parts) and not missing,roof_compute_seconds=total if time_known else None,
            analytical_seconds=analytic if analytic_known else None,
            roof_seconds_excluding_analytical= max(0.,total-analytic) if time_known and analytic_known else None,
            family_seconds=sum(row['total_seconds'] for row in ordered) if measured else None,
            families=ordered,slowest_family=ordered[0] if ordered else None,
            skeleton_considered=sk_count if measured else None,
            skeleton_eligible_calls=eligible if detailed_parts else None,
            skeleton_skipped_calls=skipped if detailed_parts else None))
    ordered_families=sorted(families.values(),key=lambda row:row['total_seconds'],reverse=True)
    for row in ordered_families:
        for key in totals:totals[key]+=row[key]
    return dict(schema='roof-candidate-report-summary/1',building_count=len(buildings),recorded_parts=recorded_parts,
        missing_parts=missing_parts,telemetry_complete=missing_parts==0,scope='current top-level part captures including nested inference',
        families=ordered_families,totals=totals,skeleton=skeleton,
        skeleton_gate_reasons=sorted(reason_rows.values(),key=lambda row:(row['status'],-row['calls'],row['reason'])),
        buildings=sorted(buildings,key=lambda row:-(row['roof_compute_seconds'] if row['roof_compute_seconds'] is not None else -1)))


def _fmt(value,digits=3):
    return '—' if value is None else f'{value:.{digits}f}'.replace('.',',')


def _e(value):return html.escape(str(value if value is not None else ''),quote=True)


def render_candidate_telemetry(summary):
    if not summary['recorded_parts']:
        return '<section id="candidate-performance" class="performance-summary"><h2>Časy a četnost kandidátů</h2><p>V tomto starším výstupu nejsou uložené podrobné časy kandidátů. Chybějící měření neznamená nulový počet pokusů.</p></section>'
    out=['<section id="candidate-performance" class="performance-summary" aria-label="Časy a četnost kandidátů"><h2>Časy a četnost kandidátů · nová verze</h2>',
      '<p>Součet uložených pokusů včetně opakovaného hledání nad dílčími objemy a přístavky. Předchozí modely se nezapočítávají. Jeden dům může zvažovat více typů i více variant stejného typu. Časy fitu a geometrie se nesčítají znovu z vnořených výsledků.</p>']
    if summary['missing_parts']:
        out.append('<p class="candidate-warning">Neúplná telemetrie: '+str(summary['missing_parts'])+' částí nemá záznam. Součty níže zahrnují pouze naměřené pokusy.</p>')
    out.append('<div class="performance-scroll"><table><thead><tr>')
    for label in ['Typ střechy','Domů','Pokusů','Vynecháno','Chyby','Fit (s)','Geometrie (s)','Ostatní (s)','Celkem (s)']:out.append('<th>'+label+'</th>')
    out.append('</tr></thead><tbody>')
    for row in summary['families']:
        vals=[FAMILY_NAMES.get(row['family'],row['family']),row['buildings_considered'],row['considered'],row['skipped'],row['failed'],
            *[_fmt(row[key]) for key in ('fitting_seconds','geometry_seconds','overhead_seconds','total_seconds')]]
        out.append('<tr>'+''.join('<td>'+_e(value)+'</td>' for value in vals)+'</tr>')
    out.append('</tbody></table></div><p class="small">Pokus = skutečně vyhodnocený kandidát, nikoli každá iterace optimalizátoru. Počet interních výběrů se nepovažuje za počet vítězných domů. Ostatní čas zahrnuje přiřazenou konstrukci a režii kandidáta; celkový čas domu navíc zahrnuje přípravu, dělení a analytiku.</p>')
    sk=summary['skeleton']
    out.append('<h3>Kdy se zvažoval straight skeleton</h3><p>Skutečně vyhodnocen na '+str(sk['attempted_buildings'])+' domech. Pravidlo jej povolilo v '+str(sk['eligible_calls'])+' voláních ('+str(sk['eligible_buildings'])+' domů), přeskočilo v '+str(sk['skipped_calls'])+' voláních ('+str(sk['skipped_buildings'])+' domů). Jeden dům může mít povolené i přeskočené dílčí objemy.</p>')
    if sk['gate_missing_parts']:
        out.append('<p class="candidate-warning">Rozhodnutí vstupního pravidla chybí u '+str(sk['gate_missing_parts'])+' částí. Uvedené počty povolení/přeskočení jsou pouze ze zaznamenaných podrobných logů; chybějící záznam není nulová aktivita.</p>')
    if summary['skeleton_gate_reasons']:
        out.append('<div class="performance-scroll"><table><thead><tr><th>Rozhodnutí</th><th>Volání</th><th>Domů</th><th>Důvod pravidla</th></tr></thead><tbody>')
        for row in summary['skeleton_gate_reasons']:
            out.append('<tr><td>'+('Zařazen' if row['status']=='eligible' else 'Přeskočen')+'</td><td>'+str(row['calls'])+'</td><td>'+str(row['buildings'])+'</td><td>'+_e(row['reason'])+'</td></tr>')
        out.append('</tbody></table></div>')
    out.append('<h3>Domy podle délky výpočtu</h3><div class="performance-scroll"><table><thead><tr>')
    for label in ['Dům','Výpočet střechy (s)','Analytické řezy (s)','Bez analytiky (s)','Nejdražší rodina kandidátů','Pokusů skeletonu','Záznam']:out.append('<th>'+label+'</th>')
    out.append('</tr></thead><tbody>')
    for row in summary['buildings']:
        expensive=row['slowest_family']
        heavy=(FAMILY_NAMES.get(expensive['family'],expensive['family'])+' · '+_fmt(expensive['total_seconds'])+' s') if expensive else '—'
        coverage='úplný' if row['telemetry_complete'] else 'částečný / chybí'
        out.append('<tr><td><a href="#'+_e(quote(str(row['id']),safe=''))+'">'+_e(row['address'])+'</a></td>'+''.join('<td>'+_e(value)+'</td>' for value in [
          _fmt(row['roof_compute_seconds']),_fmt(row['analytical_seconds']),_fmt(row['roof_seconds_excluding_analytical']),heavy,
          row['skeleton_considered'] if row['skeleton_considered'] is not None else '—',coverage])+'</tr>')
    out.append('</tbody></table></div><p class="small">Tabulky vznikly z JSON při tvorbě reportu. Prohlížeč nic nepřepočítává. Podrobná pořadí pokusů jsou u jednotlivých modelů v rozbalovacím záznamu a v JSON.</p></section>')
    return ''.join(out)
