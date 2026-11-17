# Nástavby nad plochou střechou — běh 2026-11-17

Algoritmus: modular-roofs-4.8.1. Nová sada: [HTML porovnání](http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-flat-protrusions-v481-44/report.html). Předchozí sada: roof-flat-majority-v472-44. Vlevo předchozí model, vpravo nový; žádný původní report se nepřepisoval.

## Nastavení

Vypínatelný modul flat_protrusions běží až po rozhodnutí o jednom plochém základu. Vybírá souvislé zvýšené buňky nad 2 m, s doloženou plochou alespoň 1 m², nejméně 6 buňkami a efektivní šířkou alespoň 0,6 m. Používá mediány buněk 0,35 m, výšku jejich 90. percentilu vůči základní rovině a jeden plochý vršek na komponentu. Obrysy zjednodušuje tolerancí 0,25 m, připouští nejvýše 15 % doplněné plochy; práh 1 m² ověřuje na původní obsazené ploše. Budova a její dvory zůstávají nezměněné. Podrobnosti: [ROOF_FLAT_PROTRUSIONS.md](ROOF_FLAT_PROTRUSIONS.md).

## Výsledek automatické dávky

| Adresa | Doplněné objemy | Převýšení nad základní střechou |
|---|---:|---|
| Puklicova 1032/35 | 2 | 2.24 m, 2.14 m |
| Široká 432/11 | 1 | 4.31 m |
| Pekárenská 2287/34 | 4 | 2.29 m, 2.26 m, 2.33 m, 2.39 m |
| Pekárenská 1060/25 | 1 | 2.05 m |

Celkem 44/44 budov, 8 zvýšených objemů na 4 budovách. Všech 44 sestav je podle numerické kontroly platných a uzavřených, bez geometrického fallbacku. Všech 35 modelů se šikmou střechou má přesně stejnou geometrii jako předchozí verze. Všech 44 ID je spárovaných pro porovnání.

| Měření | Hodnota |
|---|---:|
| Výpočet všech střech | 69.840 s |
| Samotný nový modul včetně sestavení geometrie | 1.329 s |
| Celá dávka včetně načítání, reportu a balení vstupů | 135.064 s |
| Ochranný proces včetně startu a kontrol | 157.064 s |
| Nejvyšší přidělená paměť stromu procesu | 331.9 MB |
| Volné místo na C: po dokončení | 63.43 GB |
| Velikost projektu po dokončení | 5.35 GB |

Výše jsou časy jednoho běhu na aktuálně zatíženém počítači, nikoli izolovaný benchmark proti předchozí verzi. 48 numerických regresních testů prošlo (14,218 s), kontrola syntaxe prohlížeče prošla, report odpovídá HTTP 200. Proces běžel lokálně s omezením vláken, paměti a priority. Modely ani body nebyly opticky posuzovány AI.

## Diagnostika a reprodukce

V novém výstupu jsou results.json, comparison.json, config.json, run.json, verification.json, přesné výřezy bodů, vstupní záznamy a RUN.txt. Metadata uvádějí základní výšku, počet nástaveb, relativní i absolutní výšky, doloženou a zjednodušenou plochu, zamítnuté kandidáty, úpravy obrysů a samostatný čas modulu. Výběrové skóre původního plochého kandidáta popisuje volbu základní střechy; nepřepočítává se jako nové skóre celé sestavy s nástavbami.

První vývojový pokus 4.8 detekoval stejné počty nástaveb, ale všechny čtyři sestavy odmítla kontrola neplatných hran. Zůstaly bezpečně původní ploché objemy. Příčinou byly bodové dotyky po oříznutí zjednodušeného obrysu zpět rastrem. Verze 4.8.1 tento krok odstranila, zavedla omezené doplnění plochy a lokální rozpojení bodových dotyků otvorů. Oprava je obecná, bez seznamu výjimek podle adres.

Jde o doplnění zvýšených objemů; nerozlišuje věže od výtahů, neobnovuje nižší terasy a neřeší soustavy střech křídel L/U/O. Ty zůstávají samostatným úkolem. Produkční mapové dlaždice tento experiment nepřegenerovává.
