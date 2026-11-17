# Samostatná noční dávka střech — 17. 11. 2026

Algoritmus `modular-roofs-4.9.1`. Čtení bodů a modelování běží odděleně, vždy lokálně v Pythonu. Dávka nevolá AI služby, nepořizuje screenshoty a nehodnotí vzhled. Generuje 3D modely a stránkované HTML galerie; neprovádí kompletní render mapových dlaždic. Vlastní Sportcentrum i stávající mapové verze zůstávají zachované.

## Spuštění / pokračování

Z kořene projektu v PowerShellu:

```powershell
.\.venv\Scripts\python.exe -S -u -X utf8 scripts/night_roof_batch.py run --output cities/velesin/experiments/roof-night-20261117-v491
```

Stejný příkaz pokračuje z uložených checkpointů. Zámek nedovolí dvě instance nad stejnou výstupní složkou. Při změně algoritmu nebo konfigurace zvolit novou výstupní složku. Přípravu lze spustit také samostatně (`night_roof_inputs.py plan` a `prepare`); při přímém spuštění s `-S` musí být v Python path `.venv/Lib/site-packages`, což řídicí skript nastavuje automaticky.

[Průběh a odkazy na výsledky](http://127.0.0.1:8877/cities/velesin/experiments/roof-night-20261117-v491/report.html). Místní HTTP server obsluhuje kořen projektu na portu 8877.

Pro zastavení vytvořit prázdný soubor `STOP` v hlavní výstupní složce. Hlídací proces ukončí svůj výpočetní podproces a zachová checkpointy; před pokračováním odstranit pouze tento STOP soubor. Systémové nastavení napájení se nemění.

## Pořadí a časová pravidla

1. Velešín: 146 domů v ulicích náměstí J. V. Kamarýta, Družstevní, Školní, U Přehrady.
2. Nová verze celého Velešína: 1 758 dalších automatických objektů plus převzatých 146. Celkem 1 904 automatických objektů a jedno chráněné vlastní Sportcentrum v obecní hranici. Počítají se i neadresované půdorysy; šest místních půdorysů mimo obec je výslovně vyloučeno.
3. ČB: 287 objektů na náměstí Přemysla Otakara II. a ve vybraných navazujících ulicích; náměstí má první prioritu.
4. Pokud předchozí etapy skončí za méně než 7 200 s a nechybí požadované pokrytí podklady, pokračuje další ČB nejvýše 14 400 s včetně přípravy bodů. Další pořadí je reprodukovatelné podle hashe ID; z této etapy se neprovádí další síťové stahování.

Časy zahrnují čtení dat, čekání na paměť a sestavení výstupů. Jeden dům má nejvýše 180 s výpočetního čekání; při překročení se uloží timeout a pokračuje se dalším. Chyba jednotlivého modelu nepřeruší frontu. Přerušení pro disk/RAM zachovává dokončené modely. Chybějící terén nebo body se zaznamenají jako neúplné vstupy, nikoli jako úspěšně vygenerovaný dům. Úspěšné technické dokončení nenahrazuje vizuální kontrolu uživatelem.

## Podklady a úspora práce

Používá se husté fotogrammetrické DMPOK, nikoli tiché nahrazení řídkým DMP1G. Velešín vyžaduje doplnit CKRU40 a CKRU41 pro 108 půdorysů; dostupnost obou ZIPů ověřena HTTP 200, součet velikostí 673,7 MB. Stahování je omezené a při přechodné chybě má nejvýše dvě opakování. Nové zdroje se sdílí mezi etapami.

Původní střešní body třídy 6 se neztenčují. Pro odvození terénu je třída 2 deterministicky ztenčena na 1/16; zaznamenáno v každém vstupu. Staré přesné NPZ se přebírají jen při shodě půdorysu, zdroje, města a kontrolního součtu. Model se přeskočí jen při shodě vstupních bodů, půdorysu, počátku, výškového základu, konfigurace a zdrojového kódu algoritmu.

LAZ se čte postupně po malých blocích. Průběžné binární výřezy mají checkpoint; po přerušení se odřízne pouze neuložený konec vytvořený skriptem. Po úspěšném vytvoření NPZ se jeho vlastní dočasné binární výřezy odstraní. Podklady, rozhodovací metadata, časy, původní zdrojové záznamy a geometrie zůstávají v JSON/NPZ. HTML má nejvýše 40 modelů na stránku.

## Limity a technické ověření

C: alespoň 25 GB volných; projekt nejvýše 20 GB. Výpočetní proces má limit 1,5 GB přidělené paměti, nejvýše dvě CPU v procesní skupině a jedno vlákno numerických knihoven; nízká priorita. Začíná při alespoň 1 GB dostupné RAM, při nedostatku čeká nejvýše hodinu; pod 250 MB zastaví. Automatické uspání systému je blokováno jen během běhu.

11 cílených testů prošlo: pravidla časů, identity modelů a vstupů, bezpečné obnovení LAZ, pořadí ulic, shoda půdorysů a dat. Technický průchod jednoho skutečného plochého modelu trval 0,632 s výpočtu; druhá verze ho převzala bez přepočtu. Současně byl ověřen záznam chybějícího terénního podkladu bez pádu celé dávky. Vzhled modelů nebyl posuzován.


## Ranní oprava souběžného zápisu — 17. 11. 2026

První dávka běžela od 03:58:05 do 04:02:37 SEČ. Dokončila 35 modelů ze 146 v prvních ulicích; k dalším etapám se nedostala. Důvodem byl `PermissionError / WinError 5` při nahrazení `active.json`, souběžně čteného hlídacím procesem. Dokončené modely a připravené vstupy zůstaly uložené.

Zápis stavů a HTML nyní používá `atomic_io.py`: jedinečný dočasný soubor, zachování starého cíle do úspěšného nahrazení a nejvýše pět sekund opakování krátkého přístupového/sdílecího konfliktu. Chyby typu plný disk se neopakují. Historie jednotlivých spuštění se ukládá zvlášť; několik hodin, kdy byl proces zastavený, se nepřičítá k dvouhodinové výpočetní podmínce. Čekání na RAM během běžícího spuštění se stále počítá.

Prošlo 11 cílených testů atomického zápisu a řízení dávky. Jeden vyvolal skutečné zamknutí na Windows otevřeným čtecím handlem bez `FILE_SHARE_DELETE`, ověřil zachování původního obsahu během konfliktu a úspěšný zápis po uvolnění. Další ověřují trvalé chyby, zachování checkpointu a navázání časového rozpočtu bez započtení odstávky. Hromadné pokračování zatím zůstává pozastavené na následné přání uživatele, který nejprve řeší geometrii rohů střech.
