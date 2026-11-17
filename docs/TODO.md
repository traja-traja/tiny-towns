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


## Víceúrovňové ploché střechy — 2026-11-17

- [x] Aktuální zjednodušení 4.7.2: vodorovné části alespoň 5 % každá, největší alespoň 20 %, součet alespoň 55 %; jedna základní rovina ve výšce největší části. Původní návrh přesného modelu několika úrovní je odložen.
- Nejprve prokázat lokální vodorovné plochy, sloučit blízké výšky a souvislé oblasti; malé nástavby zanedbat nebo oddělit. Omezit počet významných úrovní a složitost jejich půdorysu.
- Základní objemy oříznout půdorysem a uzavřít schodové stěny stávajícím build_mesh. Rozlišení výškového schodu od skutečného sklonu musí mít kontrolní testy, aby sedlové střechy nevznikaly jako schodiště.
- Regresní příklady: Fráni Šrámka 2609 a Široká 432/11. Informaci o skutečném plochém typu poskytl uživatel; automatické optické hodnocení neprobíhá.

## Soustavy střech zalomených budov — ověření 4.9.1, 2026-11-17

- [x] Vypínatelný kandidát z protilehlých okapů: samostatné směry křídel, společný sklon, varianty štít/valba a délky pásů. Při doloženém rozdílu výšek společný sklon se samostatnými okapy.
- [x] Šest kroků optimalizace a vizuální i numerické posouzení výslovně povolené uživatelem: Husova tř. 1829/12, Kněžská 410/8, Široká 421/1, Hroznová 314/18. Obecná pravidla, bez adresních výjimek; u Hroznové zachován lepší původní kandidát U.
- [x] Geometrie uzavřená; nejistota křídla bez bodů zaznamenána. Výsledky: docs/ROOF_WINGS_AND_PROTRUSIONS_2026-11-17.md.
- [ ] Ověřit zobecnění na nepoužitém vzorku a následně na celé sadě; sledovat čas, počet rovin i neúspěchy. Čtyři cílené domy neprokazují úspěšnost pro celé město.
- [ ] Později samostatné sklony křídel a 2D rozpoznání sousedních půdorysů pro pomoc při volbě štítu; nyní vstup sousedů chybí.

## Nástavby nad plochým základem — 4.8.1

- [x] Vypínatelný modul: souvislé oblasti nad 2 m a od 1 m², zjednodušený obrys, plochý vršek podle 90. percentilu; parametry a čas v JSON.
- [x] Přepočítaná sada 44 domů a porovnání s 4.7.2, 8 nástaveb na 4 domech; viz docs/ROOF_FLAT_PROTRUSIONS_RUN_2026-11-17.md.
- [ ] Vizuální posouzení uživatelem; automatické rozlišení sousedních budov a vegetace zůstává nevyřešené.

## Pravidelné obrysy nástaveb — 4.9.1

- [x] Orientované obdélníky / jednoduché pravoúhlé obrysy podle směru domu, s omezením ztracené a přidané plochy a bezpečným návratem k původnímu zjednodušení. Vypínatelné a nastavitelné.
- [x] Čtyři dotčené domy přepočteny: 8 nástaveb, 162 → 39 vrcholů obrysu; původní prahy 2 m / 1 m² / percentil 90 zachovány.
- [ ] Automatické odlišení vegetace a sousedů stále není vyřešeno; tvarové zjednodušení ho nenahrazuje.

## Samostatná noční fronta 2026-11-17

- [x] Samostatná příprava hustých bodů s obnovením, modelování po jednom domu, kontrolní součty a opakované využití shodných hotových modelů.
- [x] Postupné etapy Velešín / ČB s pravidlem méně než 2 hodiny → nejvýše další 4 hodiny; stopfile, časový limit domu, disk/RAM a ochrana před uspáním.
- [ ] Uživatel posoudí výsledné modely noční dávky; skutečné dokončení a chybějící objekty číst z night.json a stage.json, nikoli předpokládat podle plánu.
- [ ] Následně převést schválené modely do verzované mapové pipeline; noční dávka vytváří 3D galerie, nevykresluje celé městské dlaždice.


### Kontrola podpory půdorysu před modelováním střech (Husova, 2026-11-17)

