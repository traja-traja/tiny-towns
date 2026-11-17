# Dělení objemů podle místní šířky půdorysu — 4.13.0

Modul `roof_footprint_connector.py` pracuje jen s 2D obrysem. Nečte výšky bodů a nemá podmínky podle adres. Každé konkávní zalomení posoudí zvlášť. Při úhlu 90° ± 15° změří šířku obou přilehlých ramen třemi sondami kolmými na jejich vlastní směry. Poměr mediánů musí být alespoň 1,65. Šířka obalového obdélníku celého L se pro tento místní důkaz nepoužívá.

Řez prodlouží skutečnou hranu z rohu jen k první protější hraně, přes užší rameno. Nevytváří nekonečný řez skrz jiné křídlo. Výsledné části musí být dostatečně velké a přesně pokrývat původní půdorys bez plošného překryvu. Jde o modelovací objemy, nikoli důkaz hranic samostatných staveb.

První verze hledá dva nebo tři objemy. Pro tři části navíc vyžaduje dlouhé jednoduché propojení mezi dvěma většími hmotami. Dva objemy mohou vzniknout u jediného výrazného přechodu, i když navazující část tvoří L. Uzavřené půdorysy s otvorem zatím nový detektor nechává dosavadnímu postupu.

## Přísné výchozí meze

- Celý půdorys nejméně 240 m²; oddělené hlavní části nejméně 80 m² a 18 % celku.
- Zalomení 90° ± 15°, přilehlé hrany nejméně 3 m; poměr místních šířek alespoň 1,65.
- Řez nejvýše 14 m a nejvýše 1,35násobek užší místní šířky.
- Pro samostatný spoj: šířka 1,5–7 m, délka nejméně 6 m, poměr délky/šířky alespoň 2, plocha nejvýše 25 % celku a obdélníkovost alespoň 80 %.
- Všechny poměry jsou ve skupině `footprint_connector` konfigurace. Vypnutí: `modules.footprint_connector=false`. Krok se provádí pouze při zapnutém dělení objemů.

## Pořadí pipeline

1. Připravit půdorys a vyhodnotit místní 2D změny šířek.
2. Pokud vznikne jednoznačné dělení a každá část má dostatek buněk bodů, spočítat každou střechu samostatně.
3. V této větvi přeskočit výpočet společné střechy a podélné výškové profily pro dělení. Další dělení objemů a přístavků v dětech je vypnuté.
4. Při nejasném půdorysu, nedostatku bodů nebo neplatné složené geometrii se vrátit k dosavadnímu porovnání celého domu a podélných řezů.
5. Analytické řezy zobrazované v HTML zůstávají v režimu test zapnuté po dokončení výběru. Jsou odlišné od profilů používaných pro dělení a do rozhodnutí o dělení nevstupují.

JSON automaticky ukládá řezy, naměřené šířky a úhly, důvody, počet objemů, čas 2D detektoru a přeskočení podélných profilů. Stávající HTML zobrazuje půdorysy všech objemů a jejich samostatné střechy.

## Rozsah ověření

Na výslovný pokyn se neprověřuje celá sada 54 domů. Jediný reálný test je Dr. Stejskala 426/15, vedle 12 syntetických geometrických a 18 integračních/reportových testů. Všechny tyto testy prošly. Kněžská se v tomto kroku nepřepočítává; prodloužení navazujících střech zůstává samostatným nevyřešeným úkolem. Levá srovnávací verze zůstává `roof-v410-review-inputs-54`.

Čistě půdorysný test Dr. Stejskala: části 311,662 / 104,370 / 249,959 m². Místní šířky 17,45 ↔ 5,42 ↔ 11,77 m; úhly zalomení 93,32° / 93,16°. Dva řezy, překryv 0 m², rozdíl pokrytí pouze numerický (~1e-15 m²). Detektor přibližně 0,006 s.


Finální místní dávka: `roof-v413-footprint-stejskala-426/report.html`, jediný dům, dokončeno bez chyb. Tři objemy se sedlovou, pultovou a plochou střechou (automatický výběr, bez optického posouzení). V této dávce 2D detektor 0,0082 s, fit tří částí a sestavení 4,729 s, celkem střechy 6,467 s včetně 1,593 s reportové analytiky; skript s HTML 7,568 s. Podélné profily pro dělení ani fit společné střechy se nespouštěly. Dva řezy, tři dětské fity, žádné další dělení. Model je uzavřený; původní levý model nezměněný a otisky kódu odpovídají běhu.


Na následující výslovný pokyn uživatele byla poté přepočítána celá sada54: `roof-v413-all-54/report.html`. Všech54 dokončeno, nové 2D dělení vybráno u5 domů. Výpočet střech286,439s, reportová analytika36,945s je v tomto čase zahrnutá, celý skript383,001s. Předchozí omezení na jediný reálný test tím bylo rozšířeno; optické hodnocení zůstává na uživateli. Pevné levé modely jsou totožné se základem.
