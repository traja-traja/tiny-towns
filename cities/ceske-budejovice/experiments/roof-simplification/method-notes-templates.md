# Několik jednoduchých objemů ze stejného trénovacího mračna

Tato varianta je omezený experiment s automatickým rozdělením půdorysu. Využívá existující rodiny `flat`, `shed`, `gabled`, `hipped` a `barrel` z prvního pilotu. Rozdělení na části ani výběr rodiny nečtou holdout body. Všechny souřadnice modelu jsou lokální XY a výška nad stejným terénem jako ostatní varianty.

Postup a parametry jsou stanovené před prvním během nad sedmi skutečnými půdorysy:

1. Ze vstupních trénovacích bodů se deterministicky vybere nejvýše 6 000 bodů, seed 41. Pro jeden fit se použije nejvýše 1 500 bodů a dvě počáteční orientace. Rodinu šablony vybírá původní fitovací metoda s penalizací 0,04 m za její jednotku složitosti.
2. Nejprve se proloží jedna šablona nad celým půdorysem. Nové měření této varianty se liší od prvního pilotu limity bodů/orientací; původní model se nepřepisuje.
3. Kandidátní dělicí přímky procházejí polohami vrcholů půdorysu a kvantily trénovacích bodů v obou hlavních osách půdorysu. Nejde o potvrzené stavební spáry. Předběžně se seřadí podle odhadované redukce zbytkové výškové chyby na obou stranách.
4. V každém kroku se zkouší nejvýše šest řezů a obě vzniklé části se samostatně proloží. Část musí mít alespoň 25 m² a současně 3 % původního půdorysu, nejméně 40 trénovacích bodů a souvislý polygon. Výsledek může mít nejvýše čtyři části.
5. Výběrové kritérium je `sqrt(mean(2 × Huber loss, delta=0,5 m)) + 0,20 m × (počet částí − 1)`. Rozdělení se přijme, pouze pokud kritérium zlepší alespoň o 0,02 m. Všechny zkoušené řezy a důvody zastavení jsou uložené v `partition_logs`.
6. Každá střecha se ořízne přesným polygonem své části. Sjednocení částí musí zachovat celý půdorys včetně dvorů, bez plošného překryvu nebo mezer. Mezní počet kompletních fitů je 37 na budovu (první fit + tři kroky × šest řezů × dva potomci).

**Tolerance 0,5 m je parametr robustní ztrátové funkce, nikoli garantovaná maximální chyba modelu.** Následné hodnocení používá skutečnou triangulovanou geometrii a všechny oddělené holdout body; proto může být chyba vyšší. Holdout slouží k porovnání a nezávisí na něm volba dělení. Obě množiny jsou ze stejného bodového zdroje, nikoli nezávislé geodetické měření.

## Co model znamená a co ještě nedokazuje

- Výstup je kolekce jednotlivých objemů se svislými stěnami. Vnitřní stěny mezi částmi zůstávají; nejde o prokázaně manifold Boolean union. Při pozdějším použití v mapě by bylo nutné sjednotit rozhraní.
- Na styku částí může vzniknout výškový skok. Může odpovídat přístavbě, ale může být i umělým švem fitu. Každý spoj má délku a maximální/mediánový výškový rozdíl. Takový skok se nezaměňuje za ověřenou římsu.
- Samostatná válcová šablona má 12 pásů triangulované aproximace. Počet parametrických objemů není totéž jako počet rovinných plošek výsledné sítě.
- Algoritmus používá půdorys a bodová data, ne fotografie ani ručně potvrzené stavební části. Zachování rozpoznatelné siluety vyžaduje vizuální kontrolu. Malá věž nebo vikýř mohou v omezeném počtu objemů zmizet.
- Jde o kandidáta pro budoucí rozhodování podle typu střechy; univerzální klasifikátor tím nebyl ověřen.

## Ověření implementace

Čtyři cílené syntetické testy ověřily obnovení dvou skutečně odlišných výškových objemů, ponechání jednoduché sedlové střechy bez zbytečného dělení, zachování dvora a odmítnutí neomezené konfigurace. Test s chráněným vstupem kontroluje, že fit nečte holdout. Malé syntetické testy nejsou měřením kvality reálných budov.

