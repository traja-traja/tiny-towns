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
