# Vyčlenění hlavních objemů podle výškových skoků

## Protokol stanovený před měřením

Používáme sedm zmrazených půdorysů šesti objektů a původní Roofer 0,888 z předchozího kola. Toto je jiná metoda než dřívější zkoušení přímých řezů půdorysem podle os: rozdělení vzniká z grafu skutečných sousedních střešních oblastí.

1. Z původního modelu vytvořit souvislé téměř rovinné oblasti (stejný pomocník jako v minulém kole, 3 mm / 0,25°).
2. Na každém společném okraji porovnat obě výškové funkce. Úhel normál zde není důvodem pro dělení: obě strany sedlové střechy se podél spojitého hřebene musí spojit do jednoho objemu.
3. Hranu grafu oddělit, pokud výškový skok přesahuje práh na alespoň 60 % délky společného okraje. Dvě předem zvolené citlivosti: **0,75 m** a **1,50 m**. Vzorkujeme devět vnitřních bodů každého úseku, vážených délkou.
4. Spojité komponenty grafu považovat za kandidátní objemy. Pokud se oddělená hrana obejde jinou spojitou cestou, graf části nesepne násilným řezem; audit tuto situaci výslovně zaznamená.
5. Komponenty menší než `max(6 m², 2 % půdorysu)` nebo s méně než 30 fitovacími body zachovat v původní geometrii. Malá věžička se tedy automaticky neslije s lodí kostela jen kvůli minimální ploše.
6. Větším komponentám přizpůsobit jednoduché střechy ze stejných rodin jako v minulém kole: plochá, pultová, sedlová, valbová a oblouková. Limit je 1500 bodů vlastního fitu, dvě orientace a nejvýše 6000 fitovacích bodů pro porovnání kandidátů na část. Penalizace šablony 0,04 m, parametr tolerance 0,50 m. Žádné hodnoticí body se nepoužijí.
7. Všechny střešní části sestavit do jedné nepřekrývající se půdorysné partition. Vnější stěny jdou k terénu, mezi střechami vznikají jen místní svislé stěny výškového stupně. Nevkládáme duplicitní vnitřní stěny jednotlivých objemů až k zemi.

Nejvýše osm hlavních komponent a 64 komponent celkem. Překročení limitu znamená ponechání původní geometrie s explicitním stavem, nikoliv svévolné spojení dalších částí. Práh plochy není pravidlem architektonické významnosti; zde slouží k omezení a ochraně malých částí.

## Půdorys a podklady

Původní CityJSON má zaokrouhlené souřadnice. Jeho střešní oblasti se oříznou na přesný zmrazený půdorys; malé nepokryté okrajové proužky lze doplnit nejbližší zdrojovou rovinou pouze do 0,1 % plochy, zároveň do 1 m² a s dosahem nejvýše 5 cm. Větší mezera je důvod experiment odmítnout. Dvory a otvory v půdorysu zůstávají vyloučené. Všechny doplněné proužky jsou auditované.

Pokud výchozí Roofer vrátil plochý náhradní objem LoD1.1, graf nemůže odhalit chybějící členění. V takovém případě je výsledek výslovně označen `partition_source_fallback`; případná nová střecha vzniká přizpůsobením jedné šablony původním TRAIN bodům, nikoliv obnovením členění z plochého vstupu.

Souřadnice jsou lokální XY a výška nad stejným `ground_z` jako v ostatních pokusech. Zdrojový model určuje dělení, pouze TRAIN body tvar nové šablony. Holdout se připojí až pro měření hotového zobrazeného meshe.

## Význam výsledků a omezení

Toto je geometrická segmentace, nikoliv rozpoznání pojmů „loď“, „věž“, „křídlo“ nebo „komín“. Větší části se pro experiment skutečně nahradí vybranými šablonami; jejich trénovací chyba se uloží, ale přijetí se neřídí holdoutem. Nekvalitní kandidát musí zůstat viditelný pro porovnání. Malé a řídké části zůstávají zachované.

Spojitě navazující střechy různých křídel se mohou stát jedinou komponentou. Chybně rekonstruovaný svislý schod se může naopak stát falešnou hranicí. Metoda proto nezaručuje univerzálně správné architektonické členění. Další krok může kombinovat výškové skoky s úzkými půdorysnými propojeními nebo významnými změnami orientace, ale tyto další heuristiky zde nejsou implementované.

Každá varianta ukládá `component_masks`, plošné a výškové údaje, počty původních oblastí, počet fitovacích bodů, důvod zachování komponenty, vybranou rodinu střechy, parametry, celý audit hran grafu a dobu výpočtu. Případné svislé švy po fitování nejsou automaticky skutečnými stěnami stavby.

## Měření

Reálný worker se spustí až po uvolnění sériového výpočetního slotu. Jedno měření každé ze 14 variant; časy zahrnují graf, fitování a společné sestavení, ale ne původní rekonstrukci Rooferu ani následné hodnocení. Externí guard má 2 GB limit přidělené paměti, dvě CPU, nejméně 1 GB dostupné paměti před startem, průběžnou kontrolu projektu do 20 GB a volného C: nad 25 GB.

Implementace a pomocníci se archivují před měřením a na konci se kontrolují jejich otisky. Žádné zdrojové modely ani městská mapa se nepřepisují.

Před měřením prošlo sedm cílených syntetických kontrol: spojitá sedlová střecha zůstane jedním objemem; dvě výškové terasy se rozdělí a mají pouze místní spojovací stěnu; rozdíl prahů 0,75/1,50 m; zachování malé věžičky; zachování dvora; ponechání zdroje při řídkých bodech; zachování všech částí při překročení osmi hlavních objemů. Fitovací API při testech nesmí číst hodnoticí pole.

Naměřená tabulka bude doplněna po dokončení workeru.

## Naměřené dokončené kolo

14 pokusů, 11 modelů a 3 výslovně nepodporované případy. Budvar jih při 0,75 m: nejednoznačná hranice 3 oblastí. Kostel v obou variantách: neplatný nebo svislý střešní trojúhelník. Sportovní hala: 6/5 hlavních objemů při prahu 0,75/1,50 m. Wortnerův dům a Masné krámy: obě varianty se smrsknou na jeden hlavní objem a ztratí důležité členění. Podrobnosti a metriky jsou v [zavery.md](zavery.md).
