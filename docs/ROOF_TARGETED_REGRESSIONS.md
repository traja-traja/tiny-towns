# Cílené opravy střech 4.11

Sada: Hroznová 65/1 a 247/32, Jírovcova 1449/25, Senovážné nám. 229/5, Nová 1869/1, Kněžská 410/8, Jirsíkova 422/3. Změny jsou obecné, bez adresních výjimek. Speciální dvorní kombinace Dr. Stejskala 426/15 zůstává v TODO.

## Pevné porovnání

Do dalšího pokynu zachovat vlevo `cities/ceske-budejovice/experiments/roof-v410-review-inputs-54`, tedy stejný základ jako v reportu 4.10.0. RUN.txt předává původní --previous, nikoli poslední výstup. Staré výsledky se nemění.

## Příčiny a změny

- **Zalomená střecha:** vypnutí staré pravoúhlé L šablony odkrylo mezery v novějším hledání křídel. Chamtivý výběr dvojic stěn mohl vhodné křídlo vynechat; společný sklon snižoval hřeben úzkého křídla. Nový kandidát zkouší nejvýše 8 dvojic skutečných směrů × 4 orientace zakončení. Má společnou výšku hřebene a okapů, polohu hřebenů přizpůsobuje bodům. Geometrie vzniká jen pro 3 nejlepší návrhy. Stará pravoúhlá šablona zůstává vypnutá.
- **Nejistá větev:** nový kandidát vyžaduje alespoň 8 podporujících buněk rozprostřených nejméně 2 m. Slabší podpora mezi 15–35 % se penalizuje o 0,05 m a výslovně označí. Nejde o potvrzený měřený hřeben.
- **Dělení objemů:** podélný fallback začal nabízet více řezů, ale výběr neupřednostňoval jeden objem při blízkém výsledku. Dělení nyní musí zlepšit skóre o více než 0,10 m i po dosavadní penalizaci objemů. Tolerance je konfigurovatelná; nejde o důkaz fyzické oddělenosti hmot.
- **Paralelní sedlové střechy:** dříve měly volné každé půlšířky, výšky hřebenů i hloubky úžlabí. Hroznová 247/32 měla u jednoho pole strany 6,38 m a 0,89 m, úžlabí 1,52 m nad okapy. Nový výchozí symmetric_bays drží hřeben uprostřed každého pole, souměrné svahy a společnou výšku úžlabí a okapů. Pole mohou mít různou šířku a výšku. Nad 65° se tento kandidát vyřadí. Původní profil lze zapnout pro reprodukci starých testů.
- **Ochrana okapů:** dříve mohla přiřadit hranu libovolnému rovnoběžnému křídlu i v jiné části domu a zabránit jednoduššímu modelu. Nyní ověřuje místní oblast křídla a přítomnost stoupající střešní roviny. Vodorovná výplň není důkaz okapu. Odlišné roviny se násilně neslepují.

## Ověření

43 cílených numerických testů prošlo: symetrie, dělení, návaznost, šikmá křídla, uzavřená geometrie a výběr kandidátů. Analytické hřebeny z řezů zůstávají pouze diagnostikou reportu. Automatický přepočet používá stejné zabalené body. Výsledky běhu budou doplněny po dokončení.

## Dokončení 4.11.1 — 2026-11-17

Kněžská: koncové roviny lze sjednotit s existující hlavní rovinou při rozdílu směru do 3° a výškovém rozdílu do 0,25 m nad celým půdorysem. Bodové skóre a geometrie vždy používají stejné výsledné roviny. Pokud sloučení způsobí neplatnou síť, pouze při výběru výsledného kandidáta se zkusí nejvýše tři částečné návraty a původní varianta; přínos nesmí zhoršit skóre nad omezenou toleranci 0,03 m. Čas opravy je započten jednou. V konkrétním výstupu zůstala dvě sloučení (max. 0,131 m), jedno se vrátilo: 27 → 24 plošek, 19 → 18 různých rovin, platná uzavřená síť.

47 cílených testů prošlo. Finální lokální dávka dokončila 7/7 domů bez chyby, střechy 54,307 s včetně 8,080 s analytiky; celý skript s reportem 72,406 s, hlídaný proces 84,032 s. Peak 236,1 MiB, C: 69,54 GB volných. Všechny modely mají platnou geometrii; shoda všech sedmi levých modelů s pevným základem a HTTP 200 ověřeny automaticky. Bez vizuálního hodnocení.

Výstup: `cities/ceske-budejovice/experiments/roof-v4111-targeted-7/report.html`.
Jírovcova a Jirsíkova zůstávají jedním objemem; Hroznová 247/32 má dvě souměrné sedlové části. Hroznová 65/1, Senovážné a Nová vybírají nový kandidát spojených hřebenů. U Nové je vedlejší větev výslovně označena jako slabě podložená. Dr. Stejskala 426/15 se nepřepočítával; dvorní pultový kandidát je odložený.

## Upřesnění přepínačů půdorysu

Zjednodušení pracovního půdorysu křídel je obecné; vybraný model Kněžské používá connected_wings, nikoliv samostatný virtuální půdorys straight skeletonu. Rozpoznání přístavků je výchozí zapnuté. Naproti tomu modul footprint_support je výchozí vypnutý: jeho podvolby remove_unsupported=True a fill_notches=True se samy neprovedou. U Husovy 1829/12 jsou modul i obě podvolby výslovně zapnuté. Odstranění nepodložené části vyžaduje i terénní podporu; samotná absence střešních bodů není dostatečný důvod. Tato výchozí nastavení nebyla při této revizi změněna.
