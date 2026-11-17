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


## Nástavby nad plochými střechami — 2026-11-17

Modulární algoritmus 4.8.1 zachová nad plochým základem souvislé objemy vyšší než 2 m a s doloženou plochou alespoň 1 m²; plochý vršek používá 90. percentil prostorově vyvážených výšek. Parametry jsou nastavitelné, modul vypínatelný. Automatická sada 44 domů doplnila 8 objemů na 4 domech. 48 testů prošlo, všech 44 výsledných objemů je numericky uzavřených; opticky neposuzováno. Střechy 69,840 s, nový modul 1,329 s, celá dávka 135,064 s. [Dokumentace a měření](ROOF_FLAT_PROTRUSIONS_RUN_2026-11-17.md). Report: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-flat-protrusions-v481-44/report.html .


## 2026-11-17 — navazující křídla a obrysy nástaveb 4.9.1

Šest kroků optimalizace čtyř zalomených střech, obecný modul protilehlých okapů a navazujících křídel; měřené rozdílné výšky okapů při společném sklonu. Ochrana doloženého U/okruhu před záměnou za nepatrně jednodušší kandidát a úplné zvýraznění hřebenů ze sousednosti výsledné geometrie. Pravidelnější obrysy 8 nástaveb na dalších 4 domech (162 → 39 vrcholů). Osm dotčených modelů uzavřených; 63 testů, výpočet střech 22,178 s, celá dávka 39,566 s. Původní sada 44 domů zůstává pro porovnání; mapové dlaždice nepřegenerovány.

Podrobnosti a omezení: [záznam běhu](ROOF_WINGS_AND_PROTRUSIONS_2026-11-17.md). Výstup `cities/ceske-budejovice/experiments/roof-regularized-wings-v491-8/report.html`; archiv šesti kroků `cities/ceske-budejovice/experiments/roof-wings-optimization-v49/index.html`.


## 2026-11-17 — samostatná noční fronta

Připraveny `night_roof_inputs.py` (plán, husté podklady, obnovitelná extrakce) a `night_roof_batch.py` (postupné modelování, shodná cache, časové limity, stránkované HTML). Pořadí Velešín 146 ulicových → 1904 automatických objektů celkem se zachováním Sportcentra → ČB 287 centrálních objektů → podmíněně další čtyři hodiny ČB. Podrobnosti, spuštění a technické testy: [noční dávka](NIGHT_ROOFS_2026-11-17.md). Stav a výsledné počty určuje automaticky generovaný night.json; tento zápis sám netvrdí dokončení měst.

## 2026-11-17 — obnova dávky a pokus se straight skeletonem

- Opraven Windows souběh čtení/zápisu stavových JSON: jedinečný dočasný soubor, atomická náhrada s omezeným opakováním při sdílecím zámku. Starý checkpoint zůstává do úspěšného zápisu.
- Aktivní čas obnovené dávky se sčítá po relacích; ranní odstávka se nepočítá do dvouhodinové podmínky. Historie chyby se zachovává. 11 cílených testů prošlo včetně reálného Windows zámku.
- Noční běh dokončil 35 domů; další generování uživatel pozastavil kvůli rohům střech.
- Izolovaný adaptér knihovny a tři varianty jednoho domu: viz [ROOF_STRAIGHT_SKELETON.md](ROOF_STRAIGHT_SKELETON.md). Produkční generátor 4.9.1 zůstává beze změny.

## 2026-11-17 — řezy, parametry střech a výškové objemy

Izolovaný experiment 15 domů Velešína/ČB porovnává pět variant s původním modelem; výsledkem je 90 validních modelů. Přidány přepínatelné robustní profily, vyhledání výškových skoků a pomocná bloková reprezentace. 17 syntetických testů prošlo. Ve třetím kole výpočet experimentů 20,212 s, dělení doloženo u čp.94; ostatní změny/krajní odchylky viz [ROOF_VOLUME_SECTIONS.md](ROOF_VOLUME_SECTIONS.md). Produkční pipeline a plošná dávka se nemění.


## Podélné řezy bez straight skeletonu — 2026-11-17

Samostatný test Husovy tř. 1829/12 odděluje dvě výškové hmoty podle opakovaného přechodu v podélných profilech; střechy dále počítá původní 4.9.1. Detektor a lokální runner jsou v `scripts/roof_longitudinal_split.py` a `scripts/roof_longitudinal_experiment.py`. Report, parametry, časy a omezení: [ROOF_LONGITUDINAL_SPLIT.md](ROOF_LONGITUDINAL_SPLIT.md). Produkční mapy se nemění.


