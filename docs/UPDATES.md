# Aktualizace a rozšiřování Tiny Towns

## Jeden fork pro obě města

Cílový repozitář je `traja-traja/tiny-towns`, fork `adamklatovsky/izomapa`. Vlastní úpravy ukládáme na `main`, původní projekt sledujeme jako `upstream`. Lokální adresář může mít jiný název než repozitář.

Základ této přípravy identifikuje `upstream.json`. Před aktualizací porovnáme změny od uloženého commitu. Nesynchronizujeme hlavní větev automatickým přepsáním.

Po běžném naklonování vlastního forku lze jednou nastavit zdroj:

```sh
git remote add upstream https://github.com/adamklatovsky/izomapa.git
```

Aktualizaci připravíme na samostatné větvi, projdeme rozdíly, sloučíme změny a ověříme oba výřezy. Do `main` se dostane až zkontrolovaný výsledek. Například v čistém pracovním stromu:

```sh
git fetch upstream
git switch -c update/izomapa-YYYY-MM-DD
git log --oneline HEAD..upstream/main
git diff HEAD...upstream/main
git merge upstream/main
python -m unittest discover -s tests -p "test_towns.py"
python -m unittest discover -s tests -p "test_city_coverage.py"
```

Testy pokrytí vyžadují prostředí `.venv`. Následuje zkušební render obou měst, vizuální kontrola švů a ověření vlastních modelů. Závislosti případně doinstalujeme podle změn upstreamu. Nový přijatý commit zapíšeme do `upstream.json`. Frekvenci kontrol volíme podle potřeby projektu; automatické sledování zatím není nastavené.

## Oddělené druhy aktualizací

| Co měníme | Postup |
| --- | --- |
| Kód původní Izomapy | Kontrolované sloučení z upstreamu, testy a nové rendery podle změn |
| Geografická data | Samostatně stáhnout novou verzi, zaznamenat zdroj a datum, porovnat výsledek |
| Hranici nebo střed mapy | Znovu vygenerovat konfiguraci a použít nové pracovní adresáře |
| Ruční budovy a lokální opravy | Upravovat soubory v `cities/<město>/assets/`, znovu vykreslit dotčené čtverce |
| Projekty a městské informace | Uchovávat zdroj, datum platnosti a souřadnice nezávisle na rendereru |

Výměna kódu sama neaktualizuje data uložená v cache. Některé nástroje upstreamu mají zdrojové edice nebo URL přímo v kódu. Nové vydání dat je proto samostatná ověřovaná změna. Před zpracováním nových dat odložíme stávající `.work/<město>` stranou a zachováme poslední publikovaný výstup.

## Hranice a reproducibilita

`boundary.geojson` je uložená hranice obce s poskytovatelem, URL a datem stažení v `boundary-source.json`. Jde o hranici pro vizualizaci, nikoli podklad pro rozhodování o parcelách. `profile.json` obsahuje texty, střed a rozšíření mapy; vygenerovaný `mesto.json` používá přímo Izomapa. `coverage.json` dokládá pokrytí polygonu. Uložená hranice zachovává i oddělené části obce a malé úseky u okrajů. Čtverce sahají za administrativní hranici.

```text
.venv/Scripts/python scripts/configure_city.py plan velesin
.venv/Scripts/python scripts/configure_city.py generate velesin
.venv/Scripts/python scripts/configure_city.py generate velesin --preview 1
```

Na Linuxu/macOS použij `.venv/bin/python`. `scripts/fetch_city_inputs.py <město>` umí načíst hranici z ČÚZK, obnovit chybějící referenční terén a připravit konfigurace. Existující podklady zachovává a ověřuje jejich identitu; aktualizaci hranice a konfigurací provede jen s `--replace`. `plan` vypíše potřebné referenční dlaždice terénu a jejich URL; při ručním stahování musí být uložené do uvedených cest. `terrain-source.json` zaznamenává stažené soubory a jejich kontrolní součty. Generátor bez nich výškovou referenci nevymýšlí. Volba `--replace` nejprve zálohuje existující konfiguraci. Preview má stejnou výškovou referenci jako celá mapa, ale nepředstavuje celé území.

## Budoucí mapa v reálném 3D

Dnešní Izomapa vytváří 3D scény při sestavení a do webu posílá hotové obrazové dlaždice. Přechod na živé 3D bude vyžadovat jiný prohlížeč a napojení na data. Hotové obrázky nenahradí 3D model.

Až vzniknou vlastní budovy, uchováme zdrojovou geometrii zvlášť, ideálně i v přenosném GLB, s jednotkami, orientací, polohou WGS84 a zdroji podkladů. Napojení na `assets/custom_models.js` bude adaptér pro Izomapu. Samotný model, městská data a jejich identifikátory tak půjde použít znovu; napojení na jiný renderer bude nutné dopracovat. Stávající lokální souřadnice a parametry specifické pro Izomapu nejsou samy o sobě zárukou přenositelnosti.

Budoucí projekty budou mít vlastní identifikátor, geometrii, stav, zdroje a čas platnosti. Propojení s usneseními rady a rozpočtem lze přidat nad těmito daty.

## Dopravní model Českých Budějovic

Pohyb aut v původní Izomapě je animace. Ani hustota odvozená ze sčítání sama nepočítá objížďky a vznik kolon. Budoucí model musí oddělit síť, poptávku, kapacity, pravidla křižovatek a scénáře uzavírek od vizualizace. Síť i poptávku je nutné kalibrovat a scénáře porovnávat se stejnými předpoklady. Výsledné průjezdy a zdržení pak může zobrazit izometrická i skutečně 3D mapa.

V této fázi model ani příjem živých dopravních dat nejsou implementované.
