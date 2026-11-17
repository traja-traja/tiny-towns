# Záloha kódu a obnova pracovních dat

Záloha z 17. listopadu 2026 obsahuje současný kód obou měst, modulární algoritmus střech 4.9.1, automatické dávky, konfigurace, testy, výzkumné poznámky a malý vlastní model Sportcentra Velešín v JSON/GLB včetně zdrojových parametrů. Přenos nové geometrie do hlavní mapové pipeline a verzování hotových map zatím nejsou dokončené.

Velká vstupní mračna, obrazové podklady, NPZ výřezy, Parquet, dlaždice, vygenerované HTML galerie, ZIP balíky, pracovní cache a lokální tajemství do Git repozitáře nepatří. Zůstávají v lokální pracovní složce; samotný Git tedy není úplná záloha dat nebo hotových map.

Starší reprodukovatelná sada 43 domů má uložené malé `inputs.json` a `config.json` v `cities/ceske-budejovice/experiments/roof-modular-batch-43/`. Manifest obsahuje ID domů, půdorysy, původ dat a kontrolní součty výřezů, nikoli samotné body. Cesty k bodům odkazují na vynechané lokální soubory. Pro opakování na jiném počítači je nutné připravit odpovídající vstupy nebo zvlášť přenést cache. Na současném počítači zůstávají vstupy i reporty zachované.

Podrobnosti algoritmu: [ROOF_MODULES.md](ROOF_MODULES.md). Naměřené časy a historie běhů: [UPDATES.md](UPDATES.md). Experimentální výsledky nejsou automaticky opticky schválené. Čtyři zalomené střechy a čtyři domy s nástavbami byly při vývoji 4.9.1 na výslovné přání uživatele vizuálně posouzeny; další hromadné běhy posuzuje uživatel.

Aktualizace 4.9.1 zahrnuje rozpoznání převahy plochých částí, pravidelnější obrysy nástaveb, napojování křídel a příslušné testy a dokumentaci. Záloha zachovává vlastní Sportcentrum; hromadné generování jeho zdrojový model nepřepisuje. Přesný seznam nově odeslaných souborů a SHA commitu se zaznamenává do lokálního `.work/git-backup/receipt-night-2026-11-17.json`.
