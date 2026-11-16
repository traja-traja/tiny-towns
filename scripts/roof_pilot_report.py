"""Build a self-contained, offline review of the roof-pilot/1 result JSON.

Usage: python scripts/roof_pilot_report.py results.json report.html
Only the requested HTML is written. No model generation or downloads occur.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics


SOURCES = ("dmp1g", "dmpok")
METHODS = ("baseline", "templates", "roofer")


def finite(value):
    """Return an actual finite number, excluding booleans and numeric strings."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    return value


def percentile(values, fraction):
    """Linearly interpolated percentile, like NumPy's default quantile."""
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * fraction
    low, high = math.floor(pos), math.ceil(pos)
    return values[low] + (values[high] - values[low]) * (pos - low)


def model_is_renderable(model):
    if not isinstance(model, dict):
        return False
    vertices, faces = model.get("vertices"), model.get("faces")
    if not isinstance(vertices, list) or not isinstance(faces, list):
        return False
    valid = {i for i, v in enumerate(vertices)
             if isinstance(v, list) and len(v) >= 3 and all(finite(n) for n in v[:3])}
    return any(isinstance(f, list) and len(f) >= 3 and
               all(isinstance(i, int) and not isinstance(i, bool) and i in valid for i in f)
               for f in faces)


def prepare_data(data):
    """Normalize optional fields and derive summary counts without inventing runs."""
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object")
    result = clean_json(data)
    result["runs"] = [r for r in (result.get("runs") or []) if isinstance(r, dict)]
    samples = result.get("samples") or []
    if isinstance(samples, dict):
        samples = samples.get("features", [])
    buildings = {}
    unidentified = 0
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        props = sample.get("properties", sample)
        if not isinstance(props, dict):
            continue
        bid = props.get("id") or props.get("building_id") or props.get("source_building_id")
        if bid is None:
            unidentified += 1
            continue
        bid = str(bid)
        buildings[bid] = dict(props, id=bid)
    selected = {}
    duplicates = 0
    unknown = 0
    for run in result["runs"]:
        bid = run.get("id") or run.get("building_id")
        if bid is None:
            unknown += 1
            continue
        bid = str(bid)
        run["id"] = bid
        if bid not in buildings:
            buildings[bid] = {"id": bid, "name": run.get("name"), "category": run.get("category")}
        if run.get("source") not in SOURCES or run.get("method") not in METHODS:
            unknown += 1
            continue
        key = (run["source"], run["method"], bid)
        duplicates += key in selected
        selected[key] = run
    result["buildings"] = list(buildings.values())
    result["runs"] = list(selected.values())
    result["review_warnings"] = []
    if duplicates:
        result["review_warnings"].append(
            f"Duplicitní záznamy: {duplicates}. Pro každý objekt, zdroj a metodu se hodnotí poslední záznam; časy předchozích pokusů nejsou zahrnuté.")
    if unknown:
        result["review_warnings"].append(f"Nezařazené záznamy běhů s neznámým zdrojem, metodou nebo bez ID: {unknown}.")
    if unidentified:
        result["review_warnings"].append(f"Vzorky bez ID: {unidentified}; nelze je spojit s výsledky ani zahrnout do počtu chybějících běhů.")
    result["summary"] = []
    for source in SOURCES:
        for method in METHODS:
            runs = [r for (s, m, _), r in selected.items() if s == source and m == method]
            times = [r["elapsed_seconds"] for r in runs
                     if finite(r.get("elapsed_seconds")) and r["elapsed_seconds"] >= 0]
            successful = [r for r in runs if r.get("status") == "ok"]
            metric_values = {}
            for metric in ("holdout_rmse_m", "holdout_mae_m", "holdout_coverage"):
                vals = [r["metrics"].get(metric) for r in successful if isinstance(r.get("metrics"), dict)]
                vals = [v for v in vals if finite(v) and v >= 0 and (metric != "holdout_coverage" or v <= 1)]
                metric_values[metric] = statistics.median(vals) if vals else None
                metric_values[metric + "_n"] = len(vals)
            result["summary"].append({
                "source": source, "method": method, "expected": len(buildings),
                "ok": len(successful),
                "renderable": sum(model_is_renderable(r.get("model")) for r in successful),
                "failed": sum(r.get("status") == "failed" for r in runs),
                "insufficient": sum(r.get("status") == "insufficient" for r in runs),
                "other": sum(r.get("status") not in ("ok", "failed", "insufficient") for r in runs),
                "missing": len(buildings) - len(runs),
                "time_n": len(times),
                "time_total": sum(times) if times else None,
                "time_median": statistics.median(times) if times else None,
                "time_p90": percentile(times, .9),
                **metric_values,
            })
    result["complete_buildings"] = sum(
        all((source, method, bid) in selected and
            selected[source, method, bid].get("status") == "ok" and
            model_is_renderable(selected[source, method, bid].get("model"))
            for source in SOURCES for method in METHODS)
        for bid in buildings
    )
    return result


