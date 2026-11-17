# Řezy a výškové objemy — experiment 2026-11-17

## Rozsah

15 domů: Velešín náměstí J. V. Kamarýta 1 (kontrola), 5, 13, 4, 94, 70, 72,
69 a 54; ČB Husova tř. 1829/12, Kněžská 410/8, Široká 421/1, Hroznová
314/18 a obě Jirsíkovy 422/3 a 423/1. Obě Jirsíkovy jsou zahrnuté, protože
v zadání nebylo tentokrát uvedeno číslo. Výběr neobsahuje adresové výjimky
v algoritmu. Všechny NPZ už byly lokálně dostupné (celkem 884593 B), zdroj
DMP OK — fotogrammetrická data. Žádná nová mračna se nestahují.

## Co jednotlivé moduly dělají

- roof_sections.py: příčné pásy napříč domem/křídlem. Z buněčných mediánů
  robustně porovnává rovinu s dvoustranným sedlovým profilem. Hřeben vyžaduje
  opakované doložení v několika řezech, jeho polohu a výšku hodnotí odděleně.
  Okapy jsou extrapolované průsečíky profilu s půdorysem, ne přímo detekované
  žlaby. Uchovává chybějící podporu i délku extrapolace. Skok podél křídla
  vyžaduje souhlas obou okapů, a pokud jsou doložené, také vrcholů.
- roof_volume_candidates.py: společný straight skeleton; varianta s kotvami
  výšek z profilů; návrhy řezů z půdorysu/profilových změn; nezávislé ploché,
  pultové, sedlové či valbové střechy nad přijatými částmi; pomocné krabice.
- roof_volume_experiment.py: pevný výběr, kopie a hash NPZ, znovupoužití
  předchozích výsledků, sekvenční výpočet, JSON checkpointy, HTML a vyhodnocení
  odložených bodů. Konfigurace a otisky skriptů brání smíchání různých verzí.

## Varianty a rozhodování

1. baseline: produkční model 4.9.1, zachovaný pro srovnání.
2. skeleton_shared: celý půdorys, společný sklon a okap, robustní fit na body.
3. skeleton_sections: stejná topologie s pomocnými kotvami hřebenů a okapů
   z opakovaných řezů; okapová kotva musí být u skutečné hranice půdorysu,
   s extrapolací nejvýše 1.5 m. Kotvy mají omezenou váhu, nejsou pevnou pravdou.
4. split_volumes: navržené hranice ověřuje lokálními rovinami z obou stran
   několika kolmých profilů. Jejich výšky porovnává na TÉMŽ XY na hranici.
   Pouhé rozdílné výšky vzorků na svahu by vedly k falešnému dělení.
   Výchozí skok 1.1 m, nejméně 3 doložené stanice a podpora 60 % skutečného
   vnitřního spoje. Každý nový objem musí mít alespoň 15 m² a 4.5 % půdorysu;
   celkem nejvýše 4 objemy. Návrh rozdělení a jeho přijetí jsou oddělené.
   Každá část dostane jednoduchou střechu podle dat. Pro malé konvexní části
   se zkouší i sedlová střecha s volnou polohou vodorovného hřebene. Pokud
   není hranice doložená, zůstává jedna hmota; varianta pak stále může nabídnout
   jednodušší typ střechy.
5. split_scan: stejná kontrola výškového skoku doplněná řídkým posouváním
   řezů ve dvou hlavních směrech. Nejvýše 24 poloh na směr; rozdělení může
   najít i tam, kde se půdorys nezalamuje. Původní konzervativní varianta
   zůstává pro přímé porovnání.
6. lod_boxes: diagnostická reprezentace stejných navržených částí, výška jako
   70. percentil buněčných výšek. Není to maximální bod ani měření hřebene.
   Je odolnější vůči malým komínům; neznamená úplné odstranění všech nástaveb.

Výběr porovnává omezenou robustní svislou chybu, počet ploch a počet objemů.
Rozdělení musí přinést i minimální zlepšení po penalizaci složitosti. Výběr
nepoužívá odložené body. Krabice nejsou kandidátem finální šikmé střechy.
Účelem je geometrická segmentace, nikoli identifikace právně samostatných domů.

## Co tato první verze záměrně neumí

