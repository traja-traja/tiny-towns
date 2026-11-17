# Korytová (motýlková) střecha

## Aktualizace 4.9.5 — třetí plocha a ověření skutečného směru sklonů (2026-11-17)

Výchozí korytový kandidát má nyní vždy tři roviny: dvě podélné a jednu čelní, která uzavírá úžlabí trojúhelníkem. Oba možné konce se zkoušejí automaticky. Čelní sklon je průměr tangent obou bočních sklonů. Povrch je horní obálka tří rovin, oříznutá skutečným půdorysem. Žádné pravidlo není navázané na adresu.

Každá rovina vychází z hlavní skutečné stěny půdorysu; všechny tři horní referenční hrany mají společnou výšku. U mírně nerovnoběžných stěn tak zůstávají vnější hrany vodorovné, zatímco úžlabí může mít malý podélný spád. Drobné výstupky se nadále ořezávají stejnými rovinami: vodorovnost se vztahuje na hlavní referenční stěny, ne automaticky na každou krátkou hranu výstupku.

### Proč původně vyhrála i chybná korytová střecha

Globální odchylka sama nestačila: několik výškových úrovní nižšího objemu dalo dohromady zdánlivý růst k oběma krajům. Starý kandidát měl na kontrolních bodech MAE 0,553 m, pultový 0,649 m. Přesto jedna strana neměla souvislý skutečný sklon dovnitř: v lokálních rovinách jej podporovalo jen přibližně 35 % buněk, medián místního sklonu na té straně byl zhruba 0,2°.

Nový filtr před přijetím požaduje odpovídající směr místních sklonů na obou bočních plochách. Roviny se odhadují jednou nad okolím bodových buněk (poloměr 1,5 m); nejméně 60 % použitelných buněk každé strany musí stoupat od úžlabí. Čelní plocha je ze stranového testu vynechána. Buňky se nevybírají podle toho, zda předem vyhovují kandidátu. Výškové schody proto nelze tak snadno zaměnit za hladký šikmý svah. Dále platí dosavadní podmínky podpory, převýšení a robustní skóre; výběr není pravděpodobnostní záruka.

### Výsledek 114/30

- Stejné dva objemy a stejné rozdělení jako ve 4.9.4.
- Nižší objem: pultová střecha, jedna rovina.
- Hlavní objem: korytová střecha, tři roviny. Sklony 28,528° / 27,109° / čelo 27,823°.
- Horní hlavní hrany: společná výška 15,365 m nad ground_z; numerická odchylka výšky podél všech tří hran nejvýše 1,8e-15 m.
- Úžlabí: 13,124–13,244 m nad ground_z. Jeho rozdíl přibližně 12 cm je důsledek nerovnoběžných stěn a zachování vodorovných vnějších hran.
- Sklon není pevná konstanta ani dodatečné umělé zploštění. Optimalizuje se výška horních hran, hloubka a poloha úžlabí podle trénovacích buněk. Převýšení přibližně 2,2 m na boční vzdálenosti asi 4 m odpovídá uvedeným 27–29°. Původní dvouplošný model měl přibližně 26–27°. Nové omezení hrany tedy sklon nesnižuje; případné další zploštění by byla samostatná stylizační volba.
- Výpočet celého domu včetně dělení: 14,471 s. Bez optického posuzování.

Konfigurace: butterfly.end_cap_required=true; end_cap_penalty_m=0.015 nad základní penalizací 0.035; local_direction_check=true. Starý dvouplošný režim zůstává dostupný přes end_cap_required=false pro reprodukci a testy. Celý typ lze vypnout modules.butterfly=false.

„Butterfly test“ znamená automatický softwarový test korytové střechy (anglicky butterfly roof) na syntetických bodech se známým tvarem. Není to AI ani externí služba. Sedm geometrických a pět testů místních sklonů prošlo; navazující testy jsou uvedeny v ROOF_FOOTPRINT_SUPPORT.md.

Report obou domů, stará a nová verze vedle sebe:
http://127.0.0.1:8877/cities/ceske-budejovice/experiments/roof-v495-butterfly-support-2/report.html

## Historický stav 4.9.4

Verze: modular-roofs-4.9.4. Modul: scripts/roof_butterfly.py. Žádné pravidlo podle adresy.

## Postup výběru

1. Zachovat zmrazené vstupy, případně zjednodušit opakované zuby půdorysu. Pro dlouhé/zahnuté půdorysy prověřit samostatné výškové objemy.
2. Pro každou posuzovanou hmotu připravit prostorově vyvážené mediánové buňky z trénovacích bodů. Prokazatelně převažující vodorovné plochy mají nadále samostatnou větev flat_majority.
3. Korytového kandidáta zkoušet ve dvou hlavních směrech půdorysu a nad vnější i dominantní dvojicí stěn. Ze tří počátečních poloh přizpůsobit polohu vodorovného úžlabí, jeho výšku a hloubku pod společnou výškou horních referenčních hran. Dvě roviny tvoří horní obálku: z = max(rovina vlevo, rovina vpravo).
4. Vyžadovat body na obou plochách, nejméně 8 podporovaných buněk na každé straně, přijatelnou odchylku a skutečný růst mediánové výšky směrem od úžlabí (nejméně 0,20 m). Minimální modelované převýšení 0,35 m, šířka 3 m, maximální sklon 75°. Parametry jsou nastavitelné; modules.butterfly=false celý typ vypne.
5. Hodnotit stejnou robustní chybou jako ostatní šablony (vážený průměr omezených odchylek a 80. percentil), přičíst penalizaci 0,035 m jako u jednoduché sedlové střechy. Skóre není pravděpodobnost. Ve stávající toleranci skóre 0,10 m preferovat méně rovin; ochrana skutečných dvorů má nadále přísnější pravidlo.
6. Oříznout roviny půdorysem, ověřit uzavřenost geometrie. U rozděleného domu porovnat také celý model proti dvojici objemů. Nepřidávat umělý hřeben: ridge_lines je prázdné, valley_lines obsahuje odvodňovací úžlabí.

## Výsledek nám. Přemysla Otakara II. 114/30

Zůstaly dva hlavní objemy a stejný řez. Hlavní vyšší objem: U se šesti rovinami a 26 trojúhelníky → korytová střecha se dvěma rovinami a 8 trojúhelníky. Úžlabí 13,282 m a horní referenční hrany 15,306 m nad ground_z.

Původní U má nadále nižší skóre 0,323123, korytová má 0,372076; rozdíl 0,048953 je uvnitř stávající tolerance 0,10. Zvolen byl jednodušší tvar, nikoli tvar s nejnižší odchylkou. Datová složka skóre se u hlavní hmoty změnila 0,228123 → 0,337076. Obecný kandidát vyhrál také u nižší části (dříve pultová): skóre 0,523297 místo 0,689496 u nejlepší pultové.

Výpočet celého domu včetně porovnání řezů 12,463 s, hlídaný proces 27,314 s. Všechna čísla jsou z místního Pythonu; bez optického posuzování. Šest nových syntetických testů a 15 navazujících testů prošlo.

## HTML analýza

Report zobrazuje počet hlavních objemů, SVG půdorysy po rozdělení, čísla a barvy objemů, jejich plochy/typy a původní obrys. Obě verze sdílejí měřítko a orientaci; dvory zůstávají prázdné. Přepínač Úžlabí ovládá samostatné čáry. DOM/data testy, JS syntax a Python AST prošly.

Report: cities/ceske-budejovice/experiments/roof-v494-butterfly-114-30/report.html
