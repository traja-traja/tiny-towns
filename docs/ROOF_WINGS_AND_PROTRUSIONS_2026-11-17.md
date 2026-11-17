# Střechy zalomených budov a zjednodušení nástaveb — 17. 11. 2026

Verze: `modular-roofs-4.9.1`. Osm cílených modelů, porovnání s původní sadou 44 modelů verze 4.8.1. Původní výsledky zůstávají zachované.

[Interaktivní porovnání](http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-regularized-wings-v491-8/report.html) · [Přehled šesti kroků](http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-wings-optimization-v49/index.html).

## Výsledek

- Hroznová 314/18: obnoven jednoduchý hřeben U (6 rovin). Původní výběr dovolil horšímu kandidátovi se čtyřmi rovinami nahradit lepší U kvůli toleranci jednoduchosti. U významných dvorů nyní přísněji chráníme doloženou topologii. Nejde o pravidlo podle adresy.
- Husova tř. 1829/12: společný sklon, ale výšky okapů doložené pro jednotlivá křídla. Přední a zadní okap se liší přibližně o 4 m; jedna společná výška proto selhávala. Úzké křídlo bez bodové podpory zůstává výslovně označeno jako nejisté.
- Kněžská 410/8: čtyři hlavní křídla kolem dvora; prodloužení střešních pásů do skutečných vnějších konců odstranilo zbytečná krátká zakončení uvnitř spojů.
- Široká 421/1: dva hlavní směry podle skutečného tupého zalomení, dva navazující hřebeny.
- Nástavby: zachováno 8 objemů na 4 domech, počet vrcholů jejich vnějších obrysů klesl ze 162 na 39 (o 75,9 %).

## Obecný algoritmus

Modul `roof_connected_wings.py` navrhuje křídla z protilehlých hlavních okapových hran. Spojuje téměř souběžné úseky přes drobné zářezy, každý pás má vlastní směr. Omezené roviny křídel se protnou a spojí; skutečný půdorys včetně dvorů ořízne výsledek. Referenční zjednodušení dvora nemění finální půdorys. Zkouší se valbové a štítové konce, kratší a prodloužené pásy, společné nebo body doložené výšky okapů. Skóre zahrnuje odchylky a složitost. Staré jednoduché šablony stále soutěží: u Hroznové vítězí původní U před novým kandidátem křídel.

Nástavby se pravidelně orientují podle hlavní stěny domu: přednost má obdélník, následně jednoduchý pravoúhlý obrys do 8 vrcholů. Přijímá se alespoň 80 % pozorované plochy a nanejvýš 15 % přidané plochy. Výsledek se ořízne skutečným domem a dvory; nevhodné přizpůsobení použije dosavadní zjednodušení. Zůstává výška nad 2 m, plocha od 1 m² a vršek podle percentilu 90.

Moduly i prahy jsou v `roof_config.py`; vypnutí přes `modules.connected_wings` a `flat_protrusions.regularize_footprints`. Hřebeny v náhledu se odvozují ze sousednosti svařených trojúhelníků výsledné střechy, aby nepřesnosti průsečíků nevynechávaly větve.

## Šest kroků optimalizace

1. **Protilehlé stěny** — Výchozí rozklad ukázal krátké oddělené střechy a špatná napojení.
2. **Sloučení stěn a napojení pásů** — Široká získala dva správně natočené hřebeny. Krátké zářezy už netvoří samostatné střechy.
3. **Směry, dvory a štíhlost** — Příliš přísná štíhlost některá správná křídla odstranila; tato část byla odmítnuta.
4. **Doložené výšky okapů** — Husova: podobný sklon, ale přední a zadní okap se liší přibližně o 4 m. Společná výška nestačí.
5. **Uzavření spojů** — Společné nodingové schéma odstranilo numerické spáry. Uloženy i první výsledky tohoto ověření (round5). Nejde o změnu architektury.
6. **Prodloužení do vnějších rohů** — Kněžská získala souvislé napojení kolem dvora. Kratší i delší varianta zůstávají kandidáty; Široká a Husova volí kratší.

Pátý krok má dva numerické ověřovací běhy. Archiv obsahuje výsledky, parametry a geometrie, včetně zamítnutých variant. Historické snímky zdrojového kódu jednotlivých mezikroků nebyly uloženy; současné skripty reprodukují finální algoritmus.

## Ověření a výkon

Všechny výpočty a obrázky vytvořily lokální skripty. Čtyři zalomené střechy i čtyři objekty s nástavbami byly vizuálně posouzeny nad projekcí uložených bodů a výsledné geometrie, dle výslovného zadání. Nebyly přikreslovány ruční výjimky podle adres.

| Dům | P80 před (m) | P80 po (m) | Výpočet střechy (s) |
| --- | ---: | ---: | ---: |
| Hroznová 314/18 | 0.957 | 0.858 | 1.938 |
| Husova tř. 1829/12 | 1.875 | 0.898 | 4.039 |
| Kněžská 410/8 | 1.479 | 0.627 | 6.555 |
| Široká 421/1 | 1.347 | 0.572 | 4.292 |

Odchylka je absolutní svislá vzdálenost k modelu na stejných vynechaných kontrolních bodech; nejde o ověřenou architektonickou pravdu. Pokrytí kontrolních bodů je úplné. U Hroznové se medián mírně zhoršil (0,393 → 0,413 m), zatímco P80 a P90 se zlepšily. Zjednodušení nástavby Široké 432/11 zhoršilo P90 (0,668 → 0,940 m), což odpovídá záměrnému vynechání detailů obrysu. Skóre plochých střech stále hodnotí základní rovinu, nikoli celou sestavu nástaveb.

- Výpočet střech celkem: **22,178 s**.
- Celá dávka včetně načítání a výstupů: **39,566 s**.
- Ochranný spouštěč včetně kontrol disku a dalších režijních kroků: **66,544 s**.
- Špička přidělené paměti celého stromu procesů: **205,8 MiB** (Windows commit, nikoli měření fyzické RAM).
- Po dokončení: disk C: **63,17 GB** volných, projekt **5,39 GB**; dodrženy limity 25 GB volného místa a 20 GB projektu.
- Jedno výpočetní vlákno knihoven, nízká priorita, paměťový limit 1 GiB a ochrana před uspáním během dávky.
- **63 různých testů prošlo**: 61 v sadě a 2 dodatečné testy zvýraznění hřebenů. Syntetické případy ověřují napojení, dvory, otočení, rozdílné výšky, vypnutí modulu, regularizaci i ochranu starých kandidátů. Syntaxe prohlížeče ověřena přes `node --check`.
- **8/8 geometricky platných uzavřených modelů**, bez otevřených nebo nemnožinových hran.

## Meze a pokračování

Čtyři zalomené domy jsou vývojový vzorek. Zobecnění na nové domy ještě není ověřené. Husova má křídlo bez podpory bodů, napojení mohou stále obsahovat drobné plochy; automatické rozlišení sousední budovy a vegetace zůstává samostatný úkol. Nejisté případy jsou v metadatech. Nebyla přegenerována celá sada 44 domů ani mapové dlaždice.

Přesné vstupy a nastavení jsou ve výstupní složce (`inputs.json`, `config.json`, `source_records.json`, `point-clouds`, `input-bundle.zip`); `RUN.txt` obsahuje příkaz opakování do nové složky. `verification.json` zachycuje metriky všech osmi domů. Původní body a porovnávací verze se nemění.
