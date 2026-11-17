# Moduly generování střech

Verze `modular-roofs-4.9.1`. Spouštěč: `scripts/roof_batch.py`.
Výpočty používají místní body; výstupem je geometrie, metadata a HTML.

| Modul | Soubor / funkce | Úloha |
| --- | --- | --- |
| Konfigurace | `roof_config.py` / `resolve_config` | Výchozí hodnoty, kontrola klíčů, jednotek a rozsahů |
| Převaha vodorovné plochy | `roof_flat_majority.py` / `detect_flat_majority` | Součet ploch v různých výškách; při alespoň 55 % jedna plochá střecha |
| Nástavby nad plochou střechou | `roof_flat_protrusions.py` a dokončovací krok v `roof_annex.py` | Souvislé vyvýšené plochy; jeden plochý vršek v percentilu 90 |
| Půdorys přístavků | `roof_annex.py` / `footprint_candidates` | Hlavní dlouhé stěny; významné přesahy přes jednotlivé stěny |
| Jednoduchá střecha přístavku | `roof_annex.py` / `simple_annex_plane` | Robustní plochá/pultová rovina podle bodů |
| Dva výškové profily | `roof_annex.py` / `height_profiles` | Pás přes napojení a kolmý pás uvnitř přístavku |
| Ověření přístavku | `roof_annex.py` / `evaluate_annex` | Podpora bodů, rozdíl proti pokračování hlavní střechy, výšky a profily |
| Sestavení modelu | `roof_annex.py` / `infer_modular_roof` | Vynechá body přístavku z hlavního fitu, spojí plochy a uzavře výškové schody |
| Kandidáti hlavní střechy | `roof_eave_planes.py` | Plochá, přímý hřeben, pult, L, U/okruh, stanová |
| Souběžné sedlové střechy | `roof_parallel.py` | 2–4 rovnoběžné vodorovné hřebeny, mezilehlá úžlabí a jednoduché střešní roviny |
| Navazující křídla | `roof_connected_wings.py` | Protilehlé hlavní okapy, různé směry a šířky křídel; společný sklon, varianty výšek okapů a konců |
| Uzavřená geometrie | `roof_v2_geometry.py` / `build_mesh` | Střechy, stěny, podstava, schody, topologická kontrola |
| Dávka a report | `roof_batch.py`, `roof_v2_report.py` | Vstupy, rozhodnutí, časy, porovnání, přesná konfigurace |

## Přepínače a konfigurace

`--no-annex` vypne celé hledání přístavků. V JSON lze samostatně vypnout
`modules.annex_profiles` nebo jednotlivé rodiny střech: `flat`, `straight`,
`skillion`, `bent`, `networks`, `pyramidal`, `parallel_gables`, `connected_wings`. Pro původní sadu
kandidátů 4.2 vypněte `annex_detection` i `parallel_gables` a nastavte
`scoring.simplification_tolerance_m` na 0.
Samotné vypnutí profilů zachová půdorysný výběr a porovnání bodů s rovinami.

Soubor předaný přes `--config nastaveni.json` smí obsahovat jen změněné hodnoty:

```json
{
  "modules": {"annex_detection": true, "annex_profiles": true},
  "annex": {"min_depth_m": 2.0, "max_area_fraction": 0.30},
  "scoring": {"mean_weight": 0.6, "quantile_weight": 0.4}
}
```

Úplná výsledná konfigurace se automaticky uloží do `config.json`, `run.json`
a výsledku jednotlivého modelu; patří i do ZIP vstupů. `RUN.txt` odkazuje
na tuto konkrétní konfiguraci pro opakování. Prohlížeč ji pouze zobrazuje.
Neznámé klíče a neplatné hodnoty způsobí chybu před spuštěním dávky.

Parametry s `_m` jsou metry, `_m2` m², `_fraction` podíly 0–1 a `_deg` stupně.
Vzdálenost 2 m je práh, skórovací váhy jsou samostatné koeficienty.
Hlavní váhy chyb, penalizace složitosti jednotlivých střech a slabých větví
jsou ve `scoring`. Výchozí hodnoty zachovávají dosavadní skórování.

