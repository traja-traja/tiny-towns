# Varianty střech pro rozpoznatelné objemy

Dokončeno 16. 11. 2026: **18 stejných půdorysů × 3 profily skutečného Rooferu × 3 opakování** nad zmrazeným DMPOK train/holdout. Navíc proběhl omezený hypar výřez bazénu a jeden oddělený diagnostický pokus Černé věže. Mapový renderer, základní mapa ani Velešín se nemění. Cílem je jednoduchý, rozpoznatelný dům; nejnižší chyba výšky sama nestačí.

Naměřené meshe, časy a metriky jsou v [results.json](results.json); primární zdroje, licence a kvalitativní fotoaudit pěti případů v [method-review.json](method-review.json). `status=complete` znamená dokončené srovnání, nikoli 18 úspěšně ověřených modelů. Silnější regularizaci doporučujeme jako volbu úrovně detailu podle měřítka a charakteru domu, nikoli jako plošnou opravu přesnosti.

## Naměřený výsledek

Každý profil vytvořil 16 standardních modelů, jeden explicitní `lod11_fallback` (Budvar sever) a jednu budovu bez geometrie (Černá věž). Tabulka se vztahuje k prvním zobrazeným meshům 17 vzniklých modelů včetně fallbacku; hypar a diagnostika věže do ní nevstupují.

| Naměřeno | LoD2.2, c=0,888 | LoD2.2, c=0,60 | LoD1.3, step 3 m |
| --- | ---: | ---: | ---: |
| Nativní střešní plochy celkem | 324 | 139 | 65 |
| Náhledové trojúhelníky celkem | 7 492 | 4 122 | 3 655 |
| Použité vrcholy celkem | 3 780 | 2 095 | 1 872 |
| Serializované modely, bajty | 510 332 | 295 974 | 267 740 |
| Medián RMSE po budovách | 0,709 m | 0,660 m | 1,565 m |
| Nejnižší pokrytí holdout bodů | 99,980 % | 99,980 % | 99,152 % |
| Medián celé CLI dávky 18 budov | 60,95 s | 55,21 s | 62,95 s |
| Medián interního času jedné vzniklé budovy | 0,596 s | 0,532 s | 0,560 s |

**Párované srovnání c=0,60 proti výchozímu LoD2.2 na společně pokrytých bodech: 2 budovy lepší, 14 horších, 1 stejná.** Medián párovaného zhoršení RMSE je +0,111 m; největší +0,418 m u Rabenštejnské věže. Samostatné mediány 0,709 → 0,660 m tedy zakrývají zhoršení většiny budov. Pokles počtu střešních ploch o 57 % je kompromis složitosti, nikoli důkaz přesnější rekonstrukce.

Opakování nejsou bitově totožná: část rozdílů může být pořadí ploch nebo malé numerické změny, u sportovní haly se však RMSE mezi běhy mění přibližně o 0,052 m. Uchováváme všechny časy, hashe i chyby; nevybíráme nejlepší opakování pro prezentaci.

| Profil | CLI wall, tři dávky [s] | Skutečný CPU čas dávek [s] | Nejvyšší commit | Nativní CityJSONSeq, tři dávky [B] |
| --- | --- | --- | ---: | --- |
| LoD2.2 výchozí | 60,95 / 65,05 / 54,15 | 50,22 / 56,86 / 48,00 | 105 111 552 B | 243 834 / 244 546 / 243 748 |
| LoD2.2 c=0,60 | 55,21 / 60,82 / 53,69 | 49,22 / 50,19 / 47,52 | 104 615 936 B | 136 933 / 136 859 / 136 893 |
| LoD1.3 step 3 m | 62,95 / 64,49 / 60,76 | 54,89 / 54,47 / 49,42 | 118 665 216 B | 98 635 / 98 500 / 98 690 |

Celý hlídaný srovnávací proces včetně načtení, evaluace a serializace trval 724,81 s; maximum commit bylo 237 756 416 B. Commit není fyzická rezidentní RAM. CPU je skutečné Windows job user+kernel účetnictví; vnější a vnořené procesové metriky se nesčítají. Stejná CLI dávka odkazovaná z 18 řádků se započítá jednou. Jeden Roofer worker, strop job commit 2 GB, minimum dostupné RAM 1 GB, stop při volném disku pod 25 GB, projektový limit 20 GB. Výkon účelového výběru dominant se neextrapoluje na město.

## Bazén: pouze doložený výřez střechy

Skutečný hypar experiment sleduje zaoblený výběžek zmrazeného půdorysu, vrcholy 29–60 a odsazení 1 m dovnitř. Před fittingem byla prohlédnuta pouze mapa train výšek: spojitý sedlový gradient bez skoku do nízkého křídla. **Uzavírací tětiva není potvrzená stavební spára.** Výřez má 1 953,21 m², tedy 39,90 % celého půdorysu; část hlavní haly zůstává mimo něj. Vymezení a původ jsou v [pool-hypar-part.geojson](pool-hypar-part.geojson).

