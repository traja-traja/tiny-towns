# TODO – Tiny Towns

## ČB – České Budějovice: doprava, scénáře a minihry

Zapsáno 16. listopadu 2026. Jde o plánované funkce a nápady k rozpracování.
ČB = České Budějovice, městská data v `cities/ceske-budejovice/`.

### Dopravní model a zácpy

- [ ] Dopravní model ČB: síť ulic, poptávka po cestách, cíle jízd, kapacity a pravidla křižovatek; výpočty oddělit od vizualizace.
- [ ] Dopravní zácpy: vznik a rozpouštění kolon, čekání, zdržení a přenos zahlcení do okolních ulic.

Současná animace aut není kalibrovaný dopravní model. Pro modelování skutečné dopravy ověřit a kalibrovat vstupy; herní a nadsazené scénáře vést jako samostatné režimy. Kontext: [dopravní model v plánu rozvoje](UPDATES.md#dopravní-model-českých-budějovic).

### Semafory a ovládání

- [ ] Rozšířit stávající semafory pro ČB: návaznost řízení křižovatek na dopravní model a kolony.
- [ ] Režim „červená vlna“ – navazující semafory načasované tak, aby auta postupně zastavovala na červenou.
- [ ] Přepínač/ovladač „všude červená“ – v celé simulované mapě města současně zapnout červenou na všech semaforech pro auta; umožnit návrat k běžnému cyklu.

### Parkování a hromadné cíle jízd

- [ ] Auta stojící na chodníku jako překážky pro chodce.
- [ ] Režim „všechna auta zastavit na chodníku“.
- [ ] Režim „všechna auta chtějí zaparkovat na náměstí“.
- [ ] Režim „všechna auta jedou na hokej“.
- [ ] Režim „všechna auta jedou na trhy“.
- [ ] Režim „všechna auta jedou na Mariánské parkoviště“.
- [ ] Přepínání scénářů a možnost doplňovat další společné cíle jízd; sledovat hledání místa, zaplnění parkovišť a navazující kolony.

### Minihry a situace v ulicích

- [ ] Cyklista ujíždí městské policii – pracovní označení „městapo“.
- [ ] Cyklista jede po chodníku.
- [ ] Auto jede v pěší zóně.
- [ ] Auto jede rychle na náměstí.
- [ ] Chodec se vyhýbá autům – propojit i se scénáři v pěší zóně, na náměstí a s auty stojícími na chodníku.

## ČB – jednoduché typové střechy

Rešerše a audit 16. listopadu 2026: [HTML návrh](../cities/ceske-budejovice/experiments/roof-archetypes/report.html). Stav: návrh, nový benchmark ani změna produkční mapy neproběhly.

- [x] Prověřit naše šablony, Roofer, SAT2LoD2, CGAL a robustní fit; dohledat příčinu chybné sedlové šablony Wortnerova domu.
- [ ] Doplnit víceúrovňové ploché střechy a oddělení dominantních částí; Wortner jako první ověřovací případ.
- [ ] Nejprve vyloučit geometricky nepřípustné typy, potom seřadit zbývající kandidáty podle podpory v datech, chyby, pokrytí a jednoduchosti. Vždy zvolit jeden výstup; blízké skóre kandidátů uložit jako nejistotu. Tolerance přibližně ±0,5 m je výchozí požadavek, ne zaručená přesnost. Skóre nezaměňovat za kalibrovanou pravděpodobnost.
- [ ] Zpřesnit podmínky sedla/valby a přidat samostatný stan; následně úžlabní, propojené L/T a pilové střechy.
- [ ] Porovnat běžné domy i původní specifické objekty; dokumentovat vzhled, chybu, složitost, čas a RAM ve stejném HTML. Po ladění ověřit i na nových budovách.
- [ ] Významné terasy, nástavby a výstupky přidávat po volbě základní střechy; zachovat skutečné dvory a návaznost stěn na okapy.

### Rozhodnutí: rychlá pipeline a diagnostika

Upřesněno s Pavlem 16. listopadu 2026. Nejprve rozebrat postup; nový výběr střech, diagnostický render ani paletizace zatím nejsou nasazeny.

- [ ] Běžnou pipeline založit na hřebenech, hlavních sklonech, okapových hranách a jednoduchých šablonách. Roofer nespouštět automaticky ani jako zálohu při nejistotě; ponechat ho jako nástroj pozdější oddělené analýzy vybraných objektů.
- [ ] Pro každý dům zvolit jeden nejlépe podložený model. Při nejasnosti stále vygenerovat střechu, ale uložit problém k revizi; pokud data nestačí, využít zdrojový typ nebo označený procedurální odhad.
- [ ] Zachovat rozklad členitého půdorysu na obdélníky jako záložní postup, s kontrolou překryvů, návazností a dvorů.
- [ ] Generovat diagnostický JSON (navržený název roof-diagnostics.json): stabilní ID budovy, zvolený typ a metoda, alternativy a jejich skóre, odstup vítěze, pokrytí bodů, chyby, důvody nejistoty, původ a verze vstupů/algoritmu. Soubor není dosud zaveden do buildu.
- [ ] Přidat diagnostický pohled vedle čtyř ročních období: problémové střechy a domy barevně odlišit podle důvodu či závažnosti. Filtry pro střechu, výšku, zdrojový rozpor, chybějící body a barvu; proklik na důvody a budovu. Diagnostiku ukládat jako samostatnou vrstvu/variantu, s odkazem na stejné ID jako JSON.
- [ ] Náklady vyhodnocení chyb oddělit od hledání/optimalizace parametrů a od načítání souborů; nejdřív vektorový CPU výpočet. GPU posuzovat až podle změřeného úzkého místa celé pipeline.

### Barvy: původní údaje a omezená paleta výsledné mapy

- [ ] Při načítání uchovávat všechna dostupná barevná pozorování pro střechu/fasádu před jejich slučováním a přepisováním: původní hodnotu, zdroj a atribut, ID záznamu, datum/verzi (je-li dostupná), případně kvalitu, normalizovanou barvu a důvod neúspěšného převodu. Rozpory mezi zdroji uchovat; nic nedoplňovat jako domněle naměřenou barvu.
- [ ] V odděleném záznamu držet vybrané pozorování, cílové ID/odstín palety, verzi palety a způsob převodu. Původní zdrojové barvy nikdy nepřepisovat paletovou hodnotou.
- [ ] Všechny cesty k základní barvě střech/fasád (zdrojové tagy, ortofoto, ruční úpravy, dominanty i výchozí generování) vést přes schválenou tlumenou paletu. Hexadecimální barva ze zdroje nesmí paletu obejít.
- [ ] Zdrojový odstín převádět na vizuálně blízkou barvu palety, zvlášť pro střechy a fasády; posoudit vjemový barevný prostor a zachování barevné rodiny. Při chybějící/nečitelně zadané barvě volit stabilně podle ID domu a vhodné palety.
- [ ] Základní materiál musí používat paletový odstín; běžné stínování a osvětlení ponechat. Diagnostický pohled má vlastní výstražné barvy a nepatří do palety běžné mapy.

### Další vzorek domů

- [ ] Před implementačním porovnáním připravit nový vzorek běžných domů z ČB: rohové, řadové, samostatné, členité a ploché. Náhodně vybírat uvnitř skupin s uloženým seedem; nedělat pouze výběr výrazných dominant.
- [ ] Pavel může doplnit adresy problematických domů. Ty vést jako cílené případy odděleně od náhodného vzorku, aby nezkreslily odhad úspěšnosti na celém městě.
- [ ] Část nového vzorku ponechat pro kontrolu až po nastavení pravidel; zdokumentovat identitu, skutečný typ, vstupy, úspěšnost, složitost, čas a paměť.


### Implementováno v odděleném experimentu roof-v2 (2026-11-16)

- [x] Nový samostatný algoritmus nad hustými DMPOK body, bez Rooferu a bez AI hodnocení obrázků.
- [x] Vývojový vzorek 30 domů: 24 nových ve čtyřech skupinách, 5 zadaných adres, Wortnerův dům. Dalších 7 adres je ve frontě sample.json.
- [x] Oddělení stěn/střechy, jednoduché šablony, dvě ploché úrovně, záložní rozdělení dvou velkých hmot; uzavřená geometrie včetně dvorů.
- [x] Diagnostika nejistoty, původní barvy a provenance v JSON; izolovaný paletový render a diagnostické výřezy.
- [x] Numerické srovnání s existující hustou verzí na stejných bodech; odchylky včetně neúspěchů.
- [ ] Pavel vizuálně posoudí report.html a tiles/report.html. Číselná shoda sama nepotvrzuje skutečný typ střechy.
- [ ] Následný nepoužitý vzorek ověří zobecnění pravidel. Současných 30 domů je vývojový vzorek.
- [ ] Po výběru metody napojit diagnostiku a omezené palety do hlavního buildu všech budov; tento experiment produkční mapy nemění.


### Šum na hranicích budov a sousední vyšší domy (2026-11-16)

- [ ] Prověřit u Jírovcovy 1449/25 podezření na příměs bodů vyššího sousedního domu u okraje většího křídla. Příčina není potvrzená.
- [ ] Navrhnout rozpoznání okrajového šumu: porovnat výšky a místní sklony s vnitřkem střechy, návaznost na sousední půdorysy a dostupnou hustotu bodů.
- [ ] Posoudit vynechání nebo menší váhu úzkého okrajového pásu při určování hřebene; pás zvolit podle hustoty a šířky domu. Neodstraňovat automaticky skutečnou okapovou hranu, valbu nebo úzké křídlo. Zachovat nezměněný zdroj a zaznamenat použité body.
- [ ] Samostatně rozhodnout, jak zacházet se skutečně sbíhavými hlavními okapy lichoběžníkové budovy: povolit šikmý hřeben / další plochu / zjednodušený obrys, místo vynucování geometricky neslučitelných podmínek.


### Lichoběžníkové půdorysy — návrh k diskusi, bez implementace (2026-11-16)

- [ ] Zachovávat jednoduché rovinné střešní plochy; lichoběžníkový polygon nevyžaduje deformaci kvůli textuře. UV odvozovat z lokálních os každé roviny ve stejném měřítku.
- [ ] U běžných domů zachovat celý vnější obrys. Pokud je známý vnitřní obrys dvora, případné malé korekce omezit na něj a ukládat původní i navrženou geometrii; zatím bez automatického rozpoznávání uličních čar. Hranici přípustného posunu teprve určit.
- [ ] Když přesný půdorys a vodorovné okapy nedovolují vodorovný hřeben, upřednostnit několik rovin s mírně šikmým hřebenem, případně jednu dodatečnou plochu. Plynule prohnuté střechy nepřidávat jen jako opravu neslučitelných vazeb. Pořadí priorit nejprve potvrdit s Pavlem.
