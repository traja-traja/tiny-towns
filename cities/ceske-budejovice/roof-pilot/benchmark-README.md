# ČB: měřený pilot střech

Samostatný experiment pro 30 půdorysů v centru Českých Budějovic. Výběr a zdůvodnění identit jsou v `sample.json` a jeho `README.md`. Základní městské preview ani původní experiment Velešína se tímto během nemění.

## Reprodukce

Spouštět z kořene projektu. Skripty vyžadují dokončené základní preview včetně checkpointu `web`; všechny náročné kroky běží postupně pod `resource_guard`.

```powershell
.venv\Scripts\python.exe -X utf8 scripts\cb_roof_sources.py
.venv\Scripts\python.exe -X utf8 scripts\cb_roof_sources.py --prepare
.venv\Scripts\python.exe -X utf8 scripts\cb_roof_pilot.py --execute
```

První příkaz pouze vypíše vybrané mapové listy z již staženého katalogu. Další kroky stáhnou potřebná DMPOK data, vyříznou body a změří algoritmy. DMP1G se používá z cache základního preview. Dokončené kroky mají checkpoint; změna vzorku, zdrojového manifestu či implementace jeho platnost zruší. Existující zdrojový manifest s odlišným vzorkem vyžaduje vědomé spuštění `--force` po kontrole změny.

## Co se porovnává

| Metoda | Vstupy a volba modelu | Měřený čas |
| --- | --- | --- |
| Základní aproximace | Půdorys, výškové kvantily, orientovaný obdélník, dostupné zdrojové atributy | Medián 3 opakování modelu + mesh; není přesným opakováním produkčního rendereru |
| Parametrické šablony | Plochá, pultová, sedlová, valbová a válcová střecha; nejvýše 3500 bodů a 4 počáteční orientace | Medián 3 opakování včetně výběru a tvorby mesh |
| Roofer 1.0.0 | Skutečný CLI nástroj, LoD2.2, default complexity 0.888, 1 pracovní vlákno; vlastní terénní výška | Jedna dávka na zdroj: vnitřní čas každé budovy a celý CLI běh samostatně |

Půdorysy se nepovažují za nezávislé celé domy: složený objekt může mít více půdorysů. Výběr je záměrně obtížný, a proto nezastupuje průměrnou budovu celého města.

Před výpočtem se globálně oddělí 20 % bodů třídy 6, seed `20261115`. Stejné zadržené body jsou vynechány ze vstupu všech tří metod v rámci jednoho zdroje. Body třídy 2 slouží pro medián terénu v prstenci do 20 m. Klasifikace se nemění, nové body se nevymýšlejí, přesné duplicity XYZ + třída se odstraní. Souřadnice jsou EPSG:5514, výšky podle produktu Bpv.

RMSE/MAE a pokrytí vypovídají o shodě se zadrženými body **téhož zdroje**. Nejde o nezávislé zaměření ani o posouzení fasády, podloubí nebo správného typu střechy. Fotogrammetrické body jsou prostorově korelované; hustší data nejsou automaticky přesnější. Historie snímkování a změny staveb mohou být důležitější než numerická chyba.

## Záznamy a zdroje

- `results.json`: jednotlivé budovy, úspěch/selhání, modely, chyby, časy, složitost a metadata prostředí.
- `report.html`: samostatné offline porovnání šesti variant, společná rotace a měřítko.
- `.work/cb-roof-pilot/sources/sources.json`: oficiální URL, ATOM metadata, soubory, SHA256, počty bodů a oddělené časy stažení/rozbalení/výřezu.
- `.work/cb-roof-pilot/logs/`: stdout/stderr každé metody a `*.metrics.json` s časem celého pracovního procesu, CPU časem procesového stromu (user/kernel), počtem procesů a špičkou commitované paměti.
- `.work/cb-roof-pilot/implementation/`: neměnné kopie a kontrolní součty použitých skriptů; pro spuštění je potřeba původní projektové prostředí.
- `.work/cb-roof-pilot/<zdroj>/train.laz`: skutečný vstup Rooferu bez zadržených bodů; `split.json` obsahuje seed, počty a hash.

