# České Budějovice — výběr pro další pilot střech

Stav: pouze výběr kandidátů a podkladů. Základní preview se tím nemění. Následné experimenty začnou až po jeho dokončení.

Výběr obsahuje **30 původních půdorysů**, 23 skupin a **18 kandidátů** pro podrobnější práci (limit 20). Všech 30 půdorysů je celých uvnitř skutečné dlaždice centra 2,3 × 2,3 km.

Priorita 1: hlavní dominanty, haly, podloubí a fasádní pilot. Priorita 2: doplňkové výrazné historické stavby. Priorita 3: běžné kontrolní případy; podrobná rekonstrukce zatím není navržena.

| ID | Objekt | Detail | Priorita | Skupina |
|---|---|---|---:|---|
| CB-ROOF-01 | Budvar aréna – severní zdrojový půdorys | kandidát | 1 | budvar-arena |
| CB-ROOF-02 | Budvar aréna – jižní zdrojový půdorys | kandidát | 1 | budvar-arena |
| CB-ROOF-03 | Plavecký stadion – Sokolský ostrov 402/4 | kandidát | 1 | samostatný |
| CB-ROOF-04 | Sportovní hala – Stromovka 1216/12 | kandidát | 1 | samostatný |
| CB-ROOF-05 | Černá věž | kandidát | 1 | samostatný |
| CB-ROOF-06 | Radnice – náměstí Přemysla Otakara II. 1/1 | kandidát | 1 | townhall |
| CB-ROOF-07 | Katedrála svatého Mikuláše | kandidát | 1 | samostatný |
| CB-ROOF-08 | Kostel Obětování Panny Marie | kandidát | 1 | dominikansky-klaster |
| CB-ROOF-09 | Kostel svatého Václava | kandidát | 2 | samostatný |
| CB-ROOF-10 | Wortnerův dům – U Černé věže 343/22 | kandidát | 2 | samostatný |
| CB-ROOF-11 | Palác Včela – Karla IV. 92/1 | kandidát | 1 | samostatný |
| CB-ROOF-12 | Masné krámy – Krajinská 29/13 | kandidát | 1 | samostatný |
| CB-ROOF-13 | Puklicův dům – Krajinská 36/2 | kandidát | 1 | samostatný |
| CB-ROOF-14 | Rabenštejnská věž – samostatný půdorys | kandidát | 2 | rabenstejnska-complex |
| CB-ROOF-15 | Železná panna – Zátkovo nábřeží 461/15 | kandidát | 2 | samostatný |
| CB-ROOF-16 | Krajinská 43/8 – kandidát podloubí | kandidát | 1 | krajinska-arcades-43-45 |
| CB-ROOF-17 | Krajinská 44/10 – kandidát podloubí | kandidát | 1 | krajinska-arcades-43-45 |
| CB-ROOF-18 | Krajinská 45/12 – kandidát podloubí | kandidát | 1 | krajinska-arcades-43-45 |
| CB-ROOF-19 | Husova třída čp. 1839 | kontrola | 3 | husova-1838-1839 |
| CB-ROOF-20 | Husova třída čp. 1838 | kontrola | 3 | husova-1838-1839 |
| CB-ROOF-21 | Panská čp. 168 | kontrola | 3 | panska-168-169 |
| CB-ROOF-22 | Panská čp. 169 | kontrola | 3 | panska-168-169 |
| CB-ROOF-23 | Česká čp. 150 | kontrola | 3 | samostatný |
| CB-ROOF-24 | Česká čp. 143 | kontrola | 3 | ceska-143-144 |
| CB-ROOF-25 | Česká čp. 144 | kontrola | 3 | ceska-143-144 |
| CB-ROOF-26 | Na Mlýnské stoce čp. 385 | kontrola | 3 | samostatný |
| CB-ROOF-27 | Žižkova třída čp. 1321 | kontrola | 3 | samostatný |
| CB-ROOF-28 | Lidická třída čp. 178 | kontrola | 3 | samostatný |
| CB-ROOF-29 | Náměstí Přemysla Otakara II. čp. 67 | kontrola | 3 | square-67-68 |
| CB-ROOF-30 | Náměstí Přemysla Otakara II. čp. 68 | kontrola | 3 | square-67-68 |

