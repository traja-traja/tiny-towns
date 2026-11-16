"""Generate only the three requested level-ridge variants from cached DMPOK."""
from __future__ import annotations
import copy
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_name] = '1'
import numpy as np
from roof_level_ridge import infer_level_roof
from roof_v2_report import render_report
import resource_guard

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'cities/ceske-budejovice/experiments/roof-v2'
OUTPUT = SOURCE/'level-ridge'
IDS = ['d5572d0b-e221-4d5a-afab-bbca1768d7ce',
       'b3a47f0c-84bc-4052-ac91-8178a3015b5d',
       '70f1c8ae-faac-4b83-bbff-7b5a6061db86']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=['level-ridge', 'aligned-eaves', 'ridge-network'], default='level-ridge')
    parser.add_argument('--id', action='append', dest='ids', help='Only these building IDs; repeat for a subset')
    args = parser.parse_args()
    network = args.variant == 'ridge-network'
    third = args.variant in ('aligned-eaves', 'ridge-network')
    output = SOURCE/args.variant
    if third:
        from roof_eave_planes import infer_eave_roof
        infer = (lambda footprint, points: infer_eave_roof(footprint, points, allow_networks=True)) if network else infer_eave_roof
    else:
        infer = infer_level_roof
    start = time.perf_counter()
    resource_guard.check_budget(reserve_bytes=8*1024**2, force=True)
    baseline_path = SOURCE/'aligned-eaves/results.json' if network else SOURCE/'level-ridge/results.json' if third else SOURCE/'results.json'
    original = json.loads(baseline_path.read_text(encoding='utf-8'))
    inputs = json.loads((SOURCE/'inputs.json').read_text(encoding='utf-8'))
    by_id = {b['id']: b for b in original['buildings']}
    sources = {b['id']: b for b in inputs['buildings']}
    document = {k: original[k] for k in ('schema', 'city', 'source', 'crs', 'vertical_datum')}
    document.update(comparison_mode='level-ridge', buildings=[], status='complete',
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    original_results='../aligned-eaves/results.json' if network else '../level-ridge/results.json' if third else '../results.json',
                    visual_assessment_performed=False)
    with resource_guard.keep_awake():
        for oid in (args.ids or IDS):
            building = copy.deepcopy(by_id[oid])
            old_parts = building['parts'][len(sources[oid]['parts']):] if third else building['parts']
            new_parts = []
            for previous, source in zip(old_parts, sources[oid]['parts']):
                with np.load(ROOT/source['cache']['path']) as cache:
                    points = cache['train']
                result = infer(source['footprint'], points)
                variant = copy.deepcopy(source)
                variant.update(result=result, status='inferred', display_label='Verze 4 · hřebenová síť' if network else 'Verze 3 · hlavní římsy a navázané roviny' if third else 'Nová · vodorovný hřeben a okapy',
                               point_preview=previous.get('point_preview', []))
                new_parts.append(variant)
                print(json.dumps({'address': building['address'], 'seconds': result['timing']['total_seconds'],
                                  'written_variant': result['model']['metadata']['ridge_kind']}, ensure_ascii=False), flush=True)
            all_xy = np.concatenate([np.asarray(p['result']['model']['mesh']['vertices'])[:, :2] for p in old_parts+new_parts])
            right = np.array([np.cos(-.8), np.sin(-.8)])
            spacing = float(np.ptp(all_xy@right)+8)
            for p in old_parts:
                p['display_label'] = 'Verze 3 · beze změny' if network else 'Verze 2 · beze změny' if third else 'Původní · beze změny'
                p['display_offset_m'] = [*map(float, -right*spacing/2), 0.]
            for p in new_parts:
                p['display_offset_m'] = [*map(float, right*spacing/2), 0.]
            building['parts'] = old_parts+new_parts
            document['buildings'].append(building)
    document['generation_seconds'] = time.perf_counter()-start
    output.mkdir(exist_ok=True)
    (output/'results.json').write_text(json.dumps(document, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    render_report(output/'results.json', output/'report.html')
    page = (output/'report.html').read_text(encoding='utf-8')
    page = page.replace('<h1>Střechy v2</h1>', '<h1>Verze 3 · hlavní římsy a roviny střech</h1>' if third else '<h1>Vodorovný hřeben a okapy · 3 domy</h1>')
    page = page.replace('Jednoduché objemy podle mračna bodů. Interaktivní podklady k vašemu posouzení.',
                        'Při výchozím pohledu vlevo verze 2, vpravo verze 3. Verze lze vybrat také jednotlivě.' if third else
                        'Při výchozím pohledu vlevo původní model, vpravo nová varianta. Verze lze vybrat také jednotlivě.')
    begin, end = page.index('<div class="head-links">'), page.index('</header>')
    page = page[:begin]+'<div class="head-links"><a id="tile-link" hidden></a><a href="../report.html">Verze 1 ↗</a><a href="../level-ridge/report.html">Verze 2 ↗</a><a href="results.json">Modely JSON</a><a href="README.txt">Postup</a></div>\n'+page[end:]
    begin, end = page.index('<p class="rule">'), page.index('<details><summary>Porovnávané šablony')
    note = ('Hřeben je navázaný na hlavní směry stěn, jeho poloha nemusí být uprostřed. Výčnělky a výklenky se ořezávají souvislou rovinou střechy. Okapové linky zobrazují hlavní referenční římsy; malé výřezy nemusí mít celý obvod vodorovný. ' if third else '')
    page = page[:begin]+'<p class="rule">'+note+'Nová varianta používá společnou výšku hlavního hřebene a okapů. Výšky jsou nad stejným terénem jako původně. Vzhled posuzuje uživatel; další kontrolní měření nebylo spuštěno.</p>'+page[end:]
    (output/'report.html').write_text(page, encoding='utf-8')
    (output/'README.txt').write_text(
        'Tři domy: Hroznová 314/18, Jírovcova 1449/25, Havlíčkova 512/9.\n'
        'Původní results.json a report.html jsou zachovány.\n'
        'Spuštění: .venv/Scripts/python.exe scripts/cb_roof_level_ridge.py\n'
        'Data: již uložené výřezy hustého DMPOK, pouze train v NPZ.\n'
        'Postup: návrhy přímého/zalomeného hřebene; konce štít/valba; společný fit polohy hřebene, jeho výšky a výšky okapů.\n'
        'Vrcholy na okapu sdílejí jednu výšku, vrcholy hřebene druhou. Povrch se uzavře stěnami.\n'
        'Nepravidelný půdorys může vyžadovat rozdělení velké plochy na dva trojúhelníky. Koplanární plochy se slučují.\n'
        'Otvory půdorysu zůstávají zachovány. Toto je varianta jednoho hlavního objemu; nerozpoznává samostatně skutečně různě vysoká křídla.\n'
        'Požadovaná tolerance pro případné slučování samostatných úrovní je 0,5 m; detekce takových úrovní není v této omezené variantě implementována.\n'
        'Nebyly generovány mapové dlaždice ani prováděno optické hodnocení.\n', encoding='utf-8')
    if third:
        (output/'README.txt').write_text(
            'Verze 3: Hroznová 314/18, Jírovcova 1449/25, Havlíčkova 512/9.\n'
            'Spuštění: .venv/Scripts/python.exe scripts/cb_roof_level_ridge.py --variant aligned-eaves\n'
            'Zdroj: uložené výřezy hustého DMPOK, train v NPZ; stejné souřadnice a terén jako předchozí verze.\n'
            'Původní verze 1 a 2 zůstávají beze změny. Report porovnává verzi 2 (vlevo) a verzi 3 (vpravo).\n'
            'Dlouhé hlavní hrany určují společný rámec a referenční okapové linky; drobné zuby půdorysu se nestávají novými kontrolními body střechy.\n'
            'Hřeben je přímý nebo do L, rovnoběžný s hlavními směry rámce. Posun hřebene zůstává volný. Výšky hřebene a říms se fitují společně.\n'
            'Sedlová varianta má dvě hlavní okapové linky, jednostranná valba tři, oboustranná čtyři. Pultová má jednu horní hranu a jednu dolní římsu.\n'
            'Roviny dvou křídel L střechy sdílejí výšky a vnější plochy; jejich průsečíky tvoří hřeben, nároží a úžlabí.\n'
            'Celá střecha se ořízne skutečným půdorysem včetně výčnělků a otvorů; stěny se uzavřou pod výsledným povrchem.\n'
            'Lichoběžník: v rovině z=ax+by+c mají vodorovné linky ax+by=H-c a ax+by=E-c stejný směr. Vodorovný hřeben a vodorovný okap téže rovinné plochy proto musí být rovnoběžné.\n'
            'Sedlo mezi rovnoběžnými stranami funguje i při šikmých štítech. Dvě sbíhavé okapové strany obecně vyžadují šikmý hřeben, další plochu nebo zjednodušení půdorysu.\n'
            'Tento experiment používá společný hlavní rámec. U skutečně neparalelních stěn mohou být oříznuté okraje šikmé; hlavní referenční linky zůstávají vodorovné.\n'
            'Geometrický kontext (CGAL, roof model): https://doc.cgal.org/latest/Straight_skeleton_2/index.html\n'
            'Nevymazává se automaticky okraj mračna. Podezření na šum od vyššího souseda a návrh ochrany jsou jen v docs/TODO.md. Data zůstala nezměněná.\n'
            'Vzhled posuzuje Pavel. Bez AI hodnocení, bez nových obrázků či mapových dlaždic.\n', encoding='utf-8')
    if network:
        page = page.replace('Verze 3 · hlavní římsy a roviny střech', 'Verze 4 · hřeben do U nebo uzavřený okruh')
        page = page.replace('vlevo verze 2, vpravo verze 3', 'vlevo verze 3, vpravo verze 4')
        page = page.replace('<a href="results.json">', '<a href="../aligned-eaves/report.html">Verze 3 ↗</a><a href="results.json">')
        (output/'report.html').write_text(page, encoding='utf-8')
        (output/'README.txt').write_text(
            'Verze 4: rozšíření množiny kandidátů o U (3 úseky hřebene) a uzavřený okruh (4 úseky).\n'
            'Verze 3 měla jen přímý hřeben a L; další úsek proto nebylo možné identifikovat.\n'
            'Obecný algoritmus neobsahuje ID ani adresu domu. Parametr --id omezuje pouze zpracovanou dávku.\n'
            'Spuštění pro tuto budovu: .venv/Scripts/python.exe scripts/cb_roof_level_ridge.py --variant ridge-network --id '+document['buildings'][0]['id']+'\n'
            'Kandidáti se porovnávají podle shody s uloženými DMPOK body, jednoduchosti a podpory bodů u jednotlivých úseků. Skóre není pravděpodobnost.\n'
            'Všechny úseky sdílejí výšku hřebene a hlavní směry domu. Napojení tvoří společné roviny, nikoli nezávislé poskládané střechy.\n'
            'Existující dvůr poskytuje vnitřní referenční linky; výška vnitřní římsy se může lišit od vnější. Bez dvora se použijí pouze virtuální vnitřní linky a nevytvoří se nový otvor.\n'
            'Půdorys, otvor do dvora a zdrojové body se nemění. Úpravy směrem do dvora, uliční čáry a lichoběžníkové obrysy zatím nejsou součástí algoritmu.\n'
            'Report porovnává verzi 3 a verzi 4. Starší reporty zůstávají zachovány. Bez optického hodnocení výsledku a bez dlaždic.\n', encoding='utf-8')
    resource_guard.check_budget(force=True)
    print(json.dumps({'report': str(output/'report.html'), 'buildings': len(document['buildings']),
                      'generation_seconds': document['generation_seconds']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
