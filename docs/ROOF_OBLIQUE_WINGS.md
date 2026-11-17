# Zalomené střechy pod volným úhlem — 4.9.2

Ověřeno 17. 11. 2026 na spodní oddělené hmotě Husovy tř. 1829/12. Algoritmus je společný, bez adresních pravidel nebo předepsaných souřadnic. Městské dávky ani dlaždice nebyly spuštěny.

Report: `cities/ceske-budejovice/experiments/roof-longitudinal-husova-20261117-v5/report.html`. Vedle sebe původní 4.9.1, předchozí dělení v4 a nová varianta. Počet hmot zůstává 2 a počet dělení 1; opakované dělení potomků je vypnuté.

## Příčina

Nižší hmota dříve vybrala `u_shaped`, tedy šablonu se společným pravoúhlým rámem. Skutečné hlavní osy křídel ale svírají přibližně 83,5°. Střešní plochy po oříznutí skutečným půdorysem proto nevytvářely vodorovné hlavní okapy.

Rodina `connected_wings` už uměla vlastní směr každého křídla, včetně ostrých i tupých zalomení. Prohrála však kvůli falešnému širokému pásu napříč napojením: navrhl hřeben, u něhož bylo 21 okolních buněk, ale žádná jej výškově nepotvrzovala. Další malý pás neměl body. Chybějící data sama o sobě nejsou důkazem neexistující střechy.

Pouhé odstranění těchto pásů nestačilo. Skutečné boční křídlo bylo předčasně ukončené. Jeho prodloužení zase vyžadovalo správnou koncovou rovinu podle šikmé obvodové stěny, aby v rohu nepřeteklo přes okap druhého křídla.

## Obecné změny

1. Přichycení stěn do pravoúhlého rámu hlídá nejen úhel, ale také skutečný posun konců stěn. Výchozí limit je 0,30 m. Dlouhá šikmá křídla tak zachovají vlastní směr.
2. Vedle plné sestavy vzniká kandidát složený z křídel s podporou hřebene. Výchozí podpora je alespoň 8 buněk a 35 % bodů v pásu 0,9 m od hřebene, s výškovou tolerancí 0,9 m. Plná sestava zůstává v soutěži; menší varianta je hypotéza, ne tvrzení o neexistenci ostatních částí.
3. Prodlužují se pouze již doložená křídla v jejich směrech přes souvislou část půdorysu. Neopakuje se výběr pásů podle velikosti po prodloužení, protože tím mohl znovu vyhrát široký falešný pás.
4. Koncové roviny respektují skutečné hlavní obvodové stěny. U napojení na vnější okap jiného křídla zůstává omezující rovina i ve variantě se štíty. Nevytváří se globální minimum přes všechny stěny nekonvexního domu a nepoužívá se straight skeleton.
5. Každá varianta se znovu přizpůsobí bodům, porovná dosavadním skóre a musí vytvořit uzavřený model. Výběr nevychází z kontrolních bodů.

Přepínače jsou v `connected_wings`: `supported_subset_variants`, `extend_supported_wings`, `anchor_actual_end_walls`. Ostatní limity jsou také konfigurovatelné. Algoritmus je označen `modular-roofs-4.9.2`; běžná a noční dávka přebírají označení ze společné konfigurace.

## Výsledek Husova

Vybraná nižší střecha má dvě doložená hlavní křídla s vlastními směry. Zachovává společnou okapovou hladinu; hřebeny už nejsou vnucené do pravoúhlé šablony. Skutečný vnější okap dlouhý 32,22 m měl ve v4 výškový rozsah 0,819 m, nyní 0,032 m. U druhého vnějšího okapu dlouhého 30,37 m klesl rozsah z 1,393 na 0,003 m. Měří se 31 bodů na prostředních 90 % každé skutečné hrany, s nepatrným posunem dovnitř proti numerickým mezerám. Malá zbývající odchylka souvisí s ne zcela rovnoběžnými protějšími zdmi.

Tyto hodnoty platí pro hlavní okapy; šikmá hrana štítu je správně výškově proměnná. Nelze označit každou hranu střechy za okap. Automatické výškové rozsahy všech delších hran jsou v metadatech samostatných modelů `volumes/`.

| Kontrolní metrika celého domu | Předchozí dělení v4 | Volné úhly v5 |
| --- | --- | --- |
| P50 svislé odchylky | 0,175 m | 0,159 m |
| P90 | 0,690 m | 0,486 m |
| RMSE | 0,794 m | 0,762 m |
| Podíl do 0,5 m | 84,1 % | 90,5 % |
| Střešní polygonové oblasti | 10 | 13 |

Počet oblastí mírně vzrostl kvůli přesnějšímu spojení a oříznutí; nižší hmota používá 7 různých rovin. Kontrola proběhla na stejných 2 104 odložených buňkách fotogrammetrického měření, nikoli na nezávislém zaměření stavby. Optickou kontrolu provádí Pavel.

Čas celé regenerace byl 11,426 s: detektor dělení 3,396 s, oba nové modely a sestavení 7,274 s. Čas HTML 0,150 s. Výkon ovlivňuje souběžná zátěž počítače; nejde o slib rychlosti každé budovy.

