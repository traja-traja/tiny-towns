# Zjednodušení opakovaných zubů půdorysu

Modul: `scripts/roof_footprint_regularization.py`, algoritmus `modular-roofs-4.9.3`.

Před volbou střechy a před dělením velkých objemů se hledají souvislé řetězce krátkých příčných schodů a přibližně rovnoběžných úseků fasády. Je nutných nejméně šest střídajících se příčných kroků (tři opakování), celkové rozpětí alespoň 6 m a hloubka nejvýše 1,25 m. Dlouhé úseky určují směr, jejich délkami vážený medián určuje polohu náhradní přímky. Konce leží v průsečíku s navazujícími stěnami.

Návrh se přijme jen při platném polygonu, bez zásahu do vnitřních otvorů, s omezeným posunem hranice (1,5 m) a symetrickým rozdílem plochy nejvýše 10 %. Kontrola platí i vůči původnímu půdorysu po více úpravách. Samostatné přístavky, hluboké výklenky, L/U a lichoběžníky bez opakovaných zubů se nemění. Po rozdělení na objemy se tato úprava neopakuje na vzniklé řezné hraně.

Přepínač v JSON konfiguraci: `{"modules":{"footprint_regularization":false}}`. Prahy jsou ve skupině `footprint_regularization` v `roof_config.py`.

Zdrojový půdorys ani zmrazené bodové vstupy se nepřepisují. Odvozený půdorys, původní geometrie, změna plochy, posun a čas jsou v `diagnostics.footprint_regularization`; použitá geometrie je i v metadatech modelu. Jde o 2D zjednodušení kresby, nikoli detekci existence budovy z bodů.

Numerické ověření 2026-11-17: šest testů invariance vůči natočení, posunu, směru obvodu a začátku seznamu vrcholů; zachování křídel, dvora a samostatného přístavku. Vše prošlo. Kostelní 1281/18: 54 → 6 vrcholů, max. posun 0,155 m, plocha +1,722 m²; J. Plachty 2059/5: 28 → 8 vrcholů, max. posun 1,057 m, plocha −2,834 m². Časy samotného zjednodušení přibližně 0,17 s a 0,04 s.
