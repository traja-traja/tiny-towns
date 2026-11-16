# Velešín: výběr pro pilot rekonstrukce střech

`sample.json` je GeoJSON FeatureCollection s **30 původními půdorysy ve 27 skupinách**. Výběr pokrývá náměstí, oba kostely, radnici, vodárenskou věž, MŠ, ZŠ, Sportcentrum, bytové bloky, běžné domy, průmyslové objekty a drobnou garáž. Celý rozsah měří přibližně 586 × 833 metrů. Výpočetní pilot nad DMP1G i DMPOK je dokončen; výsledky obsahují `results.json` a `report.html`.

Samotný výběrový manifest není zaměřený referenční model. Typy střech z lokálních dat slouží pouze k výběru různých případů. Shoda rekonstrukce s body sama nepotvrzuje skutečný typ střechy. Výběr je účelový, nikoli statistický vzorek celého města.

## Identita a seskupení

- Radnice má dva zdrojové půdorysy, čp. 76 a 77 (`group_id: townhall`).
- Bývalý kostel sv. Filipa a Jakuba má tři zdrojové půdorysy, čp. 87, 88 a 89 (`church-jakub`). Jejich společnou identitu potvrzuje zápis zastupitelstva z 31. 10. 2011, strana 1. Při hodnocení střech je třeba posuzovat i celý komplex.
- Kostel sv. Václava je samostatný půdorys identifikovaný názvem v datech.
- MŠ je ověřena adresou Školní 223. Západní členitý objekt je **pouze kandidát části areálu**. Není doloženo, že jde o novou přístavbu, proto má samostatnou skupinu.
- Vodárenská věž je propojena s třídou `water_tower` v lokální vrstvě infrastructure přes tutéž OSM way `104236088`.
- Sportcentrum odkazuje na existující model `../models/sportcentrum-velesin.source.json`. Jde o dřívější zjednodušenou referenci kontrolovanou s uživatelem, ne o nezávislé zaměření. Zachycuje válcovou střechu, různé výšky a průchod.
- U bytových bloků jsou ověřeny adresy. Panelová konstrukce zůstává kandidátním označením. U anonymních průmyslových objektů a členitých přístaveb je nejistota výslovně zapsána.

Veřejné zdroje, jejich přesné URL a účel jsou v `identity_references`. Každý prvek má `identity.reference_keys`, zdrojové OSM odkazy a adresní body ČÚZK, které leží uvnitř jeho půdorysu. POI body jsou pouze pomocná indicie.

## Formát a opakování výběru

`Feature.id` je původní UUID budovy; `properties.pilot_id` je čitelné pořadové označení `VEL-ROOF-01` až `VEL-ROOF-30`. Geometrie zůstává beze změny v pořadí longitude, latitude (WGS84). Každý prvek obsahuje centroid, obálku WGS84, obálku EPSG:5514, plochu a atributy zdroje. Celková obálka je i na kořeni kolekce.

Ze složky projektu:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/select_roof_pilot.py
.venv/Scripts/python.exe -X utf8 scripts/select_roof_pilot.py --check
```

Skript pouze čte existující malé soubory `building`, `address`, `places` a `infrastructure` z `.work/.preview/velesin/data/` a místní referenci Sportcentra. Ověřuje jedinečnost 30 ID, validitu půdorysů, požadované adresy, název kostela a vazbu vodárenské věže. `--check` ověřuje přesnou reprodukovatelnost bez zápisu. Kontrolní otisky vstupů jsou uloženy v `source_inputs`.

Skript nic nestahuje ani nevykresluje. Před zápisem zastaví při volném místě pod 25 GiB. Správu celkového limitu pracovních dat řeší navazující pilotní workflow.

## Výpočetní porovnání

```powershell
.venv/Scripts/python.exe -X utf8 scripts/roof_pilot_sources.py --prepare
.venv/Scripts/python.exe -X utf8 scripts/roof_pilot.py --execute
```

Výsledky jsou v `results.json` a samostatném `report.html`. Report funguje bez sítě; lze vybrat dům a společně otáčet šest pohledů. Původní dlaždice Velešína se tím nemění. Mračna, binární Roofer, mezivýsledky a logy jsou v `.work/roof-pilot/`.

1. **Základní odhad:** aproximace stávající heuristiky, atribut střechy, orientovaný obdélník a percentily výšek. Není to přesný běh celého rendereru ani jeho ručních výjimek.
2. **Parametrické šablony:** plochá, pultová, sedlová, valbová a válcová/oblouková střecha. Parametry se přizpůsobí bodům, výběr penalizuje složitost. Fit má nejvýše 3 500 bodů a čtyři výchozí orientace. Složitý dům stále popisuje jediná šablona.
3. **Roofer 1.0.0:** skutečný místní program, jedno vlákno, standardní detekce rovin a rekonstrukce LoD2.2. Nižší LoD při nedostatku dat či překročení limitu zůstává označeno. Široký typ `slanted` neznamená určení sedlové či valbové střechy.

Každá metoda dostává stejné půdorysy a stejný trénovací výběr v rámci zdroje. Dvacet procent bodů budov je odloženo před rekonstrukcí včetně vstupu Rooferu. RMSE je shoda se zadrženými body téhož zdroje; **není to zaměřená přesnost ani důkaz správného typu střechy**. Fotogrammetrické body jsou prostorově korelované a dvě sady vznikly různými metodami v různém období.

Časy základního odhadu a šablon jsou mediány tří opakování modelu včetně mesh. Roofer uvádí vlastní čas rekonstrukce a odděleně celou dávku s I/O. Stažení, rozbalení, výběr bodů a procesové režie jsou vedeny zvlášť. Paměť jobu je Windows committed memory, nikoli přesná spotřeba fyzické RAM.

`resource_guard.py` omezuje procesový strom, volí dvě dostupná jádra a nižší prioritu, sleduje volnou paměť a disk. Celý projekt má rozpočet 20 desetinných GB; pod 25 GB volných na C: práce skončí. Po dobu běhu dočasně blokuje automatické uspání systému, nikoli zhasnutí monitoru. Trvalé nastavení napájení nemění.

## Následující preview Českých Budějovic

Teprve po dokončení porovnání:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/build_preview_guarded.py --execute
```

Výstup: `.work/.preview/ceske-budejovice/site/`, centrum 2,3 × 2,3 km. Zpracování je deterministické, bez AI volání, se základním modelem střech. Dokončené kroky se ukládají do checkpointu a při opakovaném spuštění se ověřují. Stav je v `build/preview-checkpoint.json`, jednotlivé logy v `build/preview-logs/`.
