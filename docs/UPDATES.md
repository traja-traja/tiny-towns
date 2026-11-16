# Aktualizace a rozšiřování Tiny Towns

## Jeden fork pro obě města

Cílový repozitář je `traja-traja/tiny-towns`, fork `adamklatovsky/izomapa`. Vlastní úpravy ukládáme na `main`, původní projekt sledujeme jako `upstream`. Lokální adresář může mít jiný název než repozitář.

Základ této přípravy identifikuje `upstream.json`. Před aktualizací porovnáme změny od uloženého commitu. Nesynchronizujeme hlavní větev automatickým přepsáním.

Po běžném naklonování vlastního forku lze jednou nastavit zdroj:

```sh
git remote add upstream https://github.com/adamklatovsky/izomapa.git
```

Aktualizaci připravíme na samostatné větvi, projdeme rozdíly, sloučíme změny a ověříme oba výřezy. Do `main` se dostane až zkontrolovaný výsledek. Například v čistém pracovním stromu:

```sh
git fetch upstream
git switch -c update/izomapa-YYYY-MM-DD
git log --oneline HEAD..upstream/main
git diff HEAD...upstream/main
git merge upstream/main
python -m unittest discover -s tests -p "test_towns.py"
python -m unittest discover -s tests -p "test_city_coverage.py"
```

Testy pokrytí vyžadují prostředí `.venv`. Následuje zkušební render obou měst, vizuální kontrola švů a ověření vlastních modelů. Závislosti případně doinstalujeme podle změn upstreamu. Nový přijatý commit zapíšeme do `upstream.json`. Frekvenci kontrol volíme podle potřeby projektu; automatické sledování zatím není nastavené.

## Oddělené druhy aktualizací

| Co měníme | Postup |
| --- | --- |
| Kód původní Izomapy | Kontrolované sloučení z upstreamu, testy a nové rendery podle změn |
| Geografická data | Samostatně stáhnout novou verzi, zaznamenat zdroj a datum, porovnat výsledek |
| Hranici nebo střed mapy | Znovu vygenerovat konfiguraci a použít nové pracovní adresáře |
| Ruční budovy a lokální opravy | Upravovat soubory v `cities/<město>/assets/`, znovu vykreslit dotčené čtverce |
| Projekty a městské informace | Uchovávat zdroj, datum platnosti a souřadnice nezávisle na rendereru |

Výměna kódu sama neaktualizuje data uložená v cache. Některé nástroje upstreamu mají zdrojové edice nebo URL přímo v kódu. Nové vydání dat je proto samostatná ověřovaná změna. Před zpracováním nových dat odložíme stávající `.work/<město>` stranou a zachováme poslední publikovaný výstup.

## Hranice a reproducibilita

`boundary.geojson` je uložená hranice obce s poskytovatelem, URL a datem stažení v `boundary-source.json`. Jde o hranici pro vizualizaci, nikoli podklad pro rozhodování o parcelách. `profile.json` obsahuje texty, střed a rozšíření mapy; vygenerovaný `mesto.json` používá přímo Izomapa. `coverage.json` dokládá pokrytí polygonu. Uložená hranice zachovává i oddělené části obce a malé úseky u okrajů. Čtverce sahají za administrativní hranici.

```text
.venv/Scripts/python scripts/configure_city.py plan velesin
.venv/Scripts/python scripts/configure_city.py generate velesin
.venv/Scripts/python scripts/configure_city.py generate velesin --preview 1
```

Na Linuxu/macOS použij `.venv/bin/python`. `scripts/fetch_city_inputs.py <město>` umí načíst hranici z ČÚZK, obnovit chybějící referenční terén a připravit konfigurace. Existující podklady zachovává a ověřuje jejich identitu; aktualizaci hranice a konfigurací provede jen s `--replace`. `plan` vypíše potřebné referenční dlaždice terénu a jejich URL; při ručním stahování musí být uložené do uvedených cest. `terrain-source.json` zaznamenává stažené soubory a jejich kontrolní součty. Generátor bez nich výškovou referenci nevymýšlí. Volba `--replace` nejprve zálohuje existující konfiguraci. Preview má stejnou výškovou referenci jako celá mapa, ale nepředstavuje celé území.

