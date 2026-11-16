# Jednodušší hlavní objemy střech — výsledky 16. 11. 2026

Porovnání je v [report.html](report.html). Obsahuje všech šest požadovaných objektů, sedm zdrojových půdorysů a deset variant na každý půdorys: 49 nových výsledků a 21 převzatých referencí. Městská mapa se neměnila.

## Co jsme skutečně zkusili

1. **Přísnější zjednodušení přímo v Rooferu:** complexity factor 0,35 a 0,15; navíc 0,35 s detekcí rovin do 0,50 m místo 0,30 m. Všechny ostatní podstatné parametry zůstaly stejné. Parametr complexity není tolerance v metrech.
2. **Sloučení sousedních podobně nakloněných rovin:** společné plošně vážené přizpůsobení a nové sestavení geometrie. Dva limity: 8° / 0,25 m a 15° / 0,50 m. Úhel se měří od každého původního trojúhelníku k výsledné rovině; metr omezuje svislou změnu původního modelu, nikoliv chybu proti skutečnosti. Omezují se také nově vznikající výškové schody.
3. **Jednoduché šablony a složení nejvýše čtyř objemů:** plochá, pultová, sedlová, valbová či oblouková střecha. Dělení vychází pouze z fitovacích bodů a půdorysu, nikoliv z hodnoticího vzorku. Za další část je penalizace, takže algoritmus nemusí využít všechny čtyři.
4. **Stejné zobrazení všech variant:** technické hrany trojúhelníků jsou oddělené od skutečných zlomů střechy. Toto samotné není geometrické zjednodušení. V galerii lze diagnostickou síť opět zapnout.

## Výsledky podle objektu

| Objekt | Kandidát k dalšímu použití | Co ukázala kontrola |
|---|---|---|
| Budvar aréna — severní půdorys | Jedna sedlová šablona | Roofer zde vrací plochý náhradní objem. Šablona má RMSE 0,334 m, 97,1 % bodů do ±0,5 m; obdobně dobře fungoval již původní fit 0,329 m. |
| Budvar aréna — jižní půdorys | Tři jednoduché objemy; přesnější alternativa Roofer 0,35 | Tři objemy mají pět rovin a 96,4 % bodů do ±0,5 m. Výškový spoj až 9,65 m je třeba ověřit jako skutečný stupeň vs. chybu řezu. Roofer 0,35 má osm nativních ploch a RMSE 0,599 m. |
| Sportovní hala | Roofer 0,35 / detekce rovin 0,50 m | 11→6 nativních ploch, RMSE 0,709→0,566 m. Zůstává hlavní vysoká část a nižší obvodové části. Jedna valbová šablona je špatně slije dohromady. |
| Kostel sv. Václava | Zatím konzervativní sloučení; dále chránit věžičku samostatně | Volnější Roofer má sice RMSE 0,704 m místo 0,757 m, ale poškodí zakončení věžičky. To je důvod variantu odmítnout i přes lepší průměr. Sloučení zachová siluetu, skutečné zjednodušení je však malé. |
| Wortnerův dům | Sloučení 15° / 0,50 m; hrubší alternativa Roofer 0,60 | Šest rovin při RMSE 0,426 m zachovává členitou část. Roofer 0,60 nabízí tři plochy při 0,607 m; dvě roviny už smažou významný výřez/členění. |
| Masné krámy | Roofer 0,60 | 14→5 nativních ploch při RMSE 0,377→0,488 m. Dvě plochy jsou příliš hrubé, v půlmetrové toleranci zůstává jen asi 59–60 % bodů. Mírný profil byl již v prvním kole. |
| Krajinská 43/8 | Konzervativní sloučení; výraznější zjednodušení zatím nevyřešeno | 95,6 % bodů do ±0,5 m, ale malá změna přehlednosti. Silnější nativní varianty i jediná šablona ztrácejí místní části a výškové členění. |

Sloučení 8° / 0,25 m většinou jen vyčistilo numerické zlomy pod 1,5 mm. Pokles přísného geometrického počtu oblastí proto sám neznamená odstranění architektonických detailů. Ani silnější sloučení nebylo univerzálním řešením: nejvíce pomohlo hale, Wortnerovu domu a Krajinské. Nové malé schody mezi rovinami jsou v geometrii a je třeba je kontrolovat.

## Čas a prostředky