### Podélné dělení 0.2: přichycení a samostatné hmoty

Obecný filtr dlouhých/zalomených půdorysů, přichycení řezu k blízké původní hraně, zachování malých přístavků i celého obrysu a zákaz dalšího dělení potomků. Dva samostatné modely používají 4.9.1. Aktuální měření a report verze v4 jsou v [ROOF_LONGITUDINAL_SPLIT.md](ROOF_LONGITUDINAL_SPLIT.md). 12 syntetických testů prošlo; městské dávky se nespouštěly.


## Volné úhly křídel střech — 4.9.2, 2026-11-17

Opraven výběr a délka doložených křídel i ukončení podle šikmých obvodových stěn. Pravý rám je omezen skutečným posunem konců stěn. Samostatná Husova v5 zachovává předchozí rozdělení a porovnává nové střechy s v4; staré mapy se nepřepisují. Příčina, obecné parametry, měření a omezení: [ROOF_OBLIQUE_WINGS.md](ROOF_OBLIQUE_WINGS.md).


## Kontrolní dávka 44 ČB + 9 Velešín — 2026-11-17

Algoritmus `modular-roofs-4.9.2` s volbou `--split-volumes` dokončil všech 53 domů bez chyby. Výpočet střech celkem 128,059 s. Po 19 domech zasáhla ochrana volné systémové RAM (350 MB); dávka byla bezpečně obnovena pomocí nového `--resume`, který ověřuje shodu konfigurace, výpočetních modulů a vstupních bodů a přeskočí uložené domy. Pět testů dávkového porovnání a obnovování prošlo.

Report: `cities/ceske-budejovice/experiments/roof-v492-review-53/report.html`. Všech 53 modelů má předchozí verzi vedle nové, JSON metadata, přesné vstupní výřezy a samostatně exportované nalezené objemy. Velešín: náměstí J. V. Kamarýta 1, 4, 5, 13, 54, 69, 70, 72, 94. Měření prostředků a přerušení v `resource-summary.json`; maximální commit procesu přibližně 382 MiB. Kontrola pouze úplnosti souborů a HTTP 200, bez vizuálního hodnocení a bez přegenerování mapových tiles.


## Zubaté půdorysy a kandidatura dlouhých/zahnutých budov — 2026-11-17

Verze `modular-roofs-4.9.3` přidává vypínatelné zjednodušení opakovaných mělkých zubů půdorysu. Kostelní 1281/18: 54 → 6 vrcholů, J. Plachty 2059/5: 28 → 8; změny plochy jsou pod 1 %. Původní vstupy zůstávají zachované. Dokumentace: `ROOF_FOOTPRINT_REGULARIZATION.md`.

Dělení objemů již nezávisí na úspěchu předchozího rozpoznání dvou střech. Dlouhé a zalomené/dvorní půdorysy se prověřují vždy, včetně předběžně plochých střech. Nové záložní podélné profily přijaly po dvou samostatných objemech u nám. Přemysla Otakara II. 114/30 v ČB a náměstí J. V. Kamarýta 4 a 72 ve Velešíně; běžné stejnovýškové L/U zůstávají v syntetických testech jedním objemem.

Report pěti domů s předchozí verzí vlevo: `cities/ceske-budejovice/experiments/roof-v493-footprints-volumes-5/report.html`. Všech pět modelů dokončeno s platnou geometrií, výpočet 41,053 s, celý hlídaný proces 61,116 s, peak commit 220 131 328 B. Ověřeno HTTP 200, metadata a porovnání; bez vizuálního posuzování a bez přegenerování městských dlaždic. Podrobnosti v `validation-summary.json`. Testy zjednodušení, modulu objemů, původního dělení, přístavků a dávkování prošly.


## Korytová střecha a půdorysy objemů — 2026-11-17