## Budoucí mapa v reálném 3D

Dnešní Izomapa vytváří 3D scény při sestavení a do webu posílá hotové obrazové dlaždice. Přechod na živé 3D bude vyžadovat jiný prohlížeč a napojení na data. Hotové obrázky nenahradí 3D model.

Až vzniknou vlastní budovy, uchováme zdrojovou geometrii zvlášť, ideálně i v přenosném GLB, s jednotkami, orientací, polohou WGS84 a zdroji podkladů. Napojení na `assets/custom_models.js` bude adaptér pro Izomapu. Samotný model, městská data a jejich identifikátory tak půjde použít znovu; napojení na jiný renderer bude nutné dopracovat. Stávající lokální souřadnice a parametry specifické pro Izomapu nejsou samy o sobě zárukou přenositelnosti.

Budoucí projekty budou mít vlastní identifikátor, geometrii, stav, zdroje a čas platnosti. Propojení s usneseními rady a rozpočtem lze přidat nad těmito daty.

## Dopravní model Českých Budějovic

Pohyb aut v původní Izomapě je animace. Ani hustota odvozená ze sčítání sama nepočítá objížďky a vznik kolon. Budoucí model musí oddělit síť, poptávku, kapacity, pravidla křižovatek a scénáře uzavírek od vizualizace. Síť i poptávku je nutné kalibrovat a scénáře porovnávat se stejnými předpoklady. Výsledné průjezdy a zdržení pak může zobrazit izometrická i skutečně 3D mapa.

V této fázi model ani příjem živých dopravních dat nejsou implementované.

Konkrétní náměty pro ČB (České Budějovice), včetně kolon, ovládání semaforů, parkovacích scénářů a miniher, jsou v [projektovém TODO](TODO.md).


## Experiment střech v2 — 2026-11-16

Nový oddělený algoritmus je v `scripts/roof_v2.py`, geometrii staví `roof_v2_geometry.py`, dávku připravuje `cb_roof_v2.py`. Nepoužívá starý `roof_inference.py` ani Roofer. Zdroj: lokální husté DMPOK CBUD22/23; 30 domů, 145 523 trénovacích a 36 446 oddělených kontrolních bodů.

Dokumentace a interaktivní výsledky: `cities/ceske-budejovice/experiments/roof-v2/ALGORITHM.md`, `RUN.md`, `report.html`, `comparison.html`, `tiles/report.html`. Přesná měření a zdrojové kontrolní součty jsou v `benchmark.json`. Vývojové iterace se uchovávají v `.work/cb-roof-v2/iterations`.

Verze 2.3 opravuje tvrdé vyřazování slabě doložených sklonů, záměnu malého úhlu za malé převýšení, záměnu úžlabí za hřeben a numerické rozpojení ploch. Výsledné objemy jsou uzavřené; 28 syntetických a geometrických testů prošlo. Kontrolní body jsou vývojový vzorek stejného měření, nikoli nezávislá architektonická pravda.

Na pěti společných domech má nová geometrie 64 střešních trojúhelníků místo 85. Medián odchylky 0,287 m místo 0,304 m, RMSE ale 1,143 m místo 1,097 m a p90 1,417 m místo 1,179 m. Úspora geometrie tedy není automaticky zlepšením všech metrik. Opticky posuzuje Pavel, nikoli AI. Hlavní mapy nejsou nahrazeny experimentem.


## Automatická dávka střech — 2026-11-16

`scripts/roof_batch.py --output <nová-složka> --test --previous <předchozí-složka> --open` generuje z uloženého vstupního manifestu modely, časy a rozhodovací metadata, HTML porovnání a ZIP použitých vstupů. `--inputs` dovoluje vlastní nebo přibalený manifest; `--id` omezuje vzorek. Bez `--test` vzniká samostatný report. `results.json` obsahuje jen aktuální modely, `comparison.json` slouží k zobrazení. Každý běh potřebuje novou výstupní složku.