Každá GeoJSON Feature zachovává UUID a přesnou geometrii z Overture, původní zdroje/licence, adresní body, metrický bbox EPSG:5514, jistotu identity a konkrétní navržené testy. Číslo zdrojové budovy je v `properties.building_id` i `Feature.id`.

## Reprodukce a měření

```powershell
.venv\Scripts\python.exe -X utf8 scripts\select_cb_roof_pilot.py
.venv\Scripts\python.exe -X utf8 scripts\select_cb_roof_pilot.py --check
```

Poslední sestavení manifestu: 72.284 s. Tento čas zahrnuje lokální načtení, spojení vrstev a kontroly; nezahrnuje rešerši ani budoucí výpočet střech. Zpracované body mraků: 0; stažení: 0; rendery: 0.

`--check` kontroluje obsah proti lokálním vstupům; ignoruje pouze čas a datum samotného spuštění. SHA-256 a velikosti všech pěti vstupních GeoParquetů, konfigurace dlaždice a existujícího DMP manifestu jsou v `source_inputs`. Skript nepřipravuje holdout ani trénovací mrak.

## Další podklady

Pro DMP1G už existují listy základního preview. Nejprve se vyberou a oříznou potřebné části, bez opakovaného stahování. DMPOK je pouze návrh dalšího zdroje; dostupnost, datum a listy musí ověřit samostatný přípravný krok. Samotný výběr nepřebírá stejné názvy listů automaticky. Metadata a ATOM odkazy jsou v `next_source_plan`.

Fasádní rešerše: `../experiments/facades/`. Rešerše podloubí: `../experiments/arcades/`. Stejná UUID propojují výběr a oba experimenty. U tří domů Krajinská 43–45 není chybějící tag dopravní sítě důkazem nepřítomnosti podloubí. Rozměry otvorů se teprve ověří.

## Omezení

- Jde o výběr kandidátů; žádná podrobná rekonstrukce, oprava základní mapy ani potvrzení geometrie tím nevzniká.
- 30 půdorysů není 30 nezávislých architektonických celků. Společné skupiny evidují arénu, domovní řady a navazující části.
- 18 detailních kandidátů je pod maximem 20; dalších 12 půdorysů slouží ke kontrolnímu srovnání jednoduchých modelů.
- Adresní number v místní ČÚZK vrstvě je číslo popisné; orientační čísla v názvech pocházejí z citovaných primárních zdrojů nebo samostatné rešerše podloubí.
- Typ, sklon, hřeben, vikýře, římsy, barva fasády ani výška průchodu nebyly tímto výběrem nově vypočítány.
- Překryv tagované dopravní linie a budovy není důkaz rozměrů otvoru; chybějící tag neznamená chybějící podloubí.
- Účelový výběr geometrických případů není statisticky reprezentativní vzorek města.

Rabenštejnská věž je vybrána jako samostatný pojmenovaný polygon. Adresa Panská 207/4 z turistického webu patří sousednímu objektu kulturního komplexu; nespojuje se násilně s věží. POI Masných krámů je mimo půdorys; přiřazení používá adresu. U Puklicova domu primární městský plán doložil čp.36/2, přímá karta NPÚ měla při rešerši chybu serveru.

## Primární zdroje identity

