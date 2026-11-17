# Straight skeleton: ověření knihoven (2026-11-17)

Dosavadní produkční modul roof_connected_wings.py není skutečný straight skeleton.
Páruje protilehlé stěny, vybírá obdélníková křídla a skládá horní obálku jejich střech.
U náměstí J. V. Kamarýta 1 se mezi variantou prodloužení o půl šířky a variantou
prodloužení k vnějšímu obrysu mění také vybraná šířka jednoho křídla
(11.4236 proti 13.7316 m). Prodloužení vstupuje do skóre pokrytí při výběru
křídel. Není tedy nezávislou opravou zakončení. Vnitřní koncové valby mohou
vytvářet malé nežádoucí plochy v napojení.

## Knihovny

- CGAL: skutečný weighted straight skeleton i pro polygon s otvory;
  extrude_skeleton vytváří přímo uzavřenou triangulovanou geometrii.
  Parametry mohou být sklony nebo váhy jednotlivých hran. Nulová váha v tomto
  extruzním API značí svislou stěnu, užitečnou pro štít. C++ integrace vyžaduje
  samostatný adaptér/build. Balíček Straight Skeleton má GPL licenci, CGAL nabízí
  i komerční licence; nejde o automaticky LGPL komponentu.
- py_straight_skeleton 0.1.0: malá Python implementace, BSD-3-Clause.
  API compute_skeleton(exterior, holes), uzly s časem a polygonální plochy.
  Základní API má jednotnou rychlost hran (společný sklon), nikoli seznam vah.
  Autoři výslovně nepovažují rychlost za hlavní cíl implementace.
- Shapely 2.2 (již používáme): simplify/preserve_topology, buffer a geometrické
  operace pro zjednodušení obrysu. simplify není samo o sobě architektonické
  rozpoznání přístavku ani zarovnání pravých úhlů.
- CGAL Shape Regularization: zarovnání přibližně rovnoběžných, kolmých a
  kolineárních segmentů i obrysů; možné pozdější doplnění.

## Doporučené rozdělení úloh

1. Omezit drobné změny půdorysu měřitelnou tolerancí, změnou plochy, zachováním
   propojení křídel a dvorů. Nevytvářet konvexní obálku celého L/U domu.
2. Knihovně předat celé propojené hlavní těleso: sama vytvoří napojení ploch,
   nároží a úžlabí. Nižší samostatné přístavky řešit zvlášť.
3. Vlastním kódem nadále volit typ, sklon, výšku okapu a případné štíty podle
   mračna bodů. Straight skeleton je konstrukce kandidáta, ne rozpoznání reality.
4. Před plošným nasazením porovnat s existujícími kandidáty. Nerovnoběžné
   okraje mohou přirozeně vytvořit výškově šikmý hřeben; knihovna sama nezaručí
   vodorovnost všech hřebenů ani jejich shodnou výšku.

## Izolovaný pokus

scripts/roof_skeleton_trial.py přijímá --model-cache a novou --output složku.
Nedotýká se produkčního výběru ani původních modelů. Porovnává surový půdorys,
Shapely simplify 0.65 m a morfologické otevření 1.8 m + simplify 0.15 m.
Otevření používá mitre rohy, limit změny plochy 3 %, Hausdorffovy vzdálenosti
2.5 m a zachování počtu částí/otvorů. Toto jsou experimentální limity.
Zjednodušený obrys platí v pokusu i pro stěny; nejde o skrytou změnu mapy.
Výšky se robustně přizpůsobují buňkám mračna 0.6 m. Všechny konce jsou prozatím
valbové. Report uvádí čas knihovny zvlášť od fitu, mesh a načítání. Odchylky
obou modelů jsou porovnány na shodné množině podporovaných buněk; vynechané
buňky jsou přiznané. Jeden dům neprokazuje vhodnost pro celé město.

## Primární zdroje

- https://doc.cgal.org/latest/Straight_skeleton_2/index.html
- https://doc.cgal.org/latest/Straight_skeleton_2/group__PkgStraightSkeleton2Extrusion.html
- https://doc.cgal.org/latest/Shape_regularization/index.html
- https://doc.cgal.org/6.2/Manual/packages.html
- https://doc.cgal.org/latest/Manual/license.html
- https://github.com/iconbuild/py_straight_skeleton
- https://shapely.readthedocs.io/en/stable/reference/shapely.simplify.html

