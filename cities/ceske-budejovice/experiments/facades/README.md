# Izolovaný test barev fasád — České Budějovice

Tato složka odděluje dohledané podklady, skutečně provedený malý barevný test a návrhy dalších metod. Výběr obsahuje **5 referenčních objektů, z nich 3 pro první výpočetní test**. Nejde o rekonstrukci celého centra, změnu rendereru ani o důkaz současných přesných odstínů.

Strojově čitelné podklady jsou v [source-review.json](source-review.json). Výpočty a všechny jednotlivé časy jsou v [results.json](results.json); schematická SVG a obrázky vyznačených vzorků jsou uložené vedle něj. Identifikátory budov jsou stejné jako u výběru agenta `cb_preview`; Krajinská 44/10 se sdílí s experimentem podloubí.

## Výběr a fotografie

| Objekt / Overture UUID | Konkrétní fotografie, autor, datum a licence | Co skutečně dokládá; omezení |
|---|---|---|
| Radnice — `e45c2485-616a-4003-92e4-428ce930f490` | [Donald Judge, 30. 12. 2023](https://commons.wikimedia.org/wiki/File:30.12.23_Ceske_Budejovice_28_(53432289739).jpg), [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | Čelní vzhled po obnově fasády v roce 2022; modrošedé pole a světlé členění. Smíšené zimní světlo, stín, strom a další překážky. **Zařazena do testu.** |
| Puklicův dům, Krajinská 36/2 — `427eb7c5-9db7-4919-9d98-7cf5bdef8e98` | [Xth-Floor, 15. 9. 2012](https://commons.wikimedia.org/wiki/File:Puklic%C5%AFv_d%C5%AFm_-_n%C3%A1m%C4%9Bst%C3%AD_P%C5%99emysla_Otakara_II.jpg), [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) | Lososové pole, světlé pásy a dvě čelní arkády na tehdejší fotografii. Nedokládá nátěr v roce 2026 ani hloubku podloubí. **Zařazena do testu.** |
| Krajinská 44/10 — `acf04bcb-18f5-41ec-b7e7-14232e12fc1f` | [Czeva, 28. 9. 2012](https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_10.jpg), [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) | Zelené pole a světlé rámy, dvě arkády. NPÚ samostatně potvrzuje zelenobílou barevnost. Použito jen horní průčelí; hluboký stín přízemí vynechán. EXIF uvádí panorama složené z pěti snímků: **není metrickou předlohou jedné roviny. Zařazena do testu.** |
| Palác Včela, Karla IV. 92/1 — `5962baef-4d3a-4d16-80c1-fb9f46dd7e93` | [Anaj7, 21. 4. 2018](https://commons.wikimedia.org/wiki/File:%C4%8Cesk%C3%A9_Bud%C4%9Bjovice,_pal%C3%A1c_V%C4%8Dela_(01).jpg), CC BY-SA 3.0 | Skutečný výrazně členitý historický dům. Protisvětlo, lampa, mnoho teplých barevných rolí a malé čisté plochy. **Po vizuální kontrole nezařazena do prvního dvoubarevného výpočtu**, ponechána jako zátěžový příklad další fáze. |
| Masné krámy, Krajinská 29/13 — `3afe9e11-0b96-481f-abcf-4c7fb28829eb` | [Anaj7, 22. 10. 2018](https://commons.wikimedia.org/wiki/File:%C4%8Cesk%C3%A9_Bud%C4%9Bjovice,_masn%C3%A9_kr%C3%A1my,_Krajinsk%C3%A1_13_(01).jpg), CC BY-SA 3.0; [Anaj7 / Jana Sekyrová, 14. 12. 2020](https://commons.wikimedia.org/wiki/File:Masn%C3%A9_kr%C3%A1my,_%C4%8Cesk%C3%A9_Bud%C4%9Bjovice,_December_2020.jpg), CC BY-SA 3.0 | První fotografie zachycuje soumrak se zapnutými teplými reflektory, druhá noční vánoční osvětlení. Užitečné pro fronton, pilastry a siluetu, **obě vyřazeny pro barvu omítky**. |

Všech šest uvedených fotografických náhledů bylo skutečně vizuálně zkontrolováno. Na úrovni rešerše šlo dohromady o 787 314 bajtů náhledů; nejde o stažené plné originály ani o dobu výpočtu. Při skutečném běhu se znovu používají lokálně uložené referenční náhledy se SHA-256; jejich skutečné bajty jsou zaznamenané ve výsledcích. Rok pořízení je oddělen od roku nahrání na Commons.

Městské a památkové zdroje potvrzují především identitu a architektonické prvky:

- [Radnice v městské encyklopedii](https://www.encyklopedie.c-budejovice.cz/clanek/radnice) uvádí obnovu východní a jižní fasády v roce 2022. [Usnesení města 390/2022](https://www.c-budejovice.cz/sites/default/files/meeting_resolutions/z_rm_a_28-03-2022_0_0.pdf) potvrzuje vypsání zakázky, samo ne její dokončení ani barvu.
- [Oficiální turistický portál: palác Včela](https://budejce.cz/aktivity/12-palac-vcela) potvrzuje adresu a bohatý plastický dekor.
- [Oficiální turistický portál: Masné krámy](https://www.budejce.cz/gastro-zazitky/6-masne-kramy) potvrzuje adresu Krajinská 13.
- [Městský územní plán, historické jádro, 06/2023](https://data.c-budejovice.cz/Oupa/VEREJNE_VYHLASKY/Z_96_az_99_vcetne_UZ/UZ_UPnM_CB_poZm99_UredniDeska_OUP__2023-06-15/TEXTY/Kryci%20listy/1_vnitrni%20mesto/1.1.1_Historicke_jadro_2023-06.pdf) uvádí Puklicův dům čp. 36/2, Krajinská. NPÚ stránka Puklicova domu při kontrole vracela HTTP 500, proto není jediným dokladem.
- [NPÚ: Krajinská 44/10](https://pamatkovykatalog.cz/mestsky-dum-21205419) popisuje dvě arkády, široké rámy, římsy a zelenobílou barevnost. Text není kolorimetrické zaměření a datum popisovaného nátěru není uvedeno.

Odkaz na městskou fotografii sám nedokládá volnou licenci. Pro zobrazení, ořezy a odvozené náhledy používáme výše uvedené konkrétní fotografie Commons. U každého odvozeného obrázku zachováváme autora, licenci, datum, odkaz a popis změn; výřezy z CC BY-SA ponecháváme pod stejnou nebo kompatibilní licencí. Vyhledávač byl pouze cestou k původnímu zdroji.

## Co přesně počítá první experiment

Spuštění z kořene projektu:

```powershell
.venv\Scripts\python.exe -X utf8 scripts/cb_facade_experiments.py --check
.venv\Scripts\python.exe -X utf8 scripts/cb_facade_experiments.py
```

Skript sám spouští pracovní proces pod `resource_guard`: nově nejvýše 200 MB commitované paměti, vlákna výpočetních knihoven nastavená na jedno, nejvýše 10 MB fotografií a delší strana každé nejvýše 1600 px. Hlídá společný limit projektu 20 GB a zastavení při méně než 25 GB volného místa. Výsledky obsahují skutečnou špičku residentní RAM i samostatný údaj o commitované paměti. Nenutí systém stáhnout velký fotobalík a nemění nastavení napájení natrvalo.

Pro každou ze tří fotografií jsou ručně určeny **tři malé trénovací oblasti a dvě oddělené kontrolní oblasti pro hlavní omítku i dekor**. Souřadnice jsou uvedeny jako normalizované polygony a také jako původní pixelové obdélníky. Vzorky se vyhýbají oknům, hranám a výrazným stínovým přechodům; nelze však tvrdit, že osvětlení je kolorimetricky neutrální.

| Varianta | Výpočet | Co ověřujeme |
|---|---|---|
| `single_sample` | Středový pixel první předem vybrané oblasti každé barevné role. | Rychlá, ale citlivá výchozí varianta. |
| `lab_median` | Složkový medián L*, a*, b* ze všech pixelů tří trénovacích oblastí stejné role. | Stabilita vůči jednotlivým přepalům, šumu a drobným nerovnostem. |
| `lab_trimmed_median` | Stejná maska; vyřadit spodních a horních 10 % jasové složky L*, potom složkový medián. | Zda omezení jasových extrémů změní výsledek; **není to odstranění stínů ani získání albeda**. |

Doložený finální běh měl ještě hardlimit 300 MB, ale skutečná špička byla pouze 57,33 MB residentní RAM. Následně byl snížen pouze bezpečnostní limit skriptu na 200 MB; výpočty ani ROI se nezměnily a žádný nový běh nebyl předstírán.

Vstup s ICC profilem se převede do sRGB; bez profilu je předpoklad `assumed_sRGB` výslovně uložený. Převod sRGB → XYZ D65 → Lab je implementovaný pomocí NumPy; ověřuje se zpětný převod barev a bílý bod. [Dokumentace scikit-image](https://scikit-image.org/docs/stable/api/skimage.color.html#skimage.color.rgb2lab) vysvětluje stejné předpoklady barevného prostoru. Bez původního barevného terče tím neobnovujeme neznámou expozici a vyvážení bílé fotoaparátu.

Každá metoda má jeden nezapočítaný zahřívací běh a **tři uložená měření**. Načtení lokálního JPEG, dekódování, ICC převod a kopie pixelů se měří třikrát samostatně. Časy statistiky obsahují výběr pixelů a barevné převody, nezahrnují dekódování, lidský výběr ROI, hodnocení ani export. Export SVG a anotovaného PNG má vlastní čas. OS cache není vyprázdněna; první a další načtení proto nelze vydávat za stejný studený diskový test. Lidský čas rešerše a výběru ROI nebyl měřen a zůstává neznámý.

Kontrolní metrika je **DeltaE76 mezi výslednou barvou a mediánem každé odložené oblasti stejného JPEG**. Jde o diagnostiku citlivosti výběru a konzistence snímku; ne o nezávislé ověření správnosti pigmentu. Použitá [DeltaE76](https://scikit-image.org/docs/stable/api/skimage.color.html#skimage.color.deltaE_cie76) je eukleidovská vzdálenost v Lab; nesmí se zaměňovat za CIEDE2000.

## Co znamenají SVG

Každá barva má vlastní roli `main` nebo `decor`. SVG používají **stejný generický rastr rámů a říms pro všechny objekty**, aby bylo vidět pouze působení dvou barev. Označení `SCHEMATIC / NOT MEASURED` je přímo v obrázku i metadatech. Počet, tvar, poloha ani hloubka oken nejsou dokumentované. Tato SVG se nesmějí bez dalšího vydávat za fasádu konkrétního domu nebo připojit jako zaměřený model.

Podloubí a průchody řeší samostatný geometrický experiment. Tmavá plocha, oblouk ve fotografii či tato barevná zkouška nedokládají volný průchod, jeho hloubku ani návaznost cesty.

## Další metody: návrh, zatím bez výsledků

1. **K-means v ručně určené společné masce omítky.** Pevný seed, nejvýše 50 000 deterministicky vybraných pixelů, `k=2`, kontrolní varianta `k=3`, explicitní inicializace, `n_init=1`, nejvýše 50 iterací. L* lze v odděleném testu vážit méně než a*, b*. Clustery nemají samy význam „omítka“ a „ostění“: přiřazení se musí ověřit. [Dokumentace KMeans](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.KMeans.html) dokládá parametry reprodukovatelnosti a rozdílné paměťové nároky algoritmů. **Tento krok zde nebyl spuštěn.**
2. **Srovnání alespoň dvou záběrů stejného nátěru a různých fotografů.** Zaznamenat datum, světlo, ICC, nezávislé kontrolní oblasti, mezisnímkovou odchylku a čas lidské anotace. Před/po obnově nátěru netvoří kontrolní pár. Pro většinu vybraných domů zatím vhodný druhý současný snímek chybí.
3. **Jednoduchý skutečný vektorový dekor.** Po ručním ověření oddělit jednotlivé roviny průčelí, zvolit měřítko a zakreslit jen doložené římsy a pásy. [Homografie](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html) předpokládá rovinu; nedává sama hloubku, zakřivení nároží ani metrickou pravdu. Složené panorama Krajinské není vhodné jako jeden přesný projektivní podklad.
4. **Korekce osvětlení jen jako oddělený pokus.** Bez známého neutrálního terče může gray-world, histogramové vyrovnání či zesvětlení stínu přeměnit skutečnou barvu. První test proto žádnou takovou korekci nepoužívá.

Při pozdějším rozhodování porovnávat kvalitu, výpočetní čas a skutečný lidský čas současně. Zhoršení vůči ručně kontrolované paletě, nedoložený nátěr, málo čistých pixelů nebo různé role slité do jednoho clusteru mají být viditelný neúspěch, nikoli automaticky přijatá barva. Zde zatím neurčujeme univerzální práh „správné“ DeltaE ani absolutně správnou sRGB fasády.


## Naměřené výsledky finálního běhu

Běh 2026-11-16T00:35:11.431567+00:00 dokončil 3 budovy × 3 metody × 3 uložená opakování. Níže jsou mediány strojových časů v milisekundách, nikoli čas lidské přípravy.

| Objekt | Decode JPEG + barevný převod | Jeden vzorek | Lab medián | Ořezaný medián |
|---|---:|---:|---:|---:|
| Historická radnice | 23.398 | 8.480 | 20.217 | 11.067 |
| Puklicův dům | 36.000 | 5.057 | 6.642 | 7.077 |
| Měšťanský dům Krajinská44/10 | 23.603 | 3.002 | 6.383 | 5.151 |

Residentní RAM dosáhla 57.33 MB; peak commit celého hlídaného procesu 81.74 MB. Pracovní úsek před závěrečnou kontrolou disku trval 8.46 s, celý hlídaný proces 17.47 s. Tyto celkové časy zahrnují kontrolu rozpočtu, přípravu a výstupy, ne lidskou anotaci. Tři opakování za běžného zatížení počítače nestačí k tvrzení, že některá varianta je univerzálně rychlejší.

Použité zdrojové JPEG: **380 279 B**; všechny cache fotografie včetně nakonec nepoužité Včely: **505 157 B**. Devět SVG a tři ROI PNG mají dohromady **2 159 245 B**. Na konci měření zbývalo na disku přibližně 70,04 GB; projekt měl 3,31 GB.

Medián Lab zlepšil shodu s kontrolními oblastmi proti jednomu vzorku u obou rolí všech tří snímků. U radnice přesto zůstává hlavní role nekonzistentní: kontrolní DeltaE76 medián přibližně 11,69 oproti 3,25 u dekoru. **Paletu radnice proto nelze považovat za spolehlivě určenou pro mapu; potřebuje lepší obrazový podklad nebo další ručně ověřené oblasti.** Puklicův dům má diagnostické mediány 1,54/1,27 a Krajinská 1,57/1,72 (hlavní/dekor). Jsou to shody uvnitř historické fotografie, nikoli správnost současné barvy.

Ořezaný medián zde většinou mění odstín jen málo; nevytváří chybějící kalibraci. Výsledkem není automatické doporučení zavést všechny palety do rendereru.

## Kontrola a průzkumné opravy

Po prvním náhledu byly vzorky Krajinské posunuty mimo okap a stín hrany. Další zvětšená kontrola opravila umístění dekoru radnice a Puklicova domu: původní tenké obdélníky ležely ve stínu římsy nebo v sousedním poli. Finální plošky byly určeny podle viditelné materiálové role, nikoli optimalizací kontrolní DeltaE.

Předchozí úplný průzkumný výsledek je archivován v `.work/cb-facades/history/`; průběh popisuje `.work/cb-facades/review-log.json`. První průzkumný soubor byl před zavedením historie přepsán a jeho jednotlivé barevné hodnoty/časy se nedoplňují odhadem. Zůstaly pouze doložené celkové procesní údaje a důvod vyřazení.

Finální kontrola ověřila SHA-256 všech 3 použitých fotografií, shodu pixelových i normalizovaných ROI se skriptem, propojení všech 3 UUID s výběrem střech ČB, platné XML všech 9 SVG a existenci 3 maskových PNG. Aktuální ROI byly znovu vizuálně zhlédnuty. Zpětný převod sRGB/Lab, bílý bod D65 a nepřekrývání masek prošly samostatnou kontrolou před měřením.
