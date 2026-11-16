# Silnější zjednodušení Rooferu při zachování šikmých střech

Nový izolovaný experiment pro šest uživatelem vybraných objektů (sedm půdorysů včetně dvou částí Budvar arény). Parametry byly ověřeny proti místnímu `roofer 1.0.0 (bb2a85a) --help-all`; staré modely a mapový renderer se nemění. Samotná existence tohoto souboru neznamená, že experiment už proběhl; skutečné výsledky a stav běhů zapisuje společný protokol.

| Nový profil | Complexity factor | Tolerance bodu vůči hledané rovině | Účel |
|---|---:|---:|---|
| `roofer_c035` | 0,35 | 0,30 m | Silnější preference menšího počtu střešních ploch |
| `roofer_c015` | 0,15 | 0,30 m | Zkouška výraznějšího zjednodušení, s rizikem ztráty významného hřebene |
| `roofer_c035_eps050` | 0,35 | 0,50 m | Při stejné optimalizační váze volnější slučování bodů při hledání rovin |

Výchozí profily c=0,888 a c=0,60 se přebírají z dokončeného předchozího experimentu. Všechny nové profily výslovně požadují **LoD2.2**, vypínají LoD1.2/1.3 a zachovávají původní test dostatečnosti bodů. Nejde tedy o převedení šikmých střech na vodorovné objemy. Případný automatický LoD1.1 fallback musí zůstat viditelně označený a nesmí být vydáván za úspěšnou šikmou střechu.

## Co parametry skutečně dělají