`modular-roofs-4.9.4` přidává obecný vypínatelný kandidát butterfly: dvě roviny spádované do vnitřního vodorovného úžlabí, s podporou měřených bodů na obou stranách. Dokumentace postupu, prahů a skóre: `ROOF_BUTTERFLY.md`. U hlavní hmoty ČB nám. Přemysla Otakara II. 114/30 se počet rovin snížil 6 → 2; vybráno dosavadním pravidlem preference jednoduššího tvaru při blízkém skóre. Nejde o adresně vynucený výběr ani o menší bodovou odchylku než u původního U. Obecný kandidát se vybral i u nižší hmoty.

HTML nově ukazuje 2D půdorysy barevně rozlišených objemů, původní obrys a počet hlavních objemů přímo v metrikách; přibyla vrstva Úžlabí. Nové porovnání: `cities/ceske-budejovice/experiments/roof-v494-butterfly-114-30/report.html`. Dvě hmoty, platná geometrie, výpočet 12,463 s, report HTTP 200. Šest nových numerických, 15 regresních a viewer DOM/data test prošly; bez optické kontroly.


## Korytová střecha se třemi rovinami a podpora půdorysu — 4.9.5, 2026-11-17

Obecný korytový kandidát nyní vychází ze skutečných hlavních stěn s vodorovnými horními hranami a přidává jednu čelní trojúhelníkovou plochu. Nové ověření místního směru sklonu brání záměně výškových úrovní za koryto. U 114/30 zůstává hlavní objem korytový (3 roviny, sklony přibližně 27–29°), nižší objem se vrací k pultové střeše. Dvě hmoty a dělicí řez zachovány. Podrobnosti: [ROOF_BUTTERFLY.md](ROOF_BUTTERFLY.md).

Volitelná kontrola půdorysu pracuje před přesným ořezem se širším zmrazeným kontextem a s oddělením kontrolních střešních bodů. Husova 1829/12: odstraněno 60,467 m² nepodložené části, doplněn výklenek 19,444 m², 2D optimalizace 0,295 s; dva výsledné objemy. Parametry, reprodukce a omezení: [ROOF_FOOTPRINT_SUPPORT.md](ROOF_FOOTPRINT_SUPPORT.md).

Report: cities/ceske-budejovice/experiments/roof-v495-butterfly-support-2/report.html. Dva domy, 41,913 s výpočtu, 59,264 s hlídaný proces, peak commit 176 MiB; C: 69,20 GB volných, projekt 5,75 GB. 38 cílených Python testů a JS viewer test prošly. Platná uzavřená geometrie a HTTP 200; bez optického hodnocení a bez přegenerování mapových tiles.


## Rozšíření vzorku: Dr. Stejskala 112/4 — 2026-11-17

Adresa přidána do roof-parallel-addresses.json a samostatného roof-additional-addresses.json. Připravena hlídaná lokální dávka .work/run-roof-stejskala-112.py: nejprve přiřazení adresy a příprava hustých bodů, poté model 4.9.5 s dělením objemů. Předchozí domy se nepřepočítávají. Při zápisu této poznámky dávka čeká na volnou RAM; dokončení je třeba ověřit podle .work/roof-stejskala-112-supervisor.log a výsledného run.json. Výstupní složka po úspěchu: cities/ceske-budejovice/experiments/roof-v495-stejskala-112. Příprava čeká na paměť nejvýše 600 s a při nedostatku bezpečně skončí. Tento záznam netvrdí dokončený model.

Dokončení přírůstku Dr. Stejskala 112/4: místní příprava podkladů doběhla, nalezen samostatný objekt 626b5c0f-4dc2-40a3-9bd1-f7862e614857 se 6 561 střešními body. Model 4.9.5 dokončen bez chyby za 3,501 s výpočtu; report roof-v495-stejskala-112/report.html. Vzorek ČB se tím rozšiřuje ze 44 na 45 různých budov (vedle 9 kontrolních objektů Velešína). Předchozí modely nebyly přepočítány.


## Husova: návaznost objemů a vyřazení pravoúhlé L šablony — 4.9.7, 2026-11-17

Obecná oprava dělení doplňuje směry skutečných stěn a preferenci podloženého přichyceného řezu při téměř shodném skóre (0,03 m). Zjednodušování chrání doložené hlavní okapy. Starý pravoúhlý kandidát bent je na pokyn uživatele výchozí vypnutý; connected_wings zachovává vlastní směry křídel. Podrobnosti v ROOF_OBLIQUE_WINGS.md.

