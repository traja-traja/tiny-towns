# Vyšší věrnost, výstupky a hlavní objemy střech

Dokončeno: 6 objektů / 7 půdorysů, 14 variant, 98 záznamů. Z toho 70 nových výsledků a 28 převzatých referencí; 3 nové pokusy rozkladu objemů skončily bez modelu a jsou výslovně označené.

Vstupem je husté DMPOK: mřížka 20 cm, přibližně 25 bodů/m². Stejné body i rozdělení 80/20 jako v minulém kole. Rozestup bodů není výšková přesnost.

Vyšší věrnost není univerzální zlepšení. Největší přínos má u severní části Budvaru zvýšení limitů detekce. U Masných krámů a sportovní haly faktor 0,99 přidává složitost s malým zlepšením chyby.

Oddělení dvou výstupků kostela a doplnění střechy se podařilo. Zjednodušené navrácení prvků se zatím nepodařilo: kontrola odmítla šablony a zachovala původní komponenty. Bezvýstupková varianta je jen diagnostika.

Dělení podle výškových skoků je užitečné pro stupňovité haly, ale samo nerozpozná všechna křídla. U kostela selhala geometrická sestava; u některých historických domů je výsledek příliš hrubý.

Nové výsledky jsou pouze v této galerii. Produkční mapa nebyla změněna. Další krok: chráněné charakteristické prvky + slučování základních ploch; pravidla ověřit na dalších budovách.

## Závěry podle budovy

### Budvar aréna – severní zdrojový půdorys

Největší přínos: Roofer 0,95 s vyššími limity vytvořil 8 nativních střešních ploch místo plochého náhradního objemu. RMSE kleslo z 0,912 na 0,226 m. Kandidát pro další zjednodušení. Samotné 0,95 či 0,99 se starými limity náhradní objem nevyřešilo.

### Budvar aréna – jižní zdrojový půdorys

Vyšší věrnost nepřináší jednoznačně lepší kompromis. Faktor 0,95 zvýšil nativní členění z 25 na 32 ploch, RMSE se změnilo jen z 0,553 na 0,550 m. Dělení objemů 0,75 m skončilo chybou geometrie, varianta 1,50 m je příliš hrubá (RMSE 1,362 m).

### Sportovní hala – Stromovka 1216/12

0,99 má 27 nativních ploch místo původních 11, ale RMSE zůstává přibližně 0,71 m. Vyšší věrnost zde nepomáhá zjednodušení. Dělení na 6 hlavních objemů při prahu 0,75 m zjednoduší plochy při RMSE 0,722 m; stojí za další doladění. Z předchozího kola zůstává zajímavá i varianta 0,35 / epsilon 0,50 m (RMSE 0,566 m).

### Kostel svatého Václava

Oddělení výstupků funguje jako mezikrok: měřítko 1,5 m vybralo dva prvky, pod nimi doplnilo střechu a základ zjednodušilo na 8 souvislých rovin. Jednoduché náhrady obou prvků neprošly kontrolou, proto se vrátila původní geometrie. Přísnější detekce 0,15 m snižuje celkové RMSE na 0,664 m, ale mění špičku věžičky. Nižší globální chyba tedy sama nestačí. Rozklad hlavních objemů zde skončil nepodporovanou geometrií.

### Wortnerův dům – U Černé věže 343/22

Přísnější detekce zlepší RMSE z 0,419 na 0,390 m, ale přidává členění kolem výstupku a nižší střechy. Pro přehledný model je vhodnější navázat na slučování hlavních rovin. Jediná sedlová šablona ztrácí rozdíl částí (RMSE 0,753 m).

### Masné krámy – Krajinská 29/13

0,99 zvýší počet nativních ploch ze 14 na 39; RMSE se zlepší jen z 0,377 na 0,351 m. V náhledu výrazně přibývají drobné zlomy. Jedna sedlová šablona je přehledná, ale zahodí charakteristické prvky a zhorší RMSE na 0,677 m. Doporučení: jednodušší hlavní střecha s chráněnými prvky, nikoli globálně 0,99.

### Krajinská 43/8 – kandidát podloubí

