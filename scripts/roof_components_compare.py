"""Common evaluation for higher fidelity and explicit roof-component experiments.

Only evaluation and metadata aggregation happen here. Fitting workers never
receive held-out points, and references remain read-only.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
import shapely
from shapely.geometry import shape

import roof_simplification_common as common
from roof_simplification_compare import add_geometric_metrics, baseline_difference
from roof_pilot_roofer import predict_roofer_z
import resource_guard as guard

ROOT = common.ROOT
DEST = ROOT/'cities/ceske-budejovice/experiments/roof-components'
WORK = ROOT/'.work/cb-roof-components'
PREVIOUS = common.DEST/'results.json'
REFERENCES = ['roofer_lod22_reference','roofer_lod22_regular',
              'roofer_c035_eps050','template_parts4_train']
METHODS = {
    'roofer_lod22_reference': ('Původní Roofer · 0,888', 'Převzatá podrobná reference, epsilon 0,30 m, ochranné limity 120 rovin / 10 s.'),
    'roofer_lod22_regular': ('Původní Roofer · 0,60', 'Převzatá jednodušší reference; změněna váha složitosti, nikoliv verze programu.'),
    'roofer_c035_eps050': ('Jednodušší Roofer · 0,35 / 0,50 m', 'Převzaté silnější zjednodušení a volnější detekce rovin; ukazuje riziko ztráty věžičky.'),
    'template_parts4_train': ('Předchozí skládání až 4 objemů', 'Převzaté dělení osovými řezy a přizpůsobování šablon; odlišná metoda než nové dělení podle výškových skoků.'),
    'roofer_c095': ('Roofer · 0,95', 'Vyšší váha shody s body, epsilon 0,30 m; stejné ochranné limity jako reference.'),
    'roofer_c099': ('Roofer · 0,99', 'Ještě menší penalizace složitosti; může zachovat užitečné detaily i šum. Stejné limity jako reference.'),
    'roofer_c095_eps015': ('Roofer · 0,95 / roviny 0,15 m', 'Vyšší váha shody s body a přísnější detekce rovin. Epsilon není záruka konečné přesnosti modelu.'),
    'roofer_c095_caps240_30s': ('Roofer · 0,95 / vyšší limity', 'Samostatná diagnostika limitu: epsilon 0,30 m, 240 rovin / 30 s. Současně mění výpočetní rozpočet.'),
    'extract_compact15_patched': ('Výstupky 1,5 m · zaplněný základ', 'Automaticky vyčlení kompaktní vysoké prvky, doplní podkladovou střechu a zjednoduší základ; prvky zde úmyslně chybí.'),
    'extract_compact15_restored': ('Výstupky 1,5 m · navrácené prvky', 'Stejný zaplněný základ s odděleně zjednodušenými prvky. Nejisté náhrady zachovají původní komponentu.'),
    'extract_compact25_patched': ('Výstupky 2,5 m · zaplněný základ', 'Druhé pevné prostorové měřítko detektoru. Není to tolerance chyby ani požadovaná výška věže.'),
    'extract_compact25_restored': ('Výstupky 2,5 m · navrácené prvky', 'Vrácení samostatných komponent po zjednodušení základní střechy; viz masky a důvody přijetí.'),
    'volume_steps_075': ('Objemy · výškový skok 0,75 m', 'Graf sousedních rovin rozdělí stavbu při výškovém skoku; spojitý sedlový hřeben zůstává v jednom objemu.'),
    'volume_steps_150': ('Objemy · výškový skok 1,50 m', 'Konzervativnější dělení podle výškových stupňů. Malé či řídkými body pokryté části se zachovají.'),
}


def snapshot_sources():
    paths = [Path(__file__), ROOT/'scripts/roof_simplification_common.py',
             ROOT/'scripts/roof_simplification_compare.py', ROOT/'scripts/roof_simplify_planes.py',
             ROOT/'scripts/roof_pilot_roofer.py', ROOT/'scripts/resource_guard.py']
    hashes = {p.relative_to(ROOT).as_posix():guard.sha256(p) for p in paths}
    fingerprint = hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    folder = WORK/'implementation'/('comparison-'+fingerprint[:16])
    for path in paths:
        target = folder/path.relative_to(ROOT)
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            shutil.copyfile(path,target)
        assert guard.sha256(target)==hashes[path.relative_to(ROOT).as_posix()]
    value = {'path':folder.relative_to(ROOT).as_posix(),'sha256':hashes,
             'fingerprint':fingerprint,'captured_at':datetime.now(timezone.utc).isoformat()}
    common.write(folder/'manifest.json',value)
    return value


def subset_metrics(predicted, observed, selected):
    selected = np.asarray(selected,dtype=bool)
    valid = selected & np.isfinite(predicted)
    delta = predicted[valid]-observed[valid]
    return {'holdout_points':int(selected.sum()),'predicted_points':int(valid.sum()),
            'coverage_fraction':float(valid.sum()/selected.sum()) if selected.any() else None,
            'rmse_m':float(np.sqrt(np.mean(delta**2))) if len(delta) else None,
            'mae_m':float(np.mean(np.abs(delta))) if len(delta) else None,
            'p95_abs_m':float(np.percentile(np.abs(delta),95)) if len(delta) else None,
            'within_0_5m_fraction':float(np.mean(np.abs(delta)<=.5)) if len(delta) else None}


def evaluate_components(row, case):
    masks = row.get('component_masks',row['model'].get('component_masks',[]))
    row['component_masks'] = masks
    test = case['test_relative']
    predicted = predict_roofer_z(row['model'],test[:,:2])
    feature_mask = np.zeros(len(test),dtype=bool)
    evaluations = []
    for mask in masks:
        if not mask.get('polygon'):
            continue
        polygon = shape(mask['polygon'])
        if not polygon.is_valid or polygon.is_empty:
            row.setdefault('warnings',[]).append('Neplatná diagnostická maska: '+str(mask.get('id')))
            continue
        selected = shapely.intersects_xy(polygon,test[:,0],test[:,1])
        stats = subset_metrics(predicted,test[:,2],selected)
        evaluations.append({'id':mask.get('id'),'kind':mask.get('kind'),'status':mask.get('status'),
                            'area_m2':polygon.area,**stats})
        if mask.get('kind')=='protrusion' and mask.get('status')=='accepted':
            feature_mask |= selected
    row['component_evaluation'] = evaluations
    if any(m.get('kind')=='protrusion' and m.get('status')=='accepted' for m in masks):
        inside = subset_metrics(predicted,test[:,2],feature_mask)
        outside = subset_metrics(predicted,test[:,2],~feature_mask)
        row['metrics'].update({'feature_holdout_rmse_m':inside['rmse_m'],
                              'feature_holdout_points':inside['holdout_points'],
                              'background_holdout_rmse_m':outside['rmse_m'],
                              'background_holdout_points':outside['holdout_points']})
        row['feature_evaluation']={'inside_accepted_protrusion_masks':inside,'outside':outside,
            'scope':'Per-output masks chosen without holdout. Different detectors may select different subsets; compare paired patched/restored rows with the same masks.'}


def main():
    started = time.perf_counter()
    provenance = snapshot_sources()
    guard.check_budget(reserve_bytes=80_000_000,force=True)
    preserved = common.read(DEST/'preserved-input-sha256.json')
    for rel,expected in preserved.items():
        if guard.sha256(ROOT/rel)!=expected:
            raise ValueError('Preserved input changed: '+rel)
    cases = common.load_cases()
    source_manifest_path = ROOT/'.work/cb-roof-pilot/sources/sources.json'
    source_manifest = common.read(source_manifest_path)
    source_provenance = {
        'active_source':'DMPOK', 'nominal_xy_spacing_m':0.2,
        'nominal_points_per_m2':25, 'training_fraction':0.8,
        'holdout_fraction':0.2, 'roofer_ceil_point_density':20,
        'split_seed':20261115,
        'source_manifest':source_manifest_path.relative_to(ROOT).as_posix(),
        'source_manifest_sha256':guard.sha256(source_manifest_path),
        'building_counts':[
            {'id':bid,'pilot_id':case['pilot_id'],'name':case['name'],
             **{source:next(b for b in source_manifest['sources'][source]['building_counts']
                           if b['building_id']==bid) for source in ['dmp1g','dmpok']}}
            for bid,case in cases.items()],
        'notes':[
            'Hustší zdroj DMPOK je stejný jako v předchozím porovnání zjednodušování; nové varianty nemění zdroj ani rozdělení bodů.',
            '20 cm je rozestup mřížky, nikoliv garantovaná výšková přesnost. DMPOK vzniká obrazovou korelací.',
            'Počty v tabulce jsou klasifikované body budov uvnitř půdorysu před rozdělením na fitovací a kontrolní část.',
            'DMP 1G zůstává zdrojem základní mapy a původního porovnání obou zdrojů. Zde je uveden pouze pro porovnání hustoty.',
            'Datum vytvoření LAZ ani zveřejnění souboru není automaticky datum snímkování.']}
    previous = common.read(PREVIOUS)
    rows = [deepcopy(r) for r in previous['runs'] if r['variant'] in REFERENCES]
    for row in rows:
        row['reused_previous_run']=True
        row['review']={'status':'reference','note':'Převzatá reference z předchozího kola; nově hodnocena stejnou metrikou.'}
    files = [DEST/f for f in ['fidelity-results.json','extraction-results.json','volumes-results.json']]
    sources = [common.read(p) for p in files]
    for source in sources:
        if source.get('status')!='complete':
            raise ValueError('Source worker incomplete')
        rows.extend(deepcopy(source['runs']))
    keys = [(r['id'],r['variant']) for r in rows]
    if len(keys)!=len(set(keys)):
        raise ValueError('Duplicate comparison row')
    reference = {r['id']:r['model'] for r in rows if r['variant']=='roofer_lod22_reference'}
    for row in rows:
        case = cases[row['id']]
        row['name'],row['source']=case['name'],'dmpok'
        model = row.get('model')
        if not model or not model.get('faces'):
            row.setdefault('status','unavailable')
            row['metrics']={}
            continue
        model['origin_epsg5514']=[*case['centre'],case['ground_z']]
        row.setdefault('metrics',{}).update(common.evaluate_model(model,case))
        add_geometric_metrics(row)
        row['metrics'].update(baseline_difference(model,reference[row['id']],case['polygon']))
        evaluate_components(row,case)
        if row.get('parent_extrusion_mode')=='lod11_fallback' and row['variant'].startswith('extract_'):
            row.setdefault('warnings',[]).append('Podklad je původní plochý náhradní objem; nebyl nalezen bezpečný výstupek. Nejde o novou úspěšnou rekonstrukci.')
        counts=row['metrics'].get('native_semantic_surface_counts',{})
        if 'RoofSurface' in counts:
            row['metrics']['native_roof_surface_count']=counts['RoofSurface']
        # A NEW template fitted over an uninformative old fallback is not itself
        # a native fallback. Do not propagate parent mode indiscriminately.
        if model.get('attributes',{}).get('rf_extrusion_mode')=='lod11_fallback':
            row['status']='lod11_fallback';row['fallback']=True
        row.setdefault('status','ok')
        timing=row.setdefault('timing',{})
        if 'median_seconds' not in timing:
            timing['median_seconds']=timing.get('median_internal_seconds',timing.get('seconds'))
        row.setdefault('review',{}).setdefault('status','pending')
        print(case['pilot_id'],row['variant'],row['status'],row['metrics'].get('actual_roof_region_count'),
              round(row['metrics']['holdout_rmse_m'],3),flush=True)
    available={r['variant'] for r in rows}
    if available-set(METHODS):
        raise ValueError('Unlabelled variants: '+str(available-set(METHODS)))
    result={'schema':'roof-components-comparison/1','status':'computed_review_pending',
        'created_at':datetime.now(timezone.utc).isoformat(),
        'buildings':previous['buildings'],'runs':rows,
        'methods':[{'id':key,'label':val[0],'description':val[1]} for key,val in METHODS.items() if key in available],
        'protocol':common.read(DEST/'protocol.json'),'source_provenance':source_provenance,'recommendations':[],
        'default_comparison_variants':['roofer_lod22_reference','roofer_c095','roofer_c099'],
        'comparison_sets':[
            {'id':'fidelity','variants':['roofer_lod22_reference','roofer_c095','roofer_c099']},
            {'id':'fidelity_detection','variants':['roofer_lod22_reference','roofer_c095_eps015','roofer_c095_caps240_30s']},
            {'id':'extraction15','variants':['roofer_lod22_reference','extract_compact15_patched','extract_compact15_restored']},
            {'id':'extraction25','variants':['roofer_lod22_reference','extract_compact25_patched','extract_compact25_restored']},
            {'id':'volumes','variants':['roofer_lod22_reference','volume_steps_075','volume_steps_150']}],
        'notes':[
            '0,60 a 0,888 jsou hodnoty stejného parametru stejné verze Rooferu, nikoliv procenta dosažené přesnosti.',
            'Vyšší váha shody s daty může zachovat šum i důležité detaily. Ochranný limit může naopak způsobit plochý náhradní objem.',
            'Vyčlenění používá původní model 0,888; tyto výsledky nejsou automaticky kombinací nového nejpodrobnějšího fitu a extrakce.',
            'Patched varianty prvky úmyslně vynechávají. Jejich odchylka uvnitř masky je proto oddělená od chyby zbývající střechy.',
            'Masky jsou výsledky algoritmu, nikoliv ručně potvrzené správné vymezení věží nebo křídel.',
            'Přísný počet téměř koplanárních oblastí může rozlišovat i numerické zlomy. Sledujte také nativní plochy, délku hran a siluetu.',
            'Čas původní rekonstrukce je nutné přičíst k samostatnému následnému zjednodušení; párový výpočet patched/restored se nepočítá dvakrát.'],
        'source_results_sha256':{p.relative_to(ROOT).as_posix():guard.sha256(p) for p in files},
        'previous_results_sha256':guard.sha256(PREVIOUS),'implementation':provenance,
        'native_batches':sources[0].get('batches',[]),'production_map_modified':False,
        'preserved_inputs_verified':len(preserved),'evaluation_seconds':time.perf_counter()-started}
    result['process_metrics']={p.relative_to(ROOT).as_posix():common.read(p)
        for p in [*WORK.glob('*.metrics.json'),*(WORK/'logs').glob('*.metrics.json')]}
    for rel,expected in provenance['sha256'].items():
        if guard.sha256(ROOT/rel)!=expected:
            raise ValueError('Comparison source changed during run')
    common.write(DEST/'results.json',result)
    print('Compared',len(rows),'rows in',round(result['evaluation_seconds'],3),'seconds',flush=True)


if __name__=='__main__':
    main()