- [x] Před přesným ořezem testovat body v půdorysu i malém okolí, ponechat dostupné třídy terén/budova a zaznamenat pokrytí zdroje. Rozlišovat nepřítomnost střechy doloženou terénem od mezery měření či klasifikace.
- [x] Samostatný vypínatelný modul pro návrh odstranění souvislých nepodložených přístavků; porovnávat plošné pokrytí v buňkách a výšky, nikoli jen celkový počet bodů. Zachovat původní půdorys a zapsat odvozenou úpravu s důvodem do JSON.
- [x] Opt-in kontrola výklenků podle konkrétního building ID: doplnit pouze lokální kapsu při souvislé podpoře pokračující střešní plochy v širším mračnu; nepoužívat konvexní obálku přes dvory. Rozlišit přesah střechy od rozšíření půdorysu stěn a nebrat sousední budovu.
- Ověřený příklad Husova tř. 1829/12: zelená prověřená část 56,606 m² má 0 bodů třídy 6 a 458 bodů třídy 2, medián výšky 0,11 m nad referenčním terénem. Červený výklenek 19,444 m² má 480 bodů třídy 6 (p10/p50/p90 9,019/10,14/11,63 m), všechny vypadly přesným ořezem půdorysu. Podklad již uložen v `roof-parallel-inputs-12/point-clouds/stream-checkpoint.npz`; obsahuje třídy 2 a 6, nikoli všechny původní třídy. Půdorys pochází z OSM přes Overture, není to parcela. Audit: `cities/ceske-budejovice/experiments/roof-v492-review-53/footprint-support-husova.json`. Při tomto původním auditu se algoritmus ani modely nezměnily; navazující implementace je popsána níže.

- Implementováno a otestováno ve 4.9.5: Husova odstranění 60,467 m² podél původní hrany, doplnění 19,444 m², samotná optimalizace 0,295 s. Modul výchozí vypnutý, u testu zapnut per-building konfigurací. Podrobnosti a omezení: [ROOF_FOOTPRINT_SUPPORT.md](ROOF_FOOTPRINT_SUPPORT.md).
- [ ] Ověřit modul na širším vzorku a doplnit nezávislou informaci o stěnách pro rozlišení přesahu střechy od skutečného rozšíření domu. Výšková návaznost chrání před řadou sousedních ploch, sama polohu fasády nedokazuje.

### Skeleton: obecné štíty a naměřená poloha hřebene

- [x] Odstraněn filtr pouze trojúhelníkových valeb. Obecný lokální adaptér zkouší
  prodloužení sousedních rovin i nad členitými zakončeními; kontroluje návaznost,
  profil štítu a společně odstraňované sousední plochy. Virtuální obrysy spojují
  drobně přerušované fasády; skutečné stěny se neposouvají. Viz ROOF_STRAIGHT_SKELETON.md.
- [ ] Rozšířit konstrukci o obecné vážené skeletony, pokud lokální pokračování
  rovin neumí konkrétní kombinaci bez porušení návaznosti. Zamítnutí z konstrukčních
  důvodů nadále není důkazem chybějícího skutečného štítu.
- [x] Pracovní hřebeny z řezů výhradně pro analýzu v testovacích HTML, bez vlivu
  na výběr/konstrukci. V mapovém režimu vypnuté, v reportovém zapnuté.
- [ ] Případné řízení konstrukce naměřeným hřebenem řešit samostatně až podle
  dalšího zadání; společný sklon skeletonu zatím jeho XY polohu nepřizpůsobuje bodům.
- [ ] Porovnat citlivost pracovních hřebenů na šířku vyloučeného pásu, sousedy
  a délku podpory. Aktuální nejisté úseky neprodlužovat automaticky k fasádám.


### Skeleton: podpora štítů, zjednodušení a náklady — doplnění 2026-11-17