| Výpočet | Naměřený čas | Rozsah |
|---|---:|---|
| Nové nativní profily Rooferu | 654,52 s | Celý worker včetně přípravy, CLI, parsování a vyhodnocení; osm dávek, 56 pozorování. Profily mají 3 / 3 / 2 opakování, další starty po 600 s byly zakázané. |
| Sloučení již vypočtených rovin | medián 0,049–0,388 s na půdorys | Samotné sloučení a nové trojúhelníky, bez předchozího Rooferu. Celý worker 16,81 s, 14 variant × 3 opakování. |
| Nové šablony a dělení | 1,49–4,60 s na půdorys | Jedno omezené hledání včetně počáteční jednoduché šablony; hodnoty se nesčítají s časem téže jednotlivé šablony. Celý worker 50,14 s včetně načítání a kontrol. |
| Jednotné přeměření všech 70 meshů | 19,11 s | Celý proces; samotné vyhodnocení a sestavení 13,37 s. |

Nativní interní časy jednotlivých budov jsou zvlášť v galerii a nelze je zaměnit za čas celé dávky. Snížení complexity factor samo nezaručuje zrychlení. Staré referenční časy jsou převzaté; nejsou to nové běhy ve stejný okamžik. Opakování na stejném počítači není nezávislý hardwarový benchmark.

Výpočty běžely sériově s limitem 2 GB přidělené paměti, dvěma CPU a kontrolou disku. Tři nové výpočetní workery měly špičky přibližně 162 / 99 / 144 MB, příprava vstupů 215 MB. Projekt zůstává kolem 4,92 GB, na C: zbývá přes 68 GB. Přesné procesní údaje jsou v `results.json`; vnořené nativní dávky se nesmějí znovu přičítat k času jejich nadřazeného workeru.

## Navržený další postup — zatím neimplementovaný

1. Oddělit výrazné malé prvky, zejména věžičky, a při zjednodušování je chránit. Mají malou plochu, takže jejich ztráta se v průměrné chybě celé střechy snadno skryje.
2. Rozdělit stavbu na hlavní výškové části. Toto je důležitější než prosté slučování podobných normál; současné omezené dělení uspělo jen u části případů.
3. Na každé hlavní části porovnat několik jednoduchých šablon s pravidelným modelem několika rovin. Hodnotit chybu, počet částí, zachování obrysu, výškové schody a charakteristické prvky.
4. Teprve na tento základ doplňovat ověřené vikýře, nástavby a menší detaily. Před převodem do mapy sjednotit sousední objemy a odstranit jejich vnitřní stěny.
5. Kandidátní pravidla ověřit na novém vzorku běžných i složitých domů. Šest záměrně vybraných staveb nestačí k tvrzení, že je metoda univerzální.

Není třeba předem správně pojmenovat každou střechu. Vhodnější může být porovnat několik jednoduchých kandidátů, ponechat nejjednodušší přijatelný model a nejisté případy označit. Tento automatický výběr s ochranou dominantních prvků je návrhem dalšího kola, ne hotovou funkcí.

## Ověření a omezení

Všechny varianty používají stejné půdorysy, stejné DMP OK, stejný původní 80/20 split a společnou výšku terénu. Metody se přizpůsobovaly jen trénovacím bodům. Hodnoticí body se použily až pro toto srovnání a výběr doporučených kandidátů. Proto další ověření potřebuje nový vzorek.

RMSE, P95 a podíl bodů v toleranci jsou odchylky zobrazeného trojúhelníkového modelu, nikoliv přesnější analytické šablony. Nejde o nezávislé geodetické zaměření. Siluety byly porovnány s původní uloženou rekonstrukcí; nebyly potvrzeny novými fotografiemi aktuálního stavu.

Přísné geometrické oblasti (3 mm / 0,25°), nativní plochy CityJSON a trojúhelníky jsou tři odlišná čísla. Například u haly je změna nativních ploch 11→6, zatímco přísných geometrických oblastí 13→11 kvůli drobným numerickým rozdílům. Obrázky a délka hlavních zlomů doplňují samotný počet.

Nové metody mají 18 cílených syntetických/protokolových testů. Galerie byla ověřena pro šest objektů, deset metod, čtyři pohledy, přepínače hran/bodů a mobilní šířku; nezávisí na internetovém spojení. Kontrolní součty deseti původních souborů map a referenčních výsledků zůstávají shodné. Do původního hlavního reportu přibyl pouze odkaz; jeho vložená původní data se nezměnila.

Podrobnosti: [Roofer](method-notes-roofer.md), [slučování rovin](method-notes-planes.md), [šablony a objemy](method-notes-templates.md), [protokol](protocol.json), [výsledky](results.json), [záznam posouzení](review.json). V pracovních podkladech jsou kontrolní součty vstupů a kopie implementací pořízené před měřením.
