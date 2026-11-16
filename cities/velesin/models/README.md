# Sportcentrum Velešín, Strahovská 661

První vlastní model Tiny Towns. Opravuje jediný vstupní polygon Overture
`78e32d1e-ecfa-4e1b-a00f-db417ea5af1b` (OSM `w104235783@2`), který Izomapa
zobrazovala jako jeden objem s plochou šedou střechou.

## Úpravy

- Tenisová hala: přibližně 37,65 × 19,35 m, téměř půlválcová zelená střecha,
  nejvyšší bod přibližně 10 m nad místním terénem.
- Dvě výškové úrovně spojovací části a dvě úrovně squashové haly.
- Samostatné půdorysy a klikací obrysy zachovávají otevřený průchod.
- Barvy střech vycházejí z ortofota ČÚZK. Fasády jsou zatím neutrální a
  neověřené; bez fotografií z ulice nejsou doplněna okna ani dveře.

Měřítko a poloha vycházejí z OSM/Overture, profil tenisové střechy z laserového
mračna DMP 1G CKRU30. Novější povrchový rastr DMP 0,5 m doplňuje výšky menších
částí. Volný kruhový proklad naměřeného profilu má poloměr asi 9,20 m;
zjednodušený model respektuje celou šířku půdorysu a používá 9,675 m. Rozměry
nejsou geodetickým zaměřením. Datum vytvoření LAS souboru není datum snímkování.

## Zdroj a přenos do dalšího rendereru

Upravuj `sportcentrum-velesin.source.json`, potom spusť z kořene repozitáře:

```text
.venv\Scripts\python.exe -X utf8 scripts/build_sportcentrum.py
```

Výstupy jsou v `cities/velesin/assets/models/`:

- `sportcentrum-velesin.json`: zdrojová síť, materiály a samostatné půdorysy;
- `sportcentrum-velesin.glb`: samostatný glTF 2.0 model pro další 3D nástroje.

Jednotky jsou metry. JSON používá osy východ/sever/nahoru a kotvu WGS84.
GLB používá X = východ, Y = nahoru, Z = jih. Oba soubory mají zdroje a
nejistoty. Nulová výška je místní podlaha; spodní dva metry stěn slouží jako
zapuštěný sokl pro navázání na nepřesný mapový terén.

`assets/custom_prep.py` připojuje model ke scéně a klikací vrstvě; `assets/custom_models.js`
kreslí vlastní trojúhelníky. Společný renderer nebyl změněn. Při aktualizaci
Overture ověř identifikátor zdrojové budovy — pokud zanikne, je třeba opravit
napárování a porovnat nový půdorys.

Po změně modelu lze sestavit již stažený náhled:

```text
.venv\Scripts\python.exe scripts/towns.py build velesin --profile preview --render-only
```

Celou obec sestaví stejný příkaz bez `--profile preview`; zkušební výřez není
hotovou mapou celého správního území.

## Pracovní podklady

Na tomto počítači jsou v `podklady/sportcentrum-velesin/` (nepatří do gitu):
originální ortofoto, výškový TIFF, vyznačené části, graf příčného profilu,
vybrané laserové body CSV, měření JSON a náhledy před/po. `download-manifest.json`
obsahuje přesné URL, souřadnicový systém, výřez a čas stažení.

`scripts/sportcentrum_review.py` z uložených vstupů obnoví kontrolní obrázky.
ČÚZK podklady jsou použity pod CC BY 4.0, půdorys pod ODbL 1.0. U každého
budoucího výstupu zachovej uvedení zdrojů a příslušné licenční informace.