- Neodhalí hranici, přes kterou je střecha zcela souvislá a která není
  výškově doložená. Rozdíl materiálu nebo parcel není v této detekci použit.
- Stejný hřeben po celé budově nevynucuje: při společném sklonu má užší křídlo
  přirozeně nižší hřeben. Rozdíl hřebenů sám nerozděluje objemy.
- Základní py_straight_skeleton má společnou výchozí výšku okapů. Vážený
  skeleton mění rychlosti/sklony hran; různé výchozí výšky okapů nejsou totéž.
  Samostatné výškové objemy mají vlastní parametry; souvislé navázání různě
  vysokých okapů u stejné střechy vyžaduje obecnější konstrukci.
- Nejde o certifikovanou implementaci LoD1.3. LoD1.3 je reprezentace významných
  výškových rozdílů, nikoli jediný předepsaný algoritmus segmentace.
- Výškové skoky vzniklé šumem u sousedního domu mohou zůstat nejasné. Absence
  bodů není sama důkazem oddělení. Žádné ruční opravy vstupních bodů zde nejsou.

## Ověření a zdroje

17 syntetických testů prošlo v 3.816 s: sedlo/komín, ploché stupně, měnící se
šířka křídla, profil kolem dvora, lokální roviny a podprahový/nadprahový skok,
přístavek, úplný výpočet dvou objemů, zachování otevřeného dvora a sken hranice bez
půdorysového zalomení. Opraveno počítání podpory hranice tak,
aby se do délky spoje nepočítala vnější stěna, kde sousední hmota neexistuje.
Časy výpočtu, načítání, geometrie, profilů, validace a HTML jsou oddělené.
Holdout je 20% odložený výběr z téhož mračna, nikoli nezávislé nové měření;
navíc sousední fotogrammetrické body mohou mít korelované chyby.

Primární dokumentace a výzkum (konzultováno 17.11.2026):

- https://docs.3dbag.nl/en/schema/concepts/ — LoD1.2 vs LoD1.3.
- https://docs.3dbag.nl/en/schema/layers/ — LoD1.3 díly a 70. percentil výšek
  rekonstruovaného LoD2.2; naše krabice používají buňky mračna, ne stejnou
  rekonstrukční pipeline 3DBAG.
- https://innovation.3dbag.nl/roofer/api_cpp.html — parametr lod13_step_height;
  Roofer se v tomto experimentu nespouští.
- https://doc.cgal.org/latest/Straight_skeleton_2/group__PkgStraightSkeleton2Extrusion.html
  — rovina základního polygonu z=0 a váhy/sklony jednotlivých hran.
- https://www.isprs.org/proceedings/XXXVII/congress/6b_pdf/09.pdf — rozlišení
  průsečnic střešních rovin a svislých výškových skoků.
- https://www.mdpi.com/2072-4292/11/14/1660 — ortogonální profily přes hranice
  segmentů jako prostředek detekce skoků. Náš experiment používá vlastní
  omezenou heuristiku, není implementací celé publikované metody.

## Spuštění

python scripts/roof_volume_experiment.py --output <nová-složka>

Volitelně --config <json>, --id <id> (opakovaně), --resume, --rebuild-report.
py_straight_skeleton 0.1.0 z předchozího izolovaného testu se načítá z
.work/roof-skeleton-test/vendor; produkční závislosti se nemění.
Výstup: cities/velesin/experiments/roof-volume-sections-20261117-v3/. První kolo zůstává v sousední složce
roof-volume-sections-20261117/.
Produkční mapy i noční plošná dávka zůstávají beze změny.

Plochy skeletonu kolem dvora mohou mít nulově široký obousměrný most
v obrysu. Adaptér je převede přes Shapely make_valid na plochy s otvory;
nevyplňuje dvůr konvexní obálkou. Výsledek znovu prochází mesh validací.

## Konečný výsledek třetího kola

Report: http://127.0.0.1:8877/cities/velesin/experiments/roof-volume-sections-20261117-v3/index.html

