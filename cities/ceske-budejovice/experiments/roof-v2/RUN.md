# Spuštění experimentu střech v2

V PowerShellu otevři kořen projektu:

```powershell
cd C:\Users\traja\claude-projects\izomapa-velesin
```

Pouhé prohlížení hotových výsledků nevyžaduje nový výpočet. Spusť místní server:

```powershell
.\.venv\Scripts\python.exe -m http.server 8877 --bind 127.0.0.1
```

Pokud server již běží, nespouštěj druhý. Prohlížeč:

- 3D: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-v2/report.html
- Dlaždice: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-v2/tiles/report.html
- Číselné srovnání: http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-v2/comparison.html

Samostatné report.html lze otevřít i přímo jako místní soubor, bez serveru. Server v terminálu zastaví Ctrl+C.

## Opakování výpočtu

V existujícím projektu jsou všechny potřebné zdroje i závislosti již místně. Žádné stahování dat se tím nespouští.

```powershell
.\.venv\Scripts\python.exe scripts\cb_roof_v2.py --prepare-only
.\.venv\Scripts\python.exe scripts\cb_roof_v2.py --run
.\.venv\Scripts\python.exe scripts\roof_v2_report.py
.\.venv\Scripts\python.exe scripts\roof_v2_compare.py
```

`--prepare-only` znovu využije nezměněnou malou cache; její první vytvoření musí projít dvě velké LAZ dlaždice. `--run` obsahuje ochranu disku, limit paměti procesu a blokování uspání po dobu úlohy. Data se zpracovávají sériově.

Výřezy skutečného rendereru se generují samostatně. Následující úsporný režim snižuje podkladové textury a stínovou mapu; geometrii střech zachovává. Používá místní grafickou kartu, vyžaduje alespoň 1,2 GB volné RAM a procesům rendereru povoluje nanejvýš 3 GB:

```powershell
.\.venv\Scripts\python.exe scripts\roof_v2_tiles.py --input cities\ceske-budejovice\experiments\roof-v2\results.json --render --texture-max-size 2048 --shadow-size 2048 --min-free-ram-gb 1.2 --max-ram-gb 3
.\.venv\Scripts\python.exe scripts\roof_v2_summary.py
```

Při nedostatku RAM úloha nezačne; stávající mapy ani data není třeba mazat. Přesné parametry skutečného testovacího běhu jsou v benchmark.json a tiles/render.log.metrics.json.

## Automatické kontroly

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_roof_v2*.py"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cb_roof_v2.py"
node cities\ceske-budejovice\experiments\roof-v2\assets\check_report.cjs
```

Kontroly neprovádějí AI hodnocení obrázků. Testují známé syntetické tvary, geometrii, rozdělení vstupů, převody souřadnic, palety a funkčnost prohlížeče.