- [x] Lokální důkaz štítu v konfigurovatelném vnitřním pásu 0,8–1,5 m od skutečné hranice domu podle následného upřesnění Pavla. Výšková tolerance vůči modelu 0,8 m je samostatný parametr. Virtuální posun fasády nesmí vpustit body u skutečné hranice. Při malém počtu buněk zůstává explicitní důvod nedostatku podpory; nejde o důkaz valby. Samotné odsazení nemusí odstranit všechny sousední body.
- [ ] Lokální rozlišení výškových skupin opírat o návaznost do vnitřku střechy nezávisle na právě zkoušeném kandidátu. Nezahazovat body pouze proto, že odporují kandidátovi.
- [x] Virtuální krátká konvexní zkosení mezi dvěma dlouhými stěnami nahradit jejich průsečíkem v limitech posunu/plochy, se zachováním dvorů a pokrytí skutečného obrysu. Implementováno obecně ve4.10.0, přepínatelné a otestované. Viz ROOF_REVIEW_TELEMETRY.md.
- [x] Ve společné pipeline skeleton nejprve fitovat a hodnotit jako roviny/oblasti, finální uzavřený mesh budovat při výběru (s návratem k dalšímu při neplatnosti). Samostatný experimentální report stále může vytvořit všechny varianty. Implementováno ve4.10.0.
- [ ] Případně dále omezit kombinace předvýběrem nejslibnějších štítů; současné podmínky omezují domy a počet konců, uvnitř kandidatury se stále zkoušejí dostupné kombinace.
- [ ] Logovat skutečný počet pokusů, předčasných zamítnutí a iterací optimalizátoru; délka seznamu uložených kandidátů není počet všech interních vyhodnocení.


### Budoucí rozlišení hraničních bodů a sousedních staveb — Pavel, 2026-11-17

- [ ] Samostatný volitelný modul pro identifikaci bodů, které nepatří hlavnímu objemu zkoumaného domu, zejména u společné hranice s jinak vysokým sousedem. Pro současné pokusy není implementace potřebná.
- [ ] Rozlišit izolované shluky bez místní prostorové návaznosti, souvislé body cizí střechy nebo svislé stěny sousedního domu a vlastní atiku či jiný skutečný prvek. Souvislost shluku sama neprokazuje příslušnost ke zkoumanému domu; výškový rozdíl sám neprokazuje šum.
- [ ] Posuzovat lokální hustotu, vzdálenosti a prostorovou návaznost bodů směrem dovnitř domu; případně využít sousední půdorysy a jejich výšky, jsou-li dostupné. Neodstraňovat body pouze podle nesouladu se zvolenou střešní šablonou.
- [ ] Uchovat zdrojové body, oddělit masku nejistých/vyloučených bodů a zaznamenat důvod i dopad na pokrytí. Nejisté případy odložit k analýze, nikoli vydávat za spolehlivě vyčištěné.
- [ ] U příčných/podélných řezů a odhadů poblíž hranice přiznat zvýšenou nejistotu. Platí zvlášť u navazujícího vyššího/nižšího souseda; odsazený pás 0,8–1,5 m pro test štítu není záruka odstranění kontaminace a nenahrazuje budoucí rozpoznání.

- [x] Testovací souhrn kandidátů: skutečné pokusy, důvody podmínek skeletonu, časy fitu/geometrie/režie a nejpomalejší domy na konci automatického HTML. Mapové logy mají souhrn bez jednotlivých pokusů. Viz ROOF_REVIEW_TELEMETRY.md.


## Dvorní pultové střechy — návrh, zatím neimplementováno (2026-11-17)

- Volitelný, výchozí vypnutý kandidát `courtyard_skillions`: sedlový hlavní objem a pultová dvorní křídla. Příklad Dr. Stejskala 426/15; bez adresních výjimek.
- Dvůr navrhnout z otvoru či velkého otevřeného zářezu v půdorysu, ale samotný zářez není důkaz. Pro každé křídlo ověřit plošnou podporu sklonu do dvora po délce i šířce. Vysoké body u sousední fasády nestačí.
- Hlavní hřeben zachovat; pultovou plochu spojit průsečíkem rovin, při doloženém výškovém rozdílu samostatným objemem. Jen několik kandidátů, sankce za složitost, bez využívání reportových analytických řezů ve výrobní pipeline.
- Neposouvat celý skeleton na okraj; pro tuto smíšenou střechu je jednodušší samostatná pultová rovina.
- Audit uloženého modelu: objem2 nyní tvořil volný `parallel_gables` se třemi hřebeny, krajní sklon85,7° a protější6,5°. To je patologické přizpůsobení volné šablony, nikoli skeleton. Obecné omezení symetrie/sklonu se řeší ve4.11; dvorní kandidát zůstává TODO.

## Pevná srovnávací verze testů (2026-11-17)

