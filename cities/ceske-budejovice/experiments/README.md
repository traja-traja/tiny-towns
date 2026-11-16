# České Budějovice – izolované experimenty

Otevři `report.html`: samostatná galerie bez síťových požadavků. Pro interaktivní mapu spusť dvojklikem [`../otevrit-nahled.cmd`](../otevrit-nahled.cmd) a nech okno terminálu otevřené. Spouštěč otevře místní přehled a mapu; nic nestahuje. Zobrazuje skutečně vygenerované výsledky a rozlišuje naměřené metriky, fotografické pozorování a předpoklady. Podrobné testy 18 střech, podloubí a fasád nejsou nasazené v městské mapě. Samostatnou opravu pravidla pro střechy dokládá mapové preview a `roof-heights/map-rebuild.json`.

- Základní pilot: 30 půdorysů, viz `../roof-pilot/report.html`.
- První srovnání ve Velešíně: `../../velesin/roof-pilot/report.html`.
- Podrobné testy: 18 různých půdorysů, limit uživatele je 20.
- Střešní varianty: 56 záznamů (54 hlavních, 2 cílených doplňujících pokusů).
- Podloubí: 21 modelů.
- Fasády: 3 domy.

## Obnovení přehledu

Z kořene projektu:

```powershell
.venv\Scripts\python.exe -X utf8 scripts\cb_experiment_report.py
```

Skript pouze čte výsledky. Nespouští rekonstrukci, nestahuje data a neupravuje renderer. Vyžaduje všechny tři dokončené soubory `roofs/results.json`, `arcades/results.json`, `facades/results.json`, společný výběr budov a existující SVG/ROI náhledy fasád. Ověřuje společné identity a limit 20 detailních půdorysů. `protocol.json` obsahuje kontrolní součty vstupů, včetně vložených obrázků.

## Ověření offline galerie

```powershell
.venv\Scripts\python.exe -X utf8 scripts\resource_guard.py run --log .work\cb-experiments\qa\gallery-ui.log --max-ram-gb 1 --min-available-gb 1 -- node scripts\check_cb_experiments.mjs
```

`../../../.work/cb-experiments/qa/gallery-ui.json` zachovává výsledek konkrétního UI běhu: všech 18 střešních voleb včetně chybějící geometrie, tři domy s podloubím v obou hloubkách, změnu kamery, devět SVG a tři ROI, pět fotografických kontrol, lokální odkazy, nulové síťové požadavky a šířku 390 px bez přetečení. Snímky jsou ve stejném adresáři. Procesní měření sestavení a UI kontroly jsou v přilehlých `report-build-final.log.metrics.json` a `gallery-ui.log.metrics.json`; jejich časy nejsou náklady rekonstrukce střech. Browser QA se spouští až po dokončení těžkých výpočtů a finálního mapového porovnání.

## Jak rozhodovat

| Oblast | Co porovnat | Co metrika neprokazuje |
| --- | --- | --- |
| Střechy | Hlavní hřeben a tvar, shoda holdout bodů, pokrytí, složitost, čas | Nízké RMSE samo nepotvrzuje skutečný typ střechy ani nezávislou přesnost |
| Výškové objemy | Počet hlavních hmot, počet ploch, velikost modelu | LoD1.3 nereprodukuje skloněné střešní roviny |
| Podloubí | Prázdný prostor, průchodnost paprsku, pilíře, 8/16 segmentů a 2/3,5 m hloubky | Odhadnutá hloubka ani úspěšný test neprokazují dnešní stav a přístupnost |
| Fasády | Stabilita dvou barev, odlehlé pixely, soulad se zdrojovou fotografií | Nejde o kalibrovanou materiálovou barvu; členění SVG je schematické |

Devět hlavních střešních dávek má zachované kontrolní součty trénovacích dat a půdorysů, nativní výstupy, příkaz a verzi Rooferu. Nemá však execution snapshot Python wrapperu; dodatečný SHA aktuálního souboru nedokazuje přesné bajty načtené při startu. Kontrolní součty protokolu zachycují vstupy v okamžiku sestavení galerie.

Ruční čas rešerše a vymezení fasádních oblastí nebyl měřen. Milisekundy barevného algoritmu nejsou celková pracnost budovy.

Čas metody, načtení, exportu a celého procesu se nesčítá ani nezaměňuje bez vysvětlení. Peak committed memory je jiná veličina než resident working set. Výběr obsahuje záměrně obtížné objekty a nelze jej bez dalšího zobecnit na celé město.

## Zdroje a licence

Rešerše jsou v `roofs/method-review.json`, `arcades/source-review.json` a `facades/source-review.json`; galerie je také obsahuje. U fotografie je uveden autor, datum, konkrétní stránka a licence. Commons fotografie a jejich zmenšené či anotované výřezy zachovávají původní licenci; pro CC BY-SA výřezy platí stejná licence. Vektorové fasády představují vlastní schematické barevné testy, nejsou fototextury ani zaměřené výkresy.

## Samostatný audit výšek

`roof-heights/README.md`, `roof-heights/results.json` a samostatná otočná galerie `roof-heights/fit-report.html` dokumentují 12 cílených diagnostických případů kolem dvou náměstí. Audit není rozšířením 30/18 půdorysů. U Na Mlýnské stoce 367 původní pravidlo přepisovalo známý sedlový typ na plochý; konzervativní oprava zachovává střešní objem. Dr. Tůmy je kandidát jednoduché sedlové šablony, Baara vyžaduje rozdělení částí; ani jeden fit není automatické nasazení. Pásy oken po 2,8 m jsou samostatná procedurální heuristika, nikoli skutečný počet podlaží. Aktuální nasazení dokládá `roof-heights/map-rebuild.json` a vložený pár snímků skutečných dlaždic; ostatní experimenty zůstávají izolované.

## Druhé kolo

`round-2-candidates.json` a `round-2-README.md` obsahují další kandidáty. Jde o dosud netestované objekty, bez přičítání k aktuálním 30 půdorysům nebo detailním testům. U Slavie rozlišujeme stav před obnovou a po ní; staré mračno nemůže potvrzovat nové detaily.

## Limity zdrojů

Celý projekt má limit 20 GB a práce se zastaví při volném místě na C: pod 25 GB. Dílčí pracovní procesy používají resource_guard. Výsledky zahrnují procesní protokoly; galerie sama nevykonává výpočetně náročné rekonstrukce. Hromadná data se nezpracovávají AI modelem.
