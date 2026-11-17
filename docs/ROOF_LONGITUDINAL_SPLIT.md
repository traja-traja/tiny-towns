# Podélné řezy a dvě výškové hmoty

Experiment z 17. 11. 2026, pouze Husova tř. 1829/12 v ČB. Produkční generátor ani hotové mapy se nemění. Nad rozdělenými hmotami běží původní `modular-roofs-4.9.1`, bez straight skeletonu.

## Postup

1. Existující rozklad půdorysu navrhne hlavní křídla. Příčné profily odhadnou jejich okapy, hřebeny a sklony. Samostatné doložené hřebeny v jednom měřeném pásu se nezahazují.
2. Křídla seskupíme podle výšek okapů. Rozdílná výška hřebene sama nestačí: širší křídlo může mít vyšší hřeben, přestože patří pod společnou střechu.
3. Podélné pásy přes napojení sledují, kde naměřené výšky přestávají odpovídat vyšší střeše a začínají odpovídat nižší. Nevyžadujeme svislou stěnu ani ostrý výškový schod. Střechy se mohou dotýkat.
4. Přechod musí opakovaně potvrdit několik pásů. Mezera přes dvůr je interval nejistoty, nikoli změřená hranice.
5. V okolí doloženého přechodu vznikne několik přímých řezů půdorysem. Musí vytvořit dvě dostatečně velké souvislé části. Půdorys se nezvětšuje ani neořezává.
6. Každou část samostatně zpracuje původní generátor. Sestavení uzavře i rozdílné výšky na společné hranici. Vybere se nejnižší trénovací chyba s cenou za druhý objem; možnost zachovat původní model zůstává.

Malé výstupky nejsou důvodem pro nové dělení. Experiment nehledá právní ani stavebněhistorické hranice domů, pouze užitečné geometrické hmoty.

## Moduly a parametry

`scripts/roof_longitudinal_split.py`: vypínatelný detektor s `enabled=false`. Konfigurace je samostatný JSON, ne pravidla podle adres.

| Parametr | Výchozí hodnota |
| --- | --- |
| Rozdíl skupin okapů | 1,5 m |
| Minimální plocha doložené reference | 12 % půdorysu |
| Minimální plocha každé výsledné hmoty | větší z 40 m² a 15 % půdorysu |
| Šířka podélného pásu | 2,5 m |
| Krok profilu | 0,6 m |
| Počet souhlasných pásů | alespoň 3 |
| Přípustná odchylka polohy přechodu od mediánu | 2 m |
| Maximální počet návrhů řezu | 5 |
| Cena druhého objemu ve výběru | 0,10 m |

`scripts/roof_longitudinal_experiment.py`: čte zmrazený JSON s původní variantou a NPZ s rozdělením train/holdout; automaticky vytvoří nové modely, metadata a HTML. `--extra-volume-penalty` nastavuje cenu dělení. Nevolá síť ani modelové API.

```powershell
.venv/Scripts/python.exe -X utf8 scripts/roof_longitudinal_experiment.py --source cities/velesin/experiments/roof-volume-sections-20261117-v3/buildings/7dfbe4f6-933d-4a01-8f72-866ed4f6a859.json --cache cities/velesin/experiments/roof-volume-sections-20261117-v3/point-clouds/ceske-budejovice-7dfbe4f6-933d-4a01-8f72-866ed4f6a859-0.npz --output cities/ceske-budejovice/experiments/roof-longitudinal-husova-NOVA-VERZE
```

## Výsledek Husova

Report: `cities/ceske-budejovice/experiments/roof-longitudinal-husova-20261117-v2/report.html`.

Pět pásů podpořilo dělení. Vybrané plochy hmot: 406,58 a 533,54 m²; dohromady zachovávají původních 940,11 m². Vyšší objem má hřeben 18,57 m a okap 12,32 m, nižší hlavní hřeben 12,29 m a okap 8,92 m nad lokálním terénem. Obrys nižší hmoty zachovává i další původní přístavky; nevnucujeme mu ručně písmeno L.

