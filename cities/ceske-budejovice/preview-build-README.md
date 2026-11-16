# České Budějovice — skutečný základní preview build

Stav: **dokončeno, UI kontrola prošla**. Dokončeno 26 z 26 kroků. Report zachycuje základní variantu před případnými pozdějšími změnami střech. Záznam je lokální; mapa tím nebyla publikována.

Výřez centra má 2,3 × 2,3 km (5,29 km²), střed [14.475588, 48.97468]. Používá původní základní renderer střech a deterministické skripty. V generovací pipeline nebylo volání generativních modelů.

Velešínský benchmark měl všech šest kombinací zdroj/metoda hotových před úspěšným ČB harvestem. Ponechání základních střech vychází z toho, že nebylo doloženo zlepšení celé pipeline v rámci +20–30 % času. Podrobný ČB pilot je následná, samostatná práce.

## Naměřené kroky

| Krok | Hotovo | Součet wall s | Max. commit MB |
|---|---:|---:|---:|
| Stažení a ořez Overture + DEM | 1/1 | 1021.524 | 436.5 |
| Stažení a extrakce DMP1G | 1/1 | 143.078 | 316.0 |
| Výšky budov z DMP1G | 1/1 | 31.310 | 1026.8 |
| Ortofoto a maska stromů | 1/1 | 15.351 | 122.1 |
| Plochy ZABAGED | 1/1 | 133.823 | 81.5 |
| Pole z ortofota | 1/1 | 4.589 | 90.7 |
| Příprava scény | 1/1 | 132.270 | 2854.1 |
| Rendery 4 ročních dob + světla | 5/5 | 173.882 | 3271.1 |
| Deep Zoom pyramidy (5) | 5/5 | 361.240 | 2015.4 |
| Exporty stromů (4) | 4/4 | 73.917 | 1732.1 |
| Rychlé náhledy (4) | 4/4 | 94.312 | 145.6 |
| Overlay a sestavení webu | 1/1 | 66.954 | 415.7 |

Součet dokončených procesů: **2252.250 s** (37.54 min). To není celkový uplynulý čas od zahájení práce. Nezahrnuje vývoj, mezikrokové kontroly a čekání ani dva dřívější přerušené harvesty. Jejich přepsané metriky nelze zpětně obnovit; čas není odhadován.

Paměť je špičkový **commit celého procesového stromu**, nikoli rezidentní fyzická RAM. Maximum kroků je 3.271 GB. CPU čas prvních 25 kroků základní guard nezaznamenal. Úspěšný web krok po aktualizaci guardu má CPU 44.046875 s; celkový CPU čas celé mapy není znám. Krátké procesové časy navíc obsahují zpoždění přibližně sekundového pollingu.

## Samostatná příprava STAC indexů

| Dávka | Indexů | Wall s | Max. commit MB |
|---|---:|---:|---:|
| STAC index budov | 1 | 527.049 | 25.8 |
| STAC indexy dalších vrstev | 9 | 439.996 | 27.1 |

Obě dávky běžely souběžně; jejich časy se nesčítají do skutečného uplynulého času. Úspěšný harvest využil hotové indexy a trval 1021.524 s. Indexace vybrala 19 referencí na datové soubory z 984 celosvětově indexovaných souborů; následně se stále aplikoval původní prostorový filtr řádků.

## Data a výsledná scéna

| Vrstva | data — řádků | data_all — řádků |
|---|---:|---:|
| address | 3996 | 4370 |
| building | 9259 | 10378 |
| division_area | — | 24 |
| infrastructure | 9426 | 10299 |
| land | 1091 | 1155 |
| land_cover | 40 | 43 |
| land_use | 1183 | 1317 |
| places | 2619 | — |
| segment | 5267 | 5750 |
| water | 129 | 145 |

data má rezervu 300 m a data_all 400 m; tyto počty nelze zaměňovat s výslednou scénou. Ta obsahuje **5454 objektů budov**, 12725 stromů, 93 mostních objektů a 3598 aut. Jde o serializované objekty, nikoli nezávislé ověření počtu reálných staveb.

DMP1G: 7 listů (CBUD12, CBUD13, CBUD14, CBUD22, CBUD23, CBUD24, CBUD33). Změřeno 8848 záznamů budov; použito 8572, 276 ponecháno ke kontrole. DMPOK se v základním preview nepoužil.

Základní web obsahuje 430 souborů o velikosti 73.79 MB. Jde o lokální snapshot po dokončení; nic nebylo publikováno.
Render má 4 sezóny a světelnou vrstvu; každá má 17596 × 9468 px při 0,2 m/px a mřížku 18 × 10 dlaždic. DZI výstup používá WebP.

## Zdroje a kontrola

- [Oficiální katalog Overture STAC](https://stac.overturemaps.org/catalog.json), release 2026-10-21.0. Konkrétní collection URL a vybrané S3 objekty jsou v JSON.
- [DMP1G ATOM](https://atom.cuzk.gov.cz/DMP1G-SJTSK/DMP1G-SJTSK.xml): výšky střech vůči terénu.
- [ČÚZK ortofoto WMS](https://ags.cuzk.gov.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer): barevná maska korun a podklad pro klasifikaci polí.
- [ZABAGED WFS](https://ags.cuzk.gov.cz/arcgis/services/ZABAGED_POLOHOPIS/MapServer/WFSServer): plochy; Terrarium z14 pro terén.

UI QA: **prošla** — žádné JavaScriptové chyby, žádné neočekávané lokální chyby požadavků, mobil bez vodorovného přetečení, vyhledání Krajinské vrací dvě ulice. Letní a zimní zobrazení i detail centra mají uložené screenshoty. Dokumentovaná 404 `mhd.json` je vypnutá volitelná MHD bez GTFS, kterou prohlížeč ošetří; falešná MHD data se nevytvářejí. QA běh trval 20.089 s a není součástí součtu build kroků. Finální pozorování při úspěšném web kroku: projekt 3.309 GB, na C: volných 70.039 GB. Metriky jednotlivých procesů, checkpoint, jejich cesty a SHA-256 jsou v preview-build-report.json. Velikost lokálních dat není měření přenosu po síti.

Limity během buildu: projekt nejvýše 20 GB, zastavit při méně než 25 GB volného C:, procesový strom nejvýše 4 GB commit, affinity nejvýše 2 CPU na job, sezóny postupně. Dočasná ochrana před uspáním je součástí guardu; nevynucuje rozsvícený displej.

## Uchovaný neúspěšný web pokus

První web pokus skončil kódem 1, protože staré `mhd.py` považovalo vypnuté GTFS za chybu. Orchestrace byla opravena podmíněným spuštěním MHD; všech 25 předchozích výstupů bylo před obnovením ověřeno. Uchovaný pokus stál 35.777 s a 419.8 MB peak commit. Je samostatně v JSON, nepřičítá se do úspěšné tabulky. Úspěšné kroky spolu s tímto uchovaným neúspěšným pokusem dávají 2288.027 s procesového wall součtu; stále to není celkový čas projektu.

STAC síťová metadata měla 8 vláken na každou ze 2 souběžných indexovacích dávek; limit 2 se vztahuje na výpočetní vlákna/CPU affinity následných jobů.