## Jednoduché přístavky a omezení

Přesah musí splnit hloubku, plochu a maximální podíl na půdorysu. Tenké pásky
vzniklé mírnou nerovnoběžností fasád neurčují umístění řezů: ty vycházejí
z hlubší části přesahu a směru konkrétní hlavní stěny. Profily jsou výběry
z již načtených bodů, nikoliv průniky s 3D sítí. Pro úzké pásy používají
jemnější buňky 0,35 m (`annex.profile_cell_size_m`) než hlavní fit 0,7 m,
aby natočení půdorysu a hrubá mřížka zbytečně nesnižovaly počet bodů v řezu.
Příprava jemnějších buněk je započtena v čase profilů.

Přístavek smí navázat ve stejné výšce jako hlavní okap: vyžaduje se odlišná
jednoduchá střešní plocha a nižší výška vůči hlavnímu vrcholu. `min_height_step_m`
udává tento minimální rozdíl vůči vrcholu, nikoliv povinný schod u napojení.
`max_join_above_main_m` omezuje případný přesah nad hlavní střechu v napojení.
Samotná nízká výška nebo půdorysný přesah nestačí; musí se zlepšit shoda
s body oproti pokračování hlavní střechy. Pultový sklon se odvozuje z bodů.

Tato první verze nerozděluje půdorysy s dvorem, souměrná velká křídla ani
složité hlavní střechy L/U/okruh/souběžné sedlové. Při nejasném profilu nebo neuzavřené geometrii
zůstane původní celý půdorys a důvod se zaznamená. Neprovádí se optické hodnocení.

## Souběžné hřebeny

Modul `parallel_gables` přizpůsobuje jednoduchý příčný výškový profil ve dvou
hlavních směrech fasád. Střídají se okap, hřeben, úžlabí, další hřeben a okap.
Každý hřeben a každé úžlabí jsou vodorovné; různé hřebeny mohou mít různé výšky.
Plochy se oříznou skutečným půdorysem. Kandidát soutěží se všemi ostatními typy,
neobsahuje pravidla podle adres. Nezavádí skleněné svislé stěny pilových střech.

Nastavení `parallel_gables` zahrnuje `max_ridges` (4), `min_bay_width_m` (3),
`profile_bin_m` (0,6), `min_prominence_m` (0,5) a podmínky podpory bodů.
Více hřebenů stojí další penalizaci ve skóre. Metadata obsahují počet hřebenů,
jejich výšky, výšky úžlabí, příčný profil a počty podporujících buněk.
Výběr typu není kalibrovaná pravděpodobnost. Složitější křížení těchto střech
nebo různě dlouhé souběžné části tento první jednoduchý kandidát neřeší.

## Měření

JSON rozlišuje `annex_2d_seconds`, `annex_profiles_seconds`,
`annex_evaluation_seconds` (zahrnuje profily), `main_roof_seconds` a
`annex_assembly_seconds`. Celkový čas je `total_seconds`; uvedené dílčí časy
se kvůli vnořenému měření nesčítají všechny dohromady. Nejasný kandidát může
vyžadovat druhý fit hlavní střechy; ten může stát více než samotné dva profily.

Skóre podobná v mezích `scoring.simplification_tolerance_m` (výchozí 0,10 m)
se rozhodují podle menšího počtu různých rovin, poté podle skóre. Nejde o
maximální vzdálenost každého bodu ani geometrickou záruku přesnosti 5 cm.
JSON uvádí nejnižší původní skóre, rozdíl vybrané varianty a případný příznak
`simpler_near_equivalent_candidate`. Hodnota 0 vypíná tuto preferenci.


## Výběr hlavní hmoty — 4.6

`modules.primary_wall_envelope` přidává pro sedlové a valbové střechy také
obálku dominantních dlouhých stěn, nejen vnější krajní body. Obě varianty
soutěží podle bodů; skutečný půdorys se nemění a pouze ořezává výsledné roviny.
Parametr lze vypnout, střecha ani její hřeben se ručně neposouvají podle adresy.