def build_report(data):
    payload = json.dumps(prepare_data(data), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    # Escape the HTML parser's script terminator, even in untrusted place names.
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return HTML.replace("__RESULT_DATA__", payload)


HTML = r'''<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>Velešín — porovnání střech</title>
<style>
:root{--ink:#1c2d32;--muted:#5e7177;--line:#dbe4e5;--accent:#176e69;--bad:#a04729;--paper:#fff;--bg:#f2f5f4}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}main{max-width:1540px;margin:auto;padding:32px 28px 56px}h1{font-size:clamp(28px,3vw,42px);letter-spacing:-.04em;line-height:1.15;margin:5px 0 12px}h2{font-size:21px;margin:0 0 15px}p{margin:8px 0 14px}.eyebrow{color:var(--accent);font-size:12px;text-transform:uppercase;font-weight:750;letter-spacing:.12em}.intro{max-width:950px;color:var(--muted)}.meta{font-size:12px;color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:23px 0}.stat,.section{background:var(--paper);border:1px solid var(--line);border-radius:14px}.stat{padding:17px 20px}.stat strong{font-size:28px;display:block;line-height:1.2;letter-spacing:-.03em}.stat span{color:var(--muted);font-size:13px}.section{padding:23px;margin-bottom:22px}.table-wrap{overflow:auto}table{border-collapse:collapse;min-width:1150px;width:100%;font-variant-numeric:tabular-nums;font-size:13px}th,td{text-align:right;padding:10px 11px;border-bottom:1px solid var(--line);white-space:nowrap}th{text-transform:none;color:var(--muted);font-weight:650;font-size:12px}th:first-child,td:first-child{text-align:left}tbody tr:nth-child(3){border-bottom:2px solid #b7c9c9}tbody tr:hover{background:#f3f8f7}.good{color:var(--accent);font-weight:650}.bad{color:var(--bad)}.small{font-size:12px;color:var(--muted)}.controls{display:flex;align-items:end;gap:20px;flex-wrap:wrap;margin:16px 0 12px}.control{display:grid;gap:5px;flex:1;min-width:180px}.control:first-child{flex:3;min-width:min(100%,340px)}label{font-size:12px;font-weight:650;color:var(--muted)}select,button{border:1px solid #b8c9c9;border-radius:7px;background:#fff;color:var(--ink);font:inherit;padding:8px 11px}select{width:100%}button{cursor:pointer;white-space:nowrap}button:hover{background:#edf5f3}input[type=range]{accent-color:var(--accent);width:100%;height:34px;margin:0}.building-meta{min-height:25px;overflow-wrap:anywhere}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:17px}.card{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#fff;min-width:0}.card-head{display:flex;align-items:start;justify-content:space-between;gap:8px;padding:13px 15px 9px}.card-head h3{font-size:15px;line-height:1.35;margin:1px 0}.source{font-size:11px;color:var(--muted);font-weight:650;letter-spacing:.07em}.badge{font-size:11px;border-radius:20px;padding:3px 8px;background:#e8f2ef;color:var(--accent);white-space:nowrap}.badge.bad{background:#faeee8;color:var(--bad)}.view{height:245px;position:relative;background:linear-gradient(#f8faf9,#edf2ef)}canvas{display:block;width:100%;height:100%}.empty{position:absolute;inset:0;display:grid;place-items:center;text-align:center;padding:26px;color:var(--muted);font-size:14px}.card-data{padding:12px 15px 14px;font-size:12px}.model-shape{font-weight:650;margin-bottom:8px}.values{display:grid;grid-template-columns:1fr 1fr;gap:5px 12px;font-variant-numeric:tabular-nums}.values span{color:var(--muted)}.error{color:var(--bad);white-space:pre-wrap;overflow-wrap:anywhere;margin:9px 0 0;font-size:12px;max-height:140px;overflow:auto}.notice{padding:13px 16px;border-left:3px solid #c59045;background:#fff8ea;border-radius:0 7px 7px 0;margin:12px 0}.limits{display:grid;grid-template-columns:1fr 1fr;gap:16px 28px}.limits p{margin:0;font-size:13px;color:var(--muted)}.limits strong{display:block;color:var(--ink);margin-bottom:4px}details{border-top:1px solid var(--line);margin-top:14px;padding-top:12px}summary{cursor:pointer;font-weight:650;font-size:13px}pre{font:12px/1.5 ui-monospace,Consolas,monospace;max-height:400px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f6;padding:14px;border-radius:7px}.note-list{padding-left:20px;font-size:13px}.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:12px 0}.dot{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;background:#b57c58}.dot.wall{background:#c4ccc5}footer{font-size:12px;color:var(--muted)}@media(max-width:1000px){main{padding:22px 16px}.section{padding:18px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){.grid,.limits{grid-template-columns:1fr}.stats{gap:8px}.stat{padding:13px 10px}.stat strong{font-size:24px}.stat span{font-size:11px}.controls{gap:12px}.control{min-width:140px}.section{padding:15px}.view{height:275px}}@media print{body{background:white}main{max-width:none;padding:0}.section{break-inside:avoid}.controls button{display:none}.grid{grid-template-columns:repeat(3,minmax(0,1fr))}.view{height:180px}.table-wrap{overflow:visible}table{min-width:0;font-size:9px}td,th{padding:5px 3px}.stats{margin:15px 0}}
</style></head><body><main>
<header><div class="eyebrow">Izomapa · Velešín · výpočetní pilot</div><h1>Střechy ze dvou datových zdrojů</h1>
<p class="intro">Stejné budovy, tři metody a dva podklady ČÚZK. Porovnání ukazuje skutečně vytvořenou geometrii, výpočetní časy a shodu s odloženými body. Chybějící výsledky zůstávají viditelné.</p><p class="meta" id="created"></p></header>
<div class="stats"><div class="stat"><strong id="building-count">—</strong><span>zdrojových půdorysů ve výběru</span></div><div class="stat"><strong id="complete-count">—</strong><span>půdorysů má všech šest modelů</span></div><div class="stat"><strong id="run-count">—</strong><span>úspěšných běhů / očekávaných</span></div></div>
<div id="warnings"></div>
<section class="section"><h2>Časy a dostupnost výsledků</h2><div class="table-wrap"><table><thead><tr><th>Zdroj / metoda</th><th>Úspěch / výběr</th><th>Modely</th><th>Chyba</th><th>Málo dat</th><th>Chybí</th><th>Čas celkem</th><th>Medián</th><th>P90</th><th>RMSE · med.</th><th>MAE · med.</th><th>Pokrytí · med.</th></tr></thead><tbody id="summary"></tbody></table></div>
<p class="small"><strong>Základ je aproximace současného generátoru mapy, bez všech jeho výjimek a ručních modelů.</strong> U základu a šablon tabulka sčítá mediány tří opakování modelu včetně tvorby mesh. Roofer uvádí vlastní vnitřní časy rekonstrukce. Režie procesů a I/O jsou vykázány zvlášť.</p>
<p class="small">Časy zahrnují zaznamenané běhy dané metody včetně selhání; stahování a příprava dat se do nich nepřičítají. P90 je interpolovaný 90. percentil. Diagnostické metriky jsou mediány dostupných hodnot úspěšných běhů, nikoli chyba celého města. Počty platných hodnot jsou v popisku buňky.</p>
<p class="small">„Modely“ počítá úspěšné běhy s alespoň jednou vykreslitelnou plochou, včetně náhradní extruze či nižšího LoD; nejde o počet ověřených střech LoD2. „Chybí“ zahrnuje nezaznamenané běhy; neznámé stavy se uvádějí v poznámce.</p></section>
<section class="section"><h2>Porovnání konkrétní budovy</h2>
<div class="controls"><div class="control"><label for="building">Budova nebo část komplexu</label><select id="building"></select></div><div class="control"><label for="rotation">Společné otočení · <span id="angle">35°</span></label><input id="rotation" type="range" min="0" max="360" step="1" value="35"></div><button id="reset" type="button">Výchozí pohled</button></div>
<p class="meta building-meta" id="building-meta"></p><p class="small" id="source-roof"></p><div class="legend"><span><i class="dot"></i>šikmé a vodorovné plochy</span><span><i class="dot wall"></i>svislé plochy</span><span>Jednotné měřítko a pohled pro všech šest modelů; barvy jsou pouze orientační.</span></div>
<div class="grid" id="models"></div><p class="small" id="scale-note"></p><p class="small">Osa hřebene používá projekční XY v S-JTSK, po směru hodinových ručiček od +Y, modulo 180°. Není to skutečný zeměpisný azimut.</p>
<details><summary>Údaje o vybraném objektu</summary><pre id="sample-details"></pre></details></section>
<section class="section"><h2>Jak porovnání číst</h2><div class="limits">
<p><strong>Odložené body nejsou zaměření skutečné střechy.</strong>RMSE a MAE měří shodu s body vynechanými při přizpůsobování. Stejný zdroj může mít chyby, vegetaci či nedostatečné pokrytí; nízká chyba sama nepotvrzuje správný tvar. Pokrytí vyjadřuje podíl odložených bodů, pro které šlo výšku modelu vyhodnotit.</p>
<p><strong>Základní model je experimentální aproximace.</strong>Varianta „Základ“ napodobuje jednoduché objemové zpracování. Není přesnou kopií výsledku současného rendereru Izomapy. Všechny zobrazené modely pocházejí z příslušných výpočetních běhů.</p>
<p><strong>Datové zdroje nemusí zachycovat stejný rok.</strong>DMP 1G a DMP OK mohou mít odlišná data pořízení, hustotu i zpracování. Rozdíl může znamenat stavební změnu, nikoli chybu metody. Ověřujte konkrétní metadata zdroje.</p>
<p><strong>Objemový model nezachycuje celý pohled z ulice.</strong>Zdejší zjednodušené modely neověřují fasády, okna, podloubí ani průchody. Více zdrojových půdorysů může patřit jedné budově nebo komplexu. Bez všech úspěšných běhů nelze označit celý pilot za dokončený.</p>
</div><details><summary>Poznámky běhu</summary><ul class="note-list" id="notes"></ul></details><details><summary>Metadata a časy zpracování zdrojů</summary><pre id="source-details"></pre></details><details><summary>Celkové procesní metriky</summary><pre id="process-details"></pre></details></section>
<footer>Samostatný přehled bez síťových požadavků. Geometrie v metrech: lokální XY vůči středu objektu, výšky Z vůči terénu. Vstupní schéma <span id="schema"></span>.</footer>
</main><script type="application/json" id="result-data">__RESULT_DATA__</script><script>
"use strict";
const D=JSON.parse(document.getElementById('result-data').textContent);
const sources=['dmp1g','dmpok'], methods=['baseline','templates','roofer'];
const sourceNames={dmp1g:'DMP 1G',dmpok:'DMP OK'}, methodNames={baseline:'Základ',templates:'Přizpůsobení šablon',roofer:'Roofer'};
const categoryNames={townhall:'radnice',church:'kostel',former_church:'bývalý kostel',water_tower:'vodárenská věž',kindergarten:'mateřská škola',kindergarten_extension_candidate:'kandidát části areálu MŠ',panel:'panelový dům',panel_block:'panelový dům',historic:'historický dům',historic_house:'historický dům',sport:'sportovní objekt',sports:'sportovní objekt'};
const shapeNames={flat:'plochá',shed:'pultová',gabled:'sedlová',hipped:'valbová',barrel:'válcová',pyramidal:'jehlanová'};
const qualityNames={review:'vyžaduje kontrolu',supported:'heuristicky podpořeno'};
const warningNames={few_roof_points:'Málo střešních bodů.',low_spatial_coverage:'Slabé prostorové pokrytí.',poor_template_fit:'Nízká shoda se šablonou.',ambiguous_roof_family:'Více typů střech má podobné skóre.',no_semantic_roof_surface:'Model nemá označenou střešní plochu.'};
const $=id=>document.getElementById(id), num=(x,d=2)=>Number.isFinite(x)?x.toLocaleString('cs-CZ',{maximumFractionDigits:d,minimumFractionDigits:d}):'—';
const seconds=x=>Number.isFinite(x)?num(x,x<1?3:2)+' s':'—';
const metres=x=>Number.isFinite(x)?num(x,2)+' m':'—';
const percent=x=>Number.isFinite(x)?num(x*100,1)+' %':'—';
function el(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function dataCell(row,value,title,cls){const c=el('td',value,cls);if(title)c.title=title;row.append(c);}
$('created').textContent='Výsledky vytvořeny: '+(D.created_at||'neuvedeno');$('schema').textContent=D.schema||'neuvedeno';
$('building-count').textContent=D.buildings.length;$('complete-count').textContent=D.complete_buildings+' / '+D.buildings.length;
const ok=D.summary.reduce((n,r)=>n+r.ok,0);$('run-count').textContent=ok+' / '+(D.buildings.length*6);
for(const text of D.review_warnings||[])$('warnings').append(el('p',text,'notice'));
if(D.complete_buildings<D.buildings.length)$('warnings').append(el('p','Pilot není kompletní: alespoň jeden objekt nemá všech šest úspěšně vytvořených modelů. Počty a mezery uvádí tabulka níže.','notice'));
for(const r of D.summary){const row=el('tr');dataCell(row,sourceNames[r.source]+' · '+methodNames[r.method]);dataCell(row,r.ok+' / '+r.expected,'Stav ok',r.ok===r.expected?'good':'');dataCell(row,r.renderable);dataCell(row,r.failed,null,r.failed?'bad':'');dataCell(row,r.insufficient);dataCell(row,r.missing,null,r.missing?'bad':'');const timing=r.time_n+' platných měření času';dataCell(row,seconds(r.time_total),timing);dataCell(row,seconds(r.time_median),timing);dataCell(row,seconds(r.time_p90),timing);dataCell(row,metres(r.holdout_rmse_m),r.holdout_rmse_m_n+' platných hodnot');dataCell(row,metres(r.holdout_mae_m),r.holdout_mae_m_n+' platných hodnot');dataCell(row,percent(r.holdout_coverage),r.holdout_coverage_n+' platných hodnot');$('summary').append(row);if(r.other)$('warnings').append(el('p',sourceNames[r.source]+' / '+methodNames[r.method]+': '+r.other+' běhů s jiným nebo chybějícím stavem.','notice'));}
for(const b of D.buildings){const o=el('option',b.name||b.id);o.value=b.id;$('building').append(o);}
const notes=Array.isArray(D.notes)?D.notes:[];for(const note of notes)$('notes').append(el('li',typeof note==='string'?note:JSON.stringify(note)));if(!notes.length)$('notes').append(el('li','Bez dalších poznámek.'));
$('source-details').textContent=JSON.stringify(D.source_metrics||{},null,2);
$('process-details').textContent=JSON.stringify(D.process_metrics||{},null,2);
const runIndex=new Map(D.runs.map(r=>[[r.id,r.source,r.method].join('|'),r]));
const cards=[];
for(const source of sources)for(const method of methods){const card=el('article',undefined,'card'),head=el('div',undefined,'card-head'),title=el('div');title.append(el('div',sourceNames[source],'source'),el('h3',methodNames[method]));const badge=el('span','','badge');head.append(title,badge);const view=el('div',undefined,'view'),canvas=el('canvas');canvas.setAttribute('role','img');canvas.setAttribute('aria-label',sourceNames[source]+' – '+methodNames[method]);const empty=el('div','','empty');view.append(canvas,empty);const body=el('div',undefined,'card-data');card.append(head,view,body);$('models').append(card);cards.push({source,method,card,canvas,empty,badge,body,mesh:null});}
function readMesh(model){if(!model||!Array.isArray(model.vertices)||!Array.isArray(model.faces))return null;const vs=model.vertices;const valid=v=>Array.isArray(v)&&v.length>=3&&v.slice(0,3).every(Number.isFinite);const fs=model.faces.filter(f=>Array.isArray(f)&&f.length>=3&&f.every(i=>Number.isInteger(i)&&i>=0&&i<vs.length&&valid(vs[i])));if(!fs.length)return null;return {vertices:vs,faces:fs,used:[...new Set(fs.flat())]};}
function rooferInfo(model){const lods=Array.isArray(model.lods)?model.lods:(model.lods==null?[]:[model.lods]);const numbers=lods.map(v=>Number(v)).filter(Number.isFinite);const attrs=model.attributes||{},metrics=model.metrics||{};const mode=model.rf_extrusion_mode??attrs.rf_extrusion_mode??attrs.extrusion_mode??metrics.roofer_extrusion_mode;const low=numbers.some(n=>n<2),nonstandard=mode!=null&&String(mode)!=='standard';return {lods,mode,low,nonstandard,unknown:!numbers.length};}
function modelDetails(card,run){const model=run.model||{},p=model.params||{};const detail=el('div');
if(Number.isFinite(p.ridge_azimuth_deg)){const line=el('p','Osa hřebene '+num(p.ridge_azimuth_deg,1)+'° (S-JTSK, 0–180°)','small');line.title='Neorientovaná osa v projekčních souřadnicích XY, po směru hodinových ručiček od +Y; nejde o zeměpisný azimut.';detail.append(line);}
const pitch=[];for(const [label,angle,slope] of [['levý',p.pitch_left_deg,p.slope_left],['pravý',p.pitch_right_deg,p.slope_right],['boční',p.pitch_side_deg,p.slope_side],['valba',p.pitch_end_deg,p.slope_end]]){const degrees=Number.isFinite(angle)?angle:Number.isFinite(slope)?Math.atan(Math.abs(slope))*180/Math.PI:null;if(Number.isFinite(degrees))pitch.push(label+' '+num(degrees,1)+'°');}if(pitch.length)detail.append(el('p','Sklon: '+pitch.join(' · '),'small'));
if(model.shape==='shed'){const degrees=Number.isFinite(p.pitch_deg)?p.pitch_deg:(Number.isFinite(p.slope_x)&&Number.isFinite(p.slope_y)?Math.atan(Math.hypot(p.slope_x,p.slope_y))*180/Math.PI:null);if(Number.isFinite(degrees))detail.append(el('p','Sklon pultu: '+num(degrees,1)+'°','small'));}
const quality=model.quality||run.quality||{};if(quality.label)detail.append(el('p','Kvalita: '+(qualityNames[quality.label]||quality.label)+' (heuristika, nikoli pravděpodobnost správnosti).',quality.label==='review'?'error':'small'));
if(card.method==='roofer'){const info=rooferInfo(model);detail.append(el('p','LoD: '+(info.lods.length?info.lods.join(', '):'neuvedeno')+' · Režim extruze: '+(info.mode??'neuvedeno'),'small'));if(info.low)detail.append(el('p','Nižší LoD: tento objem nepředstavuje rekonstruovanou střechu LoD2.','error'));if(info.nonstandard)detail.append(el('p','Nestandardní nebo náhradní extruze (fallback): výsledek nelze vydávat za úspěšnou rekonstrukci střechy LoD2.','error'));if(info.unknown)detail.append(el('p','LoD není doložené; z geometrie samotné zde nevyvozujeme úspěch LoD2.','error'));}
const rawWarnings=[model.warnings,quality.warnings,run.warnings].flatMap(v=>Array.isArray(v)?v:v?[v]:[]);const warnings=[...new Set(rawWarnings.map(v=>typeof v==='string'?v:JSON.stringify(v)))];if(warnings.length){const list=el('ul',undefined,'note-list error');for(const warning of warnings)list.append(el('li',warningNames[warning]||warning));detail.append(list);}card.body.append(detail);}
function updateBuilding(){const id=$('building').value,b=D.buildings.find(x=>x.id===id);$('sample-details').textContent=JSON.stringify(b||{},null,2);$('building-meta').textContent=b?[(categoryNames[b.category]||b.category),b.id,b.identity_note||(b.identity||{}).note].filter(Boolean).join(' · '):'V datech není žádný objekt.';const sourceShape=b&&((b.source_attributes||{}).roof_shape??b.roof_shape);$('source-roof').textContent=sourceShape?'roof_shape = '+sourceShape+' — atribut ve zdroji, ne reference.':'Zdrojový atribut roof_shape není uveden.';
for(const card of cards){const r=runIndex.get([id,card.source,card.method].join('|'));card.mesh=r&&r.status==='ok'?readMesh(r.model):null;const info=card.method==='roofer'&&r&&r.model?rooferInfo(r.model):null;const caution=info&&(info.low||info.nonstandard||info.unknown);const success=info&&info.low?'Model · nižší LoD':info&&info.nonstandard?'Model · fallback':info&&info.unknown?'Model · LoD neznámé':'Model vytvořen';const state=!r?'Chybí běh':r.status==='ok'?(card.mesh?success:'Bez geometrie'):r.status==='insufficient'?'Málo bodů':r.status==='failed'?'Chyba běhu':'Neznámý stav';card.badge.textContent=state;card.badge.className='badge'+(card.mesh&&!caution?'':' bad');card.empty.textContent=card.mesh?'':state;card.empty.style.display=card.mesh?'none':'grid';card.body.replaceChildren();if(!r){card.body.append(el('p','Výpočet není ve výsledcích zaznamenán.','small'));continue;}const m=r.metrics||{};const shape=r.model&&r.model.shape;card.body.append(el('div',shape?('Tvar: '+(shapeNames[shape]||shape)):'Tvar nebyl určen','model-shape'));const values=el('div',undefined,'values');for(const [label,val] of [['Čas',seconds(r.elapsed_seconds)],['RMSE',metres(m.holdout_rmse_m)],['MAE',metres(m.holdout_mae_m)],['Pokrytí',percent(m.holdout_coverage)],['Trénovací body',num(m.train_points,0)],['Odložené body',num(m.test_points,0)]]){const item=el('div');item.append(el('span',label+': '),document.createTextNode(val));values.append(item);}card.body.append(values);modelDetails(card,r);if(card.mesh)card.body.append(el('p',card.mesh.vertices.length+' vrcholů · '+card.mesh.faces.length+' ploch','small'));if(r.error)card.body.append(el('p',r.error,'error'));}drawAll();}
function projector(){const yaw=Number($('rotation').value)*Math.PI/180,c=Math.cos(yaw),s=Math.sin(yaw),tilt=Math.PI/3,ct=Math.cos(tilt),st=Math.sin(tilt);return v=>{const x=c*v[0]-s*v[1],y=s*v[0]+c*v[1];return [x,ct*y-st*v[2],st*y+ct*v[2]];};}
function faceColor(vertices,face){const a=vertices[face[0]];let nx=0,ny=0,nz=0;for(let i=1;i<face.length-1;i++){const b=vertices[face[i]],c=vertices[face[i+1]],u=b.map((n,j)=>n-a[j]),v=c.map((n,j)=>n-a[j]);nx+=u[1]*v[2]-u[2]*v[1];ny+=u[2]*v[0]-u[0]*v[2];nz+=u[0]*v[1]-u[1]*v[0];}const len=Math.hypot(nx,ny,nz)||1;const roof=Math.abs(nz/len)>.16,shade=.80+.20*Math.abs((nx*.4+ny*.5+nz*.77)/len),base=roof?[181,124,88]:[196,204,197];return 'rgb('+base.map(v=>Math.round(v*shade)).join(',')+')';}
function drawAll(){const project=projector();let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;for(const card of cards)if(card.mesh)for(const i of card.mesh.used){const v=project(card.mesh.vertices[i]);xmin=Math.min(xmin,v[0]);xmax=Math.max(xmax,v[0]);ymin=Math.min(ymin,v[1]);ymax=Math.max(ymax,v[1]);}const hasModels=Number.isFinite(xmin),width=Math.max(1,xmax-xmin),height=Math.max(1,ymax-ymin);let scale=Infinity;for(const card of cards){const rect=card.canvas.getBoundingClientRect();if(rect.width>0)scale=Math.min(scale,(rect.width-42)/width,(rect.height-48)/height);}if(!Number.isFinite(scale)||scale<=0)scale=1;
for(const card of cards){const canvas=card.canvas,rect=canvas.getBoundingClientRect(),dpr=Math.min(2,window.devicePixelRatio||1);canvas.width=Math.max(1,Math.round(rect.width*dpr));canvas.height=Math.max(1,Math.round(rect.height*dpr));const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,rect.width,rect.height);if(!card.mesh)continue;const cx=(xmin+xmax)/2,cy=(ymin+ymax)/2,screen=v=>{const p=project(v);return[(p[0]-cx)*scale+rect.width/2,(p[1]-cy)*scale+rect.height/2-4,p[2]];},mesh=card.mesh,vs=mesh.vertices;const projected=new Map(mesh.used.map(i=>[i,screen(vs[i])]));const faces=mesh.faces.map(f=>({f,depth:f.reduce((n,i)=>n+projected.get(i)[2],0)/f.length})).sort((a,b)=>a.depth-b.depth);ctx.lineJoin='round';ctx.lineWidth=.7;
for(const {f} of faces){ctx.beginPath();for(let i=0;i<f.length;i++){const p=projected.get(f[i]);if(i===0)ctx.moveTo(p[0],p[1]);else ctx.lineTo(p[0],p[1]);}ctx.closePath();ctx.fillStyle=faceColor(vs,f);ctx.fill();ctx.strokeStyle='rgba(53,63,58,.38)';ctx.stroke();}
const desired=rect.width*.23/scale,pow=10**Math.floor(Math.log10(Math.max(.001,desired))),length=([1,2,5,10].filter(v=>v*pow<=desired).pop()||1)*pow,x=18,y=rect.height-20;ctx.strokeStyle='#61756d';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,y-3);ctx.lineTo(x,y);ctx.lineTo(x+length*scale,y);ctx.lineTo(x+length*scale,y-3);ctx.stroke();ctx.fillStyle='#61756d';ctx.font='10px system-ui';ctx.fillText(num(length,length<1?1:0)+' m',x,y-6);}
$('scale-note').textContent=hasModels?'Všech šest pohledů používá společné měřítko. Výšky nejsou zveličené. Otáčení mění pouze pohled; neodvozuje novou geometrii.':'Pro tento objekt není k dispozici žádná vykreslitelná geometrie.';}
let frame;function scheduleDraw(){if(frame)cancelAnimationFrame(frame);frame=requestAnimationFrame(drawAll);}
$('building').addEventListener('change',updateBuilding);$('rotation').addEventListener('input',()=>{$('angle').textContent=$('rotation').value+'°';scheduleDraw();});$('reset').addEventListener('click',()=>{$('rotation').value=35;$('angle').textContent='35°';scheduleDraw();});
if('ResizeObserver' in window){const observer=new ResizeObserver(scheduleDraw);observer.observe($('models'));}else window.addEventListener('resize',scheduleDraw);
if(!D.buildings.length)$('building').disabled=true;updateBuilding();
</script></body></html>'''


def generate_report(results_json_path, html_path):
    """Read runner output and return the path of the generated offline HTML."""
    source, target = Path(results_json_path), Path(html_path)
    if source.resolve() == target.resolve():
        raise ValueError("Input and output paths must differ")
    with source.open(encoding="utf-8-sig") as stream:
        report = build_report(json.load(stream))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, help="roof-pilot/1 JSON result")
    parser.add_argument("output", type=Path, help="Standalone HTML destination")
    args = parser.parse_args()
    if args.results.resolve() == args.output.resolve():
        parser.error("Input and output paths must differ")
    target = generate_report(args.results, args.output)
    print(f"Report: {target} ({target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