0,95 / epsilon 0,15 m zlepší RMSE z 0,749 na 0,603 m a P95 z 0,440 na 0,319 m, ale nativních ploch je 23 místo 15. Je to kandidát na následné slučování ploch. Dělení pouze podle výškových skoků neoddělí vhodně hlavní a nízké křídlo; RMSE 1,103 m je zhoršení.

## Stejné vstupy pro férové porovnání

DMPOK ČÚZK, listy CBUD22 a CBUD23, souřadnice EPSG:5514, výšky Bpv. Půdorysy byly převzaté ze zmrazeného výběru a zůstávají stejné. Střecha se vybírá z klasifikace 6 uvnitř půdorysu; kontrolní body nejsou použity pro fitování. Žádné nové stahování ani dopočítávání umělých bodů.

| Půdorys | DMP 1G bodů | Bodů/m² | DMPOK bodů | Bodů/m² |
|---|---:|---:|---:|---:|
| Budvar aréna – severní zdrojový půdorys | 6367 | 1.02 | 156620 | 25.00 |
| Budvar aréna – jižní zdrojový půdorys | 4918 | 1.37 | 89836 | 24.96 |
| Sportovní hala – Stromovka 1216/12 | 4548 | 0.99 | 114102 | 24.94 |
| Kostel svatého Václava | 519 | 1.00 | 12895 | 24.84 |
| Wortnerův dům – U Černé věže 343/22 | 189 | 0.97 | 4873 | 25.00 |
| Masné krámy – Krajinská 29/13 | 498 | 0.99 | 12525 | 24.96 |
| Krajinská 43/8 – kandidát podloubí | 260 | 0.98 | 6619 | 24.87 |

Hustota před oddělením kontrolních bodů. Rozestup 20 cm není přesnost výšky; data z obrazové korelace mohou obsahovat šum a chybné hrany. Datum souboru není automaticky datum snímkování.

## Číselné srovnání nové věrnosti

Buňka: RMSE v metrech / počet nativních střešních ploch. Počet souvislých téměř koplanárních oblastí je jiná, přísnější metrika v HTML.

| Půdorys | 0,888 původní | 0,95 | 0,99 | 0,95 + ε 0,15 m | 0,95 + vyšší limity |
|---|---:|---:|---:|---:|---:|
| Budvar aréna – severní zdrojový půdorys | 0.912 / 1 (náhradní) | 0.912 / 1 (náhradní) | 0.912 / 1 (náhradní) | 0.912 / 1 (náhradní) | 0.226 / 8 |
| Budvar aréna – jižní zdrojový půdorys | 0.553 / 25 | 0.550 / 32 | 0.572 / 39 | 0.644 / 48 | 0.550 / 32 |
| Sportovní hala – Stromovka 1216/12 | 0.709 / 11 | 0.709 / 17 | 0.707 / 27 | 1.008 / 34 | 0.656 / 16 |
| Kostel svatého Václava | 0.757 / 13 | 0.758 / 16 | 0.758 / 19 | 0.664 / 17 | 0.758 / 16 |
| Wortnerův dům – U Černé věže 343/22 | 0.419 / 7 | 0.398 / 9 | 0.407 / 10 | 0.390 / 15 | 0.397 / 9 |
| Masné krámy – Krajinská 29/13 | 0.377 / 14 | 0.359 / 21 | 0.351 / 39 | 0.418 / 30 | 0.359 / 21 |
| Krajinská 43/8 – kandidát podloubí | 0.749 / 15 | 0.722 / 15 | 0.716 / 19 | 0.603 / 23 | 0.722 / 15 |

## Výkon

Každý nový nativní profil běžel dvakrát na sedmi půdorysech. Níže čas celé dávky CLI; karty mají interní čas budovy. Výsledná geometrie je vždy z prvního opakování, nikoli vybraná nejlepší z opakování.