Výstup původních 30 domů: `cities/ceske-budejovice/experiments/roof-v4-batch-30/report.html`. Algoritmus eave-planes-4.1 zachovává varianty hřebene přímý/L/U/okruh a doplňuje plochého kandidáta pro obecný vzorek. Všech 30 částí dokončeno, výpočet střech 23,752 s; celý běh 91,726 s. Vstupy obsahují přesné NPZ výřezy, souřadnicové reference, dostupné normalizované zdrojové atributy a lokální Overture záznamy včetně původu. Nejde o nově staženou úplnou historii OSM tagů. Odhad podlaží zatím není implementován, zdrojový počet se zachovává. Bez optického hodnocení a bez změny produkční mapy.


## Stanová střecha — 2026-11-16

Algoritmus `eave-planes-4.2` přidává obecného kandidáta `pyramidal`: čtyři roviny se společnou výškou hlavních okapů a jediným vrcholem s volnou polohou. Neobsahuje vodorovný hřeben. Soutěží se stávajícími kandidáty podle stejné robustní chyby a penalizace složitosti; samotná nepřítomnost hřebene typ neurčuje. Vedle vnější obálky se zkouší obálka hlavních dlouhých stěn, aby krátká hrana přístavby neurčovala celý objem. Stávající půdorys zůstává beze změny a ořezává roviny; samostatná plochá přístavba se zatím neodděluje. Vrchol, okapy, podpůrná obálka a skóre všech kandidátů jsou v JSON.

Dávka používá tuto verzi automaticky; `--no-pyramidal` reprodukuje sadu kandidátů 4.1. `scripts/roof_address_inputs.py` připravuje explicitní seznam adres z místních Overture/ČÚZK podkladů a již stažených DMPOK souborů; umí převzít nezměněné výřezy z předchozího manifestu. Vstupní seznam pro E. Pittera 270/5 a Pabláskovu 1591/11 je `cities/ceske-budejovice/pyramid-test-addresses.json`, S. K. Neumanna 269/12 přebírá původní NPZ.

Sedm cílených numerických testů prošlo: roviny a volný vrchol, ořez přes výčnělek, automatická volba jehlanu, zachování plochého typu, stávající U/okruh a párování dávky. Optické hodnocení provádí uživatel. Časová cache kontroly velikosti projektu začíná až po dokončení průchodu soubory, aby pomalý průchod nezpůsoboval okamžité opakování; limity disku zůstávají zachované.

Výsledek testu: všechny tři adresy automaticky vybraly stanovou střechu. Časy střech: S. K. Neumanna 0,689 s; E. Pittera 0,772 s; Pabláskova 0,543 s; celkem 2,004 s, celá modelovací dávka s HTML 4,343 s. Jednorázové čtení místního CBUD23 a příprava dvou nových výřezů trvaly 199,705 s. Report: `cities/ceske-budejovice/experiments/roof-pyramid-3/report.html`; předchozí model je dostupný pouze u S. K. Neumanna. Všechny tři geometrie vytvořeny bez chyby, HTML dostupné přes lokální server; bez optického hodnocení.

Opakování nad připravenými body: `python scripts/roof_batch.py --inputs cities/ceske-budejovice/experiments/roof-pyramid-3/inputs.json --output <nova-slozka> --test --previous cities/ceske-budejovice/experiments/roof-pyramid-3 --url-base http://127.0.0.1:8877/ --open`.


## Vypínatelný modul přístavků — 2026-11-16

`roof_config.py` centralizuje přepínače, nové vzdálenostní/poměrové prahy a hlavní váhy skórování. `roof_annex.py` odděluje 2D kandidáty, přizpůsobí jednoduchou střechu a ověří dva kolmé výškové profily. Přístavky se vypínají přes `--no-annex`; jednotlivé moduly/parametry přes `--config`. Efektivní konfigurace je uložená v každém výstupu a ZIP. Přehled modulů a jejich omezení: [ROOF_MODULES.md](ROOF_MODULES.md).

Finální dávka: `cities/ceske-budejovice/experiments/roof-annex-final-3/report.html`, porovnání s předchozí stanovou variantou u všech tří domů. S. K. Neumanna a Pabláskova: hlavní stanová střecha plus jeden samostatný mírně pultový přístavek podle bodů. E. Pittera: dvě kandidátní části nevyhověly jednoduché rovině/profilům, ponechán celý půdorys a důvody v JSON. Opticky neposuzováno.

