# Střechy v2 – jednoduché objemy z DMPOK

Nová samostatná implementace je `scripts/roof_v2.py`. Nepoužívá inference z předchozího vlákna, Roofer, fotografie ani rozpoznávání obrazu. Všechny výpočty běží na místním CPU. Výsledek je experiment pro ruční posouzení, nikoli ověřený model města.

## Vstupy

- Půdorysy budov z místních dat mapy, včetně vnitřních otvorů.
- Husté fotogrammetrické mračno ČÚZK DMPOK, lokálně uložené dlaždice CBUD22 a CBUD23. Nominalně 25 bodů/m², tedy rastr 20 cm. Klasifikace 6 pro budovy; klasifikace 2 pro terén. Nejde o staré řídké DMP 1G.
- Základna domu je medián terénních bodů v okolním prstenci 1–6 m, při nedostatku bodů 1–12 nebo 1–20 m. Rozptyl a počet bodů se ukládají. Chybějící terén se nevydává za známou výšku.
- Souřadnice výpočtu jsou místní XY v metrech a výška nad touto základnou. Převod zpět uchovává EPSG:5514 a absolutní výšku Bpv.
- Zdrojový typ střechy slouží k následné kontrole rozporu. Není příkazem, který přebije mračno bodů. Původní barvy a ostatní atributy zůstávají v JSON.

## Výpočet

1. Ještě před fitováním se deterministicky oddělí přibližně 20 % bodů pro kontrolu. Body se stejnou polohou XY zůstávají společně. Kontrolní body nikdy nevstupují do optimalizace.
2. Trénovací body se shrnou mediánem v buňkách od 0,6 m, pro velké budovy se buňka zvětší. Jedna buňka má jeden hlas, aby hustší oblast nepřevážila zbytek střechy. Originální body zůstávají pro závěrečnou statistiku a zobrazení.
3. Lokální roviny odhadnou směr a sklon hlavních ploch. Rozbité či příliš řídké okolí není důkazem sklonu. Směry se doplní osami půdorysu.
4. Testují se plochá, pultová, sedlová, valbová a stanová šablona. Hřeben se inicializuje z horního percentilu v příčných řezech, nikoli z absolutních maxim, která mohou patřit komínům. Výpočet hledá vodorovný hřeben; protilehlé sklony mohou být různé.
5. Dvě ploché výškové úrovně mají vlastní šablonu. Ta musí mít prostorové rozdělení a doložené převážně vodorovné plochy. Pouhé dva shluky různých výšek nestačí. Tím se omezuje chybná šikmá spojnice mezi terasou a vyšší částí domu.
6. Kandidát se vyloučí, pokud některá jeho zásadní plocha prakticky není zastoupena nebo geometrie zasahuje pod přípustnou výšku stěn. Slabší podpora a nesouhlas lokálních sklonů zvyšují skóre a vytvářejí varování; samy nevyřadí tvar, který jinak podstatně lépe odpovídá bodům. Malý sklon bez významného převýšení není důvodem k pultové střeše.
   Význam sklonu se posuzuje také podle převýšení přes skutečnou plochu: například sklon 0,09 přes 30 m znamená 2,7 m a nesmí být vyřazen jako zanedbatelný. Kombinace téměř ploché a šikmé části dostává označení složené střechy a upozornění.
7. Zbývající kandidáti dostanou skóre odchylky a penalizaci složitosti. Chyba se počítá jako 60 % průměru absolutních odchylek omezených na 1,5 m a 40 % jejich 80. percentilu. Komíny tak nepřevezmou řízení celého modelu. Skóre **není kalibrovaná pravděpodobnost**.
8. U špatného jednoduchého výsledku je záložní rozdělení do dvou velkých částí. Zkouší se strukturální rozdělení konkávního půdorysu a rozdělení podle bodů, protože i obdélníkový evidenční půdorys může obsahovat dvě různé hmoty. Výsledek musí snížit odchylku alespoň o 0,18 m a zaplatit penalizaci složitosti. Každá část dostane vlastní jednoduchou střechu; její slabá důkaznost se přenáší do celku. Toto řešení je vždy označeno k prohlédnutí.
9. Roviny se oříznou skutečným půdorysem a vytvoří uzavřený objem se stěnami, štíty, vnitřním dvorem a výškovými skoky. Kontroluje se pokrytí, překryvy, orientace, uzavřenost hran a kladný objem. Neplatná geometrie se do dlaždic nepustí.
10. Exportuje se jedna vybraná střecha, parametry, pořadí kandidátů, důvody vyřazení, odchylky a příznaky nejistoty. Při nedostatku bodů je případný jednoduchý náhradní objem výslovně označen jako náhrada, nikoli jako rozpoznaná plochá střecha.

## Výstupy a kontrola

- `report.html`: samostatný interaktivní 3D prohlížeč, výběr budov, body, hrany, hřebeny, okapy a metriky. Otevře se také přes `file:///` bez externích knihoven či CDN.
- `results.json`: modely a jejich souřadnice; `diagnostics.json`: přehled problémových objektů pro budoucí diagnostický režim mapy.
- `inputs.json`, `sample.json`: zdroje, výběr vzorku, oddělení kontrolních bodů, základny, původní atributy a měřené časy.
- `tiles/report.html`: samostatné výřezy současného a experimentálního renderu plus diagnostické zvýraznění. Původní scény ani dlaždice se nemění.
- Syntetické testy ověřují známé tvary. Reálné střechy hodnotí uživatel; AI jejich obrázky neposuzuje.

Odchylky jsou svislé vzdálenosti bodů od příslušné střešní plochy. JSON uvádí medián, percentily, RMSE, podíl do 0,5 m a odlehlé body. Kontrolní body pocházejí ze stejného fotogrammetrického měření: jde o kontrolu zobecnění výpočtu, **ne o nezávislou geodetickou pravdu**. Metriky zahrnují i komíny, vikýře a chyby měření.

Těchto 30 domů je vývojový vzorek. Při opravě výběrové logiky byly kontrolovány také jeho výsledné metriky; pro nezávislé ověření hotového algoritmu bude potřeba další dosud nepoužitý vzorek. Optimalizace parametrů konkrétní střechy nadále používá jen trénovací body.

## Rozsah první verze

V této iteraci se nevracejí vikýře, věže a komíny jako samostatné objemy. Model má nejvýše dvě velké části v záložním rozdělení; složité L/T střechy proto mohou vyžadovat další iteraci. Pilové, válcové, mansardové a jiné speciální střechy nemají vlastní šablonu. Nejasný či špatně odpovídající výsledek má příznak ke kontrole; nenastupuje za něj automaticky Roofer.

Zákres využívá stávající letní podklad a světelnou mapu. Ověřuje nové objemy a jejich skutečné zakrytí v rendereru; není plným přepočtem předem připravených stínů a podkladu celého města. Okna jsou nadále stylizovaný vzor, nikoli ověřený počet podlaží.

Plochá šablona sama o sobě nedokazuje plochou střechu. Rozhodující jsou současně odchylky, pokrytí body, konkurence ostatních šablon a příznaky. Výška stěn vychází z okraje zvolené střechy, nikoli z výšky jejího hřebene. Rytmus oken ani počet podlaží tím ještě není ověřen.

Zdroje jsou omezené: jedno výpočetní vlákno knihoven, sériové zpracování, limit paměti procesu, nejvýše 20 GB v projektu a zastavení při méně než 25 GB volného místa na disku. Během úloh se dočasně blokuje uspání systému, nastavení napájení se trvale nemění.