## Výsledek jednoho pokusu

Report: http://127.0.0.1:8877/cities/velesin/experiments/roof-skeleton-trial-20261117/index.html

| Varianta | Plochy | Skeleton (s) | Model včetně fitu/mesh (s) | Změna plochy obrysu |
| --- | ---: | ---: | ---: | ---: |
| raw | 15 | 0.0658 | 0.534 | 0.00 % |
| simplified | 12 | 0.0153 | 0.406 | 0.53 % |
| minor-features | 10 | 0.0093 | 0.339 | 1.29 % |

Všechny tři mesh byly uzavřené, bez otevřených hran a výškových schodů.
U varianty minor-features byl medián absolutní svislé odchylky 0.305 m
(pro dosavadní model na stejných buňkách 0.363 m), ale P90 se zhoršilo
z 1.394 na 1.597 m a RMSE z 0.816 na 0.984 m. Vynecháno 25 z 1700 buněk
ležících mimo zjednodušenou střechu. Jde o trénovací buňky, ne nezávislý test.
Čas 0.34 s je jeden předem zvolený valbový kandidát, ne celé porovnávání
typů jako produkční výpočet (2.88 s). Časy nezahrnují start Pythonu,
kontrolu disku, načítání vstupů ani HTML. Produkční algoritmus nebyl změněn
a plošná dávka zůstává na žádost uživatele pozastavená.

### Reprodukce pokusu

Volitelná závislost: py_straight_skeleton==0.1.0. Není součástí produkčního běhu.
Pro tento pokus byla nainstalována izolovaně do .work/roof-skeleton-test/vendor
pomocí pip --no-deps; výpočetní API neimportuje volitelný matplotlib.
V běžném prostředí lze použít pip install py_straight_skeleton==0.1.0
a spustit python scripts/roof_skeleton_trial.py --model-cache <cache.json>
--output <nova-slozka>. Vstup je uložený model z noční dávky včetně odkazu
na původní NPZ. Závislost ani kopie mračna se neukládají do Gitu.

## Dr. Stejskala 112/4 – kandidátní štíty (2026-11-17)

Samostatný obecný modul `scripts/roof_skeleton_gables.py` a dávkový vstup
`scripts/roof_skeleton_gable_trial.py`. Nezasahují do produkčního výběru v4.9.7.
Konstrukce používá dostupný py_straight_skeleton 0.1.0, nikoli CGAL.

- Virtuální půdorys střechy může odstranit drobné odchylky v mezích konfigurace;
  musí pokrývat skutečný půdorys, zachovat otvory a hlavní stěny. Hotové plochy
  se ořezávají původním obrysem, skutečné stěny se neposouvají.
- V tomto prvním adaptéru jsou kandidáty pouze trojúhelníkové koncové valby
  se dvěma sousedními střešními plochami. Jejich náhrada pokračováním těchto
  dvou rovin je lokální, uvnitř příslušné valby. Nejde o úplnou implementaci
  obecných vážených skeletonů. Sousedící koncové valby nelze zrušit zároveň.
- Výška společného okapu a společný sklon se fitují robustně z trénovacích
  buněk. Štít vyžaduje prostorově rozložené místní body nad původní valbou
  a zlepšení místní odchylky. Kontrolní body nevstupují do výběru.
- JSON uchovává důvody přijetí/zamítnutí, všechny varianty, vstupní obrysy,
  časování, otisky kódu a zdrojových dat. NPZ jsou zabalené beze změny.

Automatický výsledek: 2 kandidátní zakončení, 4 kombinace;
vybrána varianta all-hipped (0 štítů).
Varianty se štíty neprošly podmínkami místní bodové podpory. **Tento pokus
nepotvrzuje rozpoznání tří skutečných štítů, které uvádí uživatel.**
Zejména omezení na trojúhelníkové valby nepokrývá všechny vhodné strany
členitého půdorysu; 2 kandidáti nejsou důkazem existence jen 2 štítů.
Virtuální obrys zde zredukoval jen 17 → 16 hran; nejde o silné
architektonické zjednodušení výstupků. Vzhled modelů nebyl kontrolován.

