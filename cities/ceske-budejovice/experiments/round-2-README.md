# České Budějovice – kandidáti druhého kola

Jde o rešerši a netestovaný backlog, nikoli dokončené rekonstrukce. První kolo zůstává beze změny: 30 zdrojových půdorysů a 18 kandidátů na podrobnější práci při limitu nejvýše 20. Níže je 21 položek; dvě patří jedné Slavii v různých časových stavech, okresní soud je záměrně rozdělen na dvě adresy.

## Co je doložené a co ještě chybí

- Slavie: město potvrzuje slavnostní otevření 29. 12. 2025 po rekonstrukci a přístavbě směrem k muzeu. Přesné datum úplného stavebního dokončení tím není prokázané. Starší mračno má vlastní variantu s dosud neověřenou epochou; novou budovu z něj neodvozujeme.
- ČNB je na Lannově třídě 1, ČSOB na Lannově 11/3. Identitu dokládají banky, přiřazení lokálních půdorysů adresní body ČÚZK v Overture. Pouhá poloha POI nebyla použita jako rozhodující důkaz.
- Okresní soud má hlavní budovu na Lidické 98/20 a pobočku na Zátkově nábřeží 10/2. Věznice má oficiální adresu Goethova 1, místní adresní bod ji spojuje s č.p. 1929. Vnější rozsah celých areálů je nutné vymezit zvlášť.
- Popis jezu nad Dlouhým mostem odpovídá Jiráskovu jezu podle oficiálního průvodce. Jde o podloženou interpretaci zadání; pojmenovaný objekt je v místní infrastruktuře dohledán.
- Náplavka je samostatný časový problém: městská stránka z října 2026 popisuje investici s realizací do ledna 2028. Projektové vizualizace nepředstavují měření skutečného stavu. Hvězdárna navíc plánuje rekonstrukci pláště od února 2027.
- Tři vnitrobloky jsou zatím oblasti k výběru. Jejich uliční kotvy jsou ověřené, hranice konkrétních dvorů a průchodů dosud ne.

## Přehled