Měření skutečných sedmi půdorysů proběhlo samostatně pod projektovým hlídačem zdrojů dne 16. 11. 2026 a skončilo kódem 0. Zdrojové soubory byly archivovány a hashovány před rekonstrukcí; otisk implementace je `17aec7af96e10df6d3c97bf97b94c4a5ab493fab7635f080b502e5027f371346`. `templates-results.json` obsahuje modely, přesný počet fitů, společné metriky a jediné nové opakování. Čas celého hledání zahrnuje také první jednoduchý fit, proto se časy těchto dvou řádků nesčítají.

## Naměřené výsledky

Následující tabulka uvádí výsledek omezeného dělení. Sloupec „RMSE jedna → dělená“ porovnává nově měřenou jednu šablonu se stejným počátečním fitem rozšířeným o hledání částí. P95 znamená 95. percentil absolutní svislé odchylky, nikoli největší chybu. Ve všech čtrnácti modelech bylo možné vyhodnotit 100 % holdout bodů.

| Půdorys | Zvolené rodiny | Částí | RMSE jedna → dělená (m) | P95 dělená (m) | Body do ±0,5 m | Hledání včetně prvního fitu (s) |
|---|---|---:|---:|---:|---:|---:|
| Budvar aréna, sever | sedlová | 1 | 0,334 → 0,334 | 0,388 | 97,1 % | 2,33 |
| Budvar aréna, jih | 1 pultová + 2 sedlové | 3 | 2,461 → 0,855 | 0,378 | 96,4 % | 4,60 |
| Sportovní hala | valbová | 1 | 2,086 → 2,086 | 3,814 | 16,6 % | 1,72 |
| Kostel sv. Václava | 2 sedlové | 2 | 2,631 → 1,490 | 3,341 | 67,5 % | 2,68 |
| Wortnerův dům | sedlová | 1 | 0,753 → 0,753 | 1,821 | 65,8 % | 1,49 |
| Masné krámy | sedlová | 1 | 0,682 → 0,682 | 1,187 | 60,4 % | 1,75 |
| Krajinská 43/8 | sedlová | 1 | 1,571 → 1,571 | 2,202 | 38,7 % | 2,01 |

Jedna šablona se počítala přibližně 0,10–0,23 s na půdorys. Celý chráněný proces trval **50,136 s**, spotřeboval **38,313 CPU s** a jeho nejvyšší součet přidělené paměti byl **144,31 MB**. Vnitřní měření pracovního procesu, zahrnující načtení a vyhodnocení, bylo 28,233 s; liší se rozsahem od vnějšího měření. Jde o jediný běh, nikoli stabilní medián opakování. Přesný záznam je v `.work/cb-roof-simplification/logs/templates.log.metrics.json`. Po dokončení bylo na C: volných 68,22 GB a projekt měl 4,908 GB (desetinné jednotky).

Nejpřesvědčivější kandidáti jsou sever arény s jedinou sedlovou šablonou a jih arény se třemi objemy. U jižního půdorysu ovšem spojení částí dosahuje výškového skoku **9,65 m**: bez vizuální kontroly nelze rozhodnout, zda správně zachycuje skutečný výškový rozdíl, nebo vytváří nevhodný šev. Vyšší RMSE navzdory nízkému P95 také upozorňuje na menší množství velkých odchylek. Kostel se dělením zlepší, ale zbylá chyba 1,49 m a skok 5,36 m neumožňují automatické přijetí.

U sportovní haly, Wortnerova domu, Masných krámů a Krajinské 43/8 nebyl přijat žádný řez. Hledání tam pouze přidalo výpočetní čas a ponechalo výchozí geometrii. To je důležitý negativní výsledek: tato omezená varianta není univerzální metodou pro členité střechy. Parametry ani dělení nebyly po zjištění holdout výsledků upraveny. Žádný model nebyl schválen k nasazení do produkční mapy.

Příkaz pracovního procesu: `.venv\Scripts\python.exe -X utf8 scripts\roof_simplify_templates.py --execute`. Sám nepřebírá systémový limit paměti; spouštět pod `scripts/resource_guard.py` s limitem 2 GB a dvěma CPU, s povinnou kontrolou volného disku alespoň 25 GB a projektu nejvýše 20 GB. Produkční mapa ani dřívější výsledky se tím nemění.