Souběžné hřebeny musí mít souhlasné body rozprostřené alespoň přes polovinu
společné délky extrudovaného profilu (`parallel_gables.min_supported_span_fraction=0.5`).
Měří se rozsah 10.–90. percentilu podélných souřadnic buněk u hřebene s odchylkou
menší než `support_error_m`; nejde o měření souvislosti celé linie. Tím se krátké
kolmé křídlo nemůže snadno vydávat za dlouhou souběžnou střechu. Skutečné střechy
s různě dlouhými souběžnými křídly mohou vyžadovat pozdější rozdělení na objemy.
Nastavení 0 vypne tento nový délkový práh. Důvody vyřazení a metriky jsou v
`diagnostics.candidate_evidence_rejections`, nikoli vydávané za chybu sítě.

Tolerance při preferenci méně rovin je zvýšena z 0,05 na 0,10 m ve váženém skóre.
Je to obecná preference jednoduššího objemu při podobné shodě s body; není to
mezní odchylka jednotlivých bodů. Předchozí hodnotu lze obnovit konfigurací.

Geometrie několika plochých výškových úrovní zůstává v TODO. Aktuální režim
při převaze vodorovných ploch úrovně záměrně zjednodušuje na jednu střechu
(viz následující oddíl); samostatné schody se nyní nevytvářejí.


## Převaha ploché střechy — 4.7.2

Před hledáním přístavků se nově zkouší `roof_flat_majority.py`. Když téměř
vodorovné oblasti pokrývají alespoň 55 % půdorysu, celá střecha se zjednoduší
na jednu rovinu ve výšce největší takové oblasti. Každá započítaná souvislá
oblast musí mít alespoň 5 % půdorysu a největší alespoň 20 %. Různé výškové úrovně se mohou
započítat společně, ve výsledné geometrii se ale nezachovají. Nový modul lze
vypnout přes `modules.flat_majority`; podrobnosti v [ROOF_FLAT_MAJORITY.md](ROOF_FLAT_MAJORITY.md).
Tím je doplněna předchozí jediná plochá šablona. Skutečný model několika
plochých výškových úrovní zůstává budoucím úkolem.

## Nástavby na plochém základu — 4.8

Po výběru základní ploché střechy se volitelně vrací významné vyvýšené části: převýšení nad 2 m, plocha alespoň 1 m², jeden vršek v p90. Podrobnosti a přepínač: [ROOF_FLAT_PROTRUSIONS.md](ROOF_FLAT_PROTRUSIONS.md). Základní pravidlo ploché střechy 5 / 20 / 55 % zůstává stejné.


## Regularizace nástaveb a soustavy křídel — 4.9

`flat_protrusions.regularize_footprints` zkouší obdélník podle nejdelší hlavní stěny a jednoduchý pravoúhlý obrys. Výchozí maximum je 8 vnějších vrcholů, zachování alespoň 80 % pozorované plochy a doplnění nejvýše 15 %; neúspěch ponechá předchozí bezpečné zjednodušení. Prahy 2 m / 1 m² a výšky P90 se nemění.

`modules.connected_wings` přidává samostatného kandidáta, s vahami a prahy v sekci `connected_wings`. Rozměry a směry křídel vycházejí z hlavních protilehlých okapů; výšky z buněk bodů. Vedle společného okapu se zkouší doložené výškové skupiny křídel (nejméně 20 buněk, rozdíl 1 m), stále se společným sklonem. Malé výčnělky ořezávají hotové roviny. Modely s neplatnou geometrií nemohou vyhrát.

Na skutečném významném dvoře je změna rodiny nejlepší střešní soustavy při zjednodušování dovolena jen při rozdílu skóre do 0,025 m, místo běžných 0,10 m. Hodnoty jsou v `scoring.courtyard_topology_tolerance_m`, `min_courtyard_area_m2` a `min_courtyard_area_fraction`. Skóre není pravděpodobnost.
