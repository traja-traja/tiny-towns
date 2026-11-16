# Podloubí: Krajinská 43/8, 44/10 a 45/12

Tento samostatný experiment porovnává skutečnou geometrii otvorů u tří navazujících domů. Celoměstský renderer ani hotové modely Velešína nemění. Důkazy, půdorysy, vazby na adresy, licence fotografií a přesné parametry jsou v `source-review.json`; naměřené výsledky v `results.json`.

## Co je doloženo

| Dům | Zdrojové UUID | Doložená pole podloubí |
|---|---|---:|
| Krajinská 43/8 | `766e2987-0af0-4165-b25a-216597858fa9` | 2 |
| Krajinská 44/10 | `acf04bcb-18f5-41ec-b7e7-14232e12fc1f` | 2 |
| Krajinská 45/12 | `9659768d-7c0c-48f6-a646-2c1296afccd2` | 3 |

Identita je spojením adresního bodu ČÚZK uvnitř zdrojového půdorysu a označených referenčních fotografií. Městská [encyklopedie podloubí](https://encyklopedie.c-budejovice.cz/clanek/podloubi) a [Krajinské třídy](https://www.encyklopedie.c-budejovice.cz/clanek/krajinska-trida) dokládá urbanistický kontext. [NPÚ pro čp. 44](https://pamatkovykatalog.cz/mestsky-dum-21205419) popisuje dvě arkády a střední pilíř.

Přímé fotografie, všechny Czeva, 28. září 2012, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/): [43/8](https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_8_(01).jpg), [44/10](https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_10.jpg), [45/12](https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_12_(01).jpg). Byly vizuálně prohlédnuty. U čp. 43 část horního profilu zakrývá reklama. Snímky jsou složená panoramata; čp. 45 má v metadatech dokonce sférickou projekci. Nejsou proto přesným metrickým zaměřením. Fotografie nepřibalujeme ani negenerujeme jejich náhrady. Jejich stáří neprokazuje dnešní stav vybavení.

## Co současný engine dělá

`prep.py` ukládá vnější obrys a výšku; `render.html` na každé hraně vytvoří souvislou stěnu od základny k okapu. Konkrétní entity 2496, 3689 a 3181 nemají geometrii otvoru. Pro tuto trojici jde o plnou extruzi i v místě skutečného podloubí. Zvláštní přístřešky a vlastní modely dominant nejsou obecnou podporou arkád.

V lokální vrstvě segmentů u vybrané řady chybí `is_covered` i `is_tunnel`. Absence značky neznamená absenci podloubí. Jinde se podařilo ověřit původní `tunnel=building_passage` přímo v historických verzích OSM API pro pasáž Krajinská, Plachého a Radniční. Přesná ID, odpovídající díly agregovaných segmentů a protínané půdorysy jsou v JSON. `covered=yes` není samo o sobě důkaz arkády; zastřešený stojan na kola také není podloubí.

## Srovnávaná geometrie

- **Baseline:** plná prizma původního půdorysu.
- **Pilíře a překlad:** spodní uliční pás je skutečně odebrán, zachována zadní a horní hmota, vpředu přidány pilíře a překlady.
- **Oblouk 8 / 16:** stejný prázdný prostor a pilíře, ale nadpraží kopíruje parametrický oblouk s osmi nebo šestnácti díly.

Úplná původní extruze pod otvory nezůstává. Modely tvoří uzavřené dotýkající se komponenty; jejich vnitřní společné plochy mohou být zachovány. Netvrdíme, že jde o jeden topologicky sjednocený CityGML solid. Horní uzávěr je záměrně rovný a mezi variantami stejný, aby porovnání izolovalo problém otvorů.

| Parametr | Použito | Jistota |
|---|---:|---|
| Počet polí | 2 / 2 / 3 | Doložen fotografiemi |
| Uliční hrana a šířka | Z původních půdorysů | Mapový podklad, nikoli zaměření pilířů |
| Hloubka | 2,0 a 3,5 m | Dva nezměřené scénáře |
| Výška vrcholu otvoru | 3,6 m; uvažovaný rozsah 3,0–4,5 m | Odhad |
| Rovný podhled | 4,0 m | Zjednodušení skryté konstrukce |
| Šířka pilíře | 0,6 m; rozsah 0,4–1,0 m | Odhad |
| Tloušťka přední stěny | 0,5 m; rozsah 0,35–0,8 m | Odhad |
| Výška horní hmoty | Převzata z běžného preview | Stálá kontrolní hodnota, ne nové zaměření |

Oblouky jsou kruhové segmenty s rozdílným poměrem vzepětí k šířce podle kvalitativního vzhledu. Jejich přesný poloměr není doložen. Letecký povrchový model se zde nepoužívá k odhadu skrytého podhledu, zadní stěny ani hloubky.

## Měření a testy

Každý model vznikne třikrát. Ukládají se jednotlivé časy i medián generace, zvlášť export, počty vrcholů a trojúhelníků, objem a velikost souboru. Proces běží přes `resource_guard` s limitem 1 GB a požadavkem alespoň 1 GB dostupné paměti při startu. Naměřený peak commit je v `results.json`. Čas exportu zahrnuje také průběžnou kontrolu diskového rozpočtu; nejde o čistou rychlost disku.

Testy pracují s exportovanými trojúhelníky: vstupní paprsek v úrovni očí projde otvorem, narazí do pilíře a do nadpraží. U baseline stejný vstupní paprsek zastaví stěna. Samostatný test obsazenosti odliší prázdný koridor od úsečky uzavřené uvnitř plného tělesa. Testuje se i podélné propojení sousedních domů. Jde o geometrickou vlastnost modelu, nikoli potvrzení veřejné přístupnosti či bezbariérovosti.

Pro porovnání věrnosti je dále třeba aktuální čelní a podélná fotografie nebo pozemní měření se známým měřítkem. Hodnotit lze masku otvorů, polohu pilířů a průhled z ulice; hloubku a skrytou klenbu je nutné ověřit zvlášť. Pro renderer se má na stejném zařízení měřit medián/p95 času snímku, načítání, draw calls a velikost scény. Zde naměřená generace meshe není FPS celé mapy.

## Opakování a export

```powershell
.venv/Scripts/python.exe -X utf8 scripts/cb_arcade_experiments.py --run
```

Výsledkem je 21 malých JSON modelů v `meshes/`: tři baseline a pro každý dům dvě hloubky × tři reprezentace otvorů. Soubor obsahuje `vertices`, trojúhelníkové `faces`, skupiny materiálů a identitu varianty. Všechny modely mají společný vodorovný počátek v EPSG:5514, metry a osu Z vzhůru relativně k podlaze; nepředstírají absolutní Bpv výšku. `facade_frame` určuje uliční hranu, směr podél fasády a směr dovnitř domu. Pohled na otvory má být proti `inward_v_xy`, s cílem přibližně ve výšce očí.
