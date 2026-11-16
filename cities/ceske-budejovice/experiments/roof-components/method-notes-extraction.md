# Vyčlenění výstupků, zaplnění střechy a návrat jednoduchých dílů

Metoda pracuje s původním modelem Roofer 0,888 a stejnými zmrazenými fitovacími body DMP OK. Nezná název budovy, adresu ani její účel. Výsledek detekce je geometrický výstupek, nikoli spolehlivé rozpoznání věže nebo komína.

Použitá základní operace je [morfologické otevření v SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.grey_opening.html): eroze následovaná dilatací potlačuje úzká vysoká lokální maxima. Zbytek postupu — stavební brány, rozdělení regionů, zaplnění a návrat dílů — je naše zde testovaná heuristika, nikoliv převzatý validovaný klasifikátor budov.

## Pevný postup před měřením

1. Střechu převede do rastru s výchozím krokem 0,25 m; krok se zvětší, pokud by rastr překročil přibližně 100 000 buněk. Hodnoty mimo půdorys slouží jen jako nejbližší doplnění pro morfologickou operaci, nevytvářejí další budovu.
2. Morfologické otevření dvěma pevnými kruhovými měřítky **1,5 a 2,5 m** vytvoří kandidáty malých vyčnívajících částí. Kandidát musí převyšovat lokální podklad nejméně o **1,25 m**.
3. Kandidát musí mít plochu alespoň 0,35 m², nejvýše 30 m² a současně nejvýše 8 % zdrojového půdorysu. Maximální protažení je 3,5 : 1; kompaktnost nejméně 0,12. Dlouhý hlavní hřeben a roh velké vysoké roviny se tím odmítají. Zůstat smí nejvýše osm nepřekrývajících se kandidátů.
4. Rastr se přednostně napojí na celé odpovídající původní střešní regiony. Musí existovat alespoň dvanáct fitovacích bodů na vyvýšené střešní ploše; body nižší okolní střechy a boční stěny tuto podmínku nesplní.
5. Z prstence okolních střešních bodů širokého 2 m se vybere místní plochá, pultová nebo sedlová šablona pro zaplnění. Napojení musí mít P95 rozdílu od okolní původní střechy nejvýše 0,60 m a maximum 1,00 m. Nejde o kontrolu vůči vyhrazeným hodnoticím bodům; ty se zde vůbec nečtou.
6. Zaplněný základ se skutečně zjednoduší stejným dříve testovaným slučováním **15° / 0,50 m**. Obě následující varianty používají tento totožný základ.
7. Do vyčleněné části se přizpůsobí jednoduchá šablona bez obloukové rodiny. Požaduje se P95 odchylky od střešních fitovacích bodů nejvýše 0,75 m a ztráta jejich 99. percentilu výšky nejvýše 0,75 m. Pokud bezpečná jednoduchá náhrada nevznikne, vrátí se původní díl — věžička se tiše nevymaže.

## Čtyři varianty na každý půdorys

- `extract_compact15_patched` a `extract_compact25_patched`: diagnostická záměrná ztráta výstupku, zaplnění střechy a zjednodušení základu.
- `extract_compact15_restored` a `extract_compact25_restored`: tentýž základ s vrácenou jednoduchou komponentou, případně s výslovně označeným zachováním původního dílu.

Výsledná střecha se sestaví jako jediná půdorysná 2,5D partition. Otvory dvorů zůstanou otvory; střechy se nepřekrývají. Svislé stěny vznikají po obvodu a mezi různými výškami, nikoli jako vnitřní plné stěny každého dílu až k terénu. Nejde o rekonstrukci přesahů, průchodů a podloubí.

Pokud se nenajde bezpečný kandidát, zaznamená se `no_safe_component` a zůstane pouze konzervativní sloučení původního modelu. Při selhání geometrické operace se zobrazí výslovně označený původní model, nikoliv domnělá úspěšná rekonstrukce. Plochý náhradní objem původního Rooferu nemůže poskytnout věžičku, kterou neobsahuje.

## Audit a metriky

Každý kandidát má polygon masky, stav přijetí/odmítnutí, důvody, prominenci, plochu, podporu bodů, odhad základní a vrcholové výšky. Přijetí masky pro zaplnění a úspěch zjednodušeného vrácení jsou dva různé výsledky. Pole `retained_original_component` odlišuje bezpečný návrat původního dílu od nového jednoduchého modelu.

Při hodnocení je nutné oddělit chybu uvnitř masky a na zbytku střechy. Varianta se zaplněním má vůči původním bodům výstupku záměrně velkou chybu; nesmí být vydávána za věrnější úplný model.

Pro každé měřítko a půdorys se měří jeden průchod celého párového postupu: detekce, lokální zaplnění, sloučení základu a vrácení. Oba výstupní řádky sdílejí tento čas a nesmějí se sčítat. Jednotlivé fáze jsou zaznamenány zvlášť. Výsledky nejsou statistickým časovým benchmarkem.

## Syntetické kontroly

Kontroly pokrývají odstranění a návrat malé věže, lokální doplnění sedlového hřebene, odmítnutí dlouhého hřebene a velkého křídla, zachování dvora, ignorování nízkého šumu a odmítnutí prvku bez podpory bodů. Tyto testy kontrolují geometrické chování; nezaručují rozpoznání věže v reálném mračnu.

Reálná měření budou doplněna po sériovém chráněném běhu. Produkční renderer, předchozí výsledky a městské mapy tato metoda neupravuje.

## Naměřené dokončené kolo

28 výstupů pro 7 půdorysů a dvě měřítka; čas vždy společný pro dvojici patched/restored. U kostela byly přijaty 2 masky při 1,5 m a 1 maska při 2,5 m. Doplnění podkladové střechy prošlo kontrolou návaznosti. Žádná jednoduchá náhrada izolovaných prvků neprošla kontrolou zachování tvaru a výšky; restored proto vrací původní komponenty. U ostatních půdorysů neprošel žádný výstupek všemi podmínkami. Jde o výsledky konkrétního detektoru, nikoli tvrzení, že budovy nemají výstupky.
