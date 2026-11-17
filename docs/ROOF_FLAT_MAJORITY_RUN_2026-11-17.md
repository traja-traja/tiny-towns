# Výsledek dávky 4.7.2 — 44 budov

Datum: 2026-11-17. Report: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-flat-majority-v472-44/report.html

Všechny tři podmínky platí současně: každá započítaná souvislá vodorovná část alespoň 5 % půdorysu, největší alespoň 20 %, součet alespoň 55 %. Výsledek má jednu vodorovnou střechu ve výšce největší části; výškové úrovně ani nástavby se nemodelují. Půdorys včetně otvorů se zachovává.

- 44/44 modelů dokončeno; všech 44 sítí numericky platných a uzavřených.
- 43 původních modelů má porovnání vedle nové verze; nám. Přemysla Otakara II. 1/1 je nový, bez předchozí varianty.
- 33 cílených testů prošlo; syntaxe prohlížeče platná. Zdrojové SHA256 odpovídají souborům uvedeným v run.json.
- Čas výpočtu střech: 43.211 s; medián 0.840 s; maximum 2.498 s.
- Dávka včetně reportu: 70.748 s; chráněný proces včetně startu: 80.359 s.
- Vrchol přidělené paměti celého procesního stromu: 391.9 MiB. Projekt 5.29 GB, volné místo C: 63.79 GB.
- Výpočty místním Pythonem nad uloženými výřezy DMPOK. Nová adresa připravena automaticky z existujících podkladů. Žádné optické či AI hodnocení modelů.

| Zjednodušený dům | Součet ploch | Největší část |
| --- | --- | --- |
| Puklicova 1032/35 | 71.7 % | 71.7 % |
| Jiráskovo nábř. 2185/13 | 60.8 % | 60.8 % |
| Litvínovická 58 | 63.5 % | 63.5 % |
| Široká 432/11 | 66.0 % | 48.0 % |
| Pekárenská 2287/34 | 66.7 % | 66.7 % |
| Fráni Šrámka 2609 | 64.5 % | 51.0 % |
| Na Dlouhé louce 1847 | 78.5 % | 78.5 % |
| J. Plachty 2059/5 | 71.4 % | 71.4 % |
| Pekárenská 1060/25 | 73.6 % | 73.6 % |

Jírovcova 1449/25: nyní zalomený hřeben (bent/L), místo dřívějších souběžných hřebenů. Jiráskovo nábř. 1543/19: nyní jednoduchá valbová střecha. Kontrolní Hroznová 247/32 zachovává souběžné hřebeny. Jde o numericky vybrané typy, nikoliv vizuální potvrzení skutečné architektury.

Nová adresa nám. Přemysla Otakara II. 1/1 má započítanou plochu 48,9 %, tedy nesplňuje hranici 55 %. Vybrána pultová šablona, ponecháno k optickému posouzení uživatelem.

Meziverze v47-43 používala starší pravidlo. Běh v471-44 byl na pokyn uživatele přerušen při změně prahů. Aktuální dokončená verze je v472-44.
