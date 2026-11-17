# Kontrola podpory půdorysu — 4.9.5, 2026-11-17

Moduly: scripts/roof_footprint_support.py (2D geometrie a bodové pokrytí), scripts/roof_input_refinement.py (reprodukovatelné vstupy a nový ořez). Výchozí stav modules.footprint_support=false; odstranění přístavků a doplňování výklenků mají samostatné přepínače remove_unsupported / fill_notches. Parametry jsou ve scripts/roof_config.py. Žádné geometrické pravidlo nepoužívá adresu.

## Postup

1. Před přesným ořezem načíst lokální okolí půdorysu, včetně bodů budov i terénu. Ověřit souřadnice, rozsah pokrytí a kontrolní součet zdroje. Pouhé chybění bodů střechy není důvod k odstranění části.
2. V půdorysných buňkách 0,5 m spočítat podporu střechou a terénem. Střecha musí být alespoň 2,5 m nad referenčním terénem, terénní bod nejvýše 1,5 m. Geometrické návrhy jsou 2D; klasifikace a výšky slouží jako ověření.
3. Pro odstranění prodlužovat stávající půdorysné hrany a prověřit menší odříznuté připojené části. Vyžadovat nejvýše 2,5 % pokrytí střechou a nejméně 30 % pokrytí terénem. Jednotlivý úbytek nejvýše 20 %, celkově nejvýše 25 % plochy. Zachovat souvislou hlavní hmotu a dvory.
4. Pro výklenek uzavřít jen krátký konkávní řetězec hran: nejvýše 30 m², otevření a hloubka nejvýše 6 m. Vyžadovat nejméně 65 % střešního pokrytí, nejvýše 10 % terénního pokrytí a výškovou návaznost u napojení. Nevytvářet konvexní obálku přes celý dvůr.
5. Uložit původní i odvozený půdorys, všechny důvody přijetí/zamítnutí a časy do JSON. Teprve potom přesně oříznout body a spustit běžné dělení na objemy a hledání střech.

Pro výběr obrysu se používají pouze trénovací střešní body; kontrolní střešní body jsou oddělené už ve zmrazeném kontextu. Body terénu slouží jako podpůrný zdroj. Kontrolní vzorek je z téhož měření, nejde o nezávislé geodetické ověření.

## Test Husova tř. 1829/12

Zdroj: lokálně uložený širší výřez roof-parallel-inputs-12/point-clouds/stream-checkpoint.npz, třídy 2 a 6. Do samostatného kontextu v okolí 8 m bylo zabaleno 54 012 bodů (256 099 B), s původem, lokálním počátkem, ground_z, polygonem pokrytí a SHA-256. Zdrojový půdorys je OSM přes Overture, nikoli katastrální parcela.

| Výsledek | Hodnota |
| --- | ---: |
| Odstraněná nepodložená část | 60,467 m² |
| Doplněný výklenek | 19,444 m² |
| Původní / nový půdorys | 940,113 / 899,091 m² |
| Počet výsledných objemů | 2 |
| Plochy objemů | 432,461 / 466,630 m² |
| Příprava bodových buněk | 0,256 s |
| Odstraňování | 0,032 s |
| Doplňování | 0,007 s |
| Celá optimalizace půdorysu | 0,295 s |
| Čtení kontextu navíc | 0,016 s |
| Celý výpočet domu včetně optimalizace | 27,443 s |

Řez prodlužuje existující hranu č. 14. Proto je odstraněná plocha 60,467 m² mírně jiná než dřívější ručně vymezená auditovaná oblast 56,606 m²; nejde o ruční nastavení řezu. Po úpravě přibyly dříve odříznuté střešní body výklenku: trénovací 17 593 → 17 977, kontrolní 4 280 → 4 376. Oba výsledné modely jsou uzavřené. Geometrie byla ověřena programově, optické hodnocení je na uživateli.

Pokrytí střechou samo nedokazuje polohu stěny: doplnění výklenku zůstává odvozenou hypotézou. Modul je proto volitelný a u tohoto běhu zapnut pouze u Husovy pomocí per-building roof_config_overrides. Sousední vyšší plocha se kontroluje výškovou návazností; chybějící vstupní třídy nebo neznámé pokrytí se nesmějí zaměnit za prokázaný prázdný prostor. Kontrola skutečných stěn a širší ověření na dalších domech zůstávají otevřené.

## Reprodukce a výstupy

Běh použil .work/roof-v495-inputs/inputs.json a porovnání .work/roof-v495-inputs/previous. Volby runneru: --test --split-volumes --previous <předchozí složka> --inputs <inputs.json> --output <nová složka> --url-base http://127.0.0.1:8877. Přesný hlídaný příkaz je v .work/run-roof-v495.py. Do nového výstupu se kopíruje kontextové mračno, původní záznamy, trénovací/kontrolní body a konfigurace; balíček vstupů zahrnuje také context-clouds. Obnovení běhu ověřuje konfiguraci i kontrolní součty kontextu a vstupů.

Výstup: cities/ceske-budejovice/experiments/roof-v495-butterfly-support-2. Obsahuje report.html, výsledná metadata a validation-summary.json. HTML ukazuje původní a nové 3D modely, půdorysy rozdělených objemů, původní obrys, změny ploch a časy.

Celá dávka dvou domů: 41,913 s výpočtu, 59,264 s hlídaný proces, peak commit 176 MiB. Po dokončení C: 69,20 GB volných, projekt 5,75 GB. Mapové dlaždice ani další domy se nepřegenerovávaly.

## Ověření

38 cílených Python testů prošlo: 7 korytová geometrie, 5 místní podpora sklonu, 9 půdorysná podpora a 17 navazujících vstupních/dávkových/objemových/přístavkových testů. Prošel také JS test dat a DOM prohlížeče. Pokrývají zejména mezeru v měření bez důkazu terénu, skutečný přístavek s body střechy, cizí vyšší střechu, zachování dvorů, otočení půdorysu, opakované spuštění a oddělení kontrolních bodů. Oba nové modely mají platnou uzavřenou geometrii; report vrací HTTP 200.

Report: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-v495-butterfly-support-2/report.html