Robustní šestiparametrový kvadratický fit používá 3 500 train bodů; hlavní křivosti mají opačná znaménka. Mesh má 125 střešních trojúhelníků, 102 vrcholů a 12 518 B. Neobsahuje fasády, přesah ani křídla.

| Varianta na témže výřezu | Holdout RMSE | Pokrytí 9 679 holdout bodů |
| --- | ---: | ---: |
| Výchozí Roofer LoD2.2 | 0,146 m | 100 % |
| Roofer LoD2.2 c=0,60 | 0,192 m | 100 % |
| Roofer LoD1.3 | 1,789 m | 100 % |
| Hypar, skutečně zobrazený mesh | 0,140 m | 100 % |

Spojitá kvadratická funkce má RMSE 0,105 m; její mesh aproximace 0,140 m. Jde o dvě různé reprezentace. Fit a tessellace trvaly 0,0641 / 0,0663 / 0,0632 s, CPU 0,0625 / 0,0469 / 0,0625 s. Celý hlídaný Python proces včetně načtení a evaluace trval 3,09 s, maximum commit 168 513 536 B. Samotný fit nelze časově srovnávat s celobudovní CLI dávkou. Mírně nižší chyba proti výchozímu Rooferu není nezávislé ověření ani kompletní oprava bazénu.

## Černá věž a fotografická kontrola

Tři původní profily odmítly vytvořit geometrii. Jediná oddělená diagnostika změnila pouze `--no-clear-insufficient` pro stejný půdorys a train/holdout. Vznikl model s 24 nativními střešními plochami a 478 trojúhelníky; interní čas 0,189 s, CLI 0,609 s, celý hlídaný diagnostický proces 20,99 s.

Externí holdout má 590 bodů a 100% predikční pokrytí: **RMSE 8,863 m**, MAE 2,465 m, P95 absolutní chyby 16,038 m. Interní Roofer RMSE je přitom 0,487 m. Pokrytí predikcí neznamená dostatečné vstupní pokrytí. Samotný rozdíl chyb nedokazuje příčinu ani špatnou siluetu: horní 2.5D obálka a body třídy 6 na více výškách mohou měřit odlišné věci; tato hypotéza potřebuje revizi klasifikace bodů.

Vizuální kontrola je samostatná: vznikl vysoký hranol s vrcholem, ale horní zakončení je nepravidelně roztříštěné a ochoz, zaoblená helmice i lucerna z fotografie nejsou spolehlivě vystiženy. **Diagnostika zatím neprošla ověřením; bez ruční revize částí a bodů nenasazovat.** Původní tři neúspěchy zůstávají zachované.

Pět případů (bazén, Budvar, Černá věž, radnice, katedrála) bylo kvalitativně porovnáno s fotografiemi známého autora, data a licence. LoD2.2 zachovává hlavní hřeben katedrály; c=0,60 jej zjednodušuje za cenu vyšší chyby. LoD1.3 úmyslně ztrácí sklon střech. U radnice zůstává dvůr a věžové objemy, ale charakteristické báňky nejsou věrné. Uliční foto Budvaru neověřuje horní střechu obou polygonů ani nepotvrzuje válcovou šablonu. Historické fotografie nejsou metrickým potvrzením dnešního stavu. Ostatní domy nemají cílený fotoaudit.

[parser-audit.json](parser-audit.json) dokumentuje dvě přeskočené plochy prvních náhledů: LoD1.3 radnice má vodorovný RoofSurface se samokřížením prstence v serializovaném CityJSON; výchozí Krajinská 44 nulovou WallSurface se dvěma totožnými XYZ vrcholy. U radnice je střešní náhled neúplný, což se promítá do pokrytí. Neprokazuje to chybný vstupní půdorys. Původní CityJSON ani parser se zde neopravovaly.

## Metody a připravené možnosti

| Varianta | Co mění | Co má ověřit |
| --- | --- | --- |
| Roofer LoD2.2, complexity 0.888 | Výchozí skutečný Roofer | Referenční šikmé střešní plochy |
| Roofer LoD2.2, complexity 0.60 | Větší preference jednoduché partition | Zda lze odstranit drobné členění bez ztráty charakteru |
| Roofer LoD1.3, step 3 m | Vodorovné vršky, zachované významné výškové skoky | Zda čitelnější objemy postačí při oddálení |
| Šablony po doložených částech | Jednoduchá střecha nad každou samostatnou částí | Přístavby, křídla a haly, kde jedna šablona nad celým půdorysem selhává |
| Hypar hlavní haly bazénu | Robustní kvadratická sedlová plocha nad doloženou částí | Oblou strukturu, pro kterou rovinné plochy nejsou přirozeným modelem |