| Metrika | Původní 4.9.1 | Vybrané dvě hmoty |
| --- | --- | --- |
| Střešní oblasti | 28 | 11 |
| Kontrolní P50 svislé odchylky | 0,343 m | 0,181 m |
| Kontrolní P90 | 1,614 m | 0,733 m |
| Kontrolní RMSE | 1,058 m | 0,875 m |
| Kontrolní P99 | 3,698 m | 4,826 m |
| Kontrolní buňky | 2 104 | 2 104 |

Detektor 3,626 s; přizpůsobení obou návrhů dělení 13,758 s; celý výpočet po kontrole zdrojů a disku 18,246 s; sestavení HTML 0,258 s. Start Pythonu a kontrola rozpočtu disku nejsou zahrnuté do času algoritmu. Původní model se znovu nepočítal. Obě nové varianty mají uzavřenou orientovanou geometrii a úplné pokrytí půdorysu v numerické toleranci.

Holdout je odložená část stejného fotogrammetrického měření, nikoli nezávislé zaměření skutečné stavby. Celkově jsou odchylky menší, ale nejhorší procento bodů se zhoršilo. Optické posouzení provádí Pavel.

Čtyři syntetické testy ověřují vypnutí, zachování společné okapové výšky, rozdělení vyššího hlavního objemu od nižšího L a uchování více profilových hřebenů. Oprava uchování těchto hřebenů nemění žádný ze dvou řezů ani výsledné půdorysy Husovy (symetrická diference 0 m²); nebylo nutné stejné střechy přepočítávat.

## Rozsah a omezení

Zatím jde o dva hlavní výškové celky oddělitelné přímým řezem. Více výškových úrovní, přechody podél složité křivky nebo chybějící body mohou skončit zachováním původního modelu. Rozdíl výšky okapů nemusí vždy znamenat samostatnou stavbu. Tuto hypotézu proto držíme mimo hlavní dávku, dokud nebude opticky potvrzena na dalších domech.

Předběžná detekce svislých stěn se nepoužívá: na Husově nenašla dostatečně souvislou doloženou hranici. Její pracovní prototyp je odložený v `.work/`.

## Obecné přichycení k půdorysu a zákaz opakovaného dělení — verze 0.2

Aktuální porovnání: `cities/ceske-budejovice/experiments/roof-longitudinal-husova-20261117-v4/report.html`. Obsahuje původní 4.9.1, předchozí vybrané dělení a nové dělení přichycené k půdorysu. Předchozí verze se nepřepisují.

Pravidla neobsahují adresu ani souřadnice domu. Husova je pouze vstupní testovací objekt. V běžné městské pipeline tento experiment zatím není zapnutý.

- **Levná volba kandidátů:** před profily se vyhodnotí 2D půdorys. Dlouhý objekt má výchozí délku alespoň 24 m a poměr stran alespoň 2,2; výrazně zalomený půdorys nebo větší přístavek má konkávnost alespoň 6 %. Alternativou je dvůr alespoň 40 m². Celý objekt musí pojmout alespoň dvě hmoty po 40 m². Parametry jsou v konfiguraci a filtr lze vypnout.
- **Přichycení řezu:** v blízkosti nalezeného přechodu se hledají původní hrany délky alespoň 3 m, s odchylkou směru nejvýše 8°. Posun nikde přes skutečný řez nesmí přesáhnout 1 m a zhoršení průměrné ořezané chyby referencí smí být nejvýše 0,05 m. Mezi přípustnými hranami se preferuje nejdelší. Nevhodné přichycení se zamítne a původní řez zůstane.
- **Samostatné půdorysy:** řeže se přímo původní polygon. Nezávislé zjednodušení obou potomků se neprovádí, protože by mohlo vytvořit mezery nebo překryvy. Malé úlomky u řezu lze vrátit do sousední hmoty podle skutečné společné hrany; dohromady nejvýše 25 m² a 5 % půdorysu. Větší třetí objem nebo pouhý bodový dotyk takto slučovat nelze. Součet výsledných půdorysů musí zachovat původní obrys bez překryvů.
- **Druhé kolo:** každý potomek znovu dostane celý původní výpočet střech 4.9.1, včetně hledání hřebenů L/U. `annex_detection` i `annex_profiles` jsou vypnuté. Detektor dělení má navíc stráž `split_depth>=1`; při jejím dosažení vrací `child_volume_splitting_disabled`. Celé vícenásobné dělení není rekurzivní.
- **Export:** `volumes.json` popisuje vybrané hmoty a odkazy do `volumes/`, kde je samostatný půdorys, vlastní uzavřený model, konfigurace a místní souřadný systém každé hmoty. `--previous <comparison.json>` přidává předchozí vybraný výsledek do srovnání bez přepočtu.

