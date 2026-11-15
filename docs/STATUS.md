# Stav přípravy – 15. listopadu 2026

| Mapa | Celá mapa | Zkušební výřez | Pokrytí hranice obce |
| --- | --- | --- | --- |
| Velešín | 9 čtverců | 1 čtverec centra | 100 % |
| České Budějovice | 24 čtverců | 1 čtverec centra | 100 % |

Čtverec má stranu 2,3 km. Pokrytí se vztahuje k polygonům ČÚZK uloženým v `cities/*/boundary.geojson`; Velešín má navíc pokryté rozšíření o 300 m kolem hradu. Výřezy slouží ke kontrole první stavby a nepokrývají celé město.

## Co je ověřené

- Obě hranice byly stažené z oficiální polygonové vrstvy Obec v RÚIAN, podle kódů 545821 a 544256.
- Konfigurace vycházejí ze skutečných referenčních dlaždic Terrarium z12.
- Kontrola průniku čtverců s hranicemi neodhalila vynechanou plochu.
- Příprava celých map i obou výřezů proběhla úspěšně.
- Kontrola místního Chromia potvrdila WebGL2.
- Prošlo 25 cílených testů správy měst, úplnosti pokrytí a importu; opakované ověření skutečných podkladů obou měst také uspělo.

## Co dosud hotové není

Budovy, silnice a další vrstvy pro render dosud nejsou stažené. Neexistují vyrenderované mapy ani veřejný web. Vlastní dominanty, městské projekty a dopravní simulace jsou další fáze.

Pokus o sestavení v omezené pracovní relaci selhal při spuštění Git Bash (kód 3221225794). Přímé spuštění importu Pythonem následně skončilo chybou připojení k Overture S3 (`AWS Error NETWORK_CONNECTION`). Jde o pozorované překážky této relace; úspěšné stažení hranic jiným dostupným nástrojem nedokazuje síťový přístup procesu Python. Celé sestavení je potřeba ověřit v běžném terminálu.

## Další spuštění

Ve zde připravené pracovní složce už jsou závislosti nainstalované. Z běžného PowerShellu v kořeni projektu spusť nejdřív jeden výřez:

```powershell
.\.venv\Scripts\python.exe scripts\towns.py build velesin --profile preview
.\.venv\Scripts\python.exe scripts\towns.py preview velesin --profile preview --port 8000
```

Po dokončení stavby druhý příkaz otevře místní server na `http://127.0.0.1:8000`. Pro České Budějovice nahraď `velesin` za `ceske-budejovice` a použij port 8001. Ve zcela novém klonu nejdřív spusť `sh ./setup.sh` z Git Bash. Celé mapy sestav až po kontrole výřezů, bez `--profile preview`.

Referenční PNG terénu jsou cache a nepatří do Gitu. Pro opakované vytvoření konfigurací nebo obnovu této cache slouží:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_city_inputs.py velesin
.\.venv\Scripts\python.exe scripts\fetch_city_inputs.py ceske-budejovice
```

Tyto příkazy načítají pouze hranice a referenční terén. Budovy, detailní terén a podklady ČÚZK pro samotnou mapu stahuje následné `towns.py build`.
