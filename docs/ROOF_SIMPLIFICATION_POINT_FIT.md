# Ochrana shody s body při zjednodušování — 4.13.1

## Dr. Stejskala 112/4

V dávce 4.13.0 měl nejlepší kandidát small_steps / gables-1-4 ze straight skeletonu celkové skóre 0,6559186, bodovou složku 0,5389436 a deset různých rovin. Přesto vyhrála jednodušší valbová varianta s jedním štítovým koncem: skóre 0,7469420, bodová složka 0,6999420 a tři roviny. Rozdíl celkových skóre 0,0910235 byl uvnitř tolerance 0,10 pro preferenci menšího počtu rovin. Bodová shoda se ale zhoršila o 0,1609984.

Příčinou nebylo nové půdorysné dělení: objekt zůstal jedním objemem a 2D detektor žádný řez nepřijal. Skeleton se zvažoval a měl nejlepší skóre. Starý levý model navíc pochází ze samostatného skeletonového experimentu, v němž obecné jednoduché střešní rodiny nesoutěžily.

## Obecná změna

Penalizace jednotlivých rodin se nemění. Nový levný filtr dovolí preferovat méně rovin v toleranci celkového skóre pouze tehdy, pokud nárůst bodové složky proti nejlépe hodnocenému kandidátu nepřekročí 0,10 m. Platí pro všechny typy střech a uvnitř i mezi rodinami. Bodová složka je kombinací robustních odchylek, nikoli pravděpodobnost ani obyčejný průměr vzdáleností.

Nastavení: scoring.protect_point_fit=true a scoring.max_simplification_data_error_increase_m=0.10. Kandidáti mimo mez se nezahazují jako geometricky neplatní; zůstávají zálohou, pokud lépe hodnocené konstrukce selžou. JSON ukládá důvod, referenční chybu i zhoršení. Vyhodnocení pouze porovnává již spočítaná čísla; nespouští další fit ani čtení bodů.

## Jírovcova 1449/25 — pouze vysvětlení

Geometrie střešních oblastí v 4.13.0 je přesně totožná s 4.11.1. Vyhrál paired_ridge_0_00 s volnou polohou hřebene v každém rameni, společnou výškou hřebene a okapu. Hřebeny jsou na 15,00 % a 27,93 % šířky, ne uprostřed. Sklony dvojic ploch jsou přibližně 53,66°/13,49° a 32,05°/13,64°. První posun dosahuje povoleného krajního omezení. Nové půdorysné dělení nezasáhlo.

Tato šablona nahradila starší pravoúhlou L variantu (bent). Posuny vznikly optimalizací shody s body; samotná metadata neprokazují, zda je jejich příčinou sousední dům nebo skutečná nesymetrie. Jírovcova se v tomto kroku nepřepočítává ani specificky neupravuje. Možné další zlepšení: souměrný kandidát se skutečnými směry ramen a preference středových hřebenů při srovnatelné shodě.

## Ověření

37 cílených testů prošlo: nový limit, nezávislost na rodině, konfigurovatelnost, původní ochrana okapů, výběr objemů a zachování srovnávacího základu. Reálný přepočet pouze Dr. Stejskala 112/4, optické posouzení ponecháno uživateli.

Finální přepočet 4.13.1 vybral straight_skeleton / small_steps / gables-1-4, dva štíty, deset rovin; geometrie je uzavřená. Jde o aktuálního nejlepšího skeletonového kandidáta, nikoli totožnou variantu starého samostatného experimentu. Výpočet střechy 5,565 s, celý běh 6,496 s. Report roof-v4131-stejskala-112-fit/report.html, vlevo nezměněný původní základ.