Hodnota complexity je bezrozměrná váha optimalizace, nikoli tolerance v metrech. Nižší hodnota dává jednodušší model. Hodnoty 0.60 a případně 0.35 jsou experimentální volby, nikoli prokázané optimum. U LoD1.3 se sousední části s výškovým rozdílem menším než `--lod13-step-height` sloučí. Hodnota 3 m je výchozí; 5 m je volitelná citlivost na nejvýše pěti předem vybraných objektech.

Roofer hledá roviny region growingem, odvozuje jejich průsečnice a obrysy, upravuje linie a optimalizuje střešní partition graph-cutem. Přepínání complexity používá tuto existující optimalizaci. Roviny ani hřebeny se zde ručně nevymýšlejí. Podrobnosti popisuje [dokumentace algoritmu](https://github.com/3DBAG/roofer/blob/main/docs/reconstruct_params.md). Význam výškově členěného LoD1.3 a rozdíl mezi detailností a přesností shrnuje [3DBAG](https://docs.3dbag.nl/en/schema/concepts/).

## Společný srovnávací protokol

1. Zmrazit stejné identifikátory, půdorysy, centroid, ground, zdroj a jeho epochu. Použít existující globální split 80/20 se seedem 20261115. Každá varianta dostane přesně stejný `train.laz`; holdout se nepoužije pro fitting ani výběr rozkladu na části.
2. Měřit MAE, RMSE, bias a 95. percentil absolutní chyby výšky spolu s pokrytím holdout bodů. Navíc vyčíslit chybu na společné množině bodů pokrytých všemi třemi variantami. Body téhož zdroje nejsou nezávislá geodetická pravda a mohou být prostorově korelované.
3. Oddělit nativní střešní/povrchové plochy CityJSON, náhledové trojúhelníky a použité vrcholy. Počet CityJSON Solid se nerovná počtu viditelných výškových částí; u LoD1.3 uvádíme i počet souvislých vodorovných horních oblastí. Kontrolovat pokrytí půdorysu a otvory.
4. Měřit zvlášť `rf_t_run` v milisekundách převedených na sekundy a CLI dávku včetně startu, cropu, I/O a serializace. `peak_job_commit_bytes` je commit procesového stromu, nikoli fyzická rezidentní RAM. Uvést velikost nativního CityJSONSeq i serializovaného náhledového modelu.
5. Maximálně tři opakování v jednom prostředí. První skutečný běh všech tří profilů je povinný. Konfigurovatelný rozpočet (výchozí 900 sekund) omezuje pouze další opakování; běžící hlídaná dávka doběhne. Ukládáme každý čas a hash geometrie, medián/min/max a skutečný počet opakování. Nejde o nezávislé hardwarové zkoušky ani extrapolaci na celé město.
6. Zvlášť porovnat siluetu, směr hlavního hřebene, věže, křídla, dvory a doložené vikýře s fotografiemi známého původu a data. Neověřené položky zůstanou neověřené. Preferovaná varianta má být jednoduchá a rozpoznatelná při dostatečném pokrytí; chybějící střešní část není zlepšení jen kvůli nižšímu RMSE.

## API a běh

`scripts/roof_detail_variants.py list` pouze vypíše profily. Běh skutečného Rooferu je samostatná funkce:

```python
run_roofer_variant(source_name, features_epsg5514, train_laz_path, out_dir,
                   variant_id, baseline_preview_complete=True,
                   holdout_by_id=holdout_relative_xyz)

run_detail_comparison(source_name, features_epsg5514, train_laz_path, out_dir,
                      result_path, holdout_relative_xyz,
                      names_by_id=names, baseline_preview_complete=True,
                      repeats=3, max_wall_seconds=900)
```

Features mají `properties.id`, `ground_z`, `centre_x`, `centre_y` a polygon v EPSG:5514. Holdout má lokální XY a **Z nad ground**, zatímco `shared.building_data(...)["test"]` vrací absolutní Bpv Z: před předáním odečíst společné `ground_z`. Všechny náhledové meshe používají stejné lokální souřadnice. Výsledky `runs[]` nesou `id`, `name`, `variant`, `model`, `metrics`, `timing`, `repeats`; první mesh se zobrazuje, opakování ukládají časy a hashe.

`fit_partwise_templates(footprint_local, train_local_xyz_absolute_z, ground_z, parts)` má odlišnou, v názvu explicitní konvenci absolutní výšky trénovacích bodů. Vstupní části jsou maximálně osm doložených nepřekrývajících se polygonů. Jejich sjednocení musí zachovat celý půdorys i dvory; funkce tento požadavek kontroluje. Mesh je kolekce dílčích objemů se společnými vnitřními stěnami, nikoli Boolean union. `allow_barrel=True` jen povolí válcovou šablonu mezi kandidáty; neprohlašuje bazén či stadion za válcovou střechu. Použití na reálných stavbách musí předcházet kontrola půdorysu, výškových částí a fotografií, nikoli ladění proti holdout.

## Ověření a omezení

Devět cílených testů ověřuje výlučné LoD přepínače, čekání na základní náhled, viditelné pokrytí při chybě výšky, dvě skutečně odlišné výškové části, zachování dvora, robustní obnovu syntetického hyparu s odlehlými body a odmítnutí ploché střechy jako sedlové plochy a meze časového rozpočtu; devátý chrání oddělení jediné diagnostiky věže od běžných profilů. Malý skutečný syntetický běh Roofer 1.0.0 vytvořil LoD1.3 s jednou horní oblastí, 6 nativními plochami, 12 trojúhelníky a 8 vrcholy. Pokrytí půdorysu bylo 100 %, vnitřní čas 0.207 s a CLI 0.760 s. Je to ověření rozhraní a převodu, nikoli naměřená kvalita či rychlost pro České Budějovice.

Pro bazén existuje konkrétní odborný podklad: [NPÚ](https://www.npu.cz/cs/novinky/29872-ceske-budejovice-maji-novou-kulturni-pamatku-plavecky-stadion) popisuje oválnou hlavní halu, dlouhé nízké křídlo a lanovou střechu ve tvaru hyperbolického paraboloidu. Proto je připraven `fit_hypar_part(..., part_evidence=...)`: robustní šestiparametrový kvadratický fit s nejvýše 3500 body a 600 střešními trojúhelníky. Obě hlavní křivosti musí mít opačné znaménko; rovina či kupole nejsou automaticky přejmenovány na hypar. V tomto kole byl skutečně ověřen konzervativní výřez popsaný výše, s nižším limitem 160 trojúhelníků; nejde o kompletní hranici hlavní haly. Výsledek se hodnotí jen na téže části.

Roofer předpokládá po částech rovinnou střechu a svislé stěny. Podloubí, průjezd, spodní plocha mostu, převis či balkon z takového 2.5D modelu nevzniknou. Silné zjednodušení může odstranit charakteristický vikýř či věž; LoD1.3 úmyslně ztrácí sklon střechy. Výběr složitých dominant není reprezentativní vzorek celého města.

[Roofer](https://github.com/3DBAG/roofer) je GPLv3; místní kód podléhá kořenové AGPLv3 licenci projektu. Licence vstupních geodat a jejich původ se evidují samostatně. Parametry byly ověřeny na instalovaném `roofer 1.0.0 (bb2a85a)` pomocí `--help-all`; webová větev `main` se může později změnit.

Příkaz `compare-cb --source dmpok --baseline-preview-complete --max-wall-seconds 900` používá výhradně existující train LAZ a baseline centroid/ground. Parametr času se vztahuje na zahajování dalších opakování; první běh žádného ze tří profilů kvůli němu nevynechá. Tvrdé limity RAM a disku zůstávají zachované.

U Černé věže základní audit zjistil `has_parts=true`, ale rodičovské `height`, `num_floors` a `roof_shape` chybí; DMP1G obsahuje v půdorysu nula bodů třídy 6. Současný harvesting bere `building`, nikoli `building_part`. Následně má smysl prověřit konkrétní Overture/OSM části, jejich výšky a provenienci; zatím nebyly načtené a jejich kvalita se nepředjímá. Srovnávané tři Roofer varianty ponechávají totožný vstup; fixed30 se během měření nemění.

Reálné per-part/barrel šablony, c=0,35 ani step 5 m se v tomto kole nespouštěly. Jsou pouze připravené možnosti, nikoli výsledky. Výběr má SHA-256 aa3ca9cd50f0f639421545c9f1fee11391757c00ecafe7c5137adbf1b4082d21; train LAZ 3b999aa4e2c5f6611585811b45f1adb521bbbb53a162df6ab1ebba25b6ad365d.

## Provenience zdrojového kódu

Přesné bytes Python zdrojáku načtené na začátku compare-cb nebyly archivovány ani hashovány. Během běhu byl do souboru přidán oddělený tower-diagnostic CLI příkaz; podle záznamu implementační práce se srovnávací logika tří profilů neměnila. Devět dávek běželo ze stejného již načteného procesu bez reloadu modulu a má doložené stejné parametry v rámci každého profilu. Současný hash souboru po doplnění diagnostiky není execution snapshot a nedokazuje bitovou totožnost původních zdrojáků. Vstupní SHA, skutečné CLI příkazy, verze Rooferu, měření a modely jsou uchované samostatně. Podrobná kontrola je v [provenance-audit.json](provenance-audit.json). Nejde o plně zamražený snapshot veškerého běhového prostředí.