Výpočet střech celkem 5.230 s, celý běh 6.050 s. Profily včetně jemnějších buněk celkem 0.239 s (Neumanna 0,056 s, Pittera 0,123 s, Pabláskova 0,059 s). U zamítnutých kandidátů se znovu přizpůsobuje celý dům; to stojí více než samotné řezy. Nejde o izolovaný hardwarový benchmark. Všechny tři výsledné objemy prošly kontrolou uzavřenosti. 13 cílených testů prošlo, včetně vypnutí modulu, navázání u stejného okapu, otočeného půdorysu, souvislé střechy a dosavadních kandidátů.


## Úplná dávka 32 domů — 2026-11-16

Původní sada 30 + poslední trojice obsahují 32 jedinečných ID (S. K. Neumanna byl již v původní sadě). `scripts/roof_merge_runs.py --run <starší> --run <novější> --output <nová-složka>` automaticky vytvoří sjednocené vstupy a zmrazenou předchozí verzi; novější záznam stejného ID má přednost. Nepočítá nové modely a nemění zdroje.

Předchozí verze: `cities/ceske-budejovice/experiments/roof-latest-32-previous` (29 modelů z `roof-v4-batch-30`, tři z `roof-annex-final-3`). Nová: `cities/ceske-budejovice/experiments/roof-modular-batch-32/report.html`. U všech 32 domů je vlevo poslední předchozí model, vpravo nová dávka. Výpočet 32/32 bez chyb; střechy 21,202 s, celá dávka 34,135 s. Nastavení převzato beze změny z posledního testu přístavků; kontrolní součty konfigurace a jádra algoritmu souhlasí. Uzavřenost všech objemů potvrzena numericky, optické hodnocení nebylo provedeno. Úplný příkaz pro opakování je v nové složce v `RUN.txt`.


## Souběžné sedlové střechy — 2026-11-16

Verze `modular-roofs-4.4` přidává vypínatelný modul `parallel_gables` (`roof_parallel.py`). Ze stejných buněk bodů přizpůsobuje 2–4 souběžné vodorovné hřebeny s úžlabími; každý hřeben má vlastní výšku. Dva hlavní směry, robustní chyba, podpora bodů a penalizace složitosti rozhodují proti ostatním šablonám. Bez výjimek podle adres. Střešní pásy se oříznou skutečným půdorysem. Počet hřebenů a výšky jsou v JSON i v HTML.

15 cílených numerických testů prošlo (souběžné hřebeny, vypnutí modulu, přístavky, stanové a U/okružní střechy, párování porovnání). Optické hodnocení nebylo provedeno. Nové adresy jsou v `cities/ceske-budejovice/roof-parallel-addresses.json`; původní zadání Široká 422/3 je předběžně řešeno jako místní existující Široká 428/3, s výslovnou poznámkou v metadatech.

Příprava nových adres má `--resume`: ověří shodu zmrazeného výběru, průběžně uloží malý výřez bodů a pozici ve zdrojovém LAZ. Kontroluje identitu souborů a vybrané oblasti; po paměťovém přerušení pokračuje od uložené pozice. Paměťové a diskové limity zůstávají beze změny. Samostatný test ověřuje přerušení, navázání bez ztrát/duplicit, opakované načtení hotového výřezu a odmítnutí změněné oblasti. Jde o lokální skripty, nikoli posílání bodů do AI.

Finální výběr používá `modular-roofs-4.5`: při rozdílu skóre do nastavitelné tolerance 0,05 m preferuje méně různých střešních rovin. Nejde o toleranci každého bodu ani tvrzení o přesnosti zaměření. V JSON je původní minimum skóre, rozdíl vybrané varianty a příznak zjednodušení. Hroznová 247/32 tak vybírá 2 souběžné hřebeny / 4 roviny místo U; rozdíl skóre 0,027384 m. Bez ručního předepsání typu podle adresy.

