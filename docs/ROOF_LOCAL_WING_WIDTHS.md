# Lokální šířky křídel a symetrie střech — 4.13.2

Datum: 2026-11-17. Obecná oprava kandidáta paired ridges; žádná výjimka podle adresy.

## Příčina

Šablona mohla spojit dva široké, téměř totožné pásy přes celý L půdorys. Posun hřebene pak kompenzoval nesprávnou příčnou šířku a vytvářel velmi rozdílné protější sklony. Původní zjednodušení obrysu a celkové pokrytí tuto chybu neodhalovaly.

## Změna

- Před fitováním páru musí každé křídlo pokrývat vlastní část mimo druhý pás (výchozí minimum 4 % plochy domu). Dva pásy přes téměř celý dům se tak vyřadí ještě bez práce s mračnem bodů.
- V každé samostatné části se provede nejvýše pět 2D příčných kontrol. Alespoň dvě musí být použitelné a alespoň 60 % použitelných musí potvrdit obě hlavní hrany. Tolerance je větší z 1,8 m a 15 % šířky; drobné fasádní výstupky tedy nemusí měnit virtuální střešní šířku.
- V párovém kandidátu se zkouší i středové hřebeny se shodnými protějšími sklony. Volně posunuté hřebeny zůstávají možné; při odchylce přes 2 % šířky dostává nesymetrická varianta dodatečnou penalizaci 0,15 m ve skóre. Výška a směry se nadále přizpůsobují bodům a skutečným směrům stěn.
- Společná výška okapů a hřebenů této šablony zůstává zachována. Shodné protější sklony jednoho křídla neznamenají stejný sklon různě širokých křídel.
- Původní půdorys se nemění; finální roviny se ořezávají a uzavírají dosavadním postupem. Filtr platí pro alternativní dvojice křídel, nikoli pro všechny rodiny střech.

Přepínače a váhy jsou v connected_wings: paired_local_widths, paired_min_exclusive_fraction, paired_width_probe_count, paired_width_support_fraction, paired_width_tolerance_m, paired_width_tolerance_fraction, paired_prefer_symmetric, paired_asymmetry_penalty_m. Vypnutím obou nových přepínačů lze reprodukovat starý postup párových kandidátů.

Metadata obsahují local_width_evidence, naměřené šířky jednotlivých sond, opposing_slopes_symmetric, ridge_offsets_fitted a symmetry_preference_penalty_m. Důvody vyřazení se zapisují do existující telemetrie.

## Ověření a dávka

29 cílených testů prošlo (2,007 s): párové hřebeny, připojená a šikmá křídla, ochrana bodové shody a dávkový generátor. Nové regrese zahrnují široké falešné pásy, otočený L půdorys, malý výstupek, skutečně nesymetrické měření a vypnutí filtru.

Přepočítává se pouze Jírovcova 1449/25 z existujícího manifestu, bez nového stahování mračna. Výstup: cities/ceske-budejovice/experiments/roof-v4132-jirovcova-widths. Levá verze zůstává roof-v410-review-inputs-54. Vizuální posouzení dělá Pavel.

Dávka dokončena bez chyb: 1/1 dům. Výpočet střechy 15.282 s (včetně analytických testovacích řezů), celá dávka s reportem 20.209 s. Maximum paměti procesu a potomků 196.0 MiB. HTTP report 200. Žádná vizuální kontrola ani další iterace podle vzhledu.

## Regrese potvrzená uživatelem a audit výběru

Vzhled v4.13.2 uživatel odmítl. Výstup zvolil u_shaped (3 referenční hřebeny, 6 nominálních rovin), ne nově opravený párový L kandidát. Objekt zůstal jeden objem; mesh je uzavřený. Jde o problém konstrukční hypotézy a výběru, ne renderu či rozdělení objemu.

- U kandidát má skóre 0,610187 a bodovou chybu 0,515187 m; byl totožně přítomen již v pevném levém baseline, ale nebyl vybrán. Jeho virtuální vnitřní okap je 11,912 m, vnější 9,241 m. Slabou dodatečnou větev podpořilo jen 6 z 10 okolních buněk; současná kontrola sleduje reziduum k modelu, ne prokázané klesání na obě strany od hřebene ani jeho souvislou délku.
- Opravený přesně symetrický L kandidát má správně lokální šířky 5,086/11,930 m, protější sklony 45,643/45,643° a 23,557/23,557°. Skóre 0,713850 je o 0,103663 nad U, těsně mimo toleranci jednoduchosti 0,10.
- Volný L kandidát na správných lokálních šířkách téměř reprodukuje staré řešení: frakce hřebenů 0,47996/0,53001; sklony 47,546/45,252° a 22,879/25,449°. Jeho bodová chyba 0,615773 m je shodná se starým bent kandidátem do přibližně 6e-8 m. Nová skoková penalizace 0,15 m se ale spouští již nad 2 % posunu, a proto trestá i tento malý rozdíl sklonů; skóre narostlo na 0,840773. Toto nastavení je příliš hrubé.
- I po odstranění této penalizace by bodový rozdíl volného L vůči U 0,100586 m mírně překročil novější ochranu bodové shody 0,10 m. Nestačí tedy jen změnit jeden bonus či vynutit L podle adresy.

Další oprava má zachovat lokální šířky, posuzovat rozdíl protějších sklonů plynule s tolerancí místo skokového trestu za malý posun a vyžadovat pro každou dodatečnou větev U/O nezávislou lokální oporu hřebene (souvislá délka, plošná podpora a klesání po obou stranách). Analytické reportové řezy zůstávají oddělené. V tomto auditu nebyl algoritmus změněn ani spuštěna další dávka.
