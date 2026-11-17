# Rozbor střech: Jírovcova a Jiráskovo nábřeží — 2026-11-17

Aktualizace: změny jsou nyní ověřené a zahrnuté v dokončené dávce 4.7.2 pro 44 budov. Jírovcova 1449/25 vybrala L, Jiráskovo nábř. 1543/19 valbu, Široká 432/11 a Fráni Šrámka 2609 jednu plochou střechu. Podrobné časy a výsledky: [ROOF_FLAT_MAJORITY_RUN_2026-11-17.md](ROOF_FLAT_MAJORITY_RUN_2026-11-17.md).

Níže je původní rozbor a stav před dokončením nové dávky.

Stav: obecné změny algoritmu 4.6 jsou zapsané ve zdrojích. Pět porovnávacích modelů zatím nebylo vytvořeno: oba pokusy zastavila paměťová pojistka před numerickými testy. Původní modely a HTML z roof-modular-batch-43 zůstávají nezměněné. Optické hodnocení neprobíhalo.

## Jírovcova 1449/25

Poslední dávka 4.5 nevybrala L, ale parallel_gables se dvěma souběžnými hřebeny. Skóre bylo 0,5233 proti 0,6808 u nejlepšího L. Samotné L už má příčnou polohu hřebenů v 47,0 % a 52,0 % šířky křídel, tedy asi 0,36 a 0,10 m od jejich středu. Problém je výběr topologie, nikoli potřeba vynutit vystředění.

Krajní souběžný hřeben leží jen 0,857 m od hrany. Původní kontrola mu uznala deset souhlasných buněk, ale nerozlišila dlouhý hřeben od krátkého shluku na kolmém křídle. Rozsah 10.–90. percentilu podélné polohy souhlasných buněk pokrývá pouze 21,2 % délky; druhý hřeben 67,1 %. U kontrolní Hroznové 247/32 jsou hodnoty 76,7 % a 67,1 %. Vyšší sousední dům je možný další zdroj šumu, ale tento původ nebyl prokázán.

Nová obecná podmínka vyžaduje u každého souběžného hřebene alespoň 50 % podélné podpory. Nezadává konkrétní adresu ani typ střechy a neposouvá hřebeny násilně do středu. Důvody vyřazení se ukládají do candidate_evidence_rejections. Samotné vyřazení souběžné varianty ale nechává ve hře U se skóre 0,6102; proto s ním musí soutěžit jednodušší L podle obecné tolerance složitosti. Finální výsledek změny ještě není numericky ověřený.

## Jiráskovo nábř. 1543/19

Vyhrál zalomený hřeben s jedním valbovým zakončením, 5 rovin a skóre 0,7453. Jednoduchá valbová varianta se 4 rovinami existovala a měla skóre 0,8038. Rozdíl 0,0586 ve váženém skóre těsně překročil původní toleranci 0,05 pro preferenci jednodušší geometrie. Dva půdorysné kandidáty přístavků navíc odmítlo ochranné pravidlo compound_main_roof_preserved, aby neodřezávalo křídla složené střechy.

Verze 4.6 zkouší i u sedlových/valbových střech obálku dominantních dlouhých stěn. Dosud tuto alternativu používala stanová šablona; u sedla/valby byly k dispozici pouze krajní rozměry. Nové roviny se ořezávají původním půdorysem, nevymýšlí se ruční výjimka pro tento dům. Tolerance podobných kandidátů se obecně mění na 0,10 ve skóre, aby při podobné shodě vyhrál menší počet rovin. Nejde o záruku maximální odchylky bodů 10 cm.

## Fráni Šrámka 2609 a Široká 432/11

Uživatel popisuje několik plochých úrovní. Současná sada šablon umí jednu vodorovnou rovinu a malé samostatné nižší přístavky; neumí zatím několik hlavních plochých úrovní v rámci jednoho objemu. Šikmé šablony proto napodobují výškové rozdíly: u Fráni Šrámka vyhrálo U, u Široké L. To není důkaz skutečných šikmých střech.

Další vhodný modul: prokázat lokální vodorovné plochy, seskupit je podle podobné výšky a prostorové souvislosti a sestavit několik jednoduchých objemů se svislými schody. Drobné nástavby potlačit nebo oddělit. Omezit počet úrovní a složitost půdorysů; testovat, že se šikmá střecha nezmění v umělé schodiště. Tento modul je zapsaný v TODO, není součástí nynější úpravy.

## Připravené ověření

Cílené syntetické testy: krátký zavádějící druhý hřeben, skutečně nesouměrné souběžné střechy, valba oříznutá výčnělkem a dosavadní přístavky/stanové/U/okružní střechy. Dávka má použít pouze malé uložené NPZ výřezy čtyř uvedených domů a kontrolní Hroznové 247/32, nikoli znovu číst velká mračna. Po uvolnění RAM spustit `.work/roof-46/run.py` s původním limitem nebo `run-small.py` s limitem 500 MB pro dětský proces. Žádný z těchto procesů nyní neběží.