Místní automatická dávka dokončila Husovu 1829/12 (20,866 s) a novou Dr. Stejskala 112/4 (2,468 s), celkem 23,335 s výpočtu a 27,031 s běhu dávky; nadřazený hlídaný proces 36,105 s, peak commit 183 316 480 B. Skript hlásí 2 dokončené budovy a 0 chyb. Po posledním uživatelském pokynu nebyly výsledné modely dále posuzovány ani kontrolovány. Report: cities/ceske-budejovice/experiments/roof-v497-husova-stejskala/report.html.

## 2026-11-17: izolovaný skeleton a kandidátní štíty

Dr. Stejskala 112/4: nový experimentální modul a samostatný CLI runner; 4 varianty
včetně HTML porovnání se zachovanou v4.9.7, zabalené vstupy a automatická metadata.
Výpočet střech 0.268 s, vybrána valbová varianta bez štítů. První lokální adaptér
je omezen na trojúhelníková zakončení, tedy zatím neřeší všechny 3 uživatelem
popsané štíty. 3 syntetické testy prošly; bez vizuálního hodnocení či plošné dávky.
Podrobnosti a odkazy: ROOF_STRAIGHT_SKELETON.md.

## 2026-11-17: skutečná podpora hřebene a audit štítových stran

Nezávislá diagnostika z příčných řezů ukládá prostorové linky po objemech,
podloženou délku a výšku, nejistotu a čas. Report rozlišuje Hřeben z bodů
a Hřebeny modelu; všechny kandidátní i vyřazené strany mají ID a důvod.
Společné generátory doplňují diagnostiku novým modelům bez změny jejich
geometrie. Dr. Stejskala: nejistý hlavní úsek 4,80 m / 16,57 m, 5 řezů;
měření 0,54 s. 18 Python testů + 2 JS sady prošly. Podrobnosti: ROOF_OBSERVED_RIDGES.md.


## 2026-11-17: analytické řezy jen v testu a obecnější kandidátní štíty

Reportová dávka vynuceně zapíná nezávislé pracovní hřebeny; mapová dávka
je vynuceně vypíná i při opětovném použití reportové konfigurace. Řezy
neovlivňují výběr ani geometrii; čas analytiky je uložen odděleně.

Obecný experiment skeletonu zkouší tři virtuální obrysy a netrojúhelníkové
koncové plochy. Dr. Stejskala 112/4: 64 kombinací, 56 hotových variant,
vybrána varianta se dvěma štíty; všechny tři známé štíty zatím nepotvrzeny.
Výpočet bez analytiky 3,530 s + řezy 0,661 s, skript s HTML 13,271 s.
14 Python testů a 2 JS sady prošly. Předchozí model zachován, bez optického
hodnocení a bez městské dávky. Podrobnosti: ROOF_STRAIGHT_SKELETON.md
a ROOF_OBSERVED_RIDGES.md. Report: cities/ceske-budejovice/experiments/roof-skeleton-general-gables-stejskala-112/report.html.


## 2026-11-17: štíty ověřované 0,8–1,5 m dovnitř od skutečné fasády

Konfigurovatelný odsazený pás v experimentálním skeletonu nahrazuje dosavadní
0–1,5 m. Neodstraňuje data z globálního fitu; omezuje pouze místní důkaz štítu.
Dr. Stejskala: nově automaticky vyhrává small_steps / gables-1-3-4, 3 štíty.
Předchozí tvrdý filtr odmítal třetí konec; po odsazení podporuje model 5/8 buněk.
Sedm testů prošlo. Nový report roof-skeleton-inset-gables-stejskala-112/report.html,
předchozí model vedle nového; výpočet 3,357 s včetně 0,512 s analytiky,
skript 11,757 s. Bez optického posouzení a bez změny virtuálního půdorysu.
Podrobnosti: ROOF_STRAIGHT_SKELETON.md.


## 2026-11-17: 4.10.0 — skeleton ve společném výběru a měření kandidátů

Obecné zjednodušení virtuálního půdorysu odstraňuje i krátká konvexní zkosení.
Společná pipeline přidává podmíněný skeletonový kandidát, hodnotí jej na
stejných buňkách jako ostatní typy a finální mesh vytváří až při výběru.
Testovací běh zachycuje časy a počty skutečných kandidátních pokusů; souhrn
na konci HTML rozlišuje rodiny, pravidla skeletonu a nejpomalejší domy.
Mapová fronta má stručný agregovaný log a vypnutou analytiku hřebenů.

