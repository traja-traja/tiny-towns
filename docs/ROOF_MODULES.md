# Moduly generování střech

Verze `modular-roofs-4.5`. Spouštěč: `scripts/roof_batch.py`.
Výpočty používají místní body; výstupem je geometrie, metadata a HTML.

| Modul | Soubor / funkce | Úloha |
| --- | --- | --- |
| Konfigurace | `roof_config.py` / `resolve_config` | Výchozí hodnoty, kontrola klíčů, jednotek a rozsahů |
| Půdorys přístavků | `roof_annex.py` / `footprint_candidates` | Hlavní dlouhé stěny; významné přesahy přes jednotlivé stěny |
| Jednoduchá střecha přístavku | `roof_annex.py` / `simple_annex_plane` | Robustní plochá/pultová rovina podle bodů |
| Dva výškové profily | `roof_annex.py` / `height_profiles` | Pás přes napojení a kolmý pás uvnitř přístavku |
| Ověření přístavku | `roof_annex.py` / `evaluate_annex` | Podpora bodů, rozdíl proti pokračování hlavní střechy, výšky a profily |
| Sestavení modelu | `roof_annex.py` / `infer_modular_roof` | Vynechá body přístavku z hlavního fitu, spojí plochy a uzavře výškové schody |
| Kandidáti hlavní střechy | `roof_eave_planes.py` | Plochá, přímý hřeben, pult, L, U/okruh, stanová |
| Souběžné sedlové střechy | `roof_parallel.py` | 2–4 rovnoběžné vodorovné hřebeny, mezilehlá úžlabí a jednoduché střešní roviny |
| Uzavřená geometrie | `roof_v2_geometry.py` / `build_mesh` | Střechy, stěny, podstava, schody, topologická kontrola |
| Dávka a report | `roof_batch.py`, `roof_v2_report.py` | Vstupy, rozhodnutí, časy, porovnání, přesná konfigurace |

## Přepínače a konfigurace

`--no-annex` vypne celé hledání přístavků. V JSON lze samostatně vypnout
`modules.annex_profiles` nebo jednotlivé rodiny střech: `flat`, `straight`,
`skillion`, `bent`, `networks`, `pyramidal`, `parallel_gables`. Pro původní sadu
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

Skóre podobná v mezích `scoring.simplification_tolerance_m` (výchozí 0,05 m)
se rozhodují podle menšího počtu různých rovin, poté podle skóre. Nejde o
maximální vzdálenost každého bodu ani geometrickou záruku přesnosti 5 cm.
JSON uvádí nejnižší původní skóre, rozdíl vybrané varianty a případný příznak
`simpler_near_equivalent_candidate`. Hodnota 0 vypíná tuto preferenci.
