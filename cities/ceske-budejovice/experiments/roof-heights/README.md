# Audit střech a výšky fasád v centru Českých Budějovic

Stav 16. 11. 2026: dokončený audit 12 skutečných půdorysů, opravené přepisování výslovného typu střechy, 11 úspěšných regresních testů a 72 modelovacích běhů nad oběma zdroji. Vzniklo 71 geometrií; vznik souboru není schválením správnosti modelu. Skutečný přepočet celé mapy dokončen: oprava změnila **7 budov**, z toho jednu v diagnostickém vzorku. Zbylé neznámé střechy jsou zdokumentované kandidáty k další validaci; tato první oprava **neřeší všech 18 plochých střech u náměstí**.

[Otevřít interaktivní porovnání 12 budov × 6 variant](fit-report.html). Tato galerie používá stejnou obecnou benchmarkovou baseline jako původní pilot; přesný původní městský renderer je odděleně v `traces` a skutečný přepočet v `rendered_comparison`.

## Co bylo prokázáno

V původním preview je plochých 18 z 39 půdorysů s adresou na náměstí Přemysla Otakara II. To je výběr podle navázané adresy, nikoli přesný soupis první uliční řady. V celém preview končí jako plochých také 16 půdorysů s původním atributem šikmé střechy; některé případy mají protichůdný laserový údaj nebo jiný override a nejsou automaticky chybou.

Příčiny jsou oddělené:

1. Původní `prep.py` přepisoval střechu na `flat`, pokud měl dům třídu `apartments`, alespoň pět podlaží nebo zdrojovou výšku alespoň 14 m. Přepsal i explicitní `gabled`. To je opraveno.
2. Heuristika historických řadových domů byla zapnutá přes `URBAN := chunk != (0,0)`. V centrální dlaždici ČB tedy neběžela. Globálně jsme ji nezapnuli: její odhady nejsou samy o sobě dostatečným důkazem sedlové střechy.
3. Neznámá střecha obchodu/kanceláře nebo půdorysu nad 650 m² padá do plochého fallbacku. Historický dům s obchodem v přízemí proto může skončit jako plochý. Tyto případy vyžadují samostatný fit a jeho validaci; neměníme je všechny na sedlové.
4. Jakmile je zvolena plochá střecha, medián výšek laserových střešních bodů se převezme jako výška celé stěny. Medián střechy není naměřená římsa. U šikmé střechy se naopak část celkové výšky přidělí střeše.
5. Pásy oken jsou procedurální: styl 1 opakuje okna po 2,8 m. Renderer přímo nekreslí zdrojový počet podlaží. Optických šest řad oken tedy není tvrzení, že zdroj uvádí šest pater.

Geometrii a fasádní rytmus je potřeba hodnotit zvlášť. Historický dům může mít tři vysoká podlaží a správně vysokou fasádu, na níž konstantní shader 2,8 m vykreslí příliš mnoho řad. U Baara 1810 je to jedna z hypotéz vedle chybného rozdělení římsa/hřeben; tři viditelné řady samy nedokazují „3 + 2“. Navazujícím údajem může být ověřené `facade_floor_height` nebo `window_rows` pro konkrétní uliční průčelí. Tento audit globální shader nemění.

## Konkrétní diagnostický vzorek

Kompletní UUID, zdrojové OSM way/version, atributy Overture, DMP, přesná původní scéna a příznaky větvení jsou v [results.json](results.json). Půdorysy WGS84 jsou v [sample.json](sample.json). Jde o samostatnou diagnostiku, původních 30 pilotních ID a 18 kandidátů detailní digitalizace se nemění. Čísla domů odpovídají adresám ve zdrojové tabulce (č.p., nikoli nutně orientační číslo).