15 domů, 90 zobrazených modelů (původní + 5 variant), všechny geometrie validní,
žádná chyba varianty. V předchozích kolech byly odmítnuté dvě střechy kvůli
příliš přísné kontrole rovinnosti (odchylky pouze 0.012–0.014 mm při interní
toleranci knihovny 0.01 mm). Limit adaptéru je nyní 0.1 mm; půdorys se tím
nemění. U složitých dvorů může mesh obsahovat mikroskopické spojovací stěny;
nejde o detekované výškové objemy. Uzavřenost a pokrytí se kontrolují zvlášť.

Experimentální výpočty celkem 20.212 s, z toho řezy 8.058 s a hledání dělení 8.407 s.
Dopočet dvou předchozích modelů 2.582 s, validace odloženými body 0.694 s, HTML 9.106 s.
Součet wall časů jednotlivých domů 25.624 s; není v něm úvodní kontrola disku ani závěrečný report.

| Dům | Vybraná varianta | Objemů | Holdout P50 před → po (m) | Holdout P90 před → po (m) |
| --- | --- | ---: | ---: | ---: |
| náměstí J. V. Kamarýta 5 | Řezy u hran | 1 | 0.925 → 0.866 | 2.242 → 2.250 |
| náměstí J. V. Kamarýta 13 | Řezy u hran | 1 | 0.929 → 0.569 | 3.357 → 3.368 |
| náměstí J. V. Kamarýta 4 | Původní 4.9.1 | 1 | 0.337 → 0.337 | 1.604 → 1.604 |
| náměstí J. V. Kamarýta 94 | Posuvné řezy | 2 | 0.852 → 0.401 | 1.934 → 1.445 |
| náměstí J. V. Kamarýta 70 | Původní 4.9.1 | 1 | 0.294 → 0.294 | 1.693 → 1.693 |
| náměstí J. V. Kamarýta 72 | Původní 4.9.1 | 1 | 0.982 → 0.982 | 2.418 → 2.418 |
| náměstí J. V. Kamarýta 69 | Původní 4.9.1 | 1 | 0.500 → 0.500 | 2.228 → 2.228 |
| náměstí J. V. Kamarýta 54 | Původní 4.9.1 | 1 | 0.416 → 0.416 | 1.551 → 1.551 |
| náměstí J. V. Kamarýta 1 | Skeleton + řezy | 1 | 0.370 → 0.306 | 1.372 → 1.564 |
| Husova tř. 1829/12 | Původní 4.9.1 | 1 | 0.343 → 0.343 | 1.614 → 1.614 |
| Kněžská 410/8 | Společný skeleton | 1 | 0.296 → 0.206 | 1.194 → 0.706 |
| Široká 421/1 | Původní 4.9.1 | 1 | 0.318 → 0.318 | 0.712 → 0.712 |
| Hroznová 314/18 | Původní 4.9.1 | 1 | 0.414 → 0.414 | 1.239 → 1.239 |
| Jirsíkova 423/1 | Řezy u hran | 1 | 0.308 → 0.200 | 0.879 → 0.683 |
| Jirsíkova 422/3 | Řezy u hran | 1 | 0.327 → 0.185 | 1.451 → 1.132 |

Dělení prošlo u čp.94 (2 objemy). U čp.5 a13 se zlepšil kandidát jednoho
objemu; žádné nové rozdělení se nepodařilo doložit. U čp.70,72,69,54 a4
zůstává předchozí model. Je to omezení experimentálního detektoru a podklad
pro další posouzení, nikoli potvrzení, že dům skutečně nemá nižší přístavbu.
Kněžská se zlepšila společným skeletonem a zůstává jedna hmota. Husova,
Široká a Hroznová zůstávají u předchozího kandidáta; obě Jirsíkovy u jednoho
objemu s jednodušší střechou. Sedm nově zvolených kandidátů má nižší holdout
medián, ale u čp.1,5,13 je P90 horší (u5/13 jen nepatrně). Proto nejde
o univerzální náhradu produkčního algoritmu. Výběrové skóre není pravděpodobnost.

Doporučení: řezy jako levný pomocný zdroj parametrů a kontroly; společný
skeleton pro propojenou střechu; objemy rozdělovat jen po doloženém skoku
a zlepšení kandidáta. LoD krabice slouží pro diagnostiku výšek. Před
plošným nasazením zbývá vizuální posouzení uživatelem a ladění falešných
negativních případů (zejména čp.70 a72).
