// Editorial conclusions only: measured geometry, errors and timings are retained.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dir=path.join(root,'cities/ceske-budejovice/experiments/roof-components');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const write=(p,v)=>fs.writeFileSync(p,JSON.stringify(v,null,2)+'\n');
const hash=v=>createHash('sha256').update(v).digest('hex');
const d=read(path.join(dir,'results.json'));
const immutable=()=>hash(JSON.stringify(d.runs.map(r=>[r.id,r.variant,r.model,r.metrics,r.timing])));
const before=immutable();
const notes={
 'CB-ROOF-01':'Největší přínos: Roofer 0,95 s vyššími limity vytvořil 8 nativních střešních ploch místo plochého náhradního objemu. RMSE kleslo z 0,912 na 0,226 m. Kandidát pro další zjednodušení. Samotné 0,95 či 0,99 se starými limity náhradní objem nevyřešilo.',
 'CB-ROOF-02':'Vyšší věrnost nepřináší jednoznačně lepší kompromis. Faktor 0,95 zvýšil nativní členění z 25 na 32 ploch, RMSE se změnilo jen z 0,553 na 0,550 m. Dělení objemů 0,75 m skončilo chybou geometrie, varianta 1,50 m je příliš hrubá (RMSE 1,362 m).',
 'CB-ROOF-04':'0,99 má 27 nativních ploch místo původních 11, ale RMSE zůstává přibližně 0,71 m. Vyšší věrnost zde nepomáhá zjednodušení. Dělení na 6 hlavních objemů při prahu 0,75 m zjednoduší plochy při RMSE 0,722 m; stojí za další doladění. Z předchozího kola zůstává zajímavá i varianta 0,35 / epsilon 0,50 m (RMSE 0,566 m).',
 'CB-ROOF-09':'Oddělení výstupků funguje jako mezikrok: měřítko 1,5 m vybralo dva prvky, pod nimi doplnilo střechu a základ zjednodušilo na 8 souvislých rovin. Jednoduché náhrady obou prvků neprošly kontrolou, proto se vrátila původní geometrie. Přísnější detekce 0,15 m snižuje celkové RMSE na 0,664 m, ale mění špičku věžičky. Nižší globální chyba tedy sama nestačí. Rozklad hlavních objemů zde skončil nepodporovanou geometrií.',
 'CB-ROOF-10':'Přísnější detekce zlepší RMSE z 0,419 na 0,390 m, ale přidává členění kolem výstupku a nižší střechy. Pro přehledný model je vhodnější navázat na slučování hlavních rovin. Jediná sedlová šablona ztrácí rozdíl částí (RMSE 0,753 m).',
 'CB-ROOF-12':'0,99 zvýší počet nativních ploch ze 14 na 39; RMSE se zlepší jen z 0,377 na 0,351 m. V náhledu výrazně přibývají drobné zlomy. Jedna sedlová šablona je přehledná, ale zahodí charakteristické prvky a zhorší RMSE na 0,677 m. Doporučení: jednodušší hlavní střecha s chráněnými prvky, nikoli globálně 0,99.',
 'CB-ROOF-16':'0,95 / epsilon 0,15 m zlepší RMSE z 0,749 na 0,603 m a P95 z 0,440 na 0,319 m, ale nativních ploch je 23 místo 15. Je to kandidát na následné slučování ploch. Dělení pouze podle výškových skoků neoddělí vhodně hlavní a nízké křídlo; RMSE 1,103 m je zhoršení.'
};
const byId=new Map(d.buildings.map(b=>[b.id,b]));
d.recommendations=d.buildings.map(b=>({id:b.id,status:'reviewed_experiment',note:notes[b.pilot_id]}));
for(const r of d.runs){
  const pilot=byId.get(r.id).pilot_id;
  if(r.status==='unsupported')r.review={status:'unsupported',note:'Metoda tento případ bezpečně nesestavila. Chyba je uchována; chybějící model není úspěšné zjednodušení.'};
  else if(r.variant.endsWith('_patched'))r.review={status:'diagnostic',note:r.metrics.accepted_patch_count?'Úmyslně odstraněné výstupky. Mezivýsledek pro kontrolu doplněné střechy, ne finální model.':'Žádný bezpečně oddělitelný výstupek. Proběhlo pouze běžné slučování rovin.'};
  else if(r.variant.endsWith('_restored'))r.review={status:'diagnostic',note:r.metrics.accepted_patch_count?'Zjednodušených náhrad: 0. Kontrola odmítla jednoduché šablony; původní prvky byly vráceny.':'Žádný bezpečně oddělitelný výstupek. Název varianty neznamená, že zde byl nějaký prvek zjednodušen.'};
  else if(pilot==='CB-ROOF-01'&&r.variant==='roofer_c095_caps240_30s')r.review={status:'candidate',note:notes[pilot]};
  else if(pilot==='CB-ROOF-04'&&r.variant==='volume_steps_075')r.review={status:'candidate',note:'Zajímavé zjednodušení hlavních objemů, vyžaduje kontrolu návazností; není automaticky nasazeno.'};
  else if(pilot==='CB-ROOF-09'&&r.variant==='roofer_c095_eps015')r.review={status:'rejected',note:'Přes lepší globální RMSE mění špičku věžičky. Pro automatickou náhradu charakteristické stavby nedoporučeno.'};
  else if(r.variant.startsWith('volume_')&&['CB-ROOF-02','CB-ROOF-10','CB-ROOF-12','CB-ROOF-16'].includes(pilot))r.review={status:'rejected',note:'Příliš hrubé spojení hlavních částí; horší shoda a ztráta charakteristického členění.'};
  else if(pilot==='CB-ROOF-16'&&r.variant==='roofer_c095_eps015')r.review={status:'candidate',note:'Lepší shoda s body; následujícím krokem musí být omezení drobných zlomů.'};
  else r.review={status:r.reused_previous_run?'reference':'reviewed',note:r.reused_previous_run?'Převzatá reference; čas není nově změřen.':'Experimentální varianta; doporučení pro tuto budovu je uvedeno nad srovnáním.'};
}
const profileIds=['roofer_c095','roofer_c099','roofer_c095_eps015','roofer_c095_caps240_30s'];
d.performance_summary=profileIds.map(id=>{const bs=d.native_batches.filter(b=>b.variant===id);const wall=bs.map(b=>b.process_metrics.elapsed_seconds).sort((a,b)=>a-b);return {variant:id,label:d.methods.find(m=>m.id===id).label,repeats:bs.length,batch_seconds_median:(wall[0]+wall[wall.length-1])/2,batch_seconds_min:wall[0],batch_seconds_max:wall[wall.length-1],peak_MB:Math.max(...bs.map(b=>b.process_metrics.peak_job_commit_bytes))/1e6};});
d.summary=[
 'Dokončeno: 6 objektů / 7 půdorysů, 14 variant, 98 záznamů. Z toho 70 nových výsledků a 28 převzatých referencí; 3 nové pokusy rozkladu objemů skončily bez modelu a jsou výslovně označené.',
 'Vstupem je husté DMPOK: mřížka 20 cm, přibližně 25 bodů/m². Stejné body i rozdělení 80/20 jako v minulém kole. Rozestup bodů není výšková přesnost.',
 'Vyšší věrnost není univerzální zlepšení. Největší přínos má u severní části Budvaru zvýšení limitů detekce. U Masných krámů a sportovní haly faktor 0,99 přidává složitost s malým zlepšením chyby.',
 'Oddělení dvou výstupků kostela a doplnění střechy se podařilo. Zjednodušené navrácení prvků se zatím nepodařilo: kontrola odmítla šablony a zachovala původní komponenty. Bezvýstupková varianta je jen diagnostika.',
 'Dělení podle výškových skoků je užitečné pro stupňovité haly, ale samo nerozpozná všechna křídla. U kostela selhala geometrická sestava; u některých historických domů je výsledek příliš hrubý.',
 'Nové výsledky jsou pouze v této galerii. Produkční mapa nebyla změněna. Další krok: chráněné charakteristické prvky + slučování základních ploch; pravidla ověřit na dalších budovách.'
];
d.default_comparison_variants=['roofer_lod22_reference','roofer_c095_eps015','roofer_c095_caps240_30s'];
d.review={status:'visual_review_complete',scope:'Internal mesh comparison and selected rendered views for all six groups; not verification against current photographs or independent survey.',geometry_or_metrics_changed:false,unit_tests_passed:21};
d.status='complete';
d.reviewed_at=new Date().toISOString();
d.notes.push('Náhled používá hloubkový test ploch. Opravuje falešné šedé trojúhelníky způsobené kreslením vzdálené stěny přes střechu; nemění žádnou geometrii ani metriku.');
// Actual final comparison process timing is only available after its own exit.
d.process_metrics['.work/cb-roof-components/comparison.log.metrics.json']=read(path.join(root,'.work/cb-roof-components/comparison.log.metrics.json'));
if(immutable()!==before)throw Error('Editorial finalizer altered measured results');
write(path.join(dir,'results.json'),d);
write(path.join(dir,'review.json'),{...d.review,reviewed_at:d.reviewed_at,recommendations:d.recommendations,measured_payload_sha256:before,results_sha256:hash(fs.readFileSync(path.join(dir,'results.json')))});
const f=(v,n=3)=>Number.isFinite(v)?v.toFixed(n):'—';
const lines=['# Vyšší věrnost, výstupky a hlavní objemy střech','',...d.summary.map(s=>s+'\n'),'## Závěry podle budovy',''];
for(const b of d.buildings)lines.push('### '+b.name,'',notes[b.pilot_id],'');
lines.push('## Stejné vstupy pro férové porovnání','','DMPOK ČÚZK, listy CBUD22 a CBUD23, souřadnice EPSG:5514, výšky Bpv. Půdorysy byly převzaté ze zmrazeného výběru a zůstávají stejné. Střecha se vybírá z klasifikace 6 uvnitř půdorysu; kontrolní body nejsou použity pro fitování. Žádné nové stahování ani dopočítávání umělých bodů.','', '| Půdorys | DMP 1G bodů | Bodů/m² | DMPOK bodů | Bodů/m² |','|---|---:|---:|---:|---:|');
for(const b of d.source_provenance.building_counts)lines.push(`| ${b.name} | ${b.dmp1g.roof_class6_strict_points} | ${f(b.dmp1g.roof_class6_points_per_footprint_m2,2)} | ${b.dmpok.roof_class6_strict_points} | ${f(b.dmpok.roof_class6_points_per_footprint_m2,2)} |`);
lines.push('','Hustota před oddělením kontrolních bodů. Rozestup 20 cm není přesnost výšky; data z obrazové korelace mohou obsahovat šum a chybné hrany. Datum souboru není automaticky datum snímkování.','', '## Číselné srovnání nové věrnosti','','Buňka: RMSE v metrech / počet nativních střešních ploch. Počet souvislých téměř koplanárních oblastí je jiná, přísnější metrika v HTML.','', '| Půdorys | 0,888 původní | 0,95 | 0,99 | 0,95 + ε 0,15 m | 0,95 + vyšší limity |','|---|---:|---:|---:|---:|---:|');
for(const b of d.buildings){const vals=['roofer_lod22_reference',...profileIds].map(v=>{const r=d.runs.find(r=>r.id===b.id&&r.variant===v);return `${f(r.metrics.holdout_rmse_m)} / ${r.metrics.native_roof_surface_count}${r.status==='lod11_fallback'?' (náhradní)':''}`;});lines.push(`| ${b.name} | ${vals.join(' | ')} |`);}
lines.push('','## Výkon','','Každý nový nativní profil běžel dvakrát na sedmi půdorysech. Níže čas celé dávky CLI; karty mají interní čas budovy. Výsledná geometrie je vždy z prvního opakování, nikoli vybraná nejlepší z opakování.','', '| Profil | Opakování | Medián dávky (s) | Rozsah (s) | Nejvyšší commit procesu (MB) |','|---|---:|---:|---:|---:|');
for(const p of d.performance_summary)lines.push(`| ${p.label} | ${p.repeats} | ${f(p.batch_seconds_median,2)} | ${f(p.batch_seconds_min,2)}–${f(p.batch_seconds_max,2)} | ${f(p.peak_MB,1)} |`);
lines.push('','| Celý pracovní krok včetně režie | Čas (s) | CPU (s) | Peak commit stromu (MB) |','|---|---:|---:|---:|');
for(const [file,label] of [['logs/fidelity-4profiles.log.metrics.json','4 profily Rooferu × 2'],['logs/extraction.log.metrics.json','2 měřítka výstupků × 7 půdorysů'],['volumes.log.metrics.json','2 prahy rozkladu objemů × 7 půdorysů'],['comparison.log.metrics.json','Společné vyhodnocení 98 záznamů']]){const p=read(path.join(root,'.work/cb-roof-components',file));lines.push(`| ${label} | ${f(p.elapsed_seconds,2)} | ${f(p.cpu_seconds,2)} | ${f(p.peak_job_commit_bytes/1e6,1)} |`);}
lines.push('','Tabulky popisují vnořené rozsahy; nesčítejte časy nativních dávek znovu k celému kroku. Párové výstupy odstranění/navrácení mají společný čas, započítává se jednou. Původní Roofer se přičítá k dodatečné extrakci či rozkladu. Dvě opakování na zatíženém počítači nestačí k obecnému tvrzení, že určitý faktor je rychlejší.','', '## Co se nepodařilo a co ověřit dál','','- Rozklad objemů: Budvar jih při 0,75 m má nejednoznačné hranice; kostel v obou variantách nepodporovaný nebo svislý zdrojový střešní trojúhelník. Tyto tři výsledky nemají model.','- Žádná jednoduchá náhrada izolovaných prvků kostela neprošla předem určenou kontrolou tvaru a zachování výšky. Počty 2 a 1 jsou přijaté masky, nikoli úspěšně zjednodušené věžičky.','- Globální RMSE může odměnit i odstranění chybně zachyceného drobného prvku. U extrakce je proto chyba uvnitř masky a mimo ni oddělená; různé masky nejsou totožné hodnoticí podmnožiny.','- Slučování ploch nemusí snížit počet trojúhelníků: nové napojení a vyplnění vyžaduje triangulaci. Členění rovin, silueta a síť jsou odlišná kritéria.','- Další řízený test: speciální jednoduché tvary věžiček (jehlan, kužel, helmice), případně zjednodušení oddělené původní komponenty se zachováním vrcholu. Zde nejsou vykazovány jako provedené.','- Dělení křídel musí zahrnout půdorys a orientaci ploch; samotný svislý skok spojité střechy nerozdělí.','- Doporučení vznikla pro tento malý výběr. Pro univerzální pravidlo je nutné nové nezávislé kolo budov. Stejné mračno rozdělené 80/20 není nezávislé geodetické ověření.','', '## Kontroly a reprodukce','','21 cílených testů algoritmů prošlo. Galerie je offline, používá skutečné měřené sítě, společnou kameru a měřítko. Hloubkový test náhledu řeší pořadí zakrytí stěn a střech, bez úprav geometrie. Stav prohlížečových kontrol je v `.work/cb-roof-components/qa/gallery-ui.json` a konečné kontrole `gallery-final-smoke.json`.','', '16 zachovaných vstupních souborů ověřeno před porovnáním. Každý pracovní výpočet má uložené vstupy, příkaz a otisk implementace. První přerušený pokus je zvlášť v `.work/cb-roof-components/attempt-1-interrupted/`; není zamíchaný do čistého porovnání.','', 'Limity: sériové úlohy, 2 CPU, nejvýše 2 GB pro výpočet, projekt do 20 GB, zastavení pod 25 GB volného disku C:. Ochrana proti uspání je dočasná.','', '[Otevřít HTML](report.html) · [Úplná data](results.json) · [Protokol](protocol.json) · [Předchozí kolo](../roof-simplification/report.html)');
fs.writeFileSync(path.join(dir,'zavery.md'),lines.join('\n')+'\n');
console.log(JSON.stringify({rows:d.runs.length,methods:d.methods.length,unchangedMeasuredPayload:before,resultsSha256:hash(fs.readFileSync(path.join(dir,'results.json')))}));