| ID | Adresa | Zdrojová patra / střecha | DMP medián / P90 (m) | Původní stěna + střecha (m) | Mechanismus / kontrola |
|---|---|---|---|---|---|
| 01 | J. Š. Baara 1810 | 5 / neznámá | 16,7 / 19,1 | 16,7 + 0 | vysoký dům → flat |
| 02 | Dr. Tůmy 1601 | 5 / neznámá | 16,8 / 18,9 | 16,8 + 0 | vysoký dům → flat |
| 03 | Na Sadech 1855 | neuvedeno / neznámá | 13,8 / 15,8 | 13,8 + 0 | apartments → flat |
| 04 | Pražská tř. 1815 | neuvedeno / neznámá | 16,6 / 19,7 | 16,6 + 0 | velký složený půdorys |
| 05 | Na Mlýnské stoce 367 | 5 / gabled | 16,7 / 19,2 | 16,7 + 0 | prokázané přepsání atributu |
| 06 | nám. Přemysla Otakara II. 67 | 3 / neznámá | 11,0 / 14,9 | 11,0 + 0 | retail → flat |
| 07 | nám. Přemysla Otakara II. 50 | 3 / neznámá | 17,1 / 18,5 | 17,1 + 0 | retail → flat |
| 08 | nám. Přemysla Otakara II. 128 | 3 / neznámá | 16,0 / 18,2 | 16,0 + 0 | apartments → flat |
| 09 | nám. Přemysla Otakara II. 89 | 4 / neznámá | 15,4 / 22,6 | 15,4 + 0 | velký složený půdorys |
| 10 | nám. Přemysla Otakara II. 84 | 3 / neznámá | 14,9 / 16,3 | 13,26 + 3,03 | existující valbová kontrola |
| 11 | U Černé věže 69 | 3 / neznámá | 16,7 / 18,1 | 16,7 + 0 | funkcionalistická banka, plochá kontrola |
| 12 | Žižkova tř. 1321 | 15 / flat | 27,2 / 27,4 | 27,2 + 0 | explicitní plochá kontrola |

## Bezpečná první oprava a izolované před/po

Nový `nastroje/roof_policy.py` vrací výslovně uvedenému typu střechy přednost před heuristikou počtu pater/třídy budovy, nezávisle na indexu dlaždice. Zachovává dosavadní prioritu téměř vodorovných DMP bodů; konflikt s atributem je nadále konflikt, ne nezávisle ověřená pravda. Ruční DOM/SAT upřesnění se aplikují až potom a mají vyšší prioritu. Neznámý typ se tímto patchem nedoplňuje.

Na Mlýnské stoce 367 (`4360399b-b4fe-442c-aebf-299791112d22`) má v datech OSM `w49532617@4` střechu `gabled` a pět podlaží. Původní výsledek byl plochá stěna 16,7 m. Izolované spuštění skutečných geometrických a výškových bloků `prep.py` po opravě dává **stěnu 12,2 m + sedlovou střechu 7,0 m = hřeben 19,2 m**. Celková výška tudíž vzroste, zatímco fasáda se sníží o 4,5 m. Procedurální pásy oken klesnou ze 6 na 5; to není ověřený počet skutečných podlaží.

Výška střechy zde stále používá původní geometrický fallback 40° s limitem 7 m. Obnovený atribut tedy opravuje konkrétní chybu datové cesty, ale ještě neposkytuje zaměřenou římsu. Všech ostatních 11 auditních případů zůstává tímto samotným patchem beze změny. Skutečná nová scéna po plném přepočtu přesně potvrdila uvedený výsledek i zachování obou plochých kontrol.

## Skutečný rozdíl celé mapy po přepočtu

Bylo spárováno všech **5 454 půdorysných částí / 5 420 Overture UUID** podle UUID, kanonického otisku půdorysu zaokrouhleného na centimetry a pořadí případné duplicity. Žádná část nepřibyla ani nezmizela a žádná nebyla spárována jen podle nejbližšího středu. Změnilo se **7 částí patřících 7 budovám**: šestkrát `flat → gabled`, jednou `flat → hipped`. U všech sedmi se změnila výška stěny a střechy, u šesti také celková výška. Terén a styl fasády zůstaly beze změny; tolerance porovnání výšek je 0,02 m.