| Kandidát | Typ | Proč jej zkusit | Lokalizace / pokrytí |
|---|---|---|---|
| Jihočeské divadlo – historická budova | building | Členěný kulturní objekt, oddělení hlavního objemu, jeviště a menších částí. | Dr. Stejskala 424/19; `inside_preview_reference_geometry` |
| KD Slavie – stav odpovídající starému mračnu | building | Kontrolní historická varianta; stáří dat se nesmí zaměnit za chybu rekonstrukce. | Jirsíkova 243/2; `inside_preview_reference_geometry` |
| KD Slavie – stav po rekonstrukci a přístavbě | building | Samostatný aktuální objem, zejména přístavba směrem k muzeu. | Jirsíkova 243/2; `inside_preview_reference_geometry` |
| Okresní soud – hlavní budova | building | Oddělit od pobočky na nábřeží a porovnat základní objemy vícekřídlého objektu. | Lidická třída 98/20; `inside_preview_reference_geometry` |
| Okresní soud – pobočka Zátkovo nábřeží | building | Objem v kontextu soudu, věznice a nábřeží; vymezit přesné části. | Zátkovo nábřeží 10/2; `inside_preview_reference_geometry` |
| Vazební věznice České Budějovice | building | Vícekřídlý areál: jednoduché vnější objemy a zachování otevřených dvorů. | Goethova 1929/1 (primární kontaktní stránka uvádí Goethova 1); `inside_preview_reference_geometry` |
| Zátkovo nábřeží – koridor u historického jádra | corridor | Plošný test navazujících zdí, komunikací, schodů a mostů; ne jeden stavební polygon. | Úsek mezi Zlatým mostem a mostem v Biskupské ulici; přesný pás a břeh musí být zakreslen.; `locality_in_centre_boundary_not_checked` |
| Zátkovo nábřeží – nová náplavka a stavební etapa | corridor | Oddělený časový test nižšího korza, opěrné zdi, schodů a podzemního prostoru. | Levý břeh Malše mezi Železným mostem v Biskupské a Krumlovským mostem v Lidické.; `locality_in_centre_boundary_not_checked` |
| Modrý most | bridge | Otevřený prostor pod mostovkou, oblouky a návaznost komunikací. | Přes Malši mezi ulicemi Marie Vydrové a Matice školské.; `inside_preview_reference_geometry` |
| Zlatý most | bridge | Dvojice oblouků a volný průhled pod mostem. | Malše, konec ulice Dr. Stejskala.; `inside_preview_reference_geometry` |
| Dlouhý most | bridge | Zachovat konstrukční siluetu a otevřený prostor nad Vltavou. | Most přes Vltavu v ose Husovy třídy.; `inside_preview_reference_geometry` |
| Jez nad Dlouhým mostem – pravděpodobně Jiráskův jez | hydraulic | Přechod vodních hladin a nízkých konstrukcí, které nejsou vhodné pro model budovy. | Vltava, ř. km 239,605, u Sokolského ostrova proti proudu od Dlouhého mostu.; `inside_preview_reference_geometry` |
| Hvězdárna a planetárium | building | Kopule a členěné nízké objemy vyžadují jiný model než pouze rovinnou střechu. | Zátkovo nábřeží 4; `inside_preview_official_point` |
| Grandhotel Zvon | building | Více historických hmot a střešních částí, fasáda do náměstí. | náměstí Přemysla Otakara II. 90/28; `inside_preview_reference_geometry` |
| ČSOB – Lannova tř. 11/3 | building | Moderní dostavba banky a napojení různých stavebních částí. | Lannova tř. 11/3; `inside_preview_reference_geometry` |
| Česká národní banka – Lannova 1 | building | Oddělit od sousední ČSOB; výšky hmot, profil střechy a uličně exponovaná fasáda. | Lannova třída 1; `inside_preview_reference_geometry` |
| Humanoidi – sousoší chodců na Lannově | sculpture | Rozpoznatelný pouliční prvek; s řídkým leteckým mračnem jej nelze spolehlivě rekonstruovat. | Pěší zóna Lannovy třídy; bod lokalizuje sousoší, nikoli pozice každé sochy.; `inside_preview_reference_geometry` |
| Samsonova kašna | fountain | Členění nádrže, soklu a sousoší bez zkreslení na plnou stavební extruzi. | Střed náměstí Přemysla Otakara II.; `inside_preview_reference_geometry` |
| Vnitroblok za Krajinskou 43/8–45/12 | courtyard | Pokus zachovat prázdný dvůr, zadní křídla a rozhraní mezi podloubím a domem. | Pracovní oblast za třemi ověřenými domy Krajinská 43/8, 44/10, 45/12; konkrétní dvory dosud nejsou vymezené.; `anchors_inside_preview_candidate_boundary_unresolved` |
| Vnitroblok za radnicí | courtyard | Kontrast k uliční fasádě: zadní hmoty, uzavřené a otevřené části bloku. | Návrh vnitroblokové oblasti za radnicí, náměstí Přemysla Otakara II. 1/1.; `anchors_inside_preview_candidate_boundary_unresolved` |
| Vnitroblok u Puklicova domu a severní strany náměstí | courtyard | Složitější návaznost dlouhých městských parcel, dvorů a bočních křídel. | Návrh oblasti za Krajinskou 36/2 u napojení na náměstí; přesné dvory budou teprve vybrány.; `anchors_inside_preview_candidate_boundary_unresolved` |

## Metody a potřebné podklady

Budovy: nejprve jednoduché výškové objemy a části s rovinami střech; kopuli planetária řešit samostatně. Mosty: samostatná tenká mostovka, podpory a oblouky, s doloženou světlou výškou. Jez a nábřeží: příčné profily, oddělené hladiny, zdi, schody a otvory. Sochy a kašna: jednoduchý rozpoznatelný objem, podrobnosti až ze samostatného metrického modelu s použitelnou licencí. Jde o návrhy experimentů, jejich přesnost ani časy zde nebyly měřeny.

Pro každý nový výpočet je potřeba datum pořízení bodů, datový stav půdorysu a reference stejné epochy. Letecký povrch nezachycuje spolehlivě spodní stranu mostů, podloubí, průchody ani tvary soch. U Samsonovy kašny se dva oficiální turistické podklady liší v průměru 15/17 m; žádný z těchto rozměrů není převzat jako zaměřený parametr.

## Zdrojové doklady

Podrobné zdroje a jejich omezení jsou po položkách v [round-2-candidates.json](round-2-candidates.json). Primární URL:

- [Kontakty Jihočeského divadla](https://www.jihoceskedivadlo.cz/kontakty) — Jihočeské divadlo.
- [Kulturní infrastruktura ČB](https://www.c-budejovice.cz/sites/default/files/obsah/Magistrat/Informace/Archiv-poskytnutych-informaci/2025/kulturni_infrastruktura_analyza_cb_30_6_2025_popripominkach.pdf) — Statutární město České Budějovice.
- [Kulturní dům Slavie se slavnostně otevřel](https://www.c-budejovice.cz/kulturni-dum-slavie-se-slavnostne-otevrel-programem-pro-budejcaky) — Statutární město České Budějovice.
- [Rekonstrukce KD Slavie](https://www.c-budejovice.cz/rekonstrukce-kd-slavie) — Statutární město České Budějovice.
- [Gastro ve Slavii](https://www.kdslavie.cz/gastro/) — Kulturní dům Slavie.
- [Kontakty Okresního soudu](https://msp.gov.cz/web/okresni-soud-v-ceskych-budejovicich/kontakty) — Ministerstvo spravedlnosti ČR.
- [Vazební věznice České Budějovice](https://www.vs.gov.cz/organizacni-jednotky/vazebni-veznice-ceske-budejovice) — Vězeňská služba ČR.
- [Zátkovo nábřeží prošlo obnovou](https://www.c-budejovice.cz/zatkovo-nabrezi-proslo-obnovou) — Statutární město České Budějovice.
- [Zátkovo nábřeží – úprava náplavky](https://www.c-budejovice.cz/zatkovo-nabrezi-uprava-naplavky) — Statutární město České Budějovice.
- [Usnesení rady města 22. 10. 2003](https://www.c-budejovice.cz/sites/default/files/meeting_resolutions/rm2303.pdf) — Statutární město České Budějovice.
- [Zlatý most](https://www.encyklopedie.c-budejovice.cz/clanek/zlaty-most) — Městská encyklopedie Českých Budějovic / Daniel Kovář.
- [Dlouhý most](https://www.encyklopedie.c-budejovice.cz/clanek/dlouhy-most) — Městská encyklopedie Českých Budějovic / Daniel Kovář.
- [Oficiální průvodce Českými Budějovicemi 2026](https://www.visitceskebudejovice.cz/guide/cz/CBudejovice_2026.pdf) — Oficiální turistický portál města.
- [Opatření O-2026/47/0](https://sps.gov.cz/predpisy/predpis.php?id=1695&typ=oop&zdroj=uredni_deska) — Státní plavební správa.
- [Kontakty hvězdárny](https://www.hvezdarnacb.cz/cz/kontakt) — Hvězdárna a planetárium České Budějovice.
- [Provoz a plán rekonstrukce hvězdárny](https://hvezdarnacb.cz/) — Hvězdárna a planetárium České Budějovice.
- [Kontakt Grandhotelu Zvon](https://www.hotel-zvon.cz/kontakt) — Grand Hotel Zvon s.r.o..
- [ČSOB – pobočka Lannova](https://www.csob.cz/kontakty/pobocky-a-bankomaty/pobocka?id=ceske-budejovice-lannova) — ČSOB.
- [Mimopražské pracoviště České Budějovice](https://www.cnb.cz/cs/o_cnb/organizacni-struktura/mimoprazska-pracoviste/mimoprazske-pracoviste-ceske-budejovice/) — Česká národní banka.
- [Humanoidi](https://www.michaltrpak.com/portfolio/humanoidi/) — Michal Trpák, autor díla.
- [Samsonova kašna](https://www.budejce.cz/aktivity/5-samsonova-kasna) — Oficiální turistický portál města.
- [Krajinská třída](https://www.encyklopedie.c-budejovice.cz/clanek/krajinska-trida) — Městská encyklopedie Českých Budějovic.
- [Adresa magistrátu / lokalizace prvního kola](https://www.c-budejovice.cz/sportovni-zarizeni) — Statutární město České Budějovice.
- [Puklicův dům](https://pamatkovykatalog.cz/mestsky-dum-19152358) — Národní památkový ústav.

## Lokální evidence

Geometrické kotvy byly čteny z hotového preview snapshotu Overture 2026-10-21.0 (`data/address.parquet`, `building.parquet`, `infrastructure.parquet`); kontrolní SHA256 a počet řádků jsou v manifestu. U adres jde o č.p. v poli `number` a číslo orientační v `unit`. Přiřazení jednoho obsahujícího polygonu neprokazuje rozsah celého areálu.

Preview má 2,3 × 2,3 km. `inside_preview_reference_geometry` ověřuje pouze připojenou zdrojovou geometrii; `inside_preview_official_point` jen bod. U koridorů a dvorů nebyly vytvořeny smyšlené hranice.

Lehká lokální kontrola a sestavení manifestu: 1.326 s. Tento čas nezahrnuje webovou rešerši. Žádné nové stahování bodových mračen, rekonstrukce ani rendery. SHA256 neměnného prvního vzorku: `aa3ca9cd50f0f639421545c9f1fee11391757c00ecafe7c5137adbf1b4082d21`.

Ověřeno 16. 11. 2026.
