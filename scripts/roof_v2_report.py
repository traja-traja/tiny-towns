#!/usr/bin/env python3
"""Build the offline 3D review report for roof-v2 results.

No inference, external assets, screenshots, or architecture quality judgments.
The report embeds the real JSON results and the repository's local Three.js.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sys
import atomic_io
from roof_candidate_summary import summarize_candidate_telemetry,render_candidate_telemetry

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "cities" / "ceske-budejovice" / "experiments" / "roof-v2"

HTML = r'''<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>Střechy v2 · České Budějovice</title>
<style>
:root{font-family:Inter,Segoe UI,system-ui,sans-serif;color:#23342f;background:#f5f6f3;font-synthesis:none;--line:#dbe1da;--muted:#627068;--accent:#28614f}*{box-sizing:border-box}body{margin:0}button,input,select{font:inherit}button,a,select,input{touch-action:manipulation}a{color:var(--accent);text-underline-offset:3px}button{border:1px solid #bdc9c0;background:#fff;border-radius:7px;padding:8px 12px;color:#294a3b;cursor:pointer}button:hover{background:#eef3ed}button:disabled{opacity:.4;cursor:default}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,canvas:focus-visible{outline:3px solid #8eb2a1;outline-offset:2px}input,select{border:1px solid #bfcac1;border-radius:6px;background:white;padding:9px 10px;color:#23342f;max-width:100%;min-width:0}select{width:100%}[hidden]{display:none!important}.page-head{padding:22px 28px 18px;border-bottom:1px solid var(--line);display:flex;gap:24px;align-items:center;justify-content:space-between;background:#fff}.eyebrow{font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--accent);font-weight:700}.page-head h1{font-size:25px;font-weight:650;line-height:1.18;margin:5px 0 7px;letter-spacing:-.025em}.page-head p{margin:0;color:var(--muted);font-size:13px;line-height:1.5}.head-links{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;justify-content:flex-end;font-size:13px}.head-links a{white-space:nowrap}.badge{border:1px solid #cfdccf;padding:5px 8px;border-radius:5px;font-size:11px;color:#42664e;white-space:nowrap}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 380px;max-width:1900px;margin:auto}.main{min-width:0;padding:22px 24px}.selector{display:grid;grid-template-columns:1fr 1.4fr auto;gap:10px;align-items:end;margin-bottom:14px}.field{display:flex;flex-direction:column;gap:5px;min-width:0}.field label{font-size:11px;font-weight:650;color:var(--muted);letter-spacing:.035em}.stepper{display:flex;gap:5px}.stepper button{width:39px;padding:8px}.viewer{position:relative;width:100%;height:clamp(410px,calc(100vh - 340px),800px);border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#f2f4f1}.viewer canvas{display:block;width:100%;height:100%;touch-action:none}.viewer-overlay{position:absolute;top:15px;left:15px;right:15px;pointer-events:none;font-size:12px;line-height:1.5;color:#57665d}.viewer-overlay.bottom{top:auto;bottom:12px;display:flex;justify-content:space-between;gap:12px;font-size:11px}.viewer-overlay span{background:#ffffffd9;padding:4px 7px;border-radius:4px}.viewport-tools{position:absolute;top:12px;right:12px;display:flex;gap:5px}.viewport-tools button{font-size:12px;padding:6px 9px;background:#fffffff0}.viewport-tools button.square{width:31px}.center-message{position:absolute;inset:0;display:flex;justify-content:center;align-items:center;padding:30px;text-align:center;background:#f2f4f1d9;color:#58655c;pointer-events:none;font-size:14px}.layers{display:flex;flex-wrap:wrap;gap:9px 16px;padding:13px 1px 7px;font-size:12px;color:#4b5e52}.layers label{display:flex;align-items:center;gap:5px;cursor:pointer}.layers input{accent-color:#39735b;width:14px;height:14px;margin:0}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:3px}.ridge{background:#315a9c}.observed-ridge{background:#00b85a}.candidate-end{background:#dc931c}.observed-ridge-info{border-left:3px solid #00b85a;padding-left:10px;margin-top:16px}.ridge-volume-status{font-weight:600;color:#294a3b!important}.observed-ridge-info dl{margin:8px 0 15px}.valley{background:#9b4a85}.eave{background:#218a79}.cloud{background:#414853}.holdout{background:#b66925}.main-note{margin-top:9px;font-size:12px;line-height:1.6;color:var(--muted)}.main-note p{margin:5px 0}.object-head{display:flex;gap:12px;justify-content:space-between;margin-bottom:14px;align-items:end}.object-head h2{font-size:19px;margin:0 0 4px;font-weight:620;line-height:1.4;overflow-wrap:anywhere}.object-head p{font-size:12px;color:var(--muted);margin:0;overflow-wrap:anywhere}.object-head .part-field{width:180px;flex-shrink:0}.aside{border-left:1px solid var(--line);padding:25px 22px;background:#fff;min-width:0;overflow-wrap:anywhere}.aside h2{margin:0 0 14px;font-size:16px;font-weight:620}.aside h3{font-size:13px;font-weight:650;margin:19px 0 10px}.aside p{font-size:12px;line-height:1.65;margin:8px 0;color:var(--muted)}.aside .source{font-size:12px;line-height:1.6;background:#f5f7f3;border-radius:6px;padding:9px 10px;max-height:135px;overflow:auto}.small{font-size:11px!important;color:var(--muted)}dl{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px 12px;font-size:12px;line-height:1.4;margin:0}dt{color:#68756e}dd{margin:0;font-variant-numeric:tabular-nums;text-align:right;max-width:175px;overflow-wrap:anywhere;color:#293d32}ul{padding-left:19px;font-size:11px;line-height:1.65;color:#6c624b}details{border-top:1px solid var(--line);margin-top:20px;padding-top:14px;font-size:12px}summary{cursor:pointer;font-weight:600;line-height:1.5}table{width:100%;border-collapse:collapse;font-size:10px;table-layout:fixed;margin:10px 0}th,td{padding:7px 5px;text-align:left;border-bottom:1px solid #e7ece5;vertical-align:top;overflow-wrap:anywhere}th{font-weight:650;color:#52665a}th:nth-child(2),td:nth-child(2){width:57px;text-align:right;font-variant-numeric:tabular-nums}.candidate-warning{margin-top:6px;color:#80643a}.candidate-status{color:#43564a}pre{font-family:Consolas,monospace;font-size:10px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:480px;overflow:auto;background:#f6f7f5;padding:10px;border-radius:6px}.download{font-size:12px;margin-top:12px}.rule{border-top:1px solid var(--line);padding-top:17px;margin-top:20px}.footer{border-top:1px solid var(--line);padding:14px 28px;font-size:11px;color:var(--muted);display:flex;justify-content:space-between;gap:16px;line-height:1.6}.footer span{overflow-wrap:anywhere}.error-notice{max-width:700px;margin:50px auto;padding:30px;background:white}
.volume-plans-section{margin-top:24px;border-top:1px solid var(--line);padding-top:18px}.volume-plans-section h2{font-size:17px;margin:0 0 6px}.volume-plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin-top:12px}.volume-plan-card{border:1px solid var(--line);border-radius:9px;background:#fff;padding:12px;min-width:0}.volume-plan-card h3{font-size:12px;line-height:1.5;margin:0 0 8px;overflow-wrap:anywhere}.volume-plan-card svg{display:block;width:100%;height:280px;background:#f8f9f6;border-radius:5px}.volume-plan-legend{padding:0;list-style:none;font-size:12px;line-height:1.5;margin:8px 0 0}.volume-plan-legend li{display:flex;flex-wrap:wrap;align-items:center;gap:4px 6px;margin:6px 0}.volume-swatch{width:10px;height:10px;border-radius:2px;flex-shrink:0}.volume-plan-legend .small{margin-left:16px;width:100%}
.performance-summary{max-width:1900px;margin:0 auto;padding:24px 30px;border-top:1px solid var(--line);background:#fff}.performance-summary h2{font-size:20px;margin:0 0 10px}.performance-summary h3{font-size:16px;margin-top:26px}.performance-summary p{font-size:12px;line-height:1.65;color:var(--muted);max-width:1100px}.performance-scroll{overflow-x:auto}.performance-summary table{table-layout:auto;font-size:12px;min-width:780px}.performance-summary th,.performance-summary td{width:auto!important;text-align:right;padding:9px 10px;font-variant-numeric:tabular-nums}.performance-summary th:first-child,.performance-summary td:first-child{text-align:left;min-width:140px}.performance-summary td:last-child{overflow-wrap:anywhere}.candidate-trace{margin-top:14px}.candidate-trace table{table-layout:auto}.candidate-trace th,.candidate-trace td{width:auto!important}.candidate-trace th:last-child,.candidate-trace td:last-child{min-width:130px}
@media(min-width:1300px){.workspace{grid-template-columns:minmax(0,1fr) 405px}.main{padding:24px 30px}.viewer{height:clamp(470px,calc(100vh - 320px),950px)}}
@media(max-width:950px){.workspace{grid-template-columns:minmax(0,1fr) 310px}.main{padding:18px 16px}.aside{padding:21px 16px}.selector{grid-template-columns:1fr 1fr}.stepper{grid-column:2;justify-content:flex-end}.object-head{align-items:start}.object-head .part-field{width:140px}.viewer{height:490px}.page-head{padding:18px}.page-head h1{font-size:23px}.page-head p{max-width:450px}.head-links{max-width:170px}.viewport-tools{flex-wrap:wrap;max-width:230px;justify-content:flex-end}.viewer-overlay.bottom{display:none}}
@media(max-width:720px){.page-head{display:block}.head-links{max-width:none;justify-content:flex-start;margin-top:13px}.workspace{display:block}.main{padding:18px 14px}.selector{grid-template-columns:1fr auto}.field.search{grid-column:1 / -1}.stepper{grid-column:auto}.object-head{display:block}.object-head .part-field{margin-top:12px;width:100%}.viewer{height:440px}.aside{border-left:0;border-top:1px solid var(--line);padding:24px 18px}.aside .source{max-height:90px}dl{font-size:13px;gap:8px 15px}.footer{padding:15px 18px;display:block}.footer span{display:block}.viewport-tools button{padding:6px 8px}.viewer-overlay{font-size:10px}.layers{gap:12px}.main-note{font-size:11px}}
</style>
</head>
<body>
<header class="page-head">
<div><div class="eyebrow">Izomapa · České Budějovice</div><h1>Střechy v2</h1><p>Jednoduché objemy podle mračna bodů. Interaktivní podklady k vašemu posouzení.</p></div>
<div class="head-links"><span class="badge">@@COUNT@@ objektů · lokální výpočet</span><a id="tile-link" href="tiles/report.html">Zákres do dlaždic ↗</a><a href="comparison.html">Srovnání předchozí metody ↗</a><a href="ALGORITHM.md">Popis algoritmu ↗</a><a href="results.json">Všechna data JSON</a></div>
</header>
<main class="workspace">
<section class="main" aria-label="Interaktivní 3D model">
<div class="selector">
<div class="field search"><label for="search">HLEDAT OBJEKT</label><input id="search" type="search" placeholder="Název, adresa, ID" autocomplete="off"></div>
<div class="field"><label for="building">BUDOVA · <span id="found"></span></label><select id="building" aria-label="Výběr budovy"></select></div>
<div class="stepper"><button id="previous" aria-label="Předchozí budova">←</button><button id="next" aria-label="Další budova">→</button></div>
</div>
<div class="object-head"><div><h2 id="object-title">Načítání výsledků…</h2><p id="object-address"></p><p class="small">ID <span id="object-id"></span> · <a id="osm-link" target="_blank" rel="noopener noreferrer" hidden>Umístění v OSM ↗</a></p></div><div class="field part-field"><label for="part">ČÁST OBJEKTU</label><select id="part" aria-label="Výběr části"></select></div></div>
<div class="viewer"><canvas id="view" tabindex="0" aria-label="3D model, šipky otáčí, plus a minus přiblíží, nula obnoví pohled"></canvas><div class="viewport-tools"><button id="top-view">Shora</button><button id="street-view">Z ulice</button><button id="reset">Reset</button><button class="square" id="zoom-in" aria-label="Přiblížit">+</button><button class="square" id="zoom-out" aria-label="Oddálit">−</button></div><div class="viewer-overlay bottom"><span>Táhnutí: otočit · Shift / pravé tlačítko: posun · Kolečko: zoom</span><span>Síť přibližně 5 m</span></div><div id="empty" class="center-message" hidden>Model není k dispozici.</div><div id="loading" class="center-message">Spouštím místní 3D prohlížeč…</div></div>
<div class="layers" aria-label="Vrstvy"><label><input type="checkbox" data-layer="roof" checked>Střecha</label><label><input type="checkbox" data-layer="walls" checked>Stěny</label><label><input type="checkbox" data-layer="edges" checked>Hrany</label><label><input type="checkbox" data-layer="ridge" checked><span class="dot ridge"></span>Hřebeny modelu</label><label><input type="checkbox" data-layer="observedRidge" checked><span class="dot observed-ridge"></span>Hřeben z bodů</label><label><input type="checkbox" data-layer="candidateEnds"><span class="dot candidate-end"></span>Strany pro štíty</label><label><input type="checkbox" data-layer="valley" checked><span class="dot valley"></span>Úžlabí</label><label><input type="checkbox" data-layer="eave"><span class="dot eave"></span>Okapové hrany</label><label><input type="checkbox" data-layer="points"><span class="dot cloud"></span>Vstupní body</label><label><input type="checkbox" data-layer="holdout"><span class="dot holdout"></span>Kontrolní body</label></div>
<div class="main-note"><p>Zelená pracovní linka = hřeben odhadnutý z bodů; tyrkysová = nejistý odhad. Modré čáry jsou hrany výsledné střechy. Diagnostický hřeben v tomto pokusu slouží jen k analýze, nikoli k výběru střechy. Pracovní linky ukazují uloženou zjištěnou délku a skutečnou výšku, i když leží uvnitř modelu.</p><p id="geometry"></p><p id="point-legend"></p><p>Oba výběry bodů jsou jen zmenšený náhled. Výpočet používá data uvedená v podrobnostech. Barvy zde rozlišují stěny, střechy a diagnostické vrstvy; nejde o naměřené barvy domu.</p></div>
<section class="volume-plans-section" aria-label="Půdorysy hlavních objemů"><h2>Půdorysy po rozdělení na objemy</h2><p class="small">Stejná orientace a měřítko pro obě verze. Barvy a čísla označují hlavní objemy; šedá přerušovaná čára ukazuje původní půdorys. Jde o uložený výsledek dělení, ne nový výpočet.</p><div id="volume-plans" class="volume-plans"></div></section>
</section>
<aside class="aside" aria-label="Metriky a zdroje"><h2>Podklady a výsledek</h2><div id="source" class="source"></div><div id="metrics"></div><p class="rule">Kontrolní body byly odložené před přizpůsobením modelu. Jsou ze stejného bodového zdroje, nejde o nezávislé zaměření. Odchylka popisuje shodu povrchu s body; nepotvrzuje architektonickou správnost.</p><p>Výběrové skóre kombinuje shodu a jednoduchost. Nižší skóre je lepší; nejde o kalibrovanou pravděpodobnost. Označené objekty zůstávají k další kontrole.</p><details><summary>Porovnávané šablony</summary><div id="candidate-tables"></div></details><details><summary>Úplná diagnostika a původ dat</summary><pre id="raw"></pre><button id="download" class="download">Stáhnout JSON tohoto objektu</button></details></aside>
</main>
@@CANDIDATE_SUMMARY@@
<footer class="footer"><span>Vygenerováno @@GENERATED@@ · @@SCHEMA@@</span><span>Obsah je lokální a vložený do HTML. Prohlížeč nic neposílá na internet.</span></footer>
<noscript><p class="error-notice">Interaktivní model vyžaduje JavaScript a WebGL. Zdrojová data jsou v souboru results.json.</p></noscript>
<script type="application/json" id="roof-data">@@DATA@@</script>
<script type="module">
import * as THREE from "data:text/javascript;base64,@@THREE@@";
@@VIEWER@@
</script>
</body>
</html>
'''


def render_report(input_path: Path, output_path: Path, three_path: Path | None = None) -> dict:
    payload = json.loads(atomic_io.read_text(input_path))
    if not isinstance(payload, dict) or payload.get("schema") != "roof-v2/1":
        raise ValueError("Expected results schema roof-v2/1")
    buildings = payload.get("buildings")
    if not isinstance(buildings, list) or not buildings:
        raise ValueError("Results contain no buildings; refusing to create an empty report")
    for index, building in enumerate(buildings):
        if not isinstance(building, dict) or not isinstance(building.get("parts"), list):
            raise ValueError(f"Invalid building at index {index}: parts list required")
    three_path = three_path or ROOT / "node_modules" / "three" / "build" / "three.module.js"
    three_bytes = three_path.read_bytes()
    # This local Three.js distribution must be standalone. Its data URL cannot
    # resolve split relative imports; fail clearly instead of fetching a CDN.
    if b'from "./' in three_bytes or b"from './" in three_bytes:
        raise ValueError("Three.js build has relative imports; use a standalone local module")
    viewer = (ROOT / "scripts" / "roof_v2_viewer.js").read_text(encoding="utf-8")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    values = {
        "@@COUNT@@": str(len(buildings)),
        "@@CANDIDATE_SUMMARY@@":render_candidate_telemetry(summarize_candidate_telemetry(payload)),
        "@@GENERATED@@": html.escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        "@@SCHEMA@@": html.escape(payload["schema"]),
        "@@DATA@@": serialized,
        "@@THREE@@": base64.b64encode(three_bytes).decode("ascii"),
        "@@VIEWER@@": viewer.replace("</script", "<\\/script"),
    }
    document = HTML
    report = payload.get('report', {})
    if report.get('batch'):
        title = html.escape(report.get('title', 'Střechy'))
        document = document.replace('<title>Střechy v2 · České Budějovice</title>', '<title>'+title+'</title>')
        document = document.replace('<h1>Střechy v2</h1>', '<h1>'+title+'</h1>')
        document = document.replace('Jednoduché objemy podle mračna bodů. Interaktivní podklady k vašemu posouzení.', html.escape(report.get('subtitle', '')))
        begin, end = document.index('<div class="head-links">'), document.index('</header>')
        links = ''.join('<a href="'+html.escape(link['href'], quote=True)+'">'+html.escape(link['label'])+'</a>' for link in report.get('links', []))
        document = document[:begin]+'<div class="head-links"><a id="tile-link" hidden></a>'+links+'</div>\n'+document[end:]
        begin, end = document.index('<p class="rule">'), document.index('<details><summary>Porovnávané šablony')
        document = document[:begin]+'<p class="rule">'+html.escape(report.get('note', ''))+'</p>'+document[end:]
    city_name = {'velesin': 'Velešín', 'ceske-budejovice': 'České Budějovice'}.get(
        payload.get('city'), 'České Budějovice')
    document = document.replace('Izomapa · České Budějovice', 'Izomapa · ' + html.escape(city_name))
    document = document.replace('<title>Střechy v2 · České Budějovice</title>',
                                '<title>Střechy v2 · ' + html.escape(city_name) + '</title>')
    # Replace script/data placeholders last to avoid touching literal user data.
    for key in ("@@CANDIDATE_SUMMARY@@", "@@COUNT@@", "@@GENERATED@@", "@@SCHEMA@@", "@@THREE@@", "@@VIEWER@@", "@@DATA@@"):
        document = document.replace(key, values[key])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_io.write_text(output_path, document)
    return {"report": str(output_path.resolve()), "buildings": len(buildings), "bytes": output_path.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_DIR / "results.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_DIR / "report.html")
    parser.add_argument("--three", type=Path, default=None, help="Existing standalone local Three.js module")
    args = parser.parse_args()
    print(json.dumps(render_report(args.input, args.output, args.three), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