| Budova / Overture UUID bez adresy | Stěna + střecha před (m) | Stěna + střecha po (m) | Nový typ |
|---|---:|---:|---|
| Na Mlýnské stoce 367 | 16,70 + 0 | 12,20 + 7,00 | sedlová |
| Lipenská 1970 | 18,50 + 0 | 14,76 + 5,54 | sedlová |
| Rabenštejnská věž | 16,60 + 0 | 13,73 + 2,87 | valbová |
| `93e1b1bc-b490-48b7-87f4-2a931665d8ac` | 8,80 + 0 | 8,14 + 2,16 | sedlová |
| Kostelní 1226 | 11,80 + 0 | 9,26 + 5,03 | sedlová |
| Fráni Šrámka 1219 | 16,70 + 0 | 12,97 + 5,54 | sedlová |
| `ea8c5440-6234-462c-9e79-1ccf9ad93784` | 12,10 + 0 | 10,83 + 3,27 | sedlová |

Jde o skutečný rozdíl exportovaných parametrů scény, nikoli odhad podle 16 dříve podezřelých atributů. Přesné před/po, všechny UUID a otisky vstupů jsou v `whole_scene_diff`; diagnostických 12 budov a kontrolní podmínky v `rendered_comparison`. Samostatné modely z 72 experimentálních běhů nebyly automaticky přeneseny do mapy. Původní scéna a web jsou archivované v městské revizi `revisions/baseline/`.

Capture celé scény trval 5,70 s wall time / 5,48 s CPU, s maximem 146,3 MB committed memory. Po capture měl projekt 4,89 GB a na C: zbývalo 68,35 GB. Úplné časy přepočtu a renderování mapy jsou v [map-rebuild.json](map-rebuild.json).

Finální kontrola interaktivní fit galerie ověřila 12 voleb a 6 modelových panelů, 7 konkrétních přepnutí včetně chybějící geometrie a odmítnutých špiček, nulové JS chyby, nulové síťové požadavky a mobilní zobrazení bez vodorovného přetečení. Odmítnuté modely mají přímo v kartě červený stav s důvodem. Kontrola trvala 4,20 s / 224,7 MB peak committed memory; dva výsledné screenshoty byly také vizuálně prohlédnuty.

## Ověření a výkon

- 11 regresních testů prošlo. Testy spouštějí přímo AST skutečného výběrového a výškového bloku `prep.py`, nikoli kopii jeho algoritmu.
- Pokryto: explicitní šikmá střecha + 5 pater; apartments/výška; explicitní flat; banka s neznámou střechou a spreadem 1,4 m; stávající konflikt Česká 17 (`gabled`, DMP 9,0/9,1 m); ruční DOM/SAT priorita; tile independence výslovného atributu; rozdělení římsa/hřeben.
- Syntetická regrese 3 + 2 rozděluje celkovou výšku 15 m na 9 m stěny a 6 m střechy. Nezaměňuje uživatelský odhad konkrétní budovy za ground truth.
- Baseline audit: 9,56 s wall time, 7,16 s CPU, 222,4 MB peak committed memory celého jobu.
- Izolovaný před/po výpočet včetně načtení kódu a kontrol: 12,79 s wall time, 10,33 s CPU, 70,1 MB peak committed memory. Samotných 11 testů trvalo přibližně 0,004 s; příprava a IO jsou měřeny zvlášť.
- Limity tohoto jobu: 1 GB RAM, nejméně 1 GB volné RAM; projekt nejvýše 20 GB, C: nejméně 25 GB volných. Po druhém běhu projekt 4,72 GB a C: 68,59 GB volných. Jde o okamžitý stav společného projektu.

Příkaz k opakování izolované kontroly: `.venv\Scripts\python.exe -X utf8 scripts\cb_roof_height_audit.py --phase policy`. Baseline bez `--phase policy` se má spouštět pouze nad archivovanou původní scénou, jinak by se přepsal referenční stav.

## Výsledky obou bodových zdrojů

Jde o samostatných 12 diagnostických půdorysů, nikoli rozšíření původního 30budovového benchmarku nebo 18 detailních kandidátů. Hodnotí se stejným způsobem: 20 % class6 bodů odloženo před rekonstrukcí, seed 20261115, šablony nejvýše 3500 fitovacích bodů a 4 výchozí orientace. Baseline a šablony mají 3 opakování; Roofer jednu dávku pro každý zdroj. Skóre je shoda s body stejného zdroje, nikoli nezávislé zaměření.