| Měření | Čas |
| --- | ---: |
| Samotný skeleton | 0.0133 s |
| Všechny varianty včetně fitu a geometrie | 0.2678 s |
| Skript včetně načtení, metadat a HTML | 4.2154 s |
| Hlídaný proces včetně startu a kontrol prostředků | 12.6943 s |

Vrchol paměti stromu procesu: 173.8 MiB; diskové a projektové limity splněny.
Tři automatické testy prošly: dvě skutečné štítové strany, zachování skutečných
valeb bez falešných štítů a ořez virtuálního obrysu na skutečné stěny bez mezer.

Report: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-skeleton-gables-stejskala-112/report.html

Všechny varianty: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-skeleton-gables-stejskala-112/variants.html

Reprodukce: `python scripts/roof_skeleton_gable_trial.py --inputs cities/ceske-budejovice/experiments/roof-v497-husova-stejskala/inputs.json --previous cities/ceske-budejovice/experiments/roof-v497-husova-stejskala --id 626b5c0f-4dc2-40a3-9bd1-f7862e614857 --output <nova-slozka>`.
Volitelné prahy jsou v `--settings <json>`; použitá konfigurace je v reportu.


## Obecnější konce a tři virtuální obrysy — 2026-11-17

Verze skeleton-gable-trial-3-general-ends přidává obecné moduly
roof_virtual_outline.py a roof_skeleton_caps.py, bez pravidel podle adresy.

1. Z původního obrysu vzniknou nejvýše tři reference: raw, collinear, small_steps.
   Drobně přerušované přibližně rovnoběžné fasády se spojují do vnější podpůrné
   přímky. Zachovávají se dvory a hlavní návraty L/U; limity jsou nastavitelné
   (maximální posun 2 m, přidaná plocha 12 %). Skutečný půdorys se nemění.
2. Koncová plocha nemusí být trojúhelníková. Odstraněný konec se zaplní spodní
   obálkou pokračujících sousedních rovin. Musí navazovat po celé společné hraně
   bez výškového zlomu, nesmí snižovat původní střechu a průřez koncovou hranou
   musí mít vnitřní vrchol nad oběma konci. Sousedící odstraňované plochy se
   zkoušejí společně. Neřešitelné kombinace mají zapsaný konstrukční důvod.
3. Zkouší se kombinace nejvýše šesti konců na referenci. Každá má vlastní
   robustní fit společného sklonu a výšky okapu. Přijatý štít potřebuje místní
   podporu bodů; samotná konstrukční možnost nestačí. Skóre zahrnuje bodovou
   chybu, počet štítů/rovin a velikost změny virtuálního obrysu.
4. Hotové plochy se oříznou skutečným půdorysem. Analytické hřebeny z řezů se
   přidávají až po výběru; nezasahují do konstrukce ani do skóre.

Dr. Stejskala 112/4: reference mají 17 / 14 / 13 hran a 4 / 5 / 4 kandidátní
štítové konce. Prověřeno 64 kombinací; 8 neprošlo konstrukční kontrolou,
56 hotových variant je v HTML, včetně zamítnutých podle místních bodů.
Vybrána small_steps / gables-1-4, dva štíty, 11 rovin, sklon 26,72 stupně,
okap 12,884 m a maximum střechy 16,287 m nad referenčním terénem.
Virtuální obrys přidal 1,325 m² (0,498 %), maximální posun 0,655 m,
počet hran 17 → 13. Půdorys stěn zůstal nezměněný. Vybraný model má
uzavřenou geometrii, plné pokrytí a žádné výškové schody mezi plochami.

Metoda nyní zkouší i dříve vyřazené netrojúhelníkové konce a sloučený
celý konec dlouhý 13,26 m. Neprokazuje tím všechny tři skutečné štíty.
Stále jde o lokální numerické pokračování rovin nad py_straight_skeleton,
nikoli o obecný vážený CGAL skeleton. Konstrukční odmítnutí některé hrany
není důkazem, že na domě skutečný štít není.