Připravena sada54 (45ČB+9Velešín), poslední verze každého domu zachována.
Spuštěna místní sekvenční dávka roof-v410-review-54. Při tomto zápisu běží;
dokončení se určuje podle run.json. Dokumentace: ROOF_REVIEW_TELEMETRY.md.

Dokončení série4.10.0: 54/54 domů, bez chyb na úrovni domu, všechny části
mají kandidátní log. Střechy352,445s včetně33,585s analytiky; celý skript
441,866s. Skeleton u32domů,2537interních pokusů/44,140s;16konstrukčních
selhání kandidáta bezpečně přeskočeno. Report roof-v410-review-54/report.html
a tabulky #candidate-performance mají HTTP200. Peak471,7MiB, C:69,63GB,
projekt5,96GB. Bez optického posouzení. Podrobnosti ROOF_REVIEW_TELEMETRY.md.


## 2026-11-17: 4.11.1 — sedm cílených oprav a pevný srovnávací základ

Obecný kandidát spojených hřebenů podle skutečných směrů stěn nahrazuje mezery po vypnutí pravoúhlé L šablony. Paralelní sedlové střechy mají výchozí souměrné svahy a společná úžlabí/okapy. Dělení musí překonat další toleranci 0,10 m proti jednomu objemu. Ochrana okapů je místně vázána na příslušné křídlo. Téměř shodné koncové roviny lze sloučit s omezenou geometrickou změnou; numericky neplatné sloučení se omezeným postupem vrací.

Report roof-v4111-targeted-7: 7/7 dokončeno, 54,307 s střechy, 72,406 s celý skript, peak 236,1 MiB. 47 cílených testů prošlo. Levá srovnávací verze zůstává roof-v410-review-inputs-54 až do dalšího pokynu, včetně opakovaného příkazu RUN.txt. Bez optického hodnocení a bez generování mapových tiles. Nová 1869/1 má nejistou vedlejší větev označenou; Dr. Stejskala 426/15 pouze návrh v TODO. Podrobnosti v ROOF_TARGETED_REGRESSIONS.md.


## 2026-11-17: 4.12.1 — numerická fasádní stěna a místní štítové kandidáty

Obecná oprava nepatrných nepokrytých oblastí při hranici půdorysu odstraňuje falešnou stěnu u Hroznové 247/32. Nové konečné rozsahy křídel a lokální důkaz štítu používají body 0,8–1,5 m od hrany; kandidát musí zachovat uzavřenost a spojitost. Výjimka z ochrany okapů platí jen pro doloženou štítovou stranu.

Kněžská: požadované úplné prodloužení střech zatím není vyřešené. Varianta s 19 oblastmi a dvěma štíty deformuje jinou hlavní římsu o 2,34 m; kratší rozsahy vytvářejí vnitřní schody. Obě možnosti jsou správně odmítnuty, zůstává bezpečný model s 24 oblastmi. Potřebné geometrické pokračování zaznamenáno do TODO. Dr. Stejskala 426/15 má po obecných úpravách dva objemy, sedlovou a pultovou střechu; zvláštní dvorní kandidát zůstává TODO.

Report roof-v4121-junctions-3: 3/3 dokončeno, 44,431 s střechy, 53,133 s celý skript, peak 217,7 MiB. 68 cílených testů prošlo a po úklidu experimentálních větví znovu tři testy konečných křídel. Vlevo nezměněné roof-v410-review-inputs-54. Bez optického hodnocení, bez přepočtu mapových tiles. Podrobnosti ROOF_JOINED_ENDS.md.


## 2026-11-17: 4.13.0 — přísné dělení podle místní šířky ramen

Nový vypínatelný 2D modul hodnotí každé přibližně pravoúhlé zalomení samostatně: 90° ± 15°, šířky kolmými sondami v obou ramenech, poměr alespoň 1,65. Krátké řezy navazují na původní hrany; dvě nebo tři dostatečně velké části přesně pokrývají půdorys. Jednoznačné dělení předchází výpočtu střechy a přeskočí společný fit i podélné výškové profily. Nejasnost nebo chyba zachová původní postup. Děti se dále nedělí. Počty objemů a čas jsou automaticky v JSON/HTML.

