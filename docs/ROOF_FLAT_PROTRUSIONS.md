# Nástavby nad plochou střechou — 4.9.1

Modul flat_protrusions navazuje až na zvolený plochý základ střechy. Nemění rozhodnutí pravidla 5 / 20 / 55 %, základní výšku ani půdorys budovy. U šikmých střech se nespouští.

## Pravidla

- Body se převedou na prostorově vyvážené mediány v buňkách 0,35 m.
- Výběr tvoří buňky s převýšením **více než 2 m** proti již vybrané základní rovině.
- Souvislá oblast musí doložit nejméně **1 m²**, alespoň 6 buněk a šířku alespoň 0,6 m. Rozloha se měří z obsazených buněk oříznutých půdorysem, nikoliv z velkého obalového obdélníku kolem několika bodů.
- Zjednodušení smí doplnit nejvýše 15 % plochy nad rámec doloženého obrysu (konfigurovatelné); hranice 1 m² se vždy ověřuje na původně doložené ploše. Půdorys nástavby se zjednoduší, ořízne původní budovou a zachová dvory. Každá nástavba má jedinou plochou střechu ve výšce 90. percentilu mediánových výšek jejího zvýšeného shluku. Tato relativní výška se přičítá k základní rovině.
- Bodové dotyky otvorů se lokálně rozpojí drobným výřezem (při výchozím nastavení 2,5 cm), aby nevznikla svislá hrana se čtyřmi stěnami. Počet oprav, přidaná plocha a použitá tolerance jsou v metadatech.
- Pod nástavbou se odebere základní střešní plocha, aby se plochy nepřekrývaly. Společný generátor uzavře svislé stěny; neplatné sestavení ponechá původní základ a zaznamená důvod.
- Z jednotlivých nástaveb se už další výšková patra nevytahují. Nižší terasy se tímto modulem neobnovují.

## Konfigurace a metadata

Přepínač: modules.flat_protrusions. Parametry jsou v sekci flat_protrusions: cell_size_m, min_height_m, min_area_m2, min_cells, min_width_m, height_quantile, simplify_tolerance_m, max_simplification_area_increase_fraction. Lze je měnit souborem předaným přes --config. Vypnutí obnovuje předchozí způsob zjednodušení na jednu rovinu.

Příklad změny:

```json
{"modules":{"flat_protrusions":true},"flat_protrusions":{"min_height_m":2.0,"min_area_m2":1.0,"height_quantile":0.9}}
```

Rodina hlavní střechy zůstává flat; metadata obsahují main_roof_type, protrusion_count, flat_base_height_m, building_top_height_m a max_protrusion_height_m. Podrobná rozhodnutí a půdorysy jsou v diagnostics.flat_protrusions a model.regions. Časy detekce a sestavení jsou samostatné položky a zároveň součást total_seconds.

Neurčuje se, zda je objem výtahová šachta, věž nebo jiné zařízení. Falešně zatříděné body sousedních budov či vegetace mohou vytvořit kandidáta; automatický filtr sousedů zatím není implementován. Výsledek posuzuje uživatel, žádná AI nečte ani vizuálně nehodnotí mračno či model.


## Zjednodušené půdorysy — 4.9.1

Nově se nejprve zkouší obdélník rovnoběžný s nejdelší hlavní stěnou budovy a jednoduchý pravoúhlý obrys s nejvýše osmi vnějšími vrcholy. Výchozí shoda musí zachovat alespoň 80 % doložené plochy a nesmí doplnit více než 15 %. Zbytek pravidel včetně výšky P90 je nezměněný; při neúspěchu se použije dosavadní bezpečný obrys. Klíče: regularize_footprints, regularization_min_retained_area_fraction, regularization_max_vertices.

Na osmi dosavadních nástavbách klesl počet vnějších vrcholů ze 162 na 39. Puklicova má 4/4, Široká 432/11 7 (oříznutí skutečným obrysem domu), Pekárenská 2287/34 4/4/4/4, Pekárenská 1060/25 8. Původní výšky i počty zvýšených objemů jsou zachovány.