| Zdroj | Metoda | Vzniklé geometrie | Medián holdout RMSE | Součet samotného modelování |
|---|---|---:|---:|---:|
| DMP1G | baseline aproximace | 12/12 | 5,529 m | 0,207 s |
| DMP1G | šablony | 12/12 | 4,099 m | 2,854 s |
| DMP1G | Roofer | 12/12 | 6,114 m | 0,263 s |
| DMPOK | baseline aproximace | 12/12 | 1,820 m | 0,193 s |
| DMPOK | šablony | 12/12 | 1,309 m | 2,461 s |
| DMPOK | Roofer | 11/12 | 0,702 m | 7,461 s |

Časy baseline/šablon jsou součtem mediánů tří in-process opakování modelu včetně mesh. Roofer uvádí součet vlastních per-building časů; nezahrnují CLI IO. Proto se tabulka nesmí číst jako srovnání celých jobů. Celý fit worker včetně načítání, přípravy, holdout vyhodnocení a obou Roofer procesů trval **151,77 s wall / 137,55 s CPU / 266,19 MB peak commit**. Příprava výřezů z existujících LAZ trvala **261,03 s wall / 225,55 MB peak commit**; nic se znovu nestahovalo. DMP1G výřez má 27 905 bodů, DMPOK 1 171 116 bodů ve společných 20m obálkách. Body okolí jsou pro fitting každé budovy znovu omezeny přesně jejím půdorysem.

Offline UI kontrola: 12 voleb, 6 modelových panelů, nulové JS chyby, nulové externí requesty a bez mobilního horizontálního přetečení. Vizuálně byly zkontrolovány škola Baara a banka; barevné střešní roviny samy nepotvrzují stavební typ střechy.

### Párovaná interpretace

| ID / dům | DMP1G šablona / Roofer RMSE | DMPOK šablona / Roofer RMSE | Závěr |
|---|---:|---:|---|
| 01 Baara 1810 | 4,36 / 5,43 m | 3,38 / 0,89 m | Složené střechy a nižší přístavby; jediná šablona selhává. Roofer kandidát k dělení na části, ne důkaz jednoho „3 + 2“. |
| 02 Dr. Tůmy 1601 | 4,03 / 4,94 m | 0,25 / 0,21 m | Dobrá shoda jednoduché sedlové střechy v DMPOK. Šablona přibližně 14,94 m minimum střešních hran → 18,91 m hřeben. |
| 03 Na Sadech 1855 | 4,17 / 6,48 m | 0,79 / chybí | Sedlová šablona je kandidát; Roofer DMPOK skončil `no_geometry`. |
| 04 Pražská 1815 | 4,84 / 9,07 m | 4,54 / 5,77 m | Velký složený areál musí být rozdělen. Roofer DMPOK pouze LoD1.1 fallback, nikoli detailní střecha. |
| 05 Na Mlýnské stoce 367 | 3,53 / 5,16 m | 0,29 / 0,27 m | Nejlépe doložená první oprava. DMPOK gabled přibližně 12,77 → 19,43 m, konzistentní s explicitním OSM tagem. |
| 06 náměstí 67 | 3,95 / 4,72 m | 1,49 / 0,64 m | Roofer lépe zachycuje rozdílné části dlouhého půdorysu. Nevnucovat společnou římsu celému objektu. |
| 07 náměstí 50 | 3,09 / 14,09 m | 0,74 / 0,18 m | DMPOK Roofer dobrý kandidát; šablonové `barrel` není důkaz skutečné valené střechy. DMP1G špička 38,81 m odmítnuta. |
| 08 náměstí 128 | 2,91 / 5,54 m | 1,80 / 1,66 m | Oba zdroje podporují sedlový kandidát, ale složitější/nižší části a vyšší rezidua vyžadují kontrolu. |
| 09 náměstí 89 | 3,99 / 21,67 m | 3,97 / 0,77 m | DMPOK Roofer kandidát; audit potvrdil dvě degenerované stěny, všech 43 střešních ploch prošlo. DMP1G má části pod terénem a špičku 51,67 m: odmítnuto. |
| 10 náměstí 84 | 5,58 / 5,75 m | 1,13 / 0,89 m | Dosavadní šikmá střecha má rozumný výškový rozsah. Šablonový štítek sám nedokazuje, zda má být sedlová místo valbové. |
| 11 banka U Černé věže 69 | 6,57 / 7,42 m | 2,38 / 0,70 m | Fotografie potvrzuje ploché a odstupňované části. Jediný gabled fit odmítnout; Roofer `slanted` je široká kategorie, nikoli jedna sedlová střecha banky. |
| 12 Žižkova 1321 | 9,84 / 9,94 m | 0,86 / 0,67 m | Zachovat explicitní flat. DMPOK flat šablona potvrzuje hlavní vodorovnou střechu. |

