# Obnova části mapy — audit 2026-11-17

Současná pipeline neumí skládat hotové tematické vrstvy půdy, budov a stromů.
Umí zachovat vstupní data a přeskočit nezměněné prostorové čtverce.

| Možnost | Současná implementace |
| --- | --- |
| Zachovat data a dlaždice | `scripts/towns.py build <city> --render-only`, větev `postav.sh render` |
| Přeskočit nezměněný čtverec | `render_ctverec.sh` porovnává otisk po spuštění `prep.py` |
| Vybrat čtverce | `render_par.sh 1 "0,0 1,0"` |
| Vybrat obrazové dlaždice | `render.mjs`: `tiles=7_3;7_4`, případně `only=7,3`; celá scéna zůstává načtená |
| Složit sousední čtverce | `compose.py`; nejde o skládání tematických vrstev |
| Export webových dlaždic | `dzi.py` nyní exportuje celý dotčený čtverec/variantu |

Běžný build maže výsledné dlaždice. Pro průběžné aktualizace je proto třeba
používat render-only a před změnou uchovat výstupní verzi. Samostatné verzování
hotových map a automatický výběr změněných dlaždic zatím nejsou implementované.

## Doporučený malý další krok

1. Ukládat geometrii a její kontrolní součet podle ID budovy; měnit pouze vybrané domy.
2. Ze starého i nového promítnutého objemu včetně stínu a přesahu určit dotčené PNG.
3. Vykreslit je ve stávající celé scéně, aby zůstaly správné překryvy a stíny.
4. Zpočátku znovu exportovat DZI pouze dotčeného čtverce.

Prosté průhledné PNG vrstvy nestačí: strom může být před domem i za ním a dům
vrhá stín na půdu a okolní objekty. Oddělené vrstvy by vyžadovaly hloubku a
řešení společného stínování. Současný renderer má společnou stínovou mapu.

Obrazový rám se odvozuje z geometrie (`render.html`), proto při jeho změně musí
být překreslen celý čtverec, nebo se rám musí nejprve stabilizovat. `dzi.py`
odvozuje paletu z celého čtverce; částečný export DZI potřebuje stabilní paletu.
Půdní textury, lightmap a scéna v `prep.py` zatím nemají samostatnou modulovou cache.

Sportcentrum se načítá v `cities/velesin/assets/custom_prep.py` z vlastního JSON
a vkládá do scény jako `tt_mesh` s `only:1`. Jeho změnu současný otisk zachytí.
Libovolné budoucí soubory importované až rendererem by bylo třeba do otisku doplnit.

## Velešín — následující vzorek

Lokální adresy a půdorysy jsou v `.work/.preview/velesin/data_all/`.
Husté DMPOK CKRU30 a CKRU31 jsou již uložené v `.work/roof-pilot/sources/`.
Výběr podle adresních bodů dává 146 budov: náměstí J. V. Kamarýta 60,
Družstevní 13, Školní 21, U Přehrady 52. Více adres může patřit jedné budově.
Adresní body náměstí čp. 55 a U Přehrady čp. 672 neleží v žádném dostupném
půdorysu; bez ověření se automaticky nepřiřazují k nejbližšímu domu.
