# Věrnost, věžičky a hlavní objemy

Otevři `report.html` přímo v prohlížeči. Samostatná offline galerie porovnává 6 objektů / 7 půdorysů, 14 metod a 98 výsledků. Nepotřebuje server ani připojení k internetu.

[Závěry a výkon](zavery.md) · [Úplné výsledky](results.json) · [Předchozí kolo](../roof-simplification/report.html).

## Co porovnáváme

- `complexity factor` Rooferu mění váhu shody s daty vůči jednoduchosti. Čísla 0,60 a 0,888 neoznačují verzi ani přesnost. Vyšší hodnota může přidat správný detail i šum. Epsilon detekce rovin je jiný parametr.
- Vyčlenění části, doplnění základní střechy a vrácení zjednodušené části jsou samostatné zaznamenané varianty. Galerie geometrii nepřizpůsobuje.
- Malá věžička může mít malý vliv na globální RMSE. Pokud je dodané místní hodnocení, karty proto ukazují také chybu ve vyčleněných místech a počet hodnoticích bodů.
- Nenalezená část, odmítnutý výsledek a náhradní plochý objem se nesmějí vydávat za úspěšnou rekonstrukci. Hodnoty a stavy se přebírají z výsledků.

## Kresba a metriky

Všechny varianty používají stejnou kameru a měřítko; oba půdorysy Budvaru mají původní vzájemnou polohu. Přepínač triangulace ukazuje technické dělení, zatímco výchozí obrysy sledují hranice rovin. Obtažení hran ani potlačení antialiasingových švů geometrii nemění. Vzorek bodů a masky jsou výslovně rentgenová diagnostika bez testu zakrytí.

Plochy a konstrukční hrany se kreslí s hloubkovým testem po pixelech a dvojnásobným rozlišením. Vzdálené stěny tak nemohou překreslit bližší střechu jen kvůli pořadí trojúhelníků. Jde o opravu náhledu, nikoliv měřeného modelu.

Masky: tyrkysová znamená přijatý výběr, oranžová přerušovaná nevybraného kandidáta. Počty prvků a hlavních objemů nejsou počtem střešních rovin. Z výškového rozdílu nebo barevného obrysu samotného nelze odvodit, že jde skutečně o věž či komín.

RMSE a P95 porovnávají zobrazený mesh s oddělenými body téhož zdroje, ne s nezávislým zaměřením. Podíl do ±0,5 m je uveden pro pokryté i všechny hodnoticí body. Víc půdorysů agreguje RMSE přes vážené čtverce chyb; P95 je pouze rozsah percentilů částí. Chybějící údaje zůstávají „—“.

Převzaté časy a nové měření jsou rozlišené. Samotné zjednodušení už existujícího modelu není celkový čas rekonstrukce. Jednotlivé budovy, celé dávky a hledání kandidátů mohou mít jiný rozsah měření.

## Obnovení a ověření

```powershell
.venv\Scripts\python.exe -X utf8 scripts\roof_components_report.py
.venv\Scripts\python.exe -X utf8 scripts\resource_guard.py run --log .work\cb-roof-components\qa\gallery.log --max-ram-gb 1 --min-available-gb 1 -- node scripts\check_roof_components.mjs
```

Generátor kontroluje identity, jedinečné varianty, konečné XYZ a indexy. Do HTML zapisuje SHA výsledků i zdroje rendereru. Předchozí report ani městské mapy neupravuje. Prohlížečová kontrola má dynamické počty variant, šest objektů, čtyři kamery, přepínače, místní odkazy, mobilní šířku a nulové síťové požadavky. `--smoke` ověří konečná doporučení a shodu SHA bez opakování celé obrazové kontroly. Existence tohoto návodu sama neznamená, že kontrola už proběhla.
