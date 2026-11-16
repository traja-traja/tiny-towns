# Slučování sousedních podobných střešních rovin

Jde o nový geometrický postprocess původního modelu Roofer LoD2.2 c=0,888. Neprovádí nové rozpoznání z mračna bodů a při volbě sloučení vůbec nepoužívá holdout. Původní výstupy se nemění.

Porovnáváme dvě předem zvolené varianty: normály do 8° a změna výšky nejvýše 0,25 m; normály do 15° a změna výšky nejvýše 0,50 m. **Metry označují odchylku od vstupního modelu, nikoli přesnost proti ČÚZK nebo geodetickému zaměření.** Chybu vůči stejným odloženým bodům počítá zvlášť společná evaluace ostatních metod.

1. Z označených střešních trojúhelníků vytvořit sousednost podle společných úseček v půdorysu. Dvě vzdálené, stejně orientované plochy se nikdy nespojí.
2. Nejprve sloučit pouhou triangulaci téže roviny; společná rovina musí vyhovět všem vrcholům do 3 mm a normálám do 0,25°. Kontrola celého vznikajícího shluku brání řetězovému slévání zakřivené střechy.
3. Pro každou sousední dvojici najít společnou rovinu metodou nejmenších čtverců s váhou půdorysné plochy. Výpočet používá přesnou kvadratickou integraci po trojúhelnících, takže drobný detail není zvýhodněn hustší triangulací.
4. Přijmout jen spojení, u něhož jsou všechny původní vrcholy a normály v dané toleranci. Rozdíl dvou rovinných funkcí je na původním trojúhelníku lineární, takže limit ve vrcholech omezuje i celý jeho vnitřek.
5. Zkontrolovat rozhraní s ostatními oblastmi. Nově zvětšený výškový schod nesmí překročit stejných 0,25/0,50 m proti původní geometrii. Významné původní výškové rozdíly proto není možné libovolně vyhladit.
6. Skutečně sjednotit polygony, odstranit kolineární mezivrcholy a znovu triangulovat. Zůstávají stejné půdorysné pokrytí a dvory. Jde o změnu rovin i geometrie, nikoli o pouhé skrytí čar v prohlížeči.

Nový mesh tvoří střechy, vnější stěny, spodní plocha a pouze potřebné svislé stěny mezi sousedními různě vysokými oblastmi. Vnitřní stěny se nevytahují až k zemi. Mírné přizpůsobení roviny může vytvořit malý nový schod; jeho maximum je měřeno a uvedeno. Rozhraní, kde se dvě výškové funkce kříží, se rozdělí, aby nevznikla samokřížící se svislá čtyřúhelníková plocha. Překrývající se projekce střech jsou explicitně odmítnuty, nikoli automaticky vymazány.

`actual_roof_region_count` je počet skutečných spojitých rovinných oblastí výsledku. `roof_triangle_count` je počet pomocných trojúhelníků. `structural_edge_segment_count` je počet úseček hranic oblastí včetně okapových hran a výškových schodů, nikoli počet samostatných hlavních hřebenů. Původní `native_roof_surface_count` z CityJSON je další odlišná metrika.

Pro společné srovnání všech metod je dostupné `extract_roof_regions(model)` se stejnou přísnou tolerancí 3 mm / 0,25°. Jeho počet tedy lze porovnávat mezi nativními Roofer modely, šablonami a postprocessem, aniž by se zaměňovaly trojúhelníky a roviny.

Omezení: metoda vychází z původního rozdělení a nemůže objevit novou budovu, opravit chybný půdorys nebo nezdařený Roofer fallback. Silně odlišné drobné vikýře a komíny chrání úhlový limit, takže mohou zůstat. Sloučení nevytváří automaticky stavebně správné části. Mesh má uzavřenou hranici 2.5D výškového pole; jeho obecná topologická manifoldnost není nezávisle certifikována.

Implementace: `scripts/roof_simplify_planes.py`. Deset syntetických testů ověřuje skutečné odstranění rovin i trojúhelníků, zachování sedlového hřebene a dvoumetrového schodu, dvůr, oddělené objekty, odmítnutí překryvu, limit nových schodů, nepoužití předaných bodů, T-spoje s duplicitními vrcholy a ochranu proti řetězovému slévání zakřivené střechy.

## Naměřené výsledky 16. 11. 2026

Všech 14 variant na sedmi půdorysech proběhlo úspěšně. Každá má tři opakování se shodným SHA-256 výsledné geometrie. Otisky vstupů a kopie implementace vznikly před měřením; výsledky jsou v `planes-results.json`. Stávající modely mapy se nezměnily.

Mírnější varianta 8° / 0,25 m zde především odstranila numerické odchylky vzniklé kvantováním původního meshe: skutečný maximální posun byl pod 1,5 mm. Přísný společný čítač 3 mm / 0,25° totiž rozlišuje i některé úzké trojúhelníky, jejichž normály změnilo zaokrouhlení souřadnic. **Tento pokles počtu oblastí nelze vydávat za odstranění významných architektonických detailů.** Proto následující tabulka porovnává především již sjednocenou mírnější variantu se silnější variantou.

| Půdorys | Oblasti 8° / 0,25 m | Oblasti 15° / 0,50 m | Střešní trojúhelníky původně → silnější | Max. změna výšky silnější | Medián silnější varianty |
|---|---:|---:|---:|---:|---:|
| Budvar aréna – sever | 1 | 1 | 38 → 38 | < 0,001 m | 0,071 s |
| Budvar aréna – jih | 25 | 25 | 199 → 199 | 0,001 m | 0,388 s |
| Sportovní hala | 11 | 9 | 120 → 86 | 0,329 m | 0,156 s |
| Kostel sv. Václava | 13 | 13 | 107 → 107 | 0,0015 m | 0,162 s |
| Wortnerův dům | 7 | 6 | 33 → 33 | 0,345 m | 0,049 s |
| Masné krámy | 14 | 14 | 122 → 122 | 0,0013 m | 0,193 s |
| Krajinská 43/8 | 15 | 14 | 132 → 129 | 0,390 m | 0,245 s |

Smysluplný geometrický účinek tak mají silnější slučování na sportovní hale a menší změny na Wortnerově domě a Krajinské 43/8. Na ostatních vybraných střechách nastavené limity další podstatné sloučení nedovolily. Severní půdorys Budvar arény je již ve vstupu náhradní LoD1 extruze a postprocess jeho chybějící střechu neobjevil.

Všechny varianty zachovaly plochu původní střešní projekce: symetrická diference byla numericky 0 m². To ověřuje zachování půdorysných děr; samo o sobě to nedokazuje správnost vstupního půdorysu ani úplnou manifoldnost meshe. Největší naměřené zvětšení svislého schodu na rozhraní bylo 0,390 m (Krajinská), tedy pod nastavenou hranicí 0,50 m. Posouzení případných viditelných nových schodů zůstává důležitou součástí galerie.

Mediány všech variant jsou 0,049–0,388 s na jeden půdorys. Jde pouze o následné slučování a přestavbu geometrie; čas původní rekonstrukce Roofer, načtení dat a společná kontrola na odložených bodech se do těchto mediánů nepočítají. Celý chráněný pracovní proces trval 16,81 s, spotřeboval 12,81 CPU s a maximálně 94,2 MiB přidělené paměti. Běžel s limitem 2 GB a afinitou ke dvěma CPU; na konci bylo na C: 68,22 GB volného místa a projekt zabíral 4,91 GB. Záznam je v `.work/cb-roof-simplification/planes.log.metrics.json`.
