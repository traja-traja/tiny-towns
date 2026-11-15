# Dvě mapy, jeden kód izomapy

Velešín a České Budějovice používají stejný kód v kořeni projektu. Vstupy každé mapy jsou v `cities/velesin/` a `cities/ceske-budejovice/`. Každé město má vlastní stažená data, scény a web.

| Cesta | Obsah |
| --- | --- |
| `cities/<město>/mesto.json` | Konfigurace celé mapy ve formátu izomapy |
| `cities/<město>/mesto.preview.json` | Volitelný výřez pro rychlý zkušební render |
| `cities/<město>/mista.json` | Volitelné popisky a příběhy míst |
| `cities/<město>/assets/`, `obce/` | Volitelné úpravy mapy a podstránky obcí |
| `.work/<město>/` | Pracovní kopie celé mapy včetně dat a webu |
| `.work/.preview/<město>/` | Samostatná pracovní kopie výřezu včetně dat a webu |

## Příprava a sestavení

V kořeni projektu spusť jednou `sh ./setup.sh`. Na Windows použij Git Bash, na macOS nebo Linuxu běžný terminál. `scripts/towns.py` funguje i z PowerShellu a pro `build` na Windows vyhledá Git Bash podle instalace `git` v `PATH`.

```text
python scripts/towns.py status
python scripts/towns.py prepare velesin
python scripts/towns.py build velesin
python scripts/towns.py build ceske-budejovice
```

`prepare` zkopíruje do pracovní složky soubory města a kód potřebný pro sestavení. Funguje i před instalací závislostí. `build` pracovní kopii také připraví a pak spustí `postav.sh`. Python, npm balíčky a Chromium se instalují jednou pro celý projekt. Na Windows pracovní kopie obsahuje aktivační skript pro společné prostředí Pythonu a moduly Three.js, které renderer načítá přes HTTP. Na macOS a Linuxu pracovní kopie odkazuje na kořenové `.venv` a `node_modules`.

Výsledkem je statický web v `.work/<město>/site/`. `preview` spustí místní server. Pro oba weby současně použij dva terminály a různé porty.

```text
python scripts/towns.py preview velesin --port 8000
python scripts/towns.py preview ceske-budejovice --port 8001
```

Volba `--profile preview` vybere menší výřez s vlastní pracovní složkou, pokud má město `mesto.preview.json`. Lze ji použít i s `prepare`, `status` a `run`.

```text
python scripts/towns.py build ceske-budejovice --profile preview
python scripts/towns.py preview ceske-budejovice --profile preview --port 8002
```

## Úpravy a další sestavení

Změny konfigurace a vlastní modely ukládej do `cities/<město>/`. Při další přípravě se přenesou do pracovní kopie. Pokud byl soubor v pracovní kopii ručně změněn, skript ho zachová a označí konflikt. Úpravu přenes do složky města nebo pracovní soubor odlož stranou, pak příkaz zopakuj.

`prepare` zachovává stažená data i vygenerované soubory. Po změně dominant nebo jiných doplňků lze použít `build --render-only`, který převezme stažená data a překreslí změněné čtverce. Běžné `build` používá pravidla `postav.sh` a znovu vytvoří dlaždice výsledného webu. Při změně geometrie mapy přesuň stávající pracovní složku stranou, aby stará data zůstala k dispozici, a připrav novou.

Nástroje izomapy lze spouštět v kontextu jednotlivého města. Příkaz `run` použije jeho pracovní složku a kořenové prostředí Pythonu.

```text
python scripts/towns.py run velesin python compose.py summer 8
python scripts/towns.py run --profile preview ceske-budejovice python build_html.py
```

Po aktualizaci společného kódu v kořeni projektu ho `prepare` a `build` přenesou do příslušné pracovní kopie. Přidá-li aktualizace samostatný vstupní soubor v kořeni nebo nový adresář sestavení, doplň jej do seznamu `ENGINE_FILES` nebo `ENGINE_DIRS` v `scripts/towns.py`.
