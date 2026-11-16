# Velešín: připravená dávka čtyř ulic

Výběr: náměstí J. V. Kamarýta, Družstevní, Školní, U Přehrady. Používá se stejný algoritmus střech jako u ČB, bez změny jeho vah. Zdrojem jsou místní husté DMPOK CKRU30/31 a adresy/půdorysy Overture. Sportcentrum ani mapové dlaždice se touto dávkou nepřepisují.

Audit dostupných dat našel 146 jednoznačně přiřazených budov. Dvě adresy bez odpovídajícího půdorysu se zaznamenají do selection.json k dořešení. Neadresované objekty podél ulic se do tohoto výběru automaticky nepřidávají.

Příprava byla 17. 11. 2026 pozastavena pro nedostatek paměti (přibližně 270–325 MB volné RAM). Po dočasném uvolnění RAM prošlo 9 cílených testů; následný start skutečné dávky zastavila pojistka při opětovném poklesu pod 1 GB. Nové modely pro tyto ulice dosud nebyly vypočteny. Následující příkazy spouštějí Python lokálně a chrání RAM i disk. Při nedostatku paměti skončí bez výpočtu; nesnižovat ochranné prahy.

Z kořene projektu v PowerShellu, v aktivovaném .venv:

```powershell
python scripts/resource_guard.py run --min-available-gb 1 --max-ram-gb 1.5 --wait-memory-seconds 0 --log .work/velesin-roof-v2/streets-select.log -- python scripts/select_roof_streets.py --city velesin --street "náměstí J. V. Kamarýta" --street "Družstevní" --street "Školní" --street "U Přehrady" --output cities/velesin/experiments/roof-streets-selection-20261117

python scripts/resource_guard.py run --min-available-gb 1 --max-ram-gb 1.5 --wait-memory-seconds 0 --log .work/velesin-roof-v2/streets-inputs.log -- python scripts/roof_address_inputs.py --city velesin --requests cities/velesin/experiments/roof-streets-selection-20261117/requests.json --output cities/velesin/experiments/roof-streets-inputs-20261117 --resume

python scripts/resource_guard.py run --min-available-gb 1 --max-ram-gb 1.5 --wait-memory-seconds 0 --log .work/velesin-roof-v2/streets-models.log -- python scripts/roof_batch.py --inputs cities/velesin/experiments/roof-streets-inputs-20261117/inputs.json --output cities/velesin/experiments/roof-streets-models-20261117 --url-base http://127.0.0.1:8877/ --open
```

Každý další modelovací běh musí mít novou výstupní složku. Při opakování přípravy vstupů `--resume` ověří totožný výběr. Modely, časy, rozhodovací metadata i HTML vzniknou automaticky. Plánovaný report bude na `http://127.0.0.1:8877/cities/velesin/experiments/roof-streets-models-20261117/report.html` až po úspěšném výpočtu; zatím neexistuje.
