# Vyšší věrnost Rooferu — předem stanovený test

Používáme stejnou verzi Roofer 1.0.0, stejné půdorysy, DMP OK, trénovací body a původní oddělený hodnoticí vzorek jako v předchozím porovnání. Žádná nová data se nestahují. Hodnocení není nezávislým geodetickým ověřením.

## Co znamená 0,60 versus 0,888

Jsou to hodnoty `complexity_factor`, nikoliv verze programu ani procenta přesnosti. Optimalizace má podle [dokumentace Rooferu](https://github.com/3DBAG/roofer/blob/main/docs/reconstruct_params.md) tvar:

`E = λ × chyba vůči datům + (1 − λ) × penalizace nespojitosti/složitosti`.

Vyšší λ zvyšuje důraz na shodu se vstupními body. Nižší více upřednostňuje jednoduché rozdělení střechy. Váhy nemají význam pravděpodobnosti ani procentuální kvality; datový a vyhlazovací člen navíc nejsou totožné veličiny. Samotné zvýšení λ nemůže vytvořit rovinu, kterou předchozí detekce vůbec nenalezla.

## Pevné profily tohoto kola

| Varianta | λ | Tolerance detekce rovin | Limit detekce |
|---|---:|---:|---|
| `roofer_c095` | 0,95 | 0,30 m | 120 rovin / 10 s |
| `roofer_c099` | 0,99 | 0,30 m | 120 rovin / 10 s |
| `roofer_c095_eps015` | 0,95 | 0,15 m | 120 rovin / 10 s |
| `roofer_c095_caps240_30s` | 0,95 | 0,30 m | 240 rovin / 30 s |

Třetí varianta testuje přísnější přijetí bodů do roviny. Tolerance 0,15 m není záruka konečné chyby modelu. Vyšší detail může zachovat užitečné prvky i šum.

Ostatní nastavení zůstávají shodná s původními profily: nejvýše 20 bodů/m², 15 sousedů, minimálně 15 bodů roviny a jeden nativní worker. První tři varianty mají stejné ochranné limity detekce (10 000 ms / 120 rovin). Čtvrtá je samostatná diagnostika většího výpočetního rozpočtu při stejné váze0,95 a toleranci0,30 m; nejde o další čistý test complexity. Ani u ní se nezvyšuje paměťový limit nebo nevypíná fallback. Složitější detekce může limit překročit a vrátit náhradní plochý objem. Rozhodující je `rf_extrusion_mode`, nikoliv samotný zápis LoD2.2.

## Protokol

- Sedm zmrazených půdorysů šesti požadovaných objektů, včetně obou částí Budvar arény.
- Dvě opakování každého profilu, první běh všech čtyř profilů povinný. Po 600 sekundách se další dávka již nespustí; rozběhlá dávka doběhne pod vlastními limity.
- Zobrazuje se první výsledek, ne nejlépe skórující opakování. Všechna pozorování a jejich časy zůstávají uložené.
- Před startem každé dávky se ukládají skutečné zdroje včetně nového konfiguračního wrapperu, příkazová řádka, otisk programu a vstupů. Starý wrapper se mění pouze v paměti nového procesu, nikoliv na disku.
- Výsledný zobrazený trojúhelníkový model se hodnotí pomocí stejné funkce jako v minulém kole. Hodnoticí body se nepoužívají při přizpůsobování ani při výběru profilu.
- Výpočty jsou sériové s 2GB procesním limitem, dvěma CPU, alespoň 1 GB volné paměti před spuštěním a průběžnou kontrolou disku. Produkční mapa se nemění.

Naměřené výsledky budou doplněny po skutečném dokončení; tento předem uložený plán není dokladem dokončeného běhu.

## Incident při prvním spuštění

První foreground pokus s původním plánem tří profilů neposkytoval průběžný výstup přes exec transport. Byl ukončen pouze jeho známý exec handle53062 pomocí Ctrl+C (potvrzený exit1). Pozdější přímé čtení souborů ukázalo jeden skutečně dokončený běh0,95 a zahájenou přípravu druhého profilu, která čekala na alespoň1GB volné RAM (naposledy0,65GB). Dne16.11.2026 ve13:05UTC byla nezávislou procesní kontrolou potvrzena nepřítomnost tohoto workeru i Rooferu; předchozí průběžné čtení bylo opožděné. Původní protocol/progress/log a popis incidentu jsou archivované v `.work/cb-roof-components/attempt-1-interrupted/`, nativní adresáře zůstaly zachované. První dokončený batch má platný snapshot původního zdroje; do finálního srovnání ho však nepřimícháváme. Následuje čistý čtyřprofilový běh s novým logem a zdroji zmrazenými po celý výpočet.

## Naměřené dokončené kolo

Všechny čtyři profily dokončily dvě opakování: 8 dávek, 28 srovnávaných modelů. Severní Budvar zůstává v prvních třech profilech v náhradním objemu, vyšší limity 240 rovin / 30 s vytvořily 8 střešních ploch (RMSE 0,225699 m). První přerušený pokus je archivovaný a není součástí čistého porovnání. Úplné časy a závěry: [zavery.md](zavery.md).