Podle [primární dokumentace algoritmu](https://github.com/3DBAG/roofer/blob/main/docs/reconstruct_params.md) Roofer nejprve hledá roviny, z jejich hran a průsečnic odvozuje linie a upravuje jejich uspořádání. Potom optimalizuje rozdělení střechy: vyvažuje shodu s body a cenu změn mezi sousedními částmi. Když sousední části dostanou stejnou rovinu, společná hrana se odstraní. Menší `complexity-factor` upřednostňuje jednodušší rozdělení.

`--plane-detect-epsilon` mění dřívější krok hledání rovin: určuje maximální vzdálenost bodu od roviny pro přijetí bodu do jejího segmentu. Větší hodnota může potlačit rozdrobení ploch, ale může také spojit skutečně rozdílné detaily. **Hodnota 0,50 m není záruka, že konečný model bude všude od původních bodů vzdálený nejvýše půl metru.** Parametr complexity je bezrozměrný a s metry přímo nesouvisí.

Místní CLI neposkytuje samostatný úhlový práh nebo práh vzdálenosti pro slučování střešních linií. Proto je v nativních profilech nevymýšlíme. Počet sousedů i minimální počet bodů roviny zůstává 15; hustota bodů nejvýše 20/m². Třetí profil tak oproti prvnímu mění pouze epsilon. Limit náhradní rekonstrukce zůstává 120 nalezených rovin a 10 000 ms, stejně jako v referenci.

## Protokol a omezení

- Shodný zmrazený DMPOK train LAZ, půdorysy, centra a terénní výšky. Holdout se nikdy nepředává Rooferu.
- Nejvýše osm vybraných půdorysů; jeden Roofer worker, job commit nejvýše 2 GB, hlídané limity disku a systémové RAM.
- Každý běh má vlastní adresář, surový CityJSONSeq, CLI argumenty, verzi a SHA binárky a kopie všech adapter/helper zdrojáků **před** spuštěním rekonstrukce.
- Zvlášť se měří čas celé CLI dávky a interní čas budovy; hodnoty se nesčítají. Přípravu a společné vyhodnocení eviduje nadřazený protokol.
- Vyhodnocení uvádí chybu výšky, pokrytí, podíl bodů v pásmu ±0,5 m a počet nativních střešních ploch. Počet vykreslovacích trojúhelníků je samostatný údaj, nikoli počet architektonických ploch.
- Půlmetrová tolerance se posuzuje spolu se zachováním siluety, hlavního hřebene a výškových částí. Méně ploch samo o sobě neznamená lepší výsledek. Holdout stejného zdroje nenahrazuje nezávislé zaměření.

Implementace: `scripts/roof_simplify_roofer.py`; čtyři malé protokolové testy v `tests/test_roof_simplify_roofer.py` prošly. Tyto testy nespouštějí reálnou rekonstrukci a nic netvrdí o kvalitě konkrétních budov.

## Naměřeno 16. listopadu 2026

Dokončeno osm nativních dávek: tři opakování c=0,35, tři c=0,15 a dvě c=0,35 / epsilon 0,50. Poslední třetí opakování se podle předem stanoveného limitu nových startů 600 s už nespustilo. První běh všech tří profilů je kompletní; pro zobrazení je vždy první skutečná geometrie, nikoli nejlepší opakování. `native-results.json` obsahuje 21 porovnávacích řádků, všech 56 jednotlivých pozorování a odkazy na neměněné surové modely.

| Objekt | Reference c=0,888: plochy / RMSE | c=0,35: plochy / RMSE | c=0,15: plochy / RMSE | c=0,35, epsilon 0,50: plochy / RMSE |
|---|---:|---:|---:|---:|
| Budvar sever | 1 / 0,91 m, fallback | 1 / 0,91 m, fallback | 1 / 0,91 m, fallback | 1 / 0,91 m, fallback |
| Budvar jih | 25 / 0,55 m | 8 / 0,60 m | 5 / 0,79 m | 7 / 0,74 m |
| Sportovní hala | 11 / 0,71 m | 6 / 0,68 m | 6 / 0,69 m | 6 / 0,57 m |
| Sv. Václav | 13 / 0,76 m | 6 / 0,93 m | 4 / 1,30 m | 7 / 0,70 m |
| Wortnerův dům | 7 / 0,42 m | 2 / 0,72 m | 1 / 1,28 m | 2 / 0,72 m |
| Masné krámy | 14 / 0,38 m | 2 / 0,90 m | 2 / 0,90 m | 2 / 0,93 m |
| Krajinská 43/8 | 15 / 0,75 m | 4 / 1,17 m | 2 / 1,80 m | 4 / 1,22 m |

Jde o nativní RoofSurface a RMSE na společném holdoutu prvního modelu. Z těchto metrik je c=0,35 / epsilon 0,50 slibné pro halu a kostel: v pásmu ±0,5 m je 97,7 % a 94,8 % všech kontrolních bodů. U Masných krámů však toto nastavení zachytí v pásmu jen 58,5 % bodů a ztratí mnoho detailů; jednotné agresivní nastavení proto nedoporučujeme automaticky převést na celé město. Siluetu musí doplnit vizuální kontrola ve společné galerii.

| Profil | Počet dávek | Medián wall celé CLI dávky | Medián CPU celé CLI dávky | Nejvyšší commit nativního procesu |
|---|---:|---:|---:|---:|
| c=0,35 | 3 | 46,76 s | 36,77 s | 96,51 MB |
| c=0,15 | 3 | 49,54 s | 40,16 s | 95,20 MB |
| c=0,35 / epsilon 0,50 | 2 | 57,44 s | 48,45 s | 93,49 MB |

Vnější worker včetně přípravy, kontrol, parsování a vyhodnocení: 654,52 s wall, 852,31 s CPU celého stromu procesů, nejvyšší commit 162,14 MB. CPU může překročit wall; není to čas jediné budovy. Interní časy jednotlivých budov z `rf_t_run` jsou samostatně v JSON. Po skončení projekt zabíral 4,905 GB a na C: zbývalo 68,224 GB; nic se nestahovalo a renderer se neměnil. Vnější metriky jsou v `.work/cb-roof-simplification/native-worker.log.metrics.json`.

Roofer u severní arény ponechává formální geometrii `lod=2.2`, ačkoli atribut `rf_extrusion_mode=lod11_fallback` výslovně hlásí náhradní vodorovný objem. Po doběhnutí všech měření byl proto opraven pouze odvozený status v souhrnu; původní souhrn, zdrojové otisky a korekční zdroják jsou archivovány a odkazovány v `status_normalisation`. Žádná měřená geometrie, čas, nativní soubor ani jednotlivý surový `result.json` se při této korekci nezměnily. Test ověřuje tento konkrétní nesoulad LoD štítku a skutečného režimu.

Pořadí vrcholů či ploch se mezi běhy může lišit; různý hash tedy sám neprokazuje jinou siluetu. U c=0,15 se u haly současně měnila i RMSE (první dvě opakování 0,686 a 0,744 m při šesti plochách), proto jsou všechny opakované hodnoty zachované. Žádný z 21 zobrazených modelů nemá přeskočenou neplatnou face; tento údaj zůstává v `invalid_faces_skipped`.