ČÚZK: [DMP1G](https://geoportal.cuzk.cz/) a [oficiální ATOM DMPOK](https://atom.cuzk.gov.cz/DMPOK-SJTSK-LAZ/DMPOK-SJTSK-LAZ.xml). Přesné odkazy na vybrané produkty jsou v manifestu. Půdorysy pocházejí z lokálního výřezu Overture; zdrojové atributy a identifikátory zachovává `sample.json`. [Roofer](https://github.com/3DBAG/roofer) se používá jako skutečný stažený nástroj; jeho původ, verze a kontrolní součty se ukládají do výsledků.

## Výpočetní omezení

Každý pracovní proces má limit 2 GB commitované paměti včetně potomků, nejvýše 2 přidělená CPU, nízkou prioritu a před startem čeká alespoň na 1 GB dostupné RAM. Roofer používá 1 pracovní vlákno. `peak_job_commit_bytes` není rezidentní fyzická RAM. Hlídač vynucuje celý projekt do 20 GB a volné místo na C: nejméně 25 GB s rezervou. Po dobu chráněného běhu se dočasně blokuje automatické uspání, obrazovka se může vypnout.

Údaje z cache se nezapočítávají jako nové stažení. Čas přípravy celoměstského preview a sdíleného katalogu není skrytě přičítán jednotlivým střechám. Selhání zůstávají ve výsledcích, nenahrazují se úspěchem jiné metody.

## Přerušené pokusy

První příprava DMP1G byla přerušena změnou hostitelského sandboxu dříve, než vznikl zdrojový manifest a výřez. Poslední log potvrzuje přečtení CBUD22 (19,6414 s) a CBUD23 (17,7498 s), ale nepotvrzuje dokončení přípravy. Log je zachován v `.work/cb-roof-pilot/sources/prepare-dmp1g.interrupted-sandbox.log`. Celkový čas a špičku paměti tohoto nedokončeného pokusu neznáme a neodhadujeme je. Po opravě prostředí byla příprava spuštěna znovu; její naměřené metriky jsou samostatné.

## Pozorování k chybějícím podkladům

V půdorysech Černé věže, Rabenštejnské věže a Železné panny nejsou v použitém DMP1G výřezu žádné body třídy 6. Jde o nedostatek konkrétních vstupních bodů, nikoli důkaz novějšího stáří stavby. U posledních dvou vytvořila základní aproximace pouze atributový odhad, označený `source_attributes_only` a `no_point_validation`; takový model nemá ověřené RMSE.

Použitý záznam Černé věže má `has_parts=true`, ale hlavní atributy výšky a střechy jsou prázdné. Základní harvest načetl typ Overture `building`, nikoli `building_part`. `has_parts` je proto zároveň stopa dalšího nevyužitého strukturálního zdroje. Konkrétní záznamy částí věže nebyly v tomto pilotu ověřeny: **nelze z toho vyvozovat, že výšky chybí v celé Overture**. Pevný vzorek zůstal beze změny; ověření částí je kandidát pro další kolo.

## Naměřené výsledky dokončeného běhu

| Zdroj / metoda | Modely z 30 | Součet časů modelování | Medián RMSE budovy | Celý worker | CPU workeru | Peak commit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DMP1G / základní aproximace | 29 | 0,362 s | 4,847 m | 9,570 s | 8,094 s | 109,4 MB |
| DMP1G / šablony | 27 | 4,203 s | 3,770 m | 31,680 s | 27,109 s | 146,4 MB |
| DMP1G / Roofer | 27 | 1,655 s | 4,800 m | 31,710 s | 24,453 s | 118,0 MB |
| DMPOK / základní aproximace | 30 | 0,841 s | 2,230 m | 64,441 s | 45,922 s | 226,5 MB |
| DMPOK / šablony | 30 | 7,760 s | 1,167 m | 63,410 s | 59,328 s | 229,1 MB |
| DMPOK / Roofer | 29 | 58,685 s | 0,530 m | 101,233 s | 127,547 s | 310,7 MB |

Součet časů modelování má odlišný původ podle metody: baseline a šablony sčítají mediány tří lokálních opakování, Roofer sčítá vlastní zaznamenané časy budov jednoho skutečného běhu. Worker zahrnuje načtení, výběr bodů, vyhodnocení a zápis; zdrojové stažení a výřez jsou uvedeny zvlášť níže. Dva DMP1G baseline modely jsou pouze atributové odhady, takže jeho medián RMSE vychází z 27 ověřitelných budov. Model označený `lod11_fallback` se počítá jako vytvořená geometrie, nikoli jako úspěšné obnovení detailní střechy.

Samotný Roofer CLI trval 2,280 s na DMP1G a 65,955 s na DMPOK. Je vnořený do příslušného workeru; **tyto časy, CPU ani paměť se k celému workeru znovu nepřičítají**. Workerové časy pocházejí z jednoho běhu za aktuálního zatížení počítače. Rozdíl 64,44 vs. 63,41 s není důkaz, že náročnější šablony stojí méně výpočetního času.

Na stejných zadržených DMPOK bodech zlepšily šablony RMSE oproti baseline u 28 z 30 budov; Roofer u všech 29 budov, které vytvořil. Medián celkového počtu trojúhelníků byl 68 / 56 / 156 (baseline / šablony / Roofer). To neznamená, že každý konkrétní model má přijatelnou složitost: například bazén má v Rooferu 1150 trojúhelníků a výrazně složený půdorys. Jedna šablona přes celý jeho půdorys dosáhla pouze RMSE 2,16 m; Roofer 0,58 m. Zda model vystihuje rozpoznatelné architektonické části, je samostatná vizuální otázka.

### Příprava dat

| Zdroj | Výsledné body | Výřez a NPZ | Celý zdrojový worker | CPU | Peak commit |
| --- | ---: | ---: | ---: | ---: | ---: |
| DMP1G z existující cache | 70 068 | 8,197 s | 32,163 s | 23,094 s | 58,3 MB |
| DMPOK, dva nově stažené listy | 2 735 725 | 325,025 s | 779,086 s | 529,453 s | 449,3 MB |

DMPOK obsahuje v okolí vzorku 1 335 247 bodů třídy 6 a 1 031 092 bodů terénu třídy 2. Výřez zůstává v původní klasifikaci včetně ostatních tříd. Celkem se streamově přečetlo 250 milionů bodů ze dvou plných LAZ; plné nekomprimované LAS nebyly ukládány. Výsledný NPZ má 12,36 MB; DMP1G NPZ 0,59 MB.

Dva DMPOK ZIPy mají dohromady 697,16 MB. Jejich samotné stažení trvalo 377,294 s, včetně potřebných malých feedů 398,624 s; rozbalení 17,327 s. Dřívější společný hlavní katalog byl znovu použit z cache. Celé komprimované LAZ zůstaly pro další lokální výřezy. ATOM metadata obou konkrétních listů uvádějí práva textem „žádné podmínky neplatí“; původ a přesné URL jsou zachovány v manifestu, nejde o tvrzení o licencích ostatních vstupů projektu.

### Výjimky a audit ploch

- Černá věž má v DMPOK 3050 bodů třídy 6, ale Roofer ji označil `pointcloud_unusable` a `skip` a nevytvořil geometrii. Šablony a baseline model vytvořily. Samotná přítomnost bodů tudíž nezaručuje úspěch každé metody.
- Severní půdorys Budvar arény přešel u Rooferu do `lod11_fallback` po dosažení limitu region growing. Výsledek je viditelně označen jako zjednodušený náhradní objem.
- U Krajinské 44/10 se při převodu vynechala jediná nulová `WallSurface`: dva ze tří vrcholů mají už v raw CityJSON stejné souřadnice.
- U náměstí čp. 67 se vynechala jediná nulová `WallSurface`: tři vrcholy leží na stejné svislé úsečce dlouhé 2 mm.
- Všech 388 `RoofSurface` a 29 `GroundSurface` prošlo; přijato bylo 2227 stěnových ploch a vynechány dvě. Tyto stěny nevstupují do střešního testu: obě budovy mají pokrytí zadržených střešních bodů 100 %, RMSE 0,1666 a 0,5380 m. Export má krok 1 mm; příčinu před exportem neznáme. Audit nedokazuje uzavřenost celého objemu.

Podrobný audit v `.work/cb-roof-pilot/surface-audit.json` je navázán na SHA256 konkrétního raw CityJSON. Opakování převodu ploch trvalo 10,149 s za souběhu následné práce, CPU 3,188 s, peak commit 51,2 MB; nejde o nový běh rekonstrukce.

## Doporučení pro další volbu

Pro tento obtížný vzorek jsou husté DMPOK body podstatně užitečnější než samotné DMP1G. Jednoduché šablony dávají levné, malé modely pro běžné střechy; složené budovy je vhodné nejprve rozdělit na skutečné objemy. Roofer zde nejlépe vystihl výškové body, ale potřebuje kontrolu chybějících výstupů, explicitních fallbacků a složitosti. Je vhodný pro vybrané problematické budovy a pro srovnání se silnější regularizací a LoD1.3 objemy v navazujícím experimentu.

Tyto výsledky **nedokládají zlepšení celého mapového buildu v limitu +20–30 % času**. Baseline je aproximace a měříme oddělený Python/CLI pilot, nikoli výměnu v produkčním rendereru. Základní preview proto zůstává na původní metodě, detailní výstupy slouží k výběru a ověření před plošným nasazením. U věží je navíc vhodné prověřit strukturu `building_part` a doložené rozměry místo vynucování obecného tvaru z nedostatečných dat.

## Dokončené kontroly

Validace potvrdila 180 očekávaných běhů, stejná počítaná/zadržená množství bodů mezi metodami v rámci zdroje, konečné souřadnice a platné indexy/sémantiku všech 172 vytvořených modelů. Validace trvala 0,844 s, CPU 0,781 s, peak commit 58,4 MB. Nezastupuje kontrolu samoprůniků, uzavřenosti ani architektonické správnosti.

Offline Playwright kontrola prošla: 30 možností výběru, 6 panelů, změna budovy/rotace, čtyři uložené pohledy, mobilní šířka bez přetékání, žádné chyby JavaScriptu a žádné HTTP požadavky. Trvala 4,612 s, CPU 5,047 s, peak commit 243,6 MB. Screenshoty a `report-ui.json` jsou v `.work/cb-roof-pilot/qa/`. Pohled bazénu byl také prohlédnut; jednotlivé experimentální modely nelze pokládat za ověřenou podobu skutečnosti pouze na základě funkčního prohlížeče.

```powershell
# Obnova dokumentačních poznámek je vázaná na tento konkrétní raw Roofer běh.
.venv\Scripts\python.exe -X utf8 .work\cb-roof-pilot\audit_surfaces.py
.venv\Scripts\python.exe -X utf8 .work\cb-roof-pilot\review_results.py
node scripts\check_roof_report.mjs ceske-budejovice
```

Při novém benchmarku je nutné zkontrolovat a aktualizovat vazbu auditu na jeho nové raw soubory. Změna pouze poznámek nemění naměřené modely, body ani časy.