- **arena_operator** — [Kulturní a sportovní zařízení města České Budějovice](https://www.kszcb.cz/kudy-a-jak-na-stadion): Identita Budvar arény a adresa F. A. Gerstnera 7/8.
- **arena_two_halls** — [Kulturní a sportovní zařízení města České Budějovice](https://www.kszcb.cz/o-stadionu-1767963403): Areál má dvě kryté ledové haly; jejich označení I/II zde není přiřazeno k polygonům.
- **pool_operator** — [Kulturní a sportovní zařízení města České Budějovice](https://www.kszcb.cz/kudy-a-jak-do-bazenu): Plavecký stadion na Sokolském ostrově, orientační číslo 4.
- **hall_operator** — [Kulturní a sportovní zařízení města České Budějovice](https://www.kszcb.cz/kudy-a-jak-do-haly): Sportovní hala, Stromovka, orientační číslo 12.
- **black_tower** — [Oficiální turistický portál města](https://www.budejce.cz/aktivity/2-cerna-vez): Černá věž, U Černé věže 70/2.
- **townhall** — [Statutární město České Budějovice](https://www.c-budejovice.cz/sportovni-zarizeni): Kontaktní adresa magistrátu nám. Přemysla Otakara II. 1/1; přiřazení potvrzuje místní adresní bod a POI.
- **cathedral** — [Oficiální turistický portál města](https://www.budejce.cz/aktivity/7-katedrala-svateho-mikulase): Katedrála sv. Mikuláše v ulici U Černé věže.
- **monastery_church** — [Oficiální turistický portál města](https://www.budejce.cz/aktivity/14-kostel-obetovani-panny-marie): Kostel Obětování Panny Marie na Piaristickém náměstí a sousedící klášterní komplex.
- **churches** — [Statutární město České Budějovice](https://www.c-budejovice.cz/prehled-kostelu-bohosluzeb): Kostel sv. Václava v Kostelní ulici; doplňková lokalizace centrálních kostelů.
- **wortner** — [Alšova jihočeská galerie](https://www.ajg.cz/pro-navstevniky.html): Wortnerův dům na adrese U Černé věže 343/22.
- **vcela** — [Oficiální turistický portál města](https://budejce.cz/aktivity/12-palac-vcela): Palác Včela, Karla IV. 92/1, nároží náměstí.
- **masne** — [Provozovatel restaurace Masné krámy](https://www.masne-kramy.cz/): Masné krámy v Krajinské, orientační číslo 13; čp. 29 z místního adresního bodu.
- **puklic_plan** — [Statutární město České Budějovice](https://data.c-budejovice.cz/Oupa/VEREJNE_VYHLASKY/Z_96_az_99_vcetne_UZ/UZ_UPnM_CB_poZm99_UredniDeska_OUP__2023-06-15/TEXTY/Kryci%20listy/1_vnitrni%20mesto/1.1.1_Historicke_jadro_2023-06.pdf): Městský dům Puklicův čp. 36/2, Krajinská; identifikace, nikoli přebírání plánových regulativů. Text dostupný při prvním otevření; opakovaný find vrátil 404. Identita současně podporována indexovaným popisem NPÚ.
- **puklic_npu** — [Národní památkový ústav](https://pamatkovykatalog.cz/mestsky-dum-19152358): Indexovaný odborný popis objekt označuje jako Puklicův dům. Vyhledávací index dostupný; přímé otevření vrátilo 503. Nejde o úplné přečtení památkové karty.
- **rabenstejn** — [Oficiální turistický portál města](https://www.budejce.cz/aktivity/33-rabenstejnska-vez): Rabenštejnská věž a navazující kulturní centrum; adresa Panská 207/4 se vztahuje ke komplexu, nikoli automaticky k samostatnému polygonu věže.
- **zelezna** — [Oficiální turistický portál města](https://www.budejce.cz/aktivity/17-zelezna-panna): Železná panna, Zátkovo nábřeží 461/15.
- **krajinska43_photo** — [Czeva / původní fotografie na Wikimedia Commons](https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_8_(01).jpg): Identita domu Krajinská 43/8 a historická fotografie průčelí; podrobné ověření v samostatné rešerši podloubí. Zdroj prohlédl agent rešerše podloubí; zde opakované otevření selhalo. Fotografie je skládané panorama, nikoli metrický podklad.
- **krajinska44_photo** — [Czeva / původní fotografie na Wikimedia Commons](https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_10.jpg): Popis původní fotografie výslovně uvádí Krajinská 44/10; historické průčelí a podloubí řeší samostatná rešerše. Skládané panorama; identita potvrzena metadaty fotografie, rozměry se z něj zde neměří.
- **krajinska45_photo** — [Czeva / původní fotografie na Wikimedia Commons](https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_12_(01).jpg): Identita domu Krajinská 45/12 a historická fotografie průčelí; podrobné ověření v samostatné rešerši podloubí. Zdroj prohlédl agent rešerše podloubí; zde opakované otevření selhalo. Fotografie je skládané panorama, nikoli metrický podklad.