U složeného modelu nelze minimum všech střešních vrcholů použít jako římsu hlavního uličního průčelí. U Baara je například v DMPOK Roofer minimum nižší části 2,62 m a maximum 20,13 m; to neznamená fasádu vysokou 2,62 m. Naproti tomu jednoduchý sedlový kandidát Dr. Tůmy má rozumně úzký rozsah 14,94–18,91 m. Ani tam není z bodů určen počet obydlených podkrovních pater.

U náměstí 89 byl samostatně prověřen surový CityJSON: dvě přeskočené plochy (indexy 146 a 202) jsou degenerované `WallSurface`; úspěšně prošlo 201 ostatních stěn a všech 43 `RoofSurface`. Nezměněný triangulátor byl spuštěn jen nad uloženými plochami, bez nové rekonstrukce. Výsledek a SHA surového souboru jsou v `fits.face_audits`.

### Proč je řídký zdroj v tomto vzorku problematický

Ověřená cesta klasifikace je `laspy chunk.classification` → přesná kopie do NPZ → výběr `class == 6` uvnitř původního půdorysu. Reader třídy nevytváří, synteticky nedoplňuje ani nepřeklasifikuje; původní downloader pouze stáhl ZIP a rozbalil LAZ. Použitý laspy je standardní instalace v `.venv/Lib/site-packages`. [ASPRS LAS 1.2](https://www.asprs.org/a/society/committees/lidar/Downloads/ASPRS_LAS%201_2.pdf) definuje class6 jako **Building**, nikoli ověřenou střechu.

V uloženém řídkém cropu se nacházejí class6 body do 2 m nad mediánem okolního terénu: Baara 49/602 (8,1 %), banka 101/700 (14,4 %), Žižkova 59/446 (13,2 %). U Baara a Žižkovy je medián vzdálenosti těchto bodů od hranice půdorysu asi 0,26/0,30 m; u banky 1,11 m. U Pražské 1815 je nízko 179/2380 bodů a leží i hluboko uvnitř velkého areálu. Příčinou může být fasáda, podloubí, menší výškové části, nesoulad půdorysu či epoch nebo zdrojová klasifikace. Tento audit jednotlivé příčiny nezaměňuje za prokázané vysvětlení.

Žádné body nebyly dodatečně odstraněny a publikované holdout RMSE nebylo nahrazeno příznivějším filtrovaným skóre. Před dalším nasazením je potřeba samostatně validovat výběr bodů střechy a rozdělení složených půdorysů. Příklady přímého geometrického selhání Rooferu na DMP1G: Pražská minimum −8,02 m nad ground; náměstí 89 minimum −10,04 m a maximum 51,67 m; náměstí 50 maximum 38,81 m. `audit_quality` tyto podezřelé geometrie označuje konzervativním testem pod terénem / nad P99 zdroje + 3 m. Tato hranice není kalibrovaná pravděpodobnost správnosti; původní geometrie zůstává v galerii viditelná pro kontrolu.

Terén scény (`scene.g + href`) je navíc v auditním vzorku numericky o 2,14–6,82 m výše než místní class2 medián DMP1G. Jde o jiný zdroj terénu (Terrarium), ne o zde změřenou korekci vertikálního datumu. Vysoké tělo budovy v mapě tím samo není vysvětleno: renderer k vlastnímu terénu přičítá relativní výšku. Při budoucím přenosu Bpv mesh do scény je ale nutné správně oddělit absolutní souřadnice a místní výšku nad terénem.

**Rozhodnutí:** do základní mapy nyní patří konzervativní oprava prokázaného ztraceného atributu. Neznámé střechy zůstávají oddělenými kandidáty k rozhodnutí; Dr. Tůmy a Na Mlýnské stoce jsou vhodné pro další jednoduché fity, historické areály potřebují části a kontrolu ulic. Tato diagnostika nemění původních 30 pilotních ID ani 18 kandidátů detailní digitalizace.

## Zdroje a meze ověření

- [Městská encyklopedie: náměstí Přemysla Otakara II.](https://www.encyklopedie.c-budejovice.cz/clanek/namesti-premysla-otakara-ii): historická proměna střešní krajiny a moderní banka v rohu. Není zdrojem přesných výšek všech domů.
- [NPÚ: Českobudějovická záložna](https://pamatkovykatalog.cz/ceskobudejovicka-zalozna-19173283) a [NPÚ, Moderní Budějce, 2024](https://www.npu.cz/uop/ceske-budejovice/vzdelavani/moderni-budejce/qr_kody/1.-konec-starych-casu.pdf): identita banky u Černé věže a dokumentace moderní architektury. U adresy 69 proto uchováváme plochou kontrolu.
- Fotografie banky na straně 4 posledního odkazu (Jakub Drozda, 2023) byla vizuálně zkontrolována: potvrzuje horizontální atiky a odstupňované horní části, nikoli jedinou sedlovou střechu. Slouží jako reference; není použita jako textura ani převzata do veřejné galerie.
- [Primární web VOŠ/SPŠ automobilní a technické](https://spsautocb.cz/kontakty/budovy-skoly/) přiřazuje fotografii k J. Š. Baara 1810/2. Na uliční fasádě jsou vidět tři velké řady oken nad nižším soklem; střecha je fotografickým výřezem téměř zakrytá. To podporuje potřebu kontroly fasády, ale nepotvrzuje přesný počet podkrovních podlaží ani tvar celé střechy. Datum pořízení není uvedeno.
- [Provozovatel pasáže Mariánská](https://www.marianska.org/o-pasazi): historická budova bývalých kasáren navazuje na novější parkovací objekt; střecha přístavby slouží k parkování. Složený areál nelze bez prostorové kontroly nahradit jedinou sedlovou střechou.

Samotný rozdíl P90 − medián neodliší šikmou střechu od více různě vysokých plochých částí. Banka má spread 1,4 m stejně jako některé historické domy. Dobré RMSE vůči absolutním výškám Bpv navíc nepotvrzuje správně zvolenou výšku terénu a fasády. Následující fity musí porovnat ground / eave / ridge odděleně, rozdělení půdorysu a kontrolní fotografie. Zatím neprohlašujeme konkrétní domy kolem Mariánského náměstí za ověřené „3 + 2“.

[OSM `building:levels`](https://wiki.openstreetmap.org/wiki/Key:building:levels) definuje nadzemní podlaží mimo střechu; [podkrovní podlaží](https://wiki.openstreetmap.org/wiki/Key:roof:levels) mají samostatný tag. [Overture `num_floors`](https://docs.overturemaps.org/schema/reference/buildings/building/) má obecnější popis nadzemních podlaží. Pět ve zdroji proto nelze automaticky převést na „3 + 2“. Všech 12 auditních budov má v Overture `roof_height`, `roof_direction` a `roof_orientation` prázdné; samostatný sloupec pro `roof:levels` tato vstupní tabulka neobsahuje.

Přímo z OSM API byly načteny přesné verze citované v Overture: [Baara 1810, way 52528808 v2](https://api.openstreetmap.org/api/0.6/way/52528808/2.json), [Dr. Tůmy 1601, way 52528612 v2](https://api.openstreetmap.org/api/0.6/way/52528612/2.json) a [Na Mlýnské stoce 367, way 49532617 v4](https://api.openstreetmap.org/api/0.6/way/49532617/4.json). Všechny uvádějí `building:levels=5`, `source=cuzk:ruian`, žádná `roof:levels`; poslední také `roof:shape=gabled` a `roof:material=roof_tiles`. Řetězec chyby je tedy doložený až k původnímu tagu: sedlová střecha se neztratila při importu do Overture, přepsal ji až přípravný renderer. Tyto tagy samy o sobě nejsou geodetické ověření pěti podlaží.