| Měření | Čas |
| --- | ---: |
| Konstrukce, fit a výběr všech variant bez analytiky | 3,530 s |
| Analytické řezy | 0,661 s |
| Dohromady výpočet střech | 4,191 s |
| Skript včetně HTML a zabalených vstupů | 13,271 s |
| Hlídaný proces včetně startu a kontrol prostředků | 20,509 s |

Peak commit celého procesu 326,0 MiB. Po běhu C: 69,73 GB volných,
projekt 5,82 GB. Jedno spuštění, nikoli benchmark průměrné propustnosti.
Kontrolní body se nepoužily k výběru: 662 pokrytých buněk, medián absolutní
svislé odchylky 0,344 m, P90 0,889 m, RMSE 1,372 m. Jde o svislé odchylky
vůči stejnému zdroji bodů, nikoli nezávislé zaměření přesnosti domu.

14 cílených Python testů a 2 JS sady prošly. Model nebyl opticky hodnocen.
Report i varianty odpovídají HTTP 200. Starší výsledky zachovány.

Report: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-skeleton-general-gables-stejskala-112/report.html

Varianty: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-skeleton-general-gables-stejskala-112/variants.html

Pro opakování použij stejný roof_skeleton_gable_trial.py --inputs
roof-v497-husova-stejskala/inputs.json, --previous
roof-skeleton-gables-stejskala-112-ridge-audit, stejné --id a novou --output.
Úplné příkazy a měření jsou v resource-summary.json.


## Odsazený pás důkazů pro štít — 2026-11-17

Verze skeleton-gable-trial-4-inset-evidence mění pouze místní vzorkování
pro přijetí štítu: evidence_inset_m=0.8 a evidence_strip_m=1.5. Vzdálenost
je v XY od nejbližší skutečné hranice půdorysu (včetně dvorů), nikoli
od posunuté virtuální fasády. Příslušnost ke koncovému dílu a prostředních
70 % referenční hrany nadále vymezují konkrétní štít. Výšková tolerance
max_local_residual_m=0.8 je samostatná a nezměnila se. Nastavení se validuje:
0 <= inset < maximum depth. Body se nemažou ze vstupů ani z globálního fitu.

Před změnou měl small_steps / gables-1-3-4 nižší celkové skóre 0,559197 než
zvolený gables-1-4 (0,570987). Penalizace byly shodné; vyřadil jej pouze
místní požadavek 50 % podpory u konce 3: 7/22 buněk. Místní čtení uložených
buněk našlo skupiny kolem 14–15 m a 22 m. Původ sousedních bodů není tímto
samotným měřením potvrzen. Odsazení 0,4–0,8 m v kontrolním výpočtu nechalo
jen 6 buněk a 2 vyhovující, tudíž není univerzálním řešením. Podklady auditu
jsou v předchozím reportu selection-audit.json.

Po uživatelem zvoleném odsazení 0,8–1,5 m nyní vítězí small_steps /
gables-1-3-4 (tři štíty, deset rovin). Konce 1, 3 a 4 mají podporu 18/19,
5/8 a 9/9 buněk. Všechny splňují i rozložení po šířce, převýšení nad valbou
a místní zlepšení. Výběr není vynucen adresou či vizuálním hodnocením.
Geometrie tohoto kandidáta i jeho globální skóre zůstaly shodné s dřívější
zamítnutou variantou; změnilo se její přijetí. Kontrolní body se nepoužily
pro výběr: medián absolutní svislé odchylky 0,337 m, P90 0,843 m, RMSE 1,275 m.

56 variant z 64 kombinací; výpočet bez analytiky 2.845 s,
analytické řezy 0.512 s; celý skript 11,757 s. Sedm cílených testů
prošlo, včetně ochrany skutečné fasády při posunuté virtuální hraně a neplatných
mezí. Reporty HTTP 200, bez optického posouzení. Odsazený pás je ochrana,
nikoli kompletní odstranění šumu; u úzkých objemů může chybět dostatek podpory.

Report: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-skeleton-inset-gables-stejskala-112/report.html

Varianty: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-skeleton-inset-gables-stejskala-112/variants.html

Krátké zkosení vedle štítu 4 zatím nebylo algoritmem odstraněno. Numerický
2D návrh prodloužení sousedních dlouhých stěn je v TODO, stejně jako odložení
triangulace všech nevybraných kandidátů pro budoucí mapový skeleton.
