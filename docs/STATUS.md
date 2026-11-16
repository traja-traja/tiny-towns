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
- Velešín: uživatel úspěšně sestavil a otevřel náhled středu (1 čtverec). Data Overture, ČÚZK a vyrenderovaný web jsou v `.work/.preview/velesin/`.
- Sportcentrum, Strahovská 661: vlastní model pěti dílů, zelená půlválcová střecha, oddělené výškové úrovně a zachovaný průchod. Zdroj, nejistoty a postup jsou v `cities/velesin/models/README.md`.
- Model je uložen v přenosném JSON i GLB. Prošly 4 testy geometrie a adaptéru, opakovaně i 12 testů správy měst. Kontrolní letní render před/po byl vizuálně ověřen.
- Oprava Sportcentra je přepočítaná do všech čtyř sezón a světelné vrstvy místního náhledu. Obnovené jsou webové dlaždice, malé náhledy, vyhledávání, klikací vrstva a HTML. Vizuálně zkontrolován byl také zimní render. Mapa jako celek stále pokrývá pouze zkušební výřez.

## Co dosud hotové není

Celé správní území Velešína a mapa Českých Budějovic dosud nejsou vyrenderované. Neexistuje veřejný web. Další dominanty, městské projekty a dopravní simulace jsou další fáze. Fasády Sportcentra zatím nejsou ověřené fotografiemi z ulice.

V omezené pracovní relaci selhalo spuštění Git Bash a síťové připojení importu Pythonem. Uživatel následně náhled úspěšně sestavil z běžného terminálu. Pro opakované vykreslování již stažených dat je nově dostupné `node render.mjs ... offline=1`: prohlížeč dostává soubory z projektového adresáře přímo přes Playwright, bez HTTP listeneru nebo odchozích požadavků. Běžný síťový režim zůstává výchozí.

## Další spuštění

Ve zde připravené pracovní složce už jsou závislosti i náhled Velešína. Pro jeho prohlížení stačí druhý příkaz; první znovu připraví scény a změněné rendery z uložených dat:

```powershell
.\.venv\Scripts\python.exe scripts\towns.py build velesin --profile preview --render-only
.\.venv\Scripts\python.exe scripts\towns.py preview velesin --profile preview --port 8000
```

Po dokončení stavby druhý příkaz otevře místní server na `http://127.0.0.1:8000`. Pro první sestavení Českých Budějovic nahraď `velesin` za `ceske-budejovice`, vynech `--render-only` a použij jiný volný port. Ve zcela novém klonu nejdřív spusť `sh ./setup.sh` z Git Bash. Celé mapy sestav až po kontrole výřezů, bez `--profile preview`.

Referenční PNG terénu jsou cache a nepatří do Gitu. Pro opakované vytvoření konfigurací nebo obnovu této cache slouží:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_city_inputs.py velesin
.\.venv\Scripts\python.exe scripts\fetch_city_inputs.py ceske-budejovice
```

Tyto příkazy načítají pouze hranice a referenční terén. Budovy, detailní terén a podklady ČÚZK pro samotnou mapu stahuje následné `towns.py build`.