Finální report: `cities/ceske-budejovice/experiments/roof-parallel-final-12/report.html`. Obsahuje Hroznovou 247/32 a 11 nových adres: Česká 145/58, Husova tř. 1825/8 a 1829/12, Kněžská 410/8, nám. Přemysla Otakara II. 114/30, Dr. Stejskala 113/2, Jirsíkova 423/1 a 422/3, Široká 421/1 a předběžně 428/3, Dr. Stejskala 426/15. Předchozí model je dostupný u Hroznové, ostatní jsou nové. Původní výstupy zůstávají.

12/12 modelů bez chyb, numericky uzavřené objemy. Finální numerické testy střech 15/15, navíc test obnovení čtení 1/1. Výpočet střech 15,709 s, modelovací dávka včetně HTML a balení 23,742 s; měření ochranného procesu včetně startu a kontrol 32,278 s. Maximum přidělené paměti celého stromu procesu 289 MB. Projekt přibližně 5,18 GB, C: volných 59,32 GB (desetinné GB). Příprava nových výřezů proběhla zvlášť: po zavedení checkpointu 187,008 s aktivního čtení za dva navazující pokusy; dřívější přerušené pokusy bez checkpointu nejsou v tomto čísle. Jednotlivé logy a měření jsou v `.work/cb-roof-v2/parallel-*.log*`. Bez optického hodnocení nebo nového renderu městských dlaždic.

Sjednocený seznam a zmrazené poslední modely: `cities/ceske-budejovice/experiments/roof-latest-43` (32 původních + 11 nových, Hroznová nahrazená poslední variantou). Sloučení nekalkuluje střechy, kopíruje přesné výřezy a uchovává původ modelu podle ID.

## Úplná dávka 43 domů — 2026-11-16

Na výslovné přání znovu vypočítaná celá řada posledním nastavením `modular-roofs-4.5`: `cities/ceske-budejovice/experiments/roof-modular-batch-43/report.html`. Předchozí verze je `roof-latest-43`; všech 43 objektů má spárovaný poslední předchozí a aktuální model. Nastavení přesně souhlasí s finální dávkou 12. Vstupy jsou již uložené NPZ, velké LAZ soubory se znovu nečtou.

43/43 modelů bez chyb, všechny objemy numericky uzavřené. Čas střech celkem 50,569 s, medián 0,996 s na dům, maximum 2,509 s. Celá modelovací dávka včetně HTML a balení 85,453 s. JSON, přesná konfigurace, souřadnicové reference, zdrojové záznamy, vstupy a příkaz pro další dávku vznikly automaticky. HTML ověřeno HTTP 200; bez optického hodnocení. Poznámka k předběžnému přiřazení Široká 422/3 → 428/3 zůstává ve vstupních metadatech.


## Záloha a příprava Velešína — 2026-11-17

Commit `13824f25f747864c2b90eef25379062b3f708652` zálohuje 143 souborů, přibližně 2,5 MB: kód, testy, konfigurace, výzkumné poznámky a Sportcentrum. Bez mračen, dlaždic, obrazových podkladů, cache a klíčů; všech 143 blobů bylo porovnáno kontrolním součtem s GitHubem. Rozsah datové zálohy vysvětluje [BACKUP.md](BACKUP.md).

[Audit obnovy částí mapy](INCREMENTAL_RENDERING.md) rozlišuje existující cache čtverců/ruční výběr PNG od dosud neimplementované cache tematických vrstev. Vstupy střech nově podporují `--city velesin`, včetně správného zdrojového manifestu a provenance. Výpočetní algoritmus a výchozí nastavení ČB zůstávají stejné. Výběr ulic připravuje `select_roof_streets.py`; nejednoznačné adresy se nehádaným způsobem zaznamenají mimo dávku.

Dávka 146 budov ve čtyřech velešínských ulicích je připravená k následnému spuštění, nikoli dokončená. Spuštění bylo pozastaveno při 98% využití RAM. Po dočasném uvolnění paměti prošlo 9 cílených testů směrování měst, výběru ulic, dávky a obnovování čtení (2,377 s). Následný pokus o spuštění skutečné dávky zastavila paměťová pojistka ještě před prvním krokem, protože volná RAM znovu klesla pod 1 GB. Příkazy s paměťovou pojistkou jsou v `cities/velesin/roof-streets/README.md`.
