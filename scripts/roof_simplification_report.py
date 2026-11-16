"""Build the isolated, offline roof simplification comparison from measured results.

No reconstruction, downloads or edits to either city map are performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "cities/ceske-budejovice/experiments/roof-simplification"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path):
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def normalize_manifest(document):
    if isinstance(document, list):
        entries = document
    else:
        entries = document.get("buildings") or document.get("features") or document.get("selected") or []
    buildings = []
    for entry in entries:
        p = entry.get("properties", entry)
        bid = entry.get("id") or p.get("id") or p.get("building_id")
        if not bid:
            raise ValueError("Manifest entry without building identity")
        buildings.append({**p, "id": bid, "name": p.get("name", bid)})
    return buildings


def validate_model(model, context):
    if not model or not model.get("vertices") or not model.get("faces"):
        return
    vertices, faces = model["vertices"], model["faces"]
    for v in vertices:
        if len(v) != 3 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v):
            raise ValueError(f"Invalid XYZ vertex in {context}")
    for face in faces:
        if len(face) < 3 or any(not isinstance(i, int) or i < 0 or i >= len(vertices) for i in face):
            raise ValueError(f"Invalid face indices in {context}")
    if model.get("face_semantics") and len(model["face_semantics"]) != len(faces):
        raise ValueError(f"Semantic count differs from faces in {context}")


def build_data(results_path: Path, manifest_path: Path | None = None):
    document = read(results_path)
    runs = document.get("runs", [])
    if not runs:
        raise ValueError("The report requires measured runs, including recorded failures")
    buildings = normalize_manifest(read(manifest_path) if manifest_path else document)
    # Result-level display previews can be added after the frozen fitting manifest.
    # Preserve the manifest identities, while retaining those measured display fields.
    result_buildings = {b["id"]: b for b in normalize_manifest(document)}
    buildings = [{**b, **result_buildings.get(b["id"], {})} for b in buildings]
    if not buildings:
        # Identity is still taken from actual result rows, never a fabricated test.
        by_id = {r["id"]: {"id": r["id"], "name": r.get("name", r["id"]),
                            "group_id": r.get("group_id", r["id"])} for r in runs}
        buildings = list(by_id.values())
    identities = {b["id"]: b for b in buildings}
    seen = set()
    for run in runs:
        if run["id"] not in identities:
            raise ValueError(f"Run outside frozen selection: {run['id']}")
        key = (run["id"], run["variant"])
        if key in seen:
            raise ValueError(f"Duplicate displayed result {key}; repeats belong inside the run")
        seen.add(key)
        validate_model(run.get("model"), key)
    groups = []
    for building in buildings:
        group_id = building.get("display_group_id") or building.get("group_id") or building["id"]
        group = next((g for g in groups if g["id"] == group_id), None)
        if group is None:
            group = {"id": group_id, "name": building.get("group_name") or building["name"], "building_ids": []}
            groups.append(group)
        group["building_ids"].append(building["id"])
    for group in groups:
        if len(group["building_ids"]) > 1 and "budvar" in group["id"].lower():
            group["name"] = "Budvar aréna · dva zdrojové půdorysy"
    methods = document.get("methods") or document.get("variants") or []
    if isinstance(methods, dict):
        methods = [{"id": k, **(v if isinstance(v, dict) else {"label": str(v)})} for k, v in methods.items()]
    known = {m.get("id") or m.get("variant") for m in methods}
    for run in runs:
        if run["variant"] not in known:
            methods.append({"id": run["variant"], "label": run.get("label") or run.get("variant_label") or run["variant"]})
            known.add(run["variant"])
    input_files = [digest(results_path)]
    if manifest_path:
        input_files.append(digest(manifest_path))
    return clean({**document, "buildings": buildings, "groups": groups, "methods": methods,
                  "gallery": {"created_at": datetime.now(timezone.utc).isoformat(),
                              "inputs": input_files, "coordinate_rule": "Same EPSG5514 origins and ground references are used for all variants; no manual visual repositioning.",
                              "edge_rule": "Display edges: millimetre XYZ welding, boundary or semantic change or dihedral angle over one degree; explicit roof-region IDs take precedence; roof edges are clipped to actual region polygon boundaries with 4 mm collinearity tolerance to remove T-junction artifacts. This is display filtering, not geometry simplification.",
                              "scope": "isolated experiment; no map deployment"}})


HTML = r'''<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>České Budějovice · jednodušší střechy</title>
<style>
:root{--ink:#243a35;--muted:#62746c;--line:#d8e0d8;--bg:#f8faf5;--green:#27664d;--warm:#ad653f}*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}main{max-width:1660px;margin:auto;padding:34px 28px}h1{font-size:clamp(28px,4vw,46px);line-height:1.08;letter-spacing:-.045em;margin:12px 0 18px}h2{font-size:25px;line-height:1.2;margin:0 0 14px}h3{font-size:16px;line-height:1.3;margin:0}.eyebrow{font-size:11px;letter-spacing:.16em;color:var(--green);text-transform:uppercase}.lede{font-size:18px;max-width:1060px}p{max-width:1100px;margin:10px 0}.small{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.notice{max-width:none;padding:12px 16px;background:#fff3dc;border-left:4px solid #c48e3a;border-radius:4px}.good{background:#e9f1e6;border-left-color:#397154}.critical{background:#fce9e3;border-left-color:#a03f31}.controls{display:grid;grid-template-columns:2fr 1fr 1fr;gap:16px;align-items:end;margin:24px 0 12px}.control{display:flex;flex-direction:column;gap:6px;min-width:0}label{font-size:12px;font-weight:650}select{font:inherit;color:var(--ink);padding:9px 11px;border:1px solid var(--line);border-radius:6px;background:white;max-width:100%;width:100%;min-height:42px}input[type=range]{width:100%;accent-color:var(--green);height:24px}.camera{display:flex;flex-wrap:wrap;gap:8px}.camera button{font:inherit;color:var(--green);background:#edf2e9;border:1px solid var(--line);padding:7px 11px;border-radius:6px;cursor:pointer}.camera button[aria-pressed=true]{background:var(--green);color:white}.toggles{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0}.toggles label{font-size:13px;font-weight:400}.toggles input{accent-color:var(--green)}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:16px}.card{min-width:0;border:1px solid var(--line);background:white;border-radius:9px;overflow:hidden}.head{display:flex;gap:10px;align-items:start;justify-content:space-between;padding:14px 15px;min-height:65px}.badge{font-size:10px;line-height:1.4;padding:3px 7px;background:#edf2e8;border-radius:4px;flex:0 0 auto;max-width:140px}.badge.warn{background:#fff0cf}.badge.bad{background:#fbe0da;color:#913a2e}.view{height:310px;background:linear-gradient(#f0f3ec,#e6ece1);position:relative}.view canvas{display:block;width:100%;height:100%}.empty{position:absolute;inset:0;display:grid;place-items:center;text-align:center;padding:25px;color:var(--muted)}.card-data{padding:12px 15px}.values{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px 12px;font-size:13px}.values span{font-size:10px;color:var(--muted);display:block}.values b{font-weight:650}.card p{font-size:12px}.warn{color:#925927}.part{margin-top:12px;border-top:1px solid var(--line);padding-top:9px}.part summary{font-size:12px;cursor:pointer}.table-wrap{max-width:100%;overflow:auto;border:1px solid var(--line);border-radius:7px}table{width:100%;border-collapse:collapse;font-size:12px;background:white}th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:#edf2e8;font-size:11px}td:first-child{min-width:130px}section{margin-top:32px;padding-top:26px;border-top:1px solid var(--line)}a{color:var(--green)}pre{white-space:pre-wrap;word-break:break-word;font-size:11px;max-height:520px;overflow:auto;background:#edf1e9;padding:14px;border-radius:6px}details{margin:14px 0}summary{cursor:pointer}.selection-note{padding:14px 16px;border:1px solid var(--line);border-radius:7px;background:white}.scale-note{font-size:11px;color:var(--muted)}footer{padding-top:24px;margin-top:32px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}.method-name{display:block;font-weight:650}.method-desc{display:block;font-size:11px;color:var(--muted);margin-top:4px}#diagnostic-note{font-size:12px;color:#8d5132}.run-metrics{margin-top:6px}.swatch{display:inline-block;width:10px;height:10px;background:#ac795c;border-radius:2px;margin-right:6px}
@media(max-width:1100px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.controls{grid-template-columns:1fr 1fr}.control:first-child{grid-column:1/-1}}
@media(max-width:620px){main{padding:24px 14px}.grid,.controls{grid-template-columns:1fr}.control:first-child{grid-column:auto}.view{height:300px}.head{min-height:0}.lede{font-size:16px}h2{font-size:22px}.camera button{font-size:13px}.badge{max-width:120px}}
</style></head><body><main>
<header><div class="eyebrow">Izomapa · další srovnávací experiment</div><h1>Méně hran, čitelnější střechy</h1><p class="lede">Šest vybraných objektů Českých Budějovic: zachovat hlavní plochy, hřebeny a siluetu, omezit drobné zlomy. Orientační tolerance kolem půl metru je preference pro kompromis, nikoli prohlášení přesnosti každého modelu.</p><p id="scope" class="small"></p><p class="notice">Zobrazené experimenty nejsou nasazené v městské mapě. Všechny varianty jedné budovy mají stejné měřítko, kameru a neutrální materiály. Barvy slouží k porovnání tvaru.</p><p><a href="zavery.md">Závěry, doporučení a výkon</a> · <a href="../report.html">Předchozí přehled experimentů</a> · <a href="results.json">Úplné výsledky</a> · <a href="README.md">Protokol čtení výsledků</a></p></header>
<section id="comparison"><h2>Porovnání objemů</h2><div class="controls"><div class="control"><label for="building">Objekt</label><select id="building"></select></div><div class="control"><label for="rotation">Otočení <span id="rotation-value"></span></label><input id="rotation" type="range" min="0" max="360" step="1" value="35"></div><div class="control"><label for="elevation">Výška pohledu <span id="elevation-value"></span></label><input id="elevation" type="range" min="0" max="90" step="1" value="35"></div></div><div class="camera"><button data-view="iso" aria-pressed="true">Axonometrie</button><button data-view="top" aria-pressed="false">Shora</button><button data-view="front" aria-pressed="false">Boční A</button><button data-view="side" aria-pressed="false">Boční B</button></div><div class="toggles"><label><input id="edges" type="checkbox" checked> Zlomy ploch a okraje</label><label><input id="wireframe" type="checkbox"> Trojúhelníková síť (diagnostika)</label><label><input id="roof-only" type="checkbox"> Pouze střešní plochy</label><label><input id="points" type="checkbox"> Vzorek vstupních bodů</label></div><p id="point-note" class="small" hidden>Modré body: zředěný deterministický vzorek fitovacích bodů. Rentgenové překrytí ukazuje i body za modelem; neslouží jako nové měření přesnosti.</p><p id="diagnostic-note" hidden>Zapnutá trojúhelníková síť ukazuje i technické dělení rovné plochy. Více trojúhelníků samo o sobě neznamená více skutečných střešních rovin.</p><p class="scale-note">Boční A/B jsou projekce podle os modelu, nikoli automaticky ověřené uliční průčelí. Přepínače mění jen zobrazení, geometrii ani metriky neupravují.</p><p id="building-meta" class="small"></p><div id="recommendation" class="selection-note"></div><div class="controls"><div class="control"><label for="variant-a">Levé srovnání</label><select id="variant-a"></select></div><div class="control"><label for="variant-b">Prostřední srovnání</label><select id="variant-b"></select></div><div class="control"><label for="variant-c">Pravé srovnání</label><select id="variant-c"></select></div></div><p><label><input id="all-variants" type="checkbox"> Zobrazit všechny zaznamenané varianty</label></p><div id="models" class="grid"></div><p id="group-note" class="small"></p></section>
<section id="metrics"><h2>Stejné budovy, stejné hodnoticí body</h2><p>Počet souvislých střešních rovin hodnotí složitost. Délka vnitřních hranic rovin v půdorysu XY zahrnuje hřebeny, úžlabí i výškové schody. Není počtem hřebenů ani délkou obvodu. RMSE a P95 popisují odchylku výšky od vyhrazených bodů stejného mračna; nejsou nezávislým zaměřením. Pokrytí a podíl bodů do ±0,5 m čtěte současně.</p><div class="table-wrap"><table><thead><tr><th>Část objektu</th><th>Varianta</th><th>Souvislé střešní roviny</th><th>RMSE</th><th>P95 absolutní chyby</th><th>Pokrytí bodů</th><th>Do ±0,5 m / pokryté</th><th>Do ±0,5 m / všechny</th><th>Čas metody</th></tr></thead><tbody id="metrics-body"></tbody></table></div><p class="small">Chybějící údaj zůstává „—“. U dvou půdorysů Budvar arény se chyby mechanicky neprůměrují; tabulka je ukazuje samostatně. Na kartě skupiny se RMSE a MAE váží počtem pokrytých bodů, podíly mají uvedený jmenovatel. P95 zůstává rozsahem percentilů částí; jejich průměr by nebyl percentilem celého objektu.</p><details><summary>Parametry, opakování, kontroly a úplné metriky vybraného objektu</summary><pre id="details"></pre></details></section>
<section id="methods"><h2>Co jednotlivé metody skutečně mění</h2><div id="method-list"></div><p class="notice">Schování vnitřních triangulačních hran není zjednodušení modelu. Proto jsou výchozí modely zobrazené stejným způsobem jako nové varianty a počty ploch se přebírají ze zaznamenané geometrie.</p><div id="notes"></div></section>
<section id="protocol"><h2>Protokol a omezení</h2><p>Výběr obsahuje záměrně složité objekty. Nejlepší nastavení pro jednu halu není automaticky univerzální nastavení pro celé město. Odmítnuté varianty a náhradní jednoduché objemy zůstávají viditelné.</p><ul id="rules"></ul><details><summary>Zdroje, časování, paměť a kontrolní součty</summary><pre id="protocol-json"></pre></details></section>
<footer>Samostatný HTML soubor funguje offline. Výpočty a kontroly jsou lokální; galerie modely znovu nepočítá. <span id="created"></span></footer>
</main><script type="application/json" id="data">__DATA__</script><script>
'use strict';
const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);
const fmt=(v,n=2)=>Number.isFinite(v)?v.toLocaleString('cs-CZ',{maximumFractionDigits:n,minimumFractionDigits:n}):'—';
const pct=v=>Number.isFinite(v)?fmt(v*100,1)+' %':'—',met=v=>Number.isFinite(v)?fmt(v,3)+' m':'—',sec=v=>Number.isFinite(v)?fmt(v,v<.01?5:v<1?3:2)+' s':'—';
const element=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const first=(...xs)=>xs.find(v=>v!==undefined&&v!==null);
const methodMap=new Map(D.methods.map(m=>[m.id||m.variant,m]));
const label=id=>methodMap.get(id)?.label||methodMap.get(id)?.name||id;
function compact(v){if(Array.isArray(v))return v.map(compact);if(v&&typeof v==='object'){const o={};for(const[k,x]of Object.entries(v))if(!['vertices','faces','face_semantics','semantic_types','structural_edges','boundary_segments3d','roof_regions','comparison_roof_regions','face_region_ids','train_preview'].includes(k))o[k]=compact(x);return o;}return v;}
function metrics(r){const m=r.metrics||{},t=r.timing||{};return{planes:first(m.actual_roof_region_count,m.roof_plane_count,m.merged_roof_surface_count,m.native_roof_surface_count,m.roof_surface_count),nativePlanes:first(m.native_roof_surface_count,m.native_semantic_surface_counts?.RoofSurface),rmse:first(m.holdout_rmse_m,m.rmse_m),mae:first(m.holdout_mae_m,m.mae_m),predicted:m.predicted_points,total:m.holdout_points,withinAll:m.within_0_5m_all_holdout_fraction,p95:first(m.holdout_p95_abs_m,m.p95_abs_m),coverage:first(m.coverage_fraction,m.holdout_coverage),within:first(m.within_0_5m_fraction,m.holdout_within_0_5m_fraction,m.fraction_within_0_5m,m.holdout_abs_le_0_5m_fraction,m.within_0_5_fraction),time:first(t.median_seconds,t.median_internal_seconds,t.reconstruction_seconds_median,t.elapsed_seconds,t.seconds,r.elapsed_seconds),edges:first(m.structural_edge_count,m.roof_structural_edge_count),edgeLength:first(m.structural_edge_length_m,m.roof_structural_edge_length_m),internalBreakLength:m.internal_roof_break_length_xy_m}}
function rangeMetric(rs,key,format){const v=rs.map(r=>metrics(r)[key]);if(!v.length||v.some(x=>!Number.isFinite(x)))return'—';const lo=Math.min(...v),hi=Math.max(...v);return Math.abs(lo-hi)<1e-8?format(lo):format(lo)+' – '+format(hi);}
function aggregateMetric(rs,key){const rows=rs.map(metrics);if(rows.length===1)return rows[0][key];if(!rows.length)return null;const total=rows.reduce((s,m)=>s+m.total,0),predicted=rows.reduce((s,m)=>s+m.predicted,0);if(!rows.every(m=>Number.isFinite(m.predicted)&&Number.isFinite(m.total))||total<=0)return null;if(key==='coverage')return predicted/total;if(key==='withinAll'){if(!rows.every(m=>Number.isFinite(m.withinAll)))return null;return rows.reduce((s,m)=>s+m.withinAll*m.total,0)/total;}if(!rows.every(m=>Number.isFinite(m[key]))||predicted<=0)return null;const value=rows.reduce((s,m)=>s+(key==='rmse'?m[key]**2:m[key])*m.predicted,0)/predicted;return key==='rmse'?Math.sqrt(value):value;}
function sumMetric(rs,key){const v=rs.map(r=>metrics(r)[key]);return v.length&&v.every(Number.isFinite)?v.reduce((a,b)=>a+b,0):null;}
function showValues(parent,values){const box=element('div',undefined,'values');for(const[k,v]of values){const item=element('div');item.append(element('span',k),element('b',v));box.append(item);}parent.append(box);}
function reviewFor(r){return r.review||r.human_review||{};}
function problem(r){const m=r.model||{},mode=first(m.attributes?.rf_extrusion_mode,r.metrics?.roofer_extrusion_mode,r.parent_extrusion_mode);return r.error||!m.faces?.length?'missing':mode&&mode!=='standard'?'fallback':r.status==='rejected'||reviewFor(r).status==='rejected'?'rejected':null;}
function origin(m,b){const o=m.origin_epsg5514;return Array.isArray(o)&&o.length>=2?[o[0],o[1],first(o[2],m.ground_z,0)]:b?.origin_epsg5514||(b?.centre?[b.centre[0],b.centre[1],b.ground_z||0]:[0,0,0]);}
const geometryCache=new WeakMap();
function geometry(model){if(geometryCache.has(model))return geometryCache.get(model);const vs=model.vertices,faces=model.faces,sem=model.face_semantics||[],keys=vs.map(v=>v.map(x=>Math.round(x*1000)).join(','));const edgeMap=new Map(),normals=[],roles=[];for(let fi=0;fi<faces.length;fi++){const f=faces[fi],a=vs[f[0]],b=vs[f[1]],c=vs[f[2]],u=b.map((x,j)=>x-a[j]),v=c.map((x,j)=>x-a[j]),n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],len=Math.hypot(...n)||1;normals.push(n.map(x=>x/len));let role=sem[fi]||model.semantic_types?.[fi];if(role==='RoofSurface')role='roof';if(role==='WallSurface')role='wall';if(role==='GroundSurface')role='ground';roles.push(role|| (Math.abs(n[2]/len)>.2?'roof':'wall'));for(let j=0;j<f.length;j++){const a=f[j],b=f[(j+1)%f.length];if(keys[a]===keys[b])continue;const k=[keys[a],keys[b]].sort().join('|');if(!edgeMap.has(k))edgeMap.set(k,{a,b,faces:[]});edgeMap.get(k).faces.push(fi);}}
const structural=new Set(),byFace=faces.map(()=>[]);for(const[k,e]of edgeMap){let keep=e.faces.length===1;if(e.faces.length>1){const f=e.faces[0];for(const g of e.faces.slice(1)){const dot=Math.min(1,Math.abs(normals[f].reduce((s,x,j)=>s+x*normals[g][j],0))),a=model.face_region_ids?.[f],b=model.face_region_ids?.[g],sameRoofRegion=roles[f]==='roof'&&roles[g]==='roof'&&Number.isInteger(a)&&a>=0&&a===b,differentRoofRegion=roles[f]==='roof'&&roles[g]==='roof'&&Number.isInteger(a)&&Number.isInteger(b)&&a>=0&&b>=0&&a!==b;if(roles[f]!==roles[g]||differentRoofRegion||(!sameRoofRegion&&dot<Math.cos(Math.PI/180)))keep=true;}}if(keep){structural.add(k);for(const fi of e.faces)byFace[fi].push(e);}}
// Restrict roof triangle edges to actual polygon boundaries. This also removes
// unpaired interior edges at T-junctions, which exact endpoint welding misses.
const regionList=model.comparison_roof_regions||model.roof_regions||[],regionSegments=new Map();
for(const region of regionList){const polygon=region.polygon,polys=polygon?.type==='MultiPolygon'?polygon.coordinates:polygon?.type==='Polygon'?[polygon.coordinates]:[];const segments=[];for(const poly of polys)for(const ring of poly)for(let j=0;j<ring.length-1;j++)segments.push([ring[j],ring[j+1]]);regionSegments.set(region.id,segments);}
let regionFilteredFaces=0;
for(let fi=0;fi<faces.length;fi++){if(roles[fi]!=='roof')continue;const segments=regionSegments.get(model.face_region_ids?.[fi]);if(!segments)continue;regionFilteredFaces++;byFace[fi]=[];const face=faces[fi];for(let j=0;j<face.length;j++){const a=face[j],b=face[(j+1)%face.length],p=vs[a],q=vs[b],dx=q[0]-p[0],dy=q[1]-p[1],length=Math.hypot(dx,dy);if(length<1e-8)continue;const intervals=[];for(const [u,v] of segments){const distance=x=>Math.abs(dx*(x[1]-p[1])-dy*(x[0]-p[0]))/length;if(distance(u)>.004||distance(v)>.004)continue;const project=x=>((x[0]-p[0])*dx+(x[1]-p[1])*dy)/(length*length),t0=project(u),t1=project(v),lo=Math.max(0,Math.min(t0,t1)),hi=Math.min(1,Math.max(t0,t1));if(hi-lo>1e-8)intervals.push([lo,hi]);}intervals.sort((a,b)=>a[0]-b[0]);const merged=[];for(const range of intervals){const last=merged[merged.length-1];if(last&&range[0]<=last[1]+1e-8)last[1]=Math.max(last[1],range[1]);else merged.push(range);}for(const [t0,t1]of merged)byFace[fi].push({a,b,t0,t1});}}
const result={normals,roles,byFace,structuralEdgeCount:structural.size,edgeMap,regionFilteredFaces};geometryCache.set(model,result);return result;}
let cards=[],currentRuns=[],currentGroup=null,extentParts=[],pointPreview=[];
function projector(){const yaw=+$('rotation').value*Math.PI/180,elev=+$('elevation').value*Math.PI/180,c=Math.cos(yaw),s=Math.sin(yaw),se=Math.sin(elev),ce=Math.cos(elev);return v=>{const x=c*v[0]-s*v[1],y=s*v[0]+c*v[1];return[x,se*y-ce*v[2],ce*y+se*v[2]];};}
function shade(normal,role){const l=.72+.28*Math.abs(normal[0]*.38+normal[1]*.43+normal[2]*.82),base=role==='roof'?[174,119,86]:role==='ground'?[152,165,145]:[212,216,202];return'rgb('+base.map(v=>Math.round(v*l)).join(',')+')';}
function draw(){const project=projector(),roofOnly=$('roof-only').checked;let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;for(const part of extentParts){const g=geometry(part.model),indices=new Set();part.model.faces.forEach((f,i)=>{if(!roofOnly||g.roles[i]==='roof')f.forEach(k=>indices.add(k));});for(const i of indices){const p=project(part.vertices[i]);xmin=Math.min(xmin,p[0]);xmax=Math.max(xmax,p[0]);ymin=Math.min(ymin,p[1]);ymax=Math.max(ymax,p[1]);}}if(!Number.isFinite(xmin)){xmin=ymin=-1;xmax=ymax=1;}const w=Math.max(1,xmax-xmin),h=Math.max(1,ymax-ymin);let scale=Infinity;for(const card of cards){const r=card.canvas.getBoundingClientRect();if(r.width>0)scale=Math.min(scale,(r.width-40)/w,(r.height-55)/h);}if(!Number.isFinite(scale)||scale<=0)scale=1;let ci=0;for(const card of cards){const cv=card.canvas,r=cv.getBoundingClientRect(),dpr=Math.min(2,devicePixelRatio||1);cv.width=Math.max(1,Math.round(r.width*dpr));cv.height=Math.max(1,Math.round(r.height*dpr));const ctx=cv.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,r.width,r.height);let renderFaces=[],drawnFaces=0,drawnEdges=0;for(const part of card.parts){const g=geometry(part.model),ps=part.vertices.map(v=>{const p=project(v);return[(p[0]-(xmin+xmax)/2)*scale+r.width/2,(p[1]-(ymin+ymax)/2)*scale+r.height/2-7,p[2]];});part.model.faces.forEach((f,i)=>{if(roofOnly&&g.roles[i]!=='roof')return;renderFaces.push({f,i,part,g,ps,z:f.reduce((s,k)=>s+ps[k][2],0)/f.length});});}renderFaces.sort((a,b)=>a.z-b.z);ctx.lineJoin='round';for(const rf of renderFaces){const{f,i,g,ps}=rf;ctx.beginPath();f.forEach((k,j)=>j?ctx.lineTo(ps[k][0],ps[k][1]):ctx.moveTo(ps[k][0],ps[k][1]));ctx.closePath();ctx.fillStyle=shade(g.normals[i],g.roles[i]);ctx.fill();ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=.7;ctx.stroke();drawnFaces++;if($('wireframe').checked){ctx.lineWidth=.45;ctx.strokeStyle='rgba(52,62,53,.3)';ctx.stroke();drawnEdges+=f.length;}else if($('edges').checked){ctx.lineWidth=.85;ctx.strokeStyle='rgba(47,57,49,.62)';for(const edge of g.byFace[i]){if(g.roles[i]==='ground')continue;ctx.beginPath();const a=ps[edge.a],b=ps[edge.b],lo=edge.t0??0,hi=edge.t1??1;ctx.moveTo(a[0]+(b[0]-a[0])*lo,a[1]+(b[1]-a[1])*lo);ctx.lineTo(a[0]+(b[0]-a[0])*hi,a[1]+(b[1]-a[1])*hi);ctx.stroke();drawnEdges++;}}}if($('points').checked){ctx.fillStyle='rgba(28,105,151,.52)';for(const point of pointPreview){const p=project(point);ctx.fillRect((p[0]-(xmin+xmax)/2)*scale+r.width/2-1,(p[1]-(ymin+ymax)/2)*scale+r.height/2-8,2,2);}}if(card.parts.length){const desired=r.width*.22/scale,pow=10**Math.floor(Math.log10(Math.max(.001,desired))),length=([1,2,5,10].filter(v=>v*pow<=desired).pop()||1)*pow;ctx.strokeStyle='#5d7468';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(16,r.height-18);ctx.lineTo(16+length*scale,r.height-18);ctx.stroke();ctx.fillStyle='#5d7468';ctx.font='10px system-ui';ctx.fillText(fmt(length,length<1?1:0)+' m',16,r.height-24);}cv.dataset.drawnFaces=drawnFaces;cv.dataset.drawnEdges=drawnEdges;cv.dataset.scale=scale;cv.dataset.renderIndex=ci++;}
$('rotation-value').textContent=$('rotation').value+'°';$('elevation-value').textContent=$('elevation').value+'°';$('diagnostic-note').hidden=!$('wireframe').checked;$('point-note').hidden=!$('points').checked;window.__drawState={group:currentGroup?.id,scale,bounds:[xmin,ymin,xmax,ymax],camera:{yaw:+$('rotation').value,elevation:+$('elevation').value},pointCount:pointPreview.length,pointsVisible:$('points').checked,cards:cards.map(c=>({variant:c.variant,partCount:c.parts.length,faces:Number(c.canvas.dataset.drawnFaces),edges:Number(c.canvas.dataset.drawnEdges)}))};}
function update(){currentGroup=D.groups.find(g=>g.id===$('building').value);currentRuns=D.runs.filter(r=>currentGroup.building_ids.includes(r.id));const container=$('models');container.replaceChildren();cards=[];let baseOrigin=null;for(const r of currentRuns){if(r.model?.faces?.length){baseOrigin=origin(r.model,D.buildings.find(b=>b.id===r.id));break;}}baseOrigin=baseOrigin||[0,0,0];extentParts=[];pointPreview=[];for(const r of currentRuns){const m=r.model;if(!m?.faces?.length)continue;const o=origin(m,D.buildings.find(b=>b.id===r.id));extentParts.push({model:m,vertices:m.vertices.map(v=>[v[0]+o[0]-baseOrigin[0],v[1]+o[1]-baseOrigin[1],v[2]+o[2]-baseOrigin[2]])});}for(const b of D.buildings.filter(b=>currentGroup.building_ids.includes(b.id))){const o=origin({},b);for(const p of b.train_preview||[]){if(p.length===3&&p.every(Number.isFinite))pointPreview.push([p[0]+o[0]-baseOrigin[0],p[1]+o[1]-baseOrigin[1],p[2]+o[2]-baseOrigin[2]]);}}$('points').disabled=!pointPreview.length;if(!pointPreview.length)$('points').checked=false;const available=D.methods.map(m=>m.id||m.variant).filter(id=>currentRuns.some(r=>r.variant===id));const selected=[...new Set(['variant-a','variant-b','variant-c'].map(id=>$(id).value))];const variants=$('all-variants').checked?available:selected.filter(id=>available.includes(id));for(const variant of variants){const rs=currentRuns.filter(r=>r.variant===variant),card=element('article',undefined,'card');card.dataset.variant=variant;const head=element('div',undefined,'head');head.append(element('h3',label(variant)));const problems=rs.map(problem),reviews=rs.map(reviewFor);if(rs.length!==currentGroup.building_ids.length)problems.push('missing');let state='K posouzení',badge='';if(problems.includes('missing')){state='Chybí část / model';badge=' bad';}else if(problems.includes('rejected')){state='Nedoporučeno';badge=' bad';}else if(problems.includes('fallback')){state='Obsahuje náhradní objem';badge=' warn';}else if(reviews.some(r=>['recommended','candidate','preferred'].includes(r.status))){state='Kandidát';}head.append(element('span',state,'badge'+badge));const view=element('div',undefined,'view'),canvas=element('canvas');canvas.setAttribute('aria-label',currentGroup.name+' – '+label(variant));view.append(canvas);const parts=[];for(const r of rs){const m=r.model;if(!m?.vertices?.length||!m?.faces?.length)continue;const o=origin(m,D.buildings.find(b=>b.id===r.id)),vertices=m.vertices.map(v=>[v[0]+o[0]-baseOrigin[0],v[1]+o[1]-baseOrigin[1],v[2]+o[2]-baseOrigin[2]]);parts.push({model:m,vertices,id:r.id});}if(!parts.length)view.append(element('div','Model nebyl vytvořen','empty'));const body=element('div',undefined,'card-data');const triangleCount=parts.reduce((s,p)=>s+p.model.faces.length,0);showValues(body,[['Souvislé střešní roviny · součet',fmt(sumMetric(rs,'planes'),0)],['Nativní plochy CityJSON · součet',fmt(sumMetric(rs,'nativePlanes'),0)],['Trojúhelníky · celý objem',parts.length?fmt(triangleCount,0):'—'],['RMSE'+(rs.length>1?' · obě části':''),met(aggregateMetric(rs,'rmse'))],['MAE',met(aggregateMetric(rs,'mae'))],['P95'+(rs.length>1?' · rozsah částí':' absolutní chyby'),rangeMetric(rs,'p95',met)],['Pokrytí hodnoticích bodů',pct(aggregateMetric(rs,'coverage'))],['Do ±0,5 m · z pokrytých',pct(aggregateMetric(rs,'within'))],['Do ±0,5 m · ze všech bodů',pct(aggregateMetric(rs,'withinAll'))],['Čas metody'+(rs.length>1?' · součet':''),sec(sumMetric(rs,'time'))],['Vnitřní zlomy střechy · délka v XY',met(sumMetric(rs,'internalBreakLength'))]]);if(rs.length!==currentGroup.building_ids.length)body.append(element('p','U této varianty chybí záznam některého zdrojového půdorysu.','warn'));const desc=methodMap.get(variant)?.description;if(desc)body.append(element('p',desc,'small'));if(rs.some(r=>r.reused_previous_run))body.append(element('p','Čas převzat z předchozího běhu, nikoli z nového opakovaného měření.','small'));if(rs.some(r=>/merge|merging|simplification/i.test(r.timing?.scope||'')))body.append(element('p','Čas dodatečného zjednodušení hotového modelu. Předchozí rekonstrukce střechy se k němu přičítá.','small'));if(rs.some(r=>/native per-building/i.test(r.timing?.scope||'')))body.append(element('p','Interní čas rekonstrukce budovy. Načtení dat a režie celé dávky jsou evidované zvlášť.','small'));for(const r of rs){const rv=reviewFor(r);if(rv.note||rv.message)body.append(element('p',(rs.length>1?(r.name||r.id)+': ':'')+(rv.note||rv.message),'small'));if(problem(r)==='fallback')body.append(element('p',(rs.length>1?(r.name||r.id)+': ':'')+'Roofer použil náhradní objem. Jednoduchý výsledek není důkaz správně zjednodušené střechy.','warn'));if(r.error)body.append(element('p',String(r.error),'warn'));for(const warning of r.warnings||[])body.append(element('p',typeof warning==='string'?warning:JSON.stringify(warning),'warn'));}card.append(head,view,body);container.append(card);cards.push({canvas,parts,variant});}
const recs=Array.isArray(D.recommendations)?D.recommendations:Object.entries(D.recommendations||{}).map(([id,rec])=>typeof rec==='string'?{id,note:rec}:{id,...rec});const matches=recs.filter(r=>r.group_id===currentGroup.id||r.id===currentGroup.id||currentGroup.building_ids.includes(r.id));$('recommendation').replaceChildren();if(matches.length){for(const rec of matches){const b=D.buildings.find(b=>b.id===rec.id),prefix=currentGroup.building_ids.length>1&&b?b.name+': ':'';$('recommendation').append(element('p',prefix+(rec.note||rec.conclusion||rec.message||rec.status||'Záznam posouzení bez slovní poznámky.')));}}else{$('recommendation').textContent='Vizuální výběr zůstává otevřený. Porovnej hlavní hřebeny, rozdělení vysokých a nízkých částí a odchylky níže.';};$('building-meta').textContent=currentGroup.name+' · '+currentGroup.building_ids.length+' zdrojový půdorys / půdorysy · '+variants.length+' zobrazených / '+available.length+' zaznamenaných variant';$('group-note').textContent=currentGroup.building_ids.length>1?'Části jsou zobrazené společně ve své skutečné relativní poloze. Chybějící nebo náhradní část je výslovně označená; nejde o nový sjednocený model areálu.':'';const table=$('metrics-body');table.replaceChildren();for(const bid of currentGroup.building_ids)for(const r of currentRuns.filter(r=>r.id===bid)){const m=metrics(r),tr=element('tr');for(const value of [r.name||D.buildings.find(b=>b.id===bid)?.name||bid,label(r.variant),fmt(m.planes,0),met(m.rmse),met(m.p95),pct(m.coverage),pct(m.within),pct(m.withinAll),sec(m.time)])tr.append(element('td',value));table.append(tr);}$('details').textContent=JSON.stringify(compact(currentRuns),null,2);draw();}
const defaults=D.default_comparison_variants||D.methods.slice(0,3).map(m=>m.id||m.variant);for(const [i,id]of ['variant-a','variant-b','variant-c'].entries()){for(const method of D.methods){const o=element('option',method.label||method.name||method.id||method.variant);o.value=method.id||method.variant;$(id).append(o);}$(id).value=defaults[i]||defaults[0];}for(const group of D.groups){const option=element('option',group.name);option.value=group.id;$('building').append(option);}
$('building').addEventListener('change',update);for(const id of ['variant-a','variant-b','variant-c'])$(id).addEventListener('change',update);$('all-variants').addEventListener('change',()=>{for(const id of ['variant-a','variant-b','variant-c'])$(id).disabled=$('all-variants').checked;update();});for(const id of ['rotation','elevation'])$(id).addEventListener('input',()=>{document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed','false'));draw();});for(const id of ['edges','wireframe','roof-only','points'])$(id).addEventListener('change',draw);for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>{const settings={iso:[35,35],top:[0,90],front:[0,0],side:[90,0]}[button.dataset.view];$('rotation').value=settings[0];$('elevation').value=settings[1];document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));draw();});let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(draw,80);});
for(const method of D.methods){const p=element('p');p.append(element('span',method.label||method.name||method.id||method.variant,'method-name'));if(method.description||method.note)p.append(element('span',method.description||method.note,'method-desc'));$('method-list').append(p);}for(const note of D.notes||[]){$('notes').append(element('p',typeof note==='string'?note:JSON.stringify(note),'small'));}const rules=D.comparison_rules||D.protocol?.comparison_rules||['Stejný zmrazený půdorys a vstupní bodový zdroj; oddělené fitovací a hodnoticí body.','Tolerance ±0,5 m je orientační preference uživatele. Ani dobrý průměr nezaručuje, že všechny body leží v toleranci.','Plochy a trojúhelníky jsou různé počty. Diagnostické obtažení trojúhelníků nemění geometrii.','Chyby vůči bodům stejného zdroje nejsou nezávislé geodetické ověření.','Výpočet metody a čas celé dávky včetně I/O mají odlišný rozsah; chybějící měření nejsou odhadována.'];for(const rule of rules)$('rules').append(element('li',typeof rule==='string'?rule:JSON.stringify(rule)));const protocol={};for(const[k,v]of Object.entries(D))if(!['runs','buildings','groups'].includes(k))protocol[k]=v;$('protocol-json').textContent=JSON.stringify(compact(protocol),null,2);$('scope').textContent=D.groups.length+' objektů · '+D.buildings.length+' zdrojových půdorysů · '+D.runs.length+' zaznamenaných výsledků · DMP OK';$('created').textContent='Přehled sestaven '+new Date(D.gallery.created_at).toLocaleString('cs-CZ',{timeZone:'Europe/Prague'})+'.';update();
</script></body></html>'''


def write_report(data, output: Path):
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HTML.replace("__DATA__", encoded), encoding="utf-8")
    (output.parent / "README.md").write_text(f'''# Zjednodušení střech – samostatné porovnání

Otevři `report.html` přímo v prohlížeči. Soubor je samostatný, offline a nevyžaduje běžící mapový server. Zobrazuje {len(data["groups"])} objektů / {len(data["buildings"])} zdrojových půdorysů a {len(data["runs"])} zaznamenaných výsledků. Podrobné hodnoty jsou v `results.json`; jde o izolovaný experiment bez nasazení do mapy.

[Závěry, doporučení, výkon a další kolo](zavery.md) · [Záznam posouzení](review.json).

## Jak číst obrázky

- Každá varianta používá stejnou kameru, měřítko a tlumené materiály. Vzájemná poloha více půdorysů se odvozuje ze zaznamenaných souřadnic EPSG:5514 a referenčního terénu.
- Výchozí volba „Zlomy ploch a okraje“ skrývá pouze vnitřní koplanární triangulační hrany. Hrany zobrazení spojuje na shodných XYZ souřadnicích zaokrouhlených na milimetr; společnou hranu zachová při změně sémantiky nebo úhlu normál nad jeden stupeň. Dodaná ID regionů mají přednost. Střešní hrany se navíc ořezávají na skutečné polygonové hranice souvislých regionů, aby se nezobrazily falešné vnitřní čáry u T-spojů triangulace (tolerance kolinearity 4 mm). Stejnobarevný přesah výplně o zlomek obrazového pixelu potlačuje světlé antialiasingové švy trojúhelníků; nevytváří novou hranu. Tato pravidla nejsou nová rekonstrukce ani geometrické zjednodušení.
- „Trojúhelníková síť (diagnostika)“ ukazuje technickou triangulaci. Počet takových čar nelze zaměnit za počet hlavních střešních rovin.
- Volitelný vzorek fitovacích bodů je zředěné rentgenové překrytí bez testu zakrytí. Souřadnice bodů jsou lokální XY a výška nad `ground_z`; modré body mohou být i za viditelným modelem.
- Boční A/B jsou projekce podle os modelu, nikoli ověřené uliční průčelí. Pohledy shora i z boku pomáhají posoudit siluetu.
- U Budvar arény se dva půdorysy zobrazují společně; chyba a pokrytí zůstávají také v samostatných řádcích. Karta agreguje RMSE jako odmocninu váženého průměru čtverců chyb a MAE podle počtu pokrytých bodů, pokrytí jako součet pokrytých / všech bodů. P95 je pouze rozsah percentilů obou částí. Počet rovin je součet částí bez jejich prostorového sjednocení.

## Jak číst čísla

RMSE, P95, pokrytí a podíl bodů do ±0,5 m se přebírají ze skutečných výsledků. Podíl do tolerance je uveden vůči pokrytým i všem hodnoticím bodům; nepokryté body tak nelze skrýt. Chybějící údaje zůstávají prázdné; galerie je nevymýšlí. Hodnocení odchylky vůči bodům stejného zdroje není nezávislé geodetické zaměření. Půl metru je uživatelská preference kompromisu, nikoli automatický práh schválení geometrie.

Počet skutečných souvislých střešních rovin a počty trojúhelníků jsou oddělené. Společná definice souvislých koplanárních regionů používá toleranci 3 mm a 0,25 stupně a je stejná pro všechny varianty; nativní plochy CityJSON jsou zvláštní údaj. Délka vnitřních hranic v XY zahrnuje hřebeny, úžlabí i schody, není automaticky počtem hřebenů. Náhradní plochý objem či nevytvořená část jsou označeny. Doporučení je redakční zhodnocení uložené ve výsledcích, nikoli automatický důsledek nejnižšího RMSE.

## Obnovení a kontrola

Z kořene projektu:

```powershell
.venv\\Scripts\\python.exe -X utf8 scripts\\roof_simplification_report.py
.venv\\Scripts\\python.exe -X utf8 scripts\\resource_guard.py run --log .work\\roof-simplification\\qa\\gallery.log --max-ram-gb 1 --min-available-gb 1 -- node scripts\\check_roof_simplification.mjs
```

Generátor pouze čte měření. Vyžaduje `results.json` a použije `manifest.json`, pokud existuje. Kontroluje identity, unikátní varianty a konečné XYZ souřadnice/platné indexy meshe. Otisky vstupů jsou v HTML (`gallery.inputs`). Neprovádí fitting ani změnu městského rendereru.

Prohlížečová kontrola se spouští samostatně po ukončení výpočtů. Ověří všechny objekty, kameru, zapnutí/vypnutí hran, diagnostickou síť, lokální odkazy a mobilní šířku 390 px. Výsledky a snímky budou v `.work/roof-simplification/qa/`; existence tohoto návodu sama není potvrzením úspěšné kontroly.
''', encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEST / "results.json")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, default=DEST / "report.html")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    manifest = args.manifest or (DEST / "manifest.json" if (DEST / "manifest.json").exists() else None)
    data = build_data(args.results.resolve(), manifest.resolve() if manifest else None)
    if args.check_only:
        print(json.dumps({"groups": len(data["groups"]), "buildings": len(data["buildings"]), "runs": len(data["runs"])}))
    else:
        path = write_report(data, args.output.resolve())
        print(json.dumps({"report": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
