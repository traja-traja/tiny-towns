# Společná testovací sada a měření kandidátů (4.10.0)

## Co se změnilo

Virtuální obrys skeletonu může odstranit krátké konvexní zkosení mezi dvěma
významnými stěnami jejich prodloužením do průsečíku. Výchozí limity:
zkosení do 2,5 m; sousední stěny alespoň max(3 m, dvojnásobek zkosení),
úhel 20–160 stupňů. Platí limity posunu/plochy a zachování dvorů. Skutečný
půdorys se nemění. Parametry a přepínač jsou v roof_virtual_outline.py;
použitá reference a operace se ukládají do metadat kandidáta.

Modul straight_skeleton je součástí společného výběru střech a lze jej
vypnout v modules.straight_skeleton. Nejde o pravidlo podle adresy.

## Kdy je skeleton kandidátem

- Plocha alespoň 25 m², alespoň 35 buněk a rozdíl P90–P10 výšek alespoň 0,6 m.
- Půdorys má dvůr, nebo konkávnost alespoň 3,5 % vůči konvexnímu obalu,
  nebo alespoň 5 významných hran a alespoň 8 % nevyplněné plochy minimálního
  otočeného obdélníku.
- Rozpočtové limity: nejvýše 60 zjednodušených hran a 12 000 buněk.
- Plochá většina využije dosavadní přímou cestu; její přeskočení skeletonu je
  výslovně zaznamenané. Samostatné dělení dlouhých/zahnutých staveb se tím neruší.

Nastavení je ve straight_skeleton v roof_config.py. Zvolená omezení jsou
výchozí výpočetní heuristika, nikoli důkaz skutečného typu střechy. Analytické
hřebeny z řezů nevstupují do podmínek ani do výběru.

## Porovnání a náklady

Skeleton i ostatní rodiny používají stejnou mřížku 0,7 m a stejné bodové skóre.
Srovnání zohledňuje složitost a změnu virtuálního obrysu; u blízkých výsledků
nadále platí společná pravidla zjednodušení a ochrany okapů/dvorů.
Místní podpora štítu používá pás 0,8–1,5 m od skutečné hranice, nikoli od
virtuální fasády. Šum souseda se tím obecně neodstraňuje.

Ve společné pipeline se skeletonové kombinace hodnotí jako roviny/oblasti.
Kompletní uzavřený mesh se vytváří při finálním výběru s návratem k dalšímu
kandidátovi při neplatnosti. Samostatný experiment s variants.html si může
nadále vyžádat všechny kompletní geometrie. Knihovna je py_straight_skeleton,
nikoli CGAL; její nedostupnost se zaznamená a zachovají se ostatní kandidáti.

## Co report měří

roof_candidate_telemetry.capture sbírá skutečné pokusy i uvnitř dělení objemů
a zkoušení přístavků. Jednotlivé měřené etapy se nesčítají znovu s nadřazeným
obalovým časem. Rodiny mají počty uvažovaných/přeskočených/zamítnutých/selhaných
pokusů a časy fitu, geometrie a pomocných výpočtů. Počet selected označuje výběr
uvnitř jednotlivého volání, nikoli počet výsledných domů.

Pod každým modelem je rozbalovací podrobný záznam. Na konci HTML jsou tabulky:
četnost a časy rodin, důvody spuštění/přeskočení skeletonu a nejpomalejší domy
s časem analytiky a nejnáročnější rodinou. Souhrn se vytváří ze současných
vrchních částí modelu, nezapočítává znovu předchozí verze ani uložené děti.
Chybějící staré měření není vydáváno za nulu. Stejná data jsou v
candidate-summary.json a v diagnostics.candidate_telemetry jednotlivých částí.

Reportová dávka sbírá podrobnosti a zapíná analytické hřebeny. Mapová/noční
fronta uchovává jen souhrn rodin bez jednotlivých pokusů a analytické hřebeny
vynuceně vypíná. Detailní interní kandidáty není potřeba exportovat jako modely.

## Automatická reprodukce

roof_review_suite.py --source <nejstarsi-slozka> --source <novejsi-slozka>
--output <nova-slozka-vstupu> [--run-output <nova-slozka-reportu>]

Z explicitně uvedených složek vybere poslední vstup a model podle ID, ověří
kontrolní součty mračen a zachová poskytovatelské záznamy. Nečte obsah bodů
kvůli posuzování ani znovu nestahuje data. Následný roof_batch.py archivuje
skutečné NPZ vstupy a běží po jednom domu s průběžnými checkpointy.

Připravená sada 2026-11-17 má 54 domů (45 ČB + 9 Velešín), nikoli odhadovaných
50. Vstupy a předchozí modely: cities/ceske-budejovice/experiments/
roof-v410-review-inputs-54. Provenience je v suite.json.

Dávka: python scripts/roof_batch.py --inputs
cities/ceske-budejovice/experiments/roof-v410-review-inputs-54/inputs.json
--test --previous cities/ceske-budejovice/experiments/roof-v410-review-inputs-54
--split-volumes --output cities/ceske-budejovice/experiments/roof-v410-review-54
--url-base http://127.0.0.1:8877

Při přerušení použít stejný příkaz s --resume; ověřuje shodné vstupy,
konfiguraci i numerický kód. V tomto prostředí používáme lokální .venv Python,
1 numerické vlákno a resource_guard (max. 2 GB procesu, nejméně 25 GB volného
C:, maximální velikost projektu 20 GB). Ochrana před uspáním je aktivní po běh.

## Ověření a stav

Osm testů virtuálního obrysu, devět skeletonové integrace/štítů, dvě kontroly
přípravy vstupů, 27 společných integračních testů a tři JS sady prošly.
Výsledné geometrie nejsou opticky posuzované. Dokončení skutečné dávky je
uvedené až v run.json; tento popis sám o sobě dokončení netvrdí.


## Dokončený běh 2026-11-17

Série dokončila 54/54 domů, 54/54 částí má úplnou podrobnou telemetrii,
bez chyb na úrovni domu. Výpočet střech 352,445 s (5 min 52 s), z toho
analytické hřebeny 33,585 s; bez analytiky 318,860 s. Skript včetně načítání,
checkpointů, HTML a zabalených vstupů 441,866 s (7 min 22 s). Hlídaný proces
449,546 s, peak commit 471,7 MiB. Po dokončení C: 69,63 GB volných,
projekt 5,96 GB, obě stanovené diskové meze dodrženy.

Skeleton byl skutečně zkoušen na 32/54 domech: 133 povolených interních
volání, 2 537 kandidátních pokusů včetně dělení/přístavků, celkem 44,140 s.
91 volání bylo přeskočeno; jeden dům může obsahovat povolené i přeskočené
objemy. 16 dílčích skeletonových pokusů skončilo konstrukční chybou a bylo
zachováno v logu; standardní výběr pokračoval jinými kandidáty. To není
16 chybějících domů. Počty pokusů nejsou počty iterací optimalizátoru.

Nejdelší výpočty: Dr. Stejskala 426/15 (29,749 s), Husova tř. 1829/12
(27,978 s), náměstí J. V. Kamarýta 69 ve Velešíně (21,634 s).

Report, candidate-summary.json a inputs.json vracejí HTTP 200. Souhrnné
tabulky jsou pod porovnáním domů. Optické hodnocení nebylo provedeno.
Stav a prostředky: completion-summary.json, resource-summary.json, run.json.

Report: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-v410-review-54/report.html

Časy: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-v410-review-54/report.html#candidate-performance