| Profil | Opakování | Medián dávky (s) | Rozsah (s) | Nejvyšší commit procesu (MB) |
|---|---:|---:|---:|---:|
| Roofer · 0,95 | 2 | 57.66 | 54.89–60.44 | 94.2 |
| Roofer · 0,99 | 2 | 49.13 | 39.63–58.63 | 95.0 |
| Roofer · 0,95 / roviny 0,15 m | 2 | 46.55 | 45.93–47.16 | 99.3 |
| Roofer · 0,95 / vyšší limity | 2 | 51.43 | 49.98–52.88 | 125.3 |

| Celý pracovní krok včetně režie | Čas (s) | CPU (s) | Peak commit stromu (MB) |
|---|---:|---:|---:|
| 4 profily Rooferu × 2 | 635.90 | 837.67 | 194.4 |
| 2 měřítka výstupků × 7 půdorysů | 62.24 | 51.20 | 199.6 |
| 2 prahy rozkladu objemů × 7 půdorysů | 39.78 | 31.31 | 157.4 |
| Společné vyhodnocení 98 záznamů | 34.36 | 29.16 | 233.3 |

Tabulky popisují vnořené rozsahy; nesčítejte časy nativních dávek znovu k celému kroku. Párové výstupy odstranění/navrácení mají společný čas, započítává se jednou. Původní Roofer se přičítá k dodatečné extrakci či rozkladu. Dvě opakování na zatíženém počítači nestačí k obecnému tvrzení, že určitý faktor je rychlejší.

## Co se nepodařilo a co ověřit dál

- Rozklad objemů: Budvar jih při 0,75 m má nejednoznačné hranice; kostel v obou variantách nepodporovaný nebo svislý zdrojový střešní trojúhelník. Tyto tři výsledky nemají model.
- Žádná jednoduchá náhrada izolovaných prvků kostela neprošla předem určenou kontrolou tvaru a zachování výšky. Počty 2 a 1 jsou přijaté masky, nikoli úspěšně zjednodušené věžičky.
- Globální RMSE může odměnit i odstranění chybně zachyceného drobného prvku. U extrakce je proto chyba uvnitř masky a mimo ni oddělená; různé masky nejsou totožné hodnoticí podmnožiny.
- Slučování ploch nemusí snížit počet trojúhelníků: nové napojení a vyplnění vyžaduje triangulaci. Členění rovin, silueta a síť jsou odlišná kritéria.
- Další řízený test: speciální jednoduché tvary věžiček (jehlan, kužel, helmice), případně zjednodušení oddělené původní komponenty se zachováním vrcholu. Zde nejsou vykazovány jako provedené.
- Dělení křídel musí zahrnout půdorys a orientaci ploch; samotný svislý skok spojité střechy nerozdělí.
- Doporučení vznikla pro tento malý výběr. Pro univerzální pravidlo je nutné nové nezávislé kolo budov. Stejné mračno rozdělené 80/20 není nezávislé geodetické ověření.

## Kontroly a reprodukce

21 cílených testů algoritmů prošlo. Galerie je offline, používá skutečné měřené sítě, společnou kameru a měřítko. Hloubkový test náhledu řeší pořadí zakrytí stěn a střech, bez úprav geometrie. Stav prohlížečových kontrol je v `.work/cb-roof-components/qa/gallery-ui.json` a konečné kontrole `gallery-final-smoke.json`.

16 zachovaných vstupních souborů ověřeno před porovnáním. Každý pracovní výpočet má uložené vstupy, příkaz a otisk implementace. První přerušený pokus je zvlášť v `.work/cb-roof-components/attempt-1-interrupted/`; není zamíchaný do čistého porovnání.

Limity: sériové úlohy, 2 CPU, nejvýše 2 GB pro výpočet, projekt do 20 GB, zastavení pod 25 GB volného disku C:. Ochrana proti uspání je dočasná.

[Otevřít HTML](report.html) · [Úplná data](results.json) · [Protokol](protocol.json) · [Předchozí kolo](../roof-simplification/report.html)

Konečná kontrola galerie: všech 6 skupin, 14 variant, 4 kamery, 7 řádků původu bodů, mobilní šířka 390 px, 0 chyb JavaScriptu a 0 internetových požadavků. Prošel také cílený test zakrytí ploch nezávislého na pořadí trojúhelníků. Produkční vstupy: 16/16 kontrolních součtů beze změny.