Nové syntetické testy pokrývají L s úhly 80°/100°, U s více směry, pravoúhlé L, omezení posunu dlouhých stěn, vodorovné okapy, uzavření objemu a zachování plné alternativy při nejistotě. Předchozí testy návaznosti křídel zůstávají součástí kontroly.

Závěrečná kontrola: 39 testů prošlo (ostré/tupé úhly, původní křídla, podélné dělení, přístavky, HTML porovnání a cache noční dávky); 0 chyb. Oba nové samostatné modely i sloučený model jsou uzavřené a report je dostupný přes HTTP 200.


## Dávka všech kontrolovaných domů

`roof_batch.py --split-volumes` používá společný `roof_volume_pipeline.py`: nejprve aktuální celý model 4.9.2, následně u vhodných půdorysů podélné dělení s přichycením a samostatné střechy potomků. Vybere se nový celý model nebo nový dělený model podle trénovacích bodů a ceny dělení. Předchozí verze slouží pouze k zobrazení. Potomci nemohou spustit další dělení. Ověřené ploché střechy respektují dosavadní pravidlo převahy ploché části.

Běh `cities/ceske-budejovice/experiments/roof-v492-review-53` obsahuje 44 kontrolovaných domů ČB a 9 domů Velešína (náměstí J. V. Kamarýta 1, 4, 5, 13, 54, 69, 70, 72, 94). Vstupy jsou lokální zmrazené NPZ; původ každého modelu je dohledatelný v zabalených metadatech. Skript zachovává předchozí modely, ukládá vybrané výsledky a samostatné dělené objemy. Spouštěcí příkaz pro další běh vytváří sám v RUN.txt.

Dávka je sekvenční, s jedním výpočetním vláknem knihoven; nadřazený proces omezuje celou skupinu na 1,5 GB paměti a dvě CPU jádra. Automatická kontrola disku zastaví práci pod 25 GB volného místa nebo při překročení projektového limitu 20 GB. Zabraňuje uspání jen po dobu běhu. Žádné modelové API, stažení nových mračen nebo vizuální hodnocení AI.

Obnovení přerušené dávky: `roof_batch.py --resume` se stejnými argumenty ověří konfiguraci, otisky výpočetních modulů a uložené vstupní výřezy, potom přeskočí hotový prefix domů. Změna samotného dávkového spouštěče je zaznamenána; změna algoritmu vyžaduje novou výstupní složku. Časy střech z dokončených domů zůstávají zachované.


## Oprava regrese po úpravě půdorysu — 4.9.6 / 4.9.7, 2026-11-17

Změněný obrys Husovy přepnul detektor na záložní podélné profily. Ty používaly jen orientaci minimálního obalového obdélníku a minuly původní hranu vyšší hmoty. Fallback nyní zkouší nejvýše tři směry: původní a blízké normály skutečných dlouhých stěn. Všechny původní podmínky výškové podpory a zachování obrysu zůstávají. Mezi již podloženými děleními má při rozdílu skóre do 0,03 m přednost řez přichycený ke skutečné hraně; toto pravidlo nikdy nepřebije vítězný model jednoho objemu. Parametry jsou v roof_longitudinal_split.DEFAULTS a rozhodnutí v volume_decision.partition_selection.

Stará pravoúhlá bent šablona měla v chybné nižší hmotě skóre 0,4640 proti 0,3663 u connected_wings. Přesto ji původní tolerance 0,10 povýšila kvůli menšímu počtu rovin. Přidána ochrana dlouhých doložených hlavních okapů při zjednodušování; štíty a drobné výstupky se nepovažují automaticky za okapy. Číselný izolovaný test 4.9.6 na původním špatném řezu vybral connected_wings a snížil rozpětí dvou hlavních okapů z 0,85/1,22 m na přibližně 0,04/0,006 m.

Na výslovné přání uživatele je od 4.9.7 modules.bent=false: stará pevně pravoúhlá L šablona se ve výchozím generování vůbec nepočítá. Kód a explicitní přepínač zůstávají jen pro reprodukci historických experimentů. Pro současné zalomené střechy slouží connected_wings s vlastními směry křídel a bodovou podporou hřebenů. Starší bent získával natočení váženým čtyřúhlovým průměrem dlouhých hran půdorysu; optimalizoval polohu/výšku, ale nikoli nezávislé úhly obou ramen. Nešlo tedy o čistě naměřené hřebeny.

Před posledním konfiguračním vypnutím prošlo 38 cílených testů dělení, ochrany okapů a rozhodování (včetně opraveného syntetického obrysu testovací budovy). Finální modely 4.9.7 na pokyn uživatele bez dalšího posuzování a kontrol: dávka sama hlásí complete, 2 domy, 0 chyb. Husova 20,866 s, Dr. Stejskala 112/4 2,468 s, celkem 23,335 s výpočtu. Report: cities/ceske-budejovice/experiments/roof-v497-husova-stejskala/report.html. Předchozí modely zachovány.
