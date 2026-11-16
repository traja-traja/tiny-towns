"""Offline comparison of fidelity, extracted features and principal roof volumes.

Reuses the tested drawing implementation without modifying the previous report.
Only supplied measured geometry is drawn; diagnostic masks never alter it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import roof_simplification_report as base

ROOT = base.ROOT
DEST = ROOT / 'cities/ceske-budejovice/experiments/roof-components'
FROZEN = ROOT / 'cities/ceske-budejovice/experiments/roof-simplification/manifest.json'


def replace_one(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Previous renderer changed; review insertion anchor: '+old[:70])
    return text.replace(old,new,1)


MASK_JS = r'''
function maskPolygons(mask){const p=mask.polygon;return p?.type==='MultiPolygon'?p.coordinates:p?.type==='Polygon'?[p.coordinates]:[];}
function modelRoofZ(model,x,y){let best=-Infinity;const v=model.vertices;for(let i=0;i<model.faces.length;i++){if(model.face_semantics?.[i]!=='roof')continue;const f=model.faces[i],a=v[f[0]],b=v[f[1]],c=v[f[2]],den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);if(Math.abs(den)<1e-10)continue;const u=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den,w=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den,t=1-u-w;if(Math.min(u,w,t)<-1e-6)continue;best=Math.max(best,u*a[2]+w*b[2]+t*c[2]);}return Number.isFinite(best)?best:null;}
function drawMasks(ctx,card,project,scale,rect,center){let count=0;ctx.save();for(const part of card.parts){for(const mask of part.run?.component_masks||[]){const accepted=mask.status==='accepted',offset=part.offset||[0,0,0],colour=accepted?'#087e79':'#ba6428';ctx.strokeStyle=colour;ctx.lineWidth=1.8;ctx.setLineDash(accepted?[]:[4,3]);for(const poly of maskPolygons(mask))for(const ring of poly){let started=false,segments=0;ctx.beginPath();for(const xy of ring){const z=Number.isFinite(mask.base_z_m)?mask.base_z_m:modelRoofZ(part.model,xy[0],xy[1]);if(!Number.isFinite(z)){started=false;continue;}const p=project([xy[0]+offset[0],xy[1]+offset[1],z+offset[2]]),x=(p[0]-center[0])*scale+rect.width/2,y=(p[1]-center[1])*scale+rect.height/2-7;if(started){ctx.lineTo(x,y);segments++;}else{ctx.moveTo(x,y);started=true;}}ctx.stroke();if(segments)count++;}}}ctx.restore();return count;}
function componentSummary(body,rs){
 const fields=['detected_component_count','accepted_patch_count','restored_component_count','original_component_fallback_count','main_volume_count','feature_holdout_rmse_m','background_holdout_rmse_m'];
 if(!rs.some(r=>fields.some(k=>Number.isFinite(r.metrics?.[k]))||(r.component_masks||[]).length))return;
 const sum=k=>{const vals=rs.map(r=>r.metrics?.[k]);return vals.every(Number.isFinite)?vals.reduce((a,b)=>a+b,0):null;};
 const definitions=[['Detekované výstupky · součet','detected_component_count'],['Bezpečně doplněné otvory · součet','accepted_patch_count'],['Vrácené zjednodušené prvky · součet','restored_component_count'],['Zachované původní prvky · součet','original_component_fallback_count'],['Hlavní objemy · součet','main_volume_count']];
 const patched=rs.every(r=>r.variant?.endsWith('_patched'));
 const values=definitions.filter(([,key])=>(!patched||!['restored_component_count','original_component_fallback_count'].includes(key))&&rs.some(r=>Number.isFinite(r.metrics?.[key]))).map(([label,key])=>[label,fmt(sum(key),0)]);
 if(values.length)showValues(body,values);
 if(patched)body.append(element('p','Diagnostický mezikrok: přijaté výstupky jsou úmyslně odstraněné. Jejich návrat hodnotí sousední varianta.','warn'));
 if(rs.some(r=>r.timing?.scope?.includes('whole paired')))body.append(element('p','Čas patří celému páru odstranění + návrat. Nesčítejte jej z obou karet; původní rekonstrukce Rooferem se přičítá zvlášť.','small'));
 for(const r of rs){
  const m=r.metrics||{},prefix=rs.length>1?(r.name||r.id)+': ':'';
  if(Number.isFinite(m.feature_holdout_rmse_m))body.append(element('p',prefix+'Odchylka v maskách výstupků (RMSE): '+met(m.feature_holdout_rmse_m)+(Number.isFinite(m.feature_holdout_points)?' · '+fmt(m.feature_holdout_points,0)+' hodnoticích bodů':'')+'.','small'));
  if(Number.isFinite(m.background_holdout_rmse_m))body.append(element('p',prefix+'Odchylka mimo masky (RMSE): '+met(m.background_holdout_rmse_m)+'.','small'));
  const masks=r.component_masks||[];
  if(masks.length){const accepted=masks.filter(x=>x.status==='accepted').length;body.append(element('p',prefix+'Výběr obsahuje '+accepted+' přijatých a '+(masks.length-accepted)+' nevybraných kandidátů. Přijatý výběr sám nepotvrzuje úspěšné zjednodušení a vrácení prvku. Barevné obrysy lze zapnout nad modely.','small'));}
  if(r.detection_note)body.append(element('p',prefix+r.detection_note,'small'));
 }
}
'''


def html_template():
    html = base.HTML
    html = replace_one(html,'České Budějovice · jednodušší střechy','České Budějovice · věrnost a samostatné objemy')
    html = replace_one(html,'Méně hran, čitelnější střechy','Věrnost, věžičky a hlavní objemy')
    html = replace_one(html,'Šest vybraných objektů Českých Budějovic: zachovat hlavní plochy, hřebeny a siluetu, omezit drobné zlomy. Orientační tolerance kolem půl metru je preference pro kompromis, nikoli prohlášení přesnosti každého modelu.',
        'Stejných šest objektů: vyšší věrnost Rooferu, oddělení výrazných výstupků, doplnění základní střechy a vrácení jednoduchých dílů. Vyšší podrobnost i menší chyba mají smysl pouze tehdy, když model zachová rozpoznatelný tvar.')
    html = replace_one(html,'<a href="../report.html">Předchozí přehled experimentů</a>',
        '<a href="../roof-simplification/report.html">Předchozí zjednodušování</a>')
    html = replace_one(html,'<section id="comparison">',
        '<section id="input-data"><h2>Z jakých dat počítáme</h2><p>Všechny zdejší varianty používají <strong>husté DMPOK ČÚZK, mřížku 20 × 20 cm (přibližně 25 bodů/m²)</strong>. Stejný zdroj používalo i předchozí zjednodušování těchto šesti objektů. Původní DMP 1G je níže pouze pro srovnání hustoty.</p><p>20 % bodů jsme oddělili pro kontrolu výsledku. Zbývajících 80 % slouží výpočtu; Roofer má navíc limit 20 bodů/m². Vyšší faktor Rooferu tedy nemění vstupní zdroj. <strong>Rozestup 20 cm není zaručená přesnost výšky.</strong> DMPOK vzniká obrazovou korelací leteckých fotografií.</p><div class="table-wrap"><table><thead><tr><th>Budova / půdorys</th><th>DMP 1G: bodů</th><th>DMP 1G: bodů/m²</th><th>DMPOK: bodů</th><th>DMPOK: bodů/m²</th></tr></thead><tbody id="source-counts"></tbody></table></div><p class="small">Klasifikované body budov uvnitř půdorysu před rozdělením 80/20. Čísla nejsou hustota celého mapového listu. Půdorysy a výšková reference jsou shodné mezi variantami. Datum vytvoření souboru nepovažujeme za datum snímkování.</p></section><section id="comparison">')
    html = replace_one(html,'<section id="comparison">',
        '<section id="factor"><h2>Co znamená Roofer 0,60 a 0,888</h2><p>Jde o stejný program a stejný typ rekonstrukce; liší se váha <strong>complexity factor</strong>. Vyšší hodnota dává větší váhu shodě s body, nižší hodnota více upřednostňuje jednoduchost. Nejde o verzi programu ani o procento přesnosti.</p><div class="table-wrap"><table><thead><tr><th>Faktor λ</th><th>Váha shody s daty</th><th>Váha hladkosti / jednoduššího členění</th></tr></thead><tbody><tr><td>0,60</td><td>0,60</td><td>0,40</td></tr><tr><td>0,888</td><td>0,888</td><td>0,112</td></tr><tr><td>0,95</td><td>0,95</td><td>0,05</td></tr><tr><td>0,99</td><td>0,99</td><td>0,01</td></tr></tbody></table></div><p class="small">Optimalizace: E = λ × odchylka od dat + (1 − λ) × penalizace nespojitostí. Jde o váhy dvou členů výpočtu, nikoli procentuální rozdělení výsledné chyby. Tolerance detekce rovin je jiný parametr: určuje přijímání bodů do roviny, nikoli maximální chybu výsledného modelu. Více detailu může zachovat věžičku, ale také šum.</p></section><section id="comparison">')
    html = replace_one(html,'<label><input id="points" type="checkbox"> Vzorek vstupních bodů</label>',
        '<label><input id="points" type="checkbox"> Vzorek vstupních bodů</label><label><input id="component-masks" type="checkbox"> Vyčleněné části (diagnostika)</label>')
    html = replace_one(html,'<p id="point-note"',
        '<p id="component-availability" class="small"></p><p id="component-note" class="small" hidden>Tyrkysové obrysy: přijaté části; oranžové přerušované: nevybraní kandidáti. Rentgenové obtažení se kreslí ve výšce uvedené ve výsledku nebo na aktuálním povrchu střechy; může být zakryté skutečnou geometrií, ale zde se ukazuje přes ni. Obrys je diagnostika výběru, nikoli další stěna.</p><p id="point-note"')
    html = replace_one(html,"function projector(){",MASK_JS+'\nfunction projector(){')
    html = replace_one(html,"parts.push({model:m,vertices,id:r.id});",
        "parts.push({model:m,vertices,id:r.id,run:r,offset:[o[0]-baseOrigin[0],o[1]-baseOrigin[1],o[2]-baseOrigin[2]]});")
    html = replace_one(html,"$('points').disabled=!pointPreview.length;",
        "const hasMasks=currentRuns.some(r=>(r.component_masks||[]).length);$('component-masks').disabled=!hasMasks;if(!hasMasks)$('component-masks').checked=false;$('component-availability').textContent=hasMasks?'Diagnostické masky jsou dostupné u variant, které je zaznamenaly.':'U tohoto objektu nejsou uložené diagnostické masky; neznamená to, že stavba nemá výstupky.';$('points').disabled=!pointPreview.length;")
    html = replace_one(html,"if(card.parts.length){const desired=",
        "const drawnMasks=$('component-masks').checked?drawMasks(ctx,card,project,scale,r,[(xmin+xmax)/2,(ymin+ymax)/2]):0;cv.dataset.drawnMasks=drawnMasks;if(card.parts.length){const desired=")
    html = replace_one(html,"$('point-note').hidden=!$('points').checked;window.__drawState=",
        "$('point-note').hidden=!$('points').checked;$('component-note').hidden=!$('component-masks').checked;window.__drawState=")
    html = replace_one(html,"edges:Number(c.canvas.dataset.drawnEdges)}))",
        "edges:Number(c.canvas.dataset.drawnEdges),masks:Number(c.canvas.dataset.drawnMasks)}))")
    html = replace_one(html,"for(const id of ['edges','wireframe','roof-only','points'])",
        "for(const id of ['edges','wireframe','roof-only','points','component-masks'])")
    html = replace_one(html,"if(rs.length!==currentGroup.building_ids.length)body.append",
        "componentSummary(body,rs);if(rs.length!==currentGroup.building_ids.length)body.append")
    html = replace_one(html,"head.append(element('span',state,'badge'+badge));",
        "if(!problems.some(Boolean)&&rs.every(r=>['no_candidate','no_accepted_component','unchanged_no_candidate','no_safe_component'].includes(r.status))){state='Bez bezpečného vyčlenění';}if(!problems.some(Boolean)&&rs.some(r=>r.status==='unsupported')){state='Nepodporováno';badge=' warn';}head.append(element('span',state,'badge'+badge));")
    html = replace_one(html,"function problem(r){const m=r.model||{},mode=first(m.attributes?.rf_extrusion_mode,r.metrics?.roofer_extrusion_mode,r.parent_extrusion_mode);return r.error||!m.faces?.length?'missing':mode&&mode!=='standard'?'fallback':r.status==='rejected'||reviewFor(r).status==='rejected'?'rejected':null;}",
        "function problem(r){const m=r.model||{},mode=first(m.attributes?.rf_extrusion_mode,r.metrics?.roofer_extrusion_mode);const unchangedParent=r.variant?.startsWith('extract_')&&r.parent_extrusion_mode==='lod11_fallback';return r.error||!m.faces?.length?'missing':mode==='lod11_fallback'||unchangedParent?'fallback':r.status==='rejected'||reviewFor(r).status==='rejected'?'rejected':null;}")
    html = replace_one(html,"'face_region_ids','train_preview'].includes(k)",
        "'face_region_ids','train_preview','component_masks'].includes(k)")
    html = replace_one(html,"function projector(){", "for(const b of D.source_provenance?.building_counts||[]){const tr=element('tr');for(const val of [b.name,fmt(b.dmp1g.roof_class6_strict_points,0),fmt(b.dmp1g.roof_class6_points_per_footprint_m2,2),fmt(b.dmpok.roof_class6_strict_points,0),fmt(b.dmpok.roof_class6_points_per_footprint_m2,2)])tr.append(element('td',val));$('source-counts').append(tr);}\nfunction projector(){")
    html = replace_one(html,'function projector(){',(ROOT/'scripts/roof_components_depth.js').read_text(encoding='utf8')+'\nfunction projector(){')
    start=html.index("renderFaces.sort((a,b)=>a.z-b.z);")
    end=html.index("if($('points').checked)",start)
    html=html[:start]+"({drawnFaces,drawnEdges}=depthRender(ctx,renderFaces,dpr,$('wireframe').checked,$('edges').checked));"+html[end:]
    html=replace_one(html,'dpr=Math.min(2,devicePixelRatio||1)','dpr=2')
    html=replace_one(html,'<section id="input-data">','<section id="summary"><h2>Co ukázalo porovnání</h2><div id="summary-text"></div></section><section id="input-data">')
    html=replace_one(html,'<section id="factor">','<section id="performance"><h2>Čas a paměť nových profilů</h2><p>Celá dávka sedmi půdorysů, vždy dvě opakování. Časy jednotlivých budov jsou v kartách níže. Geometrie je z prvního opakování, čas je medián; nevybíráme nejlepší model z opakování.</p><div class="table-wrap"><table><thead><tr><th>Profil</th><th>Opakování</th><th>Medián dávky</th><th>Rozsah</th><th>Peak commit procesu</th></tr></thead><tbody id="performance-rows"></tbody></table></div><p class="small">Dvě opakování na zatíženém počítači nejsou důkaz obecného zrychlení. Celé pracovní kroky včetně režie, CPU a paměti jsou v připojených závěrech a podrobném protokolu. Čas páru odstranění/navrácení počítejte jednou; původní rekonstrukce se přičítá zvlášť.</p></section><section id="factor">')
    html=replace_one(html,'function projector(){',"for(const text of D.summary||[])$('summary-text').append(element('p',text));for(const p of D.performance_summary||[]){const tr=element('tr');for(const value of [p.label,p.repeats,sec(p.batch_seconds_median),sec(p.batch_seconds_min)+' – '+sec(p.batch_seconds_max),fmt(p.peak_MB,1)+' MB'])tr.append(element('td',value));$('performance-rows').append(tr);}\nfunction projector(){")
    return html


def build_data(results_path,manifest_path):
    data = base.build_data(results_path,manifest_path)
    for row in data['runs']:
        for mask in row.get('component_masks',[]):
            if mask.get('status') not in ('accepted','rejected','candidate'):
                raise ValueError('Invalid diagnostic mask status')
            polygon = mask.get('polygon',{})
            polys = polygon.get('coordinates',[]) if polygon.get('type')=='MultiPolygon' else [polygon.get('coordinates',[])] if polygon.get('type')=='Polygon' else []
            if not polys:
                raise ValueError('Mask requires Polygon/MultiPolygon')
            for poly in polys:
                for ring in poly:
                    if len(ring)<4 or any(len(p)<2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p[:2]) for p in ring):
                        raise ValueError('Invalid mask coordinate ring')
    data['gallery']['inputs'].extend([base.digest(Path(__file__)),base.digest(Path(base.__file__))])
    data['gallery']['inputs'].append(base.digest(ROOT/'scripts/roof_components_depth.js'))
    data['gallery']['depth_rule']='Per-pixel orthographic Z buffer, 2x pixel sampling; opaque faces and structural lines respect depth. Source vertices, faces and metrics are unchanged. Point and mask overlays remain explicit X-ray diagnostics.'
    data['gallery']['component_mask_rule'] = 'Diagnostic X-ray outline only. Accepted teal; rejected/candidate orange dashed. Local XY and relative-ground Z match each run model. Uses supplied base_z_m, otherwise the displayed roof upper envelope; missing projections are skipped.'
    return data


def write_report(data,output):
    encoded=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(html_template().replace('__DATA__',encoded),encoding='utf8')
    (output.parent/'README.md').write_text(f'''# Věrnost, věžičky a hlavní objemy

Otevři `report.html` přímo v prohlížeči. Samostatná offline galerie porovnává {len(data['groups'])} objektů / {len(data['buildings'])} půdorysů, {len(data['methods'])} metod a {len(data['runs'])} výsledků. Nepotřebuje server ani připojení k internetu.

[Závěry a výkon](zavery.md) · [Úplné výsledky](results.json) · [Předchozí kolo](../roof-simplification/report.html).

## Co porovnáváme

- `complexity factor` Rooferu mění váhu shody s daty vůči jednoduchosti. Čísla 0,60 a 0,888 neoznačují verzi ani přesnost. Vyšší hodnota může přidat správný detail i šum. Epsilon detekce rovin je jiný parametr.
- Vyčlenění části, doplnění základní střechy a vrácení zjednodušené části jsou samostatné zaznamenané varianty. Galerie geometrii nepřizpůsobuje.
- Malá věžička může mít malý vliv na globální RMSE. Pokud je dodané místní hodnocení, karty proto ukazují také chybu ve vyčleněných místech a počet hodnoticích bodů.
- Nenalezená část, odmítnutý výsledek a náhradní plochý objem se nesmějí vydávat za úspěšnou rekonstrukci. Hodnoty a stavy se přebírají z výsledků.

## Kresba a metriky

Všechny varianty používají stejnou kameru a měřítko; oba půdorysy Budvaru mají původní vzájemnou polohu. Přepínač triangulace ukazuje technické dělení, zatímco výchozí obrysy sledují hranice rovin. Obtažení hran ani potlačení antialiasingových švů geometrii nemění. Vzorek bodů a masky jsou výslovně rentgenová diagnostika bez testu zakrytí.

Plochy a konstrukční hrany se kreslí s hloubkovým testem po pixelech a dvojnásobným rozlišením. Vzdálené stěny tak nemohou překreslit bližší střechu jen kvůli pořadí trojúhelníků. Jde o opravu náhledu, nikoliv měřeného modelu.

Masky: tyrkysová znamená přijatý výběr, oranžová přerušovaná nevybraného kandidáta. Počty prvků a hlavních objemů nejsou počtem střešních rovin. Z výškového rozdílu nebo barevného obrysu samotného nelze odvodit, že jde skutečně o věž či komín.

RMSE a P95 porovnávají zobrazený mesh s oddělenými body téhož zdroje, ne s nezávislým zaměřením. Podíl do ±0,5 m je uveden pro pokryté i všechny hodnoticí body. Víc půdorysů agreguje RMSE přes vážené čtverce chyb; P95 je pouze rozsah percentilů částí. Chybějící údaje zůstávají „—“.

Převzaté časy a nové měření jsou rozlišené. Samotné zjednodušení už existujícího modelu není celkový čas rekonstrukce. Jednotlivé budovy, celé dávky a hledání kandidátů mohou mít jiný rozsah měření.

## Obnovení a ověření

```powershell
.venv\\Scripts\\python.exe -X utf8 scripts\\roof_components_report.py
.venv\\Scripts\\python.exe -X utf8 scripts\\resource_guard.py run --log .work\\cb-roof-components\\qa\\gallery.log --max-ram-gb 1 --min-available-gb 1 -- node scripts\\check_roof_components.mjs
```

Generátor kontroluje identity, jedinečné varianty, konečné XYZ a indexy. Do HTML zapisuje SHA výsledků i zdroje rendereru. Předchozí report ani městské mapy neupravuje. Prohlížečová kontrola má dynamické počty variant, šest objektů, čtyři kamery, přepínače, místní odkazy, mobilní šířku a nulové síťové požadavky. `--smoke` ověří konečná doporučení a shodu SHA bez opakování celé obrazové kontroly. Existence tohoto návodu sama neznamená, že kontrola už proběhla.
''',encoding='utf8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results',type=Path,default=DEST/'results.json')
    p.add_argument('--manifest',type=Path,default=FROZEN)
    p.add_argument('--output',type=Path,default=DEST/'report.html')
    p.add_argument('--check-only',action='store_true')
    a=p.parse_args()
    data=build_data(a.results.resolve(),a.manifest.resolve())
    if a.check_only:
        print(json.dumps({'groups':len(data['groups']),'runs':len(data['runs']),'methods':len(data['methods'])}))
        return
    write_report(data,a.output.resolve())
    print(json.dumps({'report':str(a.output.resolve()),'bytes':a.output.stat().st_size,'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()}))


if __name__=='__main__':
    main()
