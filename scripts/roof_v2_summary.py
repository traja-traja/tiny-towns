"""Summarise measured local runs, without classifying model appearance."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import statistics
import platform
from html import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'cities/ceske-budejovice/experiments/roof-v2'
CACHE = ROOT/'.work/cb-roof-v2'


def load(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def write_index(summary):
    models, timing = summary['models'], summary['timing']
    stages = [('Příprava bodů (první čtení LAZ)', timing['prepare'], summary['process_metrics']['prepare']),
              ('Odhad 30 střech a zápis výsledků', timing['fit_batch'], summary['process_metrics']['fit'])]
    render = summary['process_metrics'].get('tiles')
    if render and render.get('exit_code') == 0:
        stages.append(('Render 28 dotčených dlaždic ve dvou režimech',
                       {'wall_seconds':render['elapsed_seconds'],'cpu_seconds':render['cpu_seconds']},render))
    rows = ''.join(f'<tr><td>{escape(label)}</td><td>{metric["wall_seconds"]:.1f} s</td>'
                   f'<td>{metric["cpu_seconds"]:.1f} s</td><td>{proc["peak_job_commit_bytes"]/1e6:.0f} MB</td></tr>'
                   for label, metric, proc in stages)
    compare = summary['comparison']['aggregate']
    comparison_rows = ''
    for label, key in [('Medián odchylky','p50_abs_m'),('90. percentil','p90_abs_m'),('RMSE','rmse_m')]:
        comparison_rows += f'<tr><td>{label}</td><td>{compare["old"]["paired_metrics"][key]:.3f} m</td><td>{compare["new"]["paired_metrics"][key]:.3f} m</td></tr>'
    comparison_rows += f'<tr><td>Střešní trojúhelníky</td><td>{compare["old"]["roof_face_count"]}</td><td>{compare["new"]["roof_face_count"]}</td></tr>'
    names = {'flat':'Plochá', 'flat_levels':'Dvě ploché úrovně', 'gabled':'Sedlová',
             'hipped':'Valbová', 'pyramidal':'Stanová', 'skillion':'Pultová', 'compound':'Složená'}
    model_rows = ''.join(f'<tr><td>{escape(names.get(kind,kind))}</td><td>{count}</td></tr>' for kind,count in models['types'].items())
    page = f'''<!doctype html><html lang="cs"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jednoduché střechy · ČB · výsledky v2.3</title><style>
*{{box-sizing:border-box}}body{{font:16px/1.55 system-ui,sans-serif;margin:0;background:#f3f4ef;color:#263b32}}main{{max-width:1000px;margin:auto;padding:32px 22px 60px}}h1{{font-size:clamp(28px,5vw,44px);line-height:1.1}}h2{{margin-top:32px;font-size:23px}}.intro{{font-size:19px;max-width:800px}}nav{{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}}nav a{{display:block;border:1px solid #a9b9ad;border-radius:8px;padding:12px 18px;background:white;text-decoration:none;font-weight:600}}a{{color:#256346}}.notice{{border-left:4px solid #b98a3a;padding:12px 18px;background:#fff7e8}}table{{border-collapse:collapse;width:100%;background:#fff;margin:15px 0}}td,th{{padding:10px 13px;border-bottom:1px solid #dce2d8;text-align:left}}th{{background:#e8eee4}}.scroll{{overflow:auto}}small{{color:#5e6d62}}code{{overflow-wrap:anywhere}}</style><main>
<p><small>Izomapa · České Budějovice · verze {escape(', '.join(summary['algorithm_versions']))}</small></p>
<h1>Jednoduché střechy z hustého mračna bodů</h1>
<p class="intro">Nový algoritmus a vývojový vzorek 30 domů. ČÚZK DMPOK, nominálně 25 bodů/m². Výpočty i rendery proběhly místně, bez Rooferu a bez AI posuzování vzhledu.</p>
<nav><a href="report.html">Prohlédnout 3D modely</a><a href="tiles/report.html">Před / po v mapě</a><a href="comparison.html">Číselné srovnání</a></nav>
<div class="notice"><strong>Určeno k tvému vizuálnímu posouzení.</strong> Všechny exportované objemy prošly kontrolou uzavřenosti a geometrie. {models['review_required']} z 30 budov má alespoň jeden příznak ke kontrole: například nejasný typ, slabší podporu ploch nebo výraznější odchylky. Počet příznaků není počet prokázaných chyb.</div>
<h2>Co algoritmus dělá</h2><p>Hledá hlavní sklony, polohu hřebene nebo vrcholu, oddělí stěny od střechy a porovná několik jednoduchých šablon. Zvlášť řeší ploché výškové úrovně a záložní rozdělení velkých hmot. Vybere jeden model a uchová důvody nejistoty i alternativy. <a href="ALGORITHM.md">Úplný popis algoritmu</a> · <a href="RUN.md">Příkazy pro spuštění</a>.</p>
<h2>Čas a paměť</h2><div class="scroll"><table><thead><tr><th>Krok</th><th>Čas běhu</th><th>CPU čas</th><th>Špička paměti procesů</th></tr></thead><tbody>{rows}</tbody></table></div>
<p><small>První příprava četla dvě lokální LAZ dlaždice; další běh používá malou cache. Paměť je Windows peak committed memory celé úlohy. Samotná dávka fitování trvala {timing['fit_batch']['wall_seconds']:.1f} s, včetně spuštění a ochranného wrapperu {summary['process_metrics']['fit']['elapsed_seconds']:.1f} s. Podrobnosti, přesné parametry a kontrolní součty: <a href="benchmark.json">benchmark.json</a>.</small></p>
<h2>Jednodušší geometrie má i svůj kompromis</h2><p>Na pěti domech společných s původní hustou verzí se obě geometrie porovnaly se stejnými 6 989 body. Nová verze má méně trojúhelníků a mírně lepší medián, ale horší vyšší odchylky:</p>
<table><thead><tr><th>Metrika</th><th>Původní</th><th>Nová</th></tr></thead><tbody>{comparison_rows}</tbody></table>
<p>Nejde o důkaz plošně vyšší přesnosti. Původní výpočet mohl stejné body už použít při fitování; současný vzorek je vývojový. Komíny a další detaily zůstávají ve statistikách. <a href="comparison.html">Rozpad po jednotlivých domech</a>.</p>
<h2>Co je v náhledu</h2><p>3D prohlížeč umožňuje zapnout body, hřebeny, okapy, hrany a stěny. Mapa porovnává původní podobu, novou geometrii a diagnostické zvýraznění. Pro úsporu paměti má nový mapový náhled menší podkladové textury a stínovou mapu; samotná geometrie střech tím není zjednodušena navíc.</p>
<table><thead><tr><th>Zvolený typ střechy</th><th>Počet</th></tr></thead><tbody>{model_rows}</tbody></table>
<p>Původní barvy jsou uložené s původem v datech; nové budovy v mapovém náhledu používají omezené tlumené palety. Podrobnosti: <a href="tiles/color-audit.json">barvy</a>, <a href="diagnostics.json">diagnostika</a>, <a href="inputs.json">vstupy</a>, <a href="sample.json">výběr domů</a>.</p>
<p><small>28 syntetických a geometrických testů prošlo. Samostatně prošly testy vstupů, rendereru a funkční kontrola všech 30 modelů v prohlížeči. Optické hodnocení provede uživatel. Podklady © ČÚZK, Overture Maps a přispěvatelé OpenStreetMap.</small></p>
</main></html>'''
    (OUT/'index.html').write_text(page,encoding='utf-8')


def main():
    inputs, results = load(OUT/'inputs.json'), load(OUT/'results.json')
    if results['status'] != 'complete':
        raise ValueError('Refusing to summarise an unfinished batch as complete')
    parts = [p for b in results['buildings'] for p in b['parts'] if p.get('result')]
    diagnostics = [p['result']['diagnostics'] for p in parts]
    meshes = [p['result']['model']['mesh'] for p in parts]
    errors = [p['external_metrics'] for p in parts if p.get('external_metrics',{}).get('evaluated')]
    n = sum(e['evaluated'] for e in errors)
    timing = [b['timing']['wall_seconds'] for b in results['buildings']]
    files = ['scripts/roof_v2.py', 'scripts/roof_v2_geometry.py', 'scripts/cb_roof_v2.py',
             'scripts/roof_v2_tiles.py', 'scripts/roof_v2_tiles_driver.mjs',
             'scripts/roof_v2_report.py', 'scripts/roof_v2_viewer.js',
             'scripts/roof_v2_compare.py', 'scripts/roof_v2_summary.py']
    summary = {
        'schema':'roof-v2-benchmark/1',
        'algorithm_versions': sorted({p['result']['algorithm'] for p in parts}),
        'python':platform.python_version(), 'platform':platform.platform(),
        'input': {'source':'ČÚZK DMPOK', 'nominal_points_per_m2':25,
                  'buildings':len(inputs['buildings']),
                  'train_points':sum(p['measurement']['train_points'] for b in inputs['buildings'] for p in b['parts']),
                  'holdout_points':sum(p['measurement']['holdout_points'] for b in inputs['buildings'] for p in b['parts']),
                  'cache_bytes':inputs['output_cache_bytes'], 'sample_sha256':inputs['sample_sha256']},
        'models': {'building_count':len(results['buildings']), 'part_count':len(parts),
                   'all_meshes_valid':all(m['diagnostics']['valid'] for m in meshes),
                   'types':dict(Counter(p['result']['model']['type'] for p in parts)),
                   'review_required':sum(d['review_required'] for d in diagnostics),
                   'flag_counts':dict(Counter(f for d in diagnostics for f in d['flags'])),
                   'roof_regions':sum(len(p['result']['model']['regions']) for p in parts),
                   'roof_triangles':sum(len(m['roof_faces']) for m in meshes),
                   'median_roof_regions':statistics.median(len(p['result']['model']['regions']) for p in parts)},
        'same_source_holdout': {
            'evaluated_points':n,
            'point_weighted_rmse_m':math.sqrt(sum(e['rmse_m']**2*e['evaluated'] for e in errors)/n),
            'point_weighted_within_05m':sum(e['within_05m']*e['evaluated'] for e in errors)/n,
            'median_of_building_median_abs_m':statistics.median(e['median_abs_m'] for e in errors),
            'median_of_building_p90_abs_m':statistics.median(e['p90_abs_m'] for e in errors),
            'limitation':'Development sample; correlated survey; includes roof details. Not independent architectural truth or calibrated probability.'},
        'timing': {'prepare':inputs['timing'], 'fit_batch':results['timing'],
                   'sum_building_seconds':sum(timing), 'median_building_seconds':statistics.median(timing),
                   'max_building_seconds':max(timing)},
        'process_metrics': {'prepare':load(CACHE/'prepare.log.metrics.json'),
                           'fit':load(CACHE/'run.log.metrics.json'),
                           'tiles':load(OUT/'tiles/render.log.metrics.json')},
        'functional_qa':{'interface':load(OUT/'viewer-qa.json'),
                         'final_geometry':load(OUT/'viewer-qa-geometry.json')},
        'tiles':load(OUT/'tiles/manifest.json'),
        'comparison':load(OUT/'comparison.json'),
        'source_code_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
        'results_sha256':hashlib.sha256((OUT/'results.json').read_bytes()).hexdigest(),
    }
    (OUT/'benchmark.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    write_index(summary)
    print(json.dumps({k:summary[k] for k in ('algorithm_versions','models','same_source_holdout','timing')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
