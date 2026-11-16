# Pilot rekonstrukce střech v ČB

Z kořene repozitáře s připraveným výřezem centra a jeho soubory ČÚZK:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/cb_roof_inference.py
.venv/Scripts/python.exe -X utf8 scripts/cb_roof_tile_review.py --input .work/cb-roof-inference/roofs.json
```

Výsledek je v `.work/cb-roof-inference/`. Soubor `roofs.json` obsahuje měření,
diagnostiku i trojúhelníkovou geometrii v S‑JTSK (EPSG:5514) a Bpv.
`map-detail/index.html` je samostatný přehled, který srovnává původní letní
dlaždice se shodným záběrem přepočítaným s novými modely. Seznam adres je městský vstup.
Pro srovnání s lokálním DMP OK:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/cb_roof_inference.py --source dmpok
.venv/Scripts/python.exe -X utf8 scripts/cb_roof_tile_review.py --input .work/cb-roof-inference/roofs-dmpok.json --output .work/cb-roof-inference/map-detail-dmpok
```

Vlastní sadu výškových dlaždic lze zadat pomocí `--point-dir`.

## Odhad a konstrukce

1. Adresní bod RÚIAN přiřadí půdorys z Overture. Výšky střech se berou z bodů
   třídy 6 uvnitř půdorysu, úroveň paty stěn z mediánu terénních bodů v okolí.
   Při odhadu střechy se použijí mediány v prostorových buňkách, aby husté
   shluky bodů nedostaly nepřiměřenou váhu.
2. Rozpětí výšek vyřadí zjevně nevhodné šablony. Průřezy ve směrech odvozených
   z půdorysu hledají horní nebo dolní pás bodů. Robustní fit zpřesní úhel,
   posun, výšku a podle typu i konce hřebene nebo polohu vrcholu. Hřeben a
   okapové hrany jsou vodorovné v modelu jednotlivé šablony. Sedlová střecha
   může mít dva okapy v různých výškách, pokud to zlepší shodu. U zalomeného
   půdorysu může obvod protínat střešní rovinu i mimo vodorovný okap.
3. Šablony potřebují podporu na jednotlivých plochách. Mezi modely, u nichž
   alespoň 90 % prostorových buněk vychází do ±0,5 m a medián absolutní chyby
   činí nejvýše 0,25 m, vyhrává nejjednodušší. Jinak rozhoduje robustní
   chyba s penalizací za slabou podporu a složitost. Malý odstup tvarů či směrů,
   slabé pokrytí nebo velký podíl odlehlých bodů označí návrh ke kontrole.
4. Při slabé shodě se zkoušejí dva samostatné objemy oddělené přímým řezem.
   Vyhodnocují se i dvě ploché výškové úrovně a pilová střecha se dvěma zuby.
   Složené modely mohou aproximovat křídla L/T a vyžadují vizuální
   kontrolu styku. Geometrie ukládá objemy samostatně včetně stěn v místě styku.
5. Diagnostika finální geometrie porovnává výšku všech dodaných bodů s
   modelem na stejném XY. Obsahuje medián se znaménkem, absolutní
   medián, P75/P90/P95/P99, RMSE, robustní RMSE a počty bodů více než metr nad a pod
   modelem. Kladné výjimky mohou odpovídat komínům, vikýřům i odlišným částem
   budovy. Chyba vůči stejnému mračnu slouží k porovnání šablon.

Modely `review` jsou kandidáti pro prohlídku. Pro automatickou volbu mapové
geometrie se počítá se stávající geometrií jako zálohou u nejistých nebo
chybějících výsledků. DMP 1G pochází z laserového skenování, DMP OK z obrazové
korelace. Rozdíly mezi oběma zdroji mohou zahrnovat i skutečné změny stavby.