### Naměřeno u Husovy

| Počet / vlastnost | Hodnota |
| --- | --- |
| Podélné pásy vyhodnocené | 13 |
| Pásy potvrzující přesnou hranici | 5 |
| Levně otestované polohy dělicí čáry | 15 |
| Odlišné návrhy po přichycení a sloučení duplicit | 1 |
| Skutečná dělení půdorysu | 1 |
| Výsledné samostatné geometrické hmoty | 2 |
| Nové výpočty střech potomků | 2 |
| Další volání dělení potomků | 0 |
| Pomocné příčné profily pro okapy a hřebeny | 38 |
| Největší posun čáry | 0,147 m |
| Natočení čáry | 0,240° |
| Připojený malý výstupek | 12,915 m² |
| Plochy hmot | 421,862 a 518,252 m² |

Pomocné příčné profily neslouží k dalšímu dělení; hranici hledají podélné pásy. Výsledné dvě geometrické hmoty nejsou důkazem dvou evidovaných staveb.

Nová varianta má 10 střešních oblastí oproti 11 v předchozím dělení. Na stejných 2 104 kontrolních buňkách kleslo P50 z 0,181 na 0,175 m, P90 z 0,733 na 0,690 m a RMSE z 0,875 na 0,794 m. Výpočet detektoru 0,961 s, obou střech se sestavením 3,812 s, celý měřený výpočet 5,113 s. Časy jsou závislé na aktuální zátěži počítače.

12 syntetických testů prošlo: mimo jiné filtr půdorysu, společná hladina okapů, dělení vyššího a nižšího celku, nevhodný směr/vzdálenost/chyba přichycení, přesné pokrytí půdorysu, malý přístavek versus velký třetí objem, orientace čáry a zákaz dělení potomků. Modely hodnotí opticky Pavel.


## Záložní profily bez předem známých střech — 2026-11-17

Dlouhý, zalomený nebo dvorní půdorys je kandidátem podle 2D tvaru. JSON odděluje `shape_candidate` od `area_sufficient_for_split`; dva výsledné objemy musejí stále splnit minimální plochu 40 m² a podíl 15 %. Ani předběžně vybraná plochá střecha již neobchází test způsobilosti.

Pokud chybějí dvě spolehlivé hřebenové reference nebo různé úrovně okapů, `long_profile_fallback` prověří podélné pásy přímo z bodů. Porovnává jednoduchý lineární/sedlový profil s dvojicí lokálních profilů; požaduje zlepšení alespoň 0,20 m, rozdíl spodních výšek alespoň 1,5 m a opakovanou podporu nejméně tří pásů. Práce je omezená na 11 pásů a 50 poloh. Diagnostika uchovává provedené kontroly i při nulovém počtu kandidátů.

Kandidatura neznamená automatické rozdělení. Celá budova i každá část se přepočítají a porovnají s penalizací dalšího objemu; děti již nesmějí spustit další dělení ani opakovanou úpravu půdorysu. Testy zahrnují nezalomenou sedlovou/pultovou střechu, společnou L/U střechu, malý výstupek, skutečný výškový předěl a malé zalomené kandidáty.

Nová dávka `roof-v493-footprints-volumes-5` vybrala po dvou objemech u ČB nám. Přemysla Otakara II. 114/30, Velešín náměstí J. V. Kamarýta 4 a 72. Jedna z pěti alternativ prvního domu byla odmítnuta kontrolou uzavřenosti mesh; vybraná geometrie je platná. Počty pásů/poloh: 6/34, 6/25, 9/36.
