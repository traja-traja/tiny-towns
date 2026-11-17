# Pracovní hřebeny odhadnuté z bodů

Modul: scripts/roof_observed_ridges.py, verze point-profile-ridges-1.
Přepínač: modules.observed_ridges; parametry: observed_ridges v roof_config.py.

## Co znamená linka

Jde o nezávislý diagnostický odhad z trénovacích bodů, nikoli o hranu hotové
střechy ani potvrzené geodetické zaměření. Obrys poskytuje směry příčných
řezů, body určují polohu vrcholu, výšku a podloženou délku. Hřeben nemusí být
uprostřed profilu: sklony na obou stranách jsou nezávislé. Výsledné střechy
tato diagnostika neposouvá.

1. Mediánové buňky 0,5 m; vynechání pásu 0,65 m při hranici každého objemu.
2. Příčné řezy široké 1,6 m po 1,2 m, směry podle významných hran půdorysu.
3. Robustní fit dvou klesajících stran kolem vrcholu. Vyžaduje skutečnou
   podporu na obou stranách; samotné maximum nestačí.
4. Spojení opakovaných vrcholů do souvislých téměř vodorovných úseků,
   s kontrolou rozptylu a alespoň čtyřmi řezy. Linie se nepřetahuje přes
   nepodložené konce ani automaticky až k fasádě.
5. Výška pracovní vodorovné linky je medián výšek podporujících vrcholů.
   Nejméně šest řezů a přísnější rozptyl dávají stav detected; slabší
   přijatelné úseky stav uncertain. Jde o prahy, ne kalibrovanou pravděpodobnost.

Zelená = podpořený odhad, tyrkysová = nejistý odhad; modré Hřebeny modelu jsou
samostatná vrstva. Data jsou v diagnostics.observed_ridges.volumes, volume_id
je číslován od 1. U každého objemu se ukládá stav i v případě nenalezení hřebene.

## Zapojení a omezení

Výpočetní jádro má modules.observed_ridges výchozí vypnuté. Režim report
(resolve_execution_config(..., mode="report")) jej vynuceně zapíná, režim map
jej vynuceně vypíná, i při opětovném použití staré konfigurace z reportu.
roof_batch.py vždy vytváří testovací HTML a měření zapíná; jeho --test pouze
přidává srovnání s předchozí složkou. Produkční night_roof_batch.py v plánovači
i pracovním procesu měření vypíná. Samostatné experimentální HTML runnery
přidávají diagnostiku až po konstrukci a výběru střechy.

V objemové pipeline se měření spouští až po výběru rozdělení, nikoli pro každého
kandidáta. Pro děti se uchovávají odpovídající záznamy. Čas analytiky se ukládá
samostatně a reportová dávka uvádí i čas výpočtu bez analytiky. Výsledky řezů
neovlivňují kandidáty ani jejich skóre. Počet řezů není pevně 30: odvíjí se od
rozměrů a směrů objemu. Pokud chybí podpora, report ukáže nenalezený či nejistý
hřeben místo vymyšlené linky.
Nové reporty umějí vrstvy zobrazit; staré složky se nepřepisují. Hranice
vynechaného pásu, čas a počty buněk jsou uložené. Prázdné či nedostatečné
vstupy mají explicitní stav.

Šum od souseda může zasahovat dál než 0,65 m. Široká komínová nástavba,
neobvyklý směr střechy, nízká hustota, různé výšky a členitá napojení mohou
odhad omezit či zkreslit. Nalezená krátká nejvyšší linka není důkazem, že
pokrývá celý hlavní hřeben. Délka znamená pouze doložený úsek. Diagnostika slouží výhradně analytickému zobrazení; její případné budoucí
použití pro konstrukci by bylo samostatnou změnou algoritmu.

## Dr. Stejskala 112/4 – 2026-11-17

Měření 0,5404 s; všechny 4 skeletonové varianty a diagnostika dohromady
0,7972 s; běh s HTML 4,7652 s. Hlavní pracovní úsek: 4,801 m, výška
16,574 m nad ground_z, pět řezů, stav uncertain. Maximum původního
skeletonového modelu bylo 15,900 m. V místech pracovní linky je odhad
mediánově o 1,989 m nad povrchem modelu; nejbližší přibližně rovnoběžná
modelová hřebenová linka je mediánově vzdálena 6,387 m v půdorysu. Tyto
rozdíly signalizují neshodu, nepotvrzují správnost odhadu ani směr vlevo/vpravo
v otočeném prohlížeči. Vynecháno 230 okrajových buněk.

Audit všech 16 referenčních hran ukázal, že dvě jsou vhodné pro dosavadní
konverzi trojúhelníkové valby na štít, dvě jsou kratší než 2 m a dvanáct
je vyřazeno kvůli netrojúhelníkové střešní ploše. Jde o omezení konstrukčního
adaptéru, nikoli o výsledek testu bodů. Proto report nepředstírá, že byly
vyzkoušeny všechny možné štítové strany.

18 cílených Python testů prošlo; dvě sady JS testů prošly. Modely nebyly
vizuálně hodnoceny. Nebyla spuštěna plošná dávka ani přegenerování tiles.

Report: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-skeleton-gables-stejskala-112-ridge-audit/report.html

Varianty: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-skeleton-gables-stejskala-112-ridge-audit/variants.html


Poznámka Pavla 2026-11-17: řezy a místní odhady u půdorysné hranice jsou
nejisté zvláště při navazujícím jinak vysokém domě. Body mohou tvořit izolovaný
shluk, souvislou cizí stěnu/střechu nebo vlastní atiku. Ani spojitost, ani
výškový rozdíl samy neurčují příslušnost. Budoucí rozlišovací filtr je v TODO;
v současném výpočtu není implementovaný. Diagnostický odstup 0,65 m a nově
odsazené lokální testy štítů 0,8–1,5 m nejsou zárukou odstranění cizích bodů.
