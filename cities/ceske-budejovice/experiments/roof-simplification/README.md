# Zjednodušení střech – samostatné porovnání

Otevři `report.html` přímo v prohlížeči. Soubor je samostatný, offline a nevyžaduje běžící mapový server. Zobrazuje 6 objektů / 7 zdrojových půdorysů a 70 zaznamenaných výsledků. Podrobné hodnoty jsou v `results.json`; jde o izolovaný experiment bez nasazení do mapy.

[Závěry, doporučení, výkon a další kolo](zavery.md) · [Záznam posouzení](review.json).

## Jak číst obrázky

- Každá varianta používá stejnou kameru, měřítko a tlumené materiály. Vzájemná poloha více půdorysů se odvozuje ze zaznamenaných souřadnic EPSG:5514 a referenčního terénu.
- Výchozí volba „Zlomy ploch a okraje“ skrývá pouze vnitřní koplanární triangulační hrany. Hrany zobrazení spojuje na shodných XYZ souřadnicích zaokrouhlených na milimetr; společnou hranu zachová při změně sémantiky nebo úhlu normál nad jeden stupeň. Dodaná ID regionů mají přednost. Střešní hrany se navíc ořezávají na skutečné polygonové hranice souvislých regionů, aby se nezobrazily falešné vnitřní čáry u T-spojů triangulace (tolerance kolinearity 4 mm). Stejnobarevný přesah výplně o zlomek obrazového pixelu potlačuje světlé antialiasingové švy trojúhelníků; nevytváří novou hranu. Tato pravidla nejsou nová rekonstrukce ani geometrické zjednodušení.
- „Trojúhelníková síť (diagnostika)“ ukazuje technickou triangulaci. Počet takových čar nelze zaměnit za počet hlavních střešních rovin.
- Volitelný vzorek fitovacích bodů je zředěné rentgenové překrytí bez testu zakrytí. Souřadnice bodů jsou lokální XY a výška nad `ground_z`; modré body mohou být i za viditelným modelem.
- Boční A/B jsou projekce podle os modelu, nikoli ověřené uliční průčelí. Pohledy shora i z boku pomáhají posoudit siluetu.
- U Budvar arény se dva půdorysy zobrazují společně; chyba a pokrytí zůstávají také v samostatných řádcích. Karta agreguje RMSE jako odmocninu váženého průměru čtverců chyb a MAE podle počtu pokrytých bodů, pokrytí jako součet pokrytých / všech bodů. P95 je pouze rozsah percentilů obou částí. Počet rovin je součet částí bez jejich prostorového sjednocení.

## Jak číst čísla

RMSE, P95, pokrytí a podíl bodů do ±0,5 m se přebírají ze skutečných výsledků. Podíl do tolerance je uveden vůči pokrytým i všem hodnoticím bodům; nepokryté body tak nelze skrýt. Chybějící údaje zůstávají prázdné; galerie je nevymýšlí. Hodnocení odchylky vůči bodům stejného zdroje není nezávislé geodetické zaměření. Půl metru je uživatelská preference kompromisu, nikoli automatický práh schválení geometrie.

Počet skutečných souvislých střešních rovin a počty trojúhelníků jsou oddělené. Společná definice souvislých koplanárních regionů používá toleranci 3 mm a 0,25 stupně a je stejná pro všechny varianty; nativní plochy CityJSON jsou zvláštní údaj. Délka vnitřních hranic v XY zahrnuje hřebeny, úžlabí i schody, není automaticky počtem hřebenů. Náhradní plochý objem či nevytvořená část jsou označeny. Doporučení je redakční zhodnocení uložené ve výsledcích, nikoli automatický důsledek nejnižšího RMSE.

## Obnovení a kontrola

Z kořene projektu:

```powershell
.venv\Scripts\python.exe -X utf8 scripts\roof_simplification_report.py
.venv\Scripts\python.exe -X utf8 scripts\resource_guard.py run --log .work\roof-simplification\qa\gallery.log --max-ram-gb 1 --min-available-gb 1 -- node scripts\check_roof_simplification.mjs
```

Generátor pouze čte měření. Vyžaduje `results.json` a použije `manifest.json`, pokud existuje. Kontroluje identity, unikátní varianty a konečné XYZ souřadnice/platné indexy meshe. Otisky vstupů jsou v HTML (`gallery.inputs`). Neprovádí fitting ani změnu městského rendereru.

Prohlížečová kontrola se spouští samostatně po ukončení výpočtů. Ověří všechny objekty, kameru, zapnutí/vypnutí hran, diagnostickou síť, lokální odkazy a mobilní šířku 390 px. Výsledky a snímky budou v `.work/roof-simplification/qa/`; existence tohoto návodu sama není potvrzením úspěšné kontroly.