Do dalšího pokynu Pavla používat jako levou stranu `cities/ceske-budejovice/experiments/roof-v410-review-inputs-54`. Nové výstupy ji nesmějí automaticky nahradit; `roof_batch.py` předává stejnou cestu do následného příkazu v RUN.txt.


### Navazující křídla: hranice působnosti — 2026-11-17

- [ ] Obecně ukončovat prostorovou působnost střechy křídla podle průsečnice se sousední střechou a změny šířky křídla. Pouhé prodloužení celého pásu u Kněžské 410/8 zvedá jinou dlouhou římsu o 2,34 m; původní kratší obdélníkové rozsahy s odstraněnými koncovými valbami zase vytvářejí vnitřní výškové schody. Obě varianty musí zůstat odmítnuté.
- [ ] Zachovat vodorovné okapy skutečných vnějších hran, lokálně doložené štíty a spojitou střechu bez falešných svislých ploch. Bez výjimek podle adres.
- [ ] Zkoušet na širším/sužujícím se křídle, šikmém napojení a uzavřeném dvoře. Porovnání s pevným základem roof-v410-review-inputs-54.


### Šířka křídel před symetrií sklonů — audit Jírovcovy, 2026-11-17

- [ ] Opravit obecný výběr lokálních párů stěn v `_paired_ridge_proposals` / `_wing_boxes`: šířka křídla se musí vztahovat k jeho vlastnímu rameni, ne k téměř celému L půdorysu. Propojení křídel může prodloužit oblast napojení, nesmí bez kontroly změnit význam příčné šířky. Pouhé pokrytí celého půdorysu ani sjednocení sklonů tuto chybu neřeší.
- Audit uloženého v4.13 modelu: vybrané pásy mají šířky 16,839 a 19,636 m. Reprodukce na uloženém zjednodušeném obrysu našla také lokální protilehlé stěny vzdálené 5,086 a 11,930 m; vybrané široké pásy každý samostatně pokrývají téměř celý objekt (99,7 % / 100 %), takže nejde o dvě lokálně vymezená ramena. Tyto hodnoty jsou geometrie kandidátů, nikoli nezávisle ověřené zaměření střechy.
- První hřeben je 2,526 m od okapu (15 % ze 16,839 m), tedy téměř polovina lokální šířky 5,086 m. Šablona však protější spád počítá na zbývajících 14,313 m a při společné výšce okapů vyrobí 53,66° / 13,49°. Posun hřebene tak může kompenzovat chybnou šířku šablony.
- [ ] Pro virtuální střešní obrys vynechat drobné výstupky při odhadu hlavních stěn, ale zachovat velké zářezy, dvory a zalomení. Ověřit lokální šířku v několika 2D průřezech mimo křížení ramen; kandidáty hodnotit i podle této podpory, ne jen celkového pokrytí. Finální roviny oříznout skutečným půdorysem a uzavřít objem.
- [ ] Až po opravě šířek preferovat shodné protější sklony každého sedlového křídla; silně nesymetrickou variantu připustit jen při podstatném zlepšení plošné podpory bodů. Při různých šířkách nelze současně vynucovat stejný sklon, společnou výšku okapů a stejnou výšku všech hřebenů. Žádná adresní výjimka.
- V tomto auditu se měřil pouze uložený 2D půdorys; generátor ani hotové modely se neměnily.

- [x] Ve 4.13.2 doplněna kontrola vlastních ramen a 2D šířek pro párové kandidáty; preference symetrických protějších sklonů. Viz ROOF_LOCAL_WING_WIDTHS.md. Obecné zjednodušení ostatních rodin se touto úpravou nemění.

- [ ] Regrese Jírovcovy v4.13.2: zachovat opravu lokálních šířek, odstranit skokovou penalizaci malého posunu hřebene (2–3° rozdílu sklonů dostává stejný trest jako silná nesymetrie) a doplnit skutečný důkaz dodatečných hřebenů U/O. Výběr dosud upřednostnil U před vhodným L; audit a přesná skóre v ROOF_LOCAL_WING_WIDTHS.md.

- [x] Ve4.13.3 odstraněna skoková penalizace malého posunu hřebene a doplněna obecná lokální evidence každé větve U/O; pouze jeden nový přepočet Jírovcovy. Viz ROOF_NETWORK_RIDGE_EVIDENCE.md.
