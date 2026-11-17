# Převaha vodorovných ploch — modul 4.7.2

Na přání uživatele: když téměř vodorovné plochy pokrývají alespoň 55 % půdorysu, celý dům dostane jednu plochou střechu. Výškové úrovně a drobné nástavby se nyní nezachovávají. Půdorys včetně otvorů zůstává původní.

## Postup

1. Již uložené body se převedou na mediány v pravidelné síti, stejně jako při ostatních výpočtech. Hustota bodů nemění váhu části střechy.
2. V okolí každé buňky se proloží rovina. Její okolí musí být plošné, nikoli jen řada bodů; kontroluje se sklon a odchylka od bodů.
3. U okrajů se jedním průchodem započítají i naměřené buňky, které odpovídají alespoň třem lokálním rovinám sousední potvrzené plochy (v okruhu 1,5 m, odchylka nejvýše 0,25 m). Z těchto doplněných buněk se dál nepokračuje; nejde o doplňování chybějících bodů ani modelování schodů. Vodorovné buňky se spojí do souvislých oblastí. Malé a příliš úzké oblasti se vynechají. Pokrytí je součet ploch buněk oříznutých skutečným půdorysem. Chybějící body se nezapočítávají jako plochá střecha.
4. Každá započítaná souvislá část musí mít alespoň 5 % půdorysu a největší musí mít alespoň 20 %. Plochy přijatých částí se sečtou bez ohledu na jejich výšku. Při součtu alespoň 55 % půdorysu se použije jedna vodorovná rovina. Výšku určí plošně vážený medián pozorovaných výšek největší přijaté oblasti; nevznikne průměrná výška mezi dvěma vzdálenými patry.
5. V tomto případě se přeskočí přizpůsobování složitých střech a oddělování přístavků. Když vodorovné plochy nepřevažují, pokračuje dosavadní algoritmus.

## Nastavení

| Parametr | Výchozí hodnota |
| --- | --- |
| `modules.flat_majority` | `true` (vyžaduje také `modules.flat`) |
| `flat_majority.min_coverage_fraction` | 0,55; podíl musí být alespoň roven prahu |
| `flat_majority.min_patch_area_fraction` | 0,05 |
| `flat_majority.min_largest_patch_fraction` | 0,20 |
| `flat_majority.radius_m` | 1,5 m |
| `flat_majority.max_slope_deg` | 7° |
| `flat_majority.max_p80_error_m` | 0,25 m |
| `flat_majority.min_patch_area_m2` | 4 m² |
| `flat_majority.min_patch_width_m` | 1,2 m |
| `flat_majority.complete_boundaries` | true |
| `flat_majority.boundary_min_support` | 3 podpůrné roviny |
| `flat_majority.boundary_max_residual_m` | 0,25 m |

Všechny prahy jsou konfigurovatelné, bez pravidel podle adres. Rozhodnutí a velikosti/výšky podpůrných oblastí se ukládají do `diagnostics.flat_majority`; prohlížeč zobrazuje podíl vodorovných ploch a čas detekce. Čas je součástí celkového času výpočtu střechy. Jednorovinný výsledek může mít vůči záměrně zanedbaným úrovním velkou odchylku; klasifikace podle převahy ploch má v tomto režimu přednost před soutěží šikmých šablon.

Metoda je deterministická, používá NumPy/SciPy/Shapely na místním CPU. Nezavádí Roofer, AI posuzování ani čtení velkých mračen při opakování dávky. Lokální sklon, šum měření, úzké střechy a chybějící pokrytí mohou ovlivnit přijetí; automatický výsledek posuzuje uživatel.