Na pokyn uživatele byl generován pouze Dr. Stejskala 426/15, nikoli sada54. Výsledek: 3 části 311,662 / 104,370 / 249,959 m², střechy sedlová / pultová / plochá. Detektor 0,0082 s; střechy 6,467 s včetně analytiky; celý skript 7,568 s. Uzavřený mesh, 12 geometrických + 18 integračních/reportových testů prošlo. Pevný levý základ zachován. Report roof-v413-footprint-stejskala-426/report.html; podrobnosti ROOF_FOOTPRINT_WIDTHS.md. Kněžská se nepřepočítávala, její návaznosti zůstávají v TODO.


## 2026-11-17: spuštění celé pracovní sady s 4.13.0

Na nový výslovný pokyn spuštěno všech 54 pracovních modelů (45 ČB + 9 Velešín), sekvenčně místním skriptem. Výstup roof-v413-all-54, levá srovnávací verze stále roof-v410-review-inputs-54. V této chvíli běží; dokončení určuje run.json. Beze změny algoritmu, bez optické kontroly a bez mapových tiles.

Dokončení celé sady 4.13.0: 54/54 modelů bez chyb; všechny výsledné sítě uzavřené, všech 54 levých modelů shodných s pevným srovnávacím základem. Nové přímé 2D dělení se uplatnilo u 5 domů. Střechy 286,439 s včetně 36,945 s analytiky; celý skript 383,001 s (6 min 23 s). Peak místního výpočetního procesu 471,2 MiB; C: 70,00 GB volno, projekt 6,06 GB. Report roof-v413-all-54/report.html dostupný přes localhost:8877. JSON uchovává rozhodování, kandidáty, časy, konfiguraci, validaci a zdrojové otisky. Bez optického hodnocení a beze změny mapových tiles.


## 2026-11-17: 4.13.1 — omezení ztráty shody při zjednodušování

Dr. Stejskala 112/4: skeleton již měl nejlepší skóre 0,6559, ale tolerance zjednodušování 0,10 vybrala třírovinnou střechu se skóre 0,7469. Nový obecný limit dovolí preferovat méně rovin pouze při zvýšení bodové složky nejvýše o 0,10 m; zde se zhoršovala o 0,161 m. Váhy rodin se nemění, vyřazené zjednodušení zůstává geometrickou zálohou. Konfigurace a důvod v JSON.

Přepočítán pouze Dr. Stejskala 112/4: nyní skeleton small_steps / gables-1-4 (2 štíty, 10 rovin), uzavřený mesh. Výpočet 5,565 s, celý běh 6,496 s, 37 testů prošlo. Report roof-v4131-stejskala-112-fit/report.html; levý základ beze změny. Jírovcova pouze audit: geometrie stejná jako 4.11.1, paired ridge s polohami 15 % a 27,93 % šířky ramen vysvětluje nesymetrii; nebyla přepočtena. Podrobnosti ROOF_SIMPLIFICATION_POINT_FIT.md.


## Lokální šířky párových křídel — 4.13.2 (2026-11-17)

Obecný filtr odstraňuje dvojice pásů, které každý pokrývají téměř celý L půdorys. Lokální šířky ověřuje několika 2D sondami mimo napojení; přidána preference shodných protějších sklonů s možností doložené nesymetrie. Přepočet pouze Jírovcovy, levá srovnávací verze zachována. Viz [ROOF_LOCAL_WING_WIDTHS.md](ROOF_LOCAL_WING_WIDTHS.md).


## Důkaz síťových hřebenů — 4.13.3 (2026-11-17)

Lokální šířky zachovány. Malé rozdíly protějších sklonů do 5° bez trestu, větší plynule penalizovány. Každá větev U/O potřebuje souvislou délku výškové podpory a měřený pokles na obě strany; nejistota znamená měkkou penalizaci. Zjednodušení chrání také shodu s body každého podloženého křídla zvlášť a při volbě dělení na objemy se přenášejí penalizace nejistoty vybraných střech, vážené plochou. 52 cílených testů a následných 20 testů křídel/objemů prošlo. Viz [ROOF_NETWORK_RIDGE_EVIDENCE.md](ROOF_NETWORK_RIDGE_EVIDENCE.md).

Finální přepočet Jírovcovy: roof-v4133-jirovcova-ridge-evidence-final/report.html, 1 objem / 4 roviny, uzavřená síť. Střecha 11,290 s, dávka 14,517 s; levá geometrie nezměněna, bez optické kontroly.
