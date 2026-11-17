# Propojené konce křídel a numerické zbytky půdorysu — 4.12.1

## Falešná fasádní plocha

Zaokrouhlení hranic střechy a půdorysu na mřížku 1e-7 m může vytvořit dlouhou, mimořádně úzkou nepokrytou oblast. Dosavadní přiřazení jediné sousední roviny takové oblasti neplatí, když oblast prochází pod více střešními svahy. U uložené Hroznové 247/32 vznikla z 1,85e-7 m² velké oblasti stěna vysoká až 4,08 m. Uzavřenost sítě sama tento případ nevylučovala.

Obecná oprava vynechá pouze nepřiřazenou oblast v původní plošné numerické toleranci, celou uvnitř pásu 3 × XY_GRID (0,3 mikrometru) kolem hranice půdorysu a bez průniku se skutečnými střešními oblastmi. Fasády uzavírají skutečné sousední střešní buňky. Skutečné výškové stupně a vnitřní mezery toto pravidlo neodstraňuje. Do diagnostiky se zapisuje počet a plocha těchto mezer a horní mez posunu.

## Pokračování střech a štítové konce

Dosavadní kandidát spojovaných křídel mohl ponechat valbové ukončení uvnitř propojeného celku a povoloval štít jen na celkovém krajním konci půdorysu. Nový konečný prostorový rozsah každého křídla dovoluje pokračovat přes celé křídlo; překryvy se spojují horní obálkou rovin. Vynechání čelní valby nesmí neomezeně pokračovat přes dvůr do dalšího křídla.

Zkouší se základní propojená varianta a nejvýše jedna kombinace místně podložených štítů (nejvýše čtyři konce). Body jsou 0,8–1,5 m dovnitř od skutečné hranice a ve středních 15–85 % šířky konce. Nutná podpora: alespoň šest buněk ve třech příčných pásmech, nejméně 0,2 m naměřeného zvýšení nad valbou, zlepšení místní chyby alespoň 0,1 m a alespoň 50 % buněk do 0,8 m od pokračující střechy. Prahy i modul jsou konfigurovatelné.

Stejné roviny se používají k hodnocení bodů i tvorbě geometrie. Kandidát musí vytvořit uzavřenou střechu bez vnitřních výškových schodů. Doložený štít může nahradit nízkou hranu valby; výjimka z ochrany okapů se týká pouze jeho odpovídající koncové hrany, nikoli jiných fasád. Analytické hřebeny z reportových řezů se do výběru nezapojují.

## Vztah ke straight skeletonu

Skeleton zůstává samostatným kandidátem. Před revizí u Kněžské: vlastní spojená křídla měla bodovou složku skóre 0,4250 a penalizaci 0,089 (celkem 0,5140, 18 různých rovin); skeleton měl bodovou složku 0,3345, ale penalizaci 0,2155 (celkem 0,5500, 32 rovin). Vlastní řešení tedy nevyhrálo menší bodovou chybou, nýbrž celkovým kompromisem shody a složitosti. Skóre není pravděpodobnost.

## Ověření

68 cílených testů prošlo. Zahrnují zachování reálných výškových stupňů, odstranění numerické fasádní stěny, šikmá křídla, uzavřenost, nezasahování přes dvůr, vyloučení šumu těsně při hraně, zachování skutečné valby a místní rozsah výjimky pro štít. Po odstranění neúspěšných experimentálních větví prošly znovu tři cílené testy konečných křídel.

Izolovaný číselný test Kněžské dal čtyři křídla, 19 oblastí, dva podložené štíty, uzavřenou síť a žádné vnitřní výškové schody. Celkový výběr však tohoto kandidáta správně odmítl: na jiné dlouhé vnější okapové hraně vytvořil výškový rozsah 2,3385 m proti 0,0178 m v původním modelu. Podložené štíty se této hrany netýkají, takže výjimka z ochrany okapu neplatí. Varianta s původními pěti kratšími rozsahy sice zachovala okap, ale vytvořila 18 vnitřních výškových schodů. Ani ta se neaktivuje. Bezpečný výběr Kněžské zůstává 24 oblastí / 18 rovin. Požadované úplné prodloužení spojů a štítů tím zatím není vyřešeno.

Hroznová 247/32: odstraněna jediná nepodložená numerická oblast; čtyři střešní oblasti, žádný vnitřní výškový schod, uzavřený mesh. Dr. Stejskala 426/15: dva nezávislé objemy, sedlová a pultová střecha; skutečný výškový stupeň mezi objemy je dovolený. Nejde o implementaci zvláštního dvorního kandidáta.

Pevná levá srovnávací verze nadále: `roof-v410-review-inputs-54`. Dr. Stejskala 426/15 se přepočítává se společnými pravidly; zvláštní dvorní pultový kandidát není součástí této změny.


Finální automatická dávka 4.12.1: `roof-v4121-junctions-3/report.html`, 3/3 bez chyb. Střechy 44,431 s; celý skript 53,133 s. Hroznová 1,351 s, Kněžská 13,045 s, Dr. Stejskala 30,035 s. Všechny modely uzavřené; jejich geometrii AI opticky neposuzovala. Pevné levé modely porovnány se zmrazeným základem a zůstaly totožné. Peak 217,7 MiB, C: 69,53 GB volno, projekt 6,00 GB. Metadata, kandidátní časy, validace a zdrojové otisky jsou ve výstupní složce.
