"""Compare frozen simplification experiments using the actual displayed meshes.

This is evaluation only. No fitting, profile selection, production edits, or
source geometry changes happen here. The held-out points never reach a fitter.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import time

import numpy as np
import shapely
from shapely.geometry import shape

import roof_simplification_common as common
from roof_simplify_planes import extract_roof_regions
from roof_pilot_roofer import predict_roofer_z
import resource_guard as guard


METHODS = [
    ('roofer_lod22_reference', 'Původní Roofer · 0,888', 'Původní podrobná rekonstrukce; znovu hodnotíme uloženou geometrii.'),
    ('roofer_lod22_regular', 'Původní Roofer · 0,60', 'Dřívější mírně zjednodušená rekonstrukce; převzatý výpočet.'),
    ('roofer_c035', 'Roofer · 0,35', 'Silnější penalizace členitosti, detekce rovin s tolerancí 0,30 m.'),
    ('roofer_c015', 'Roofer · 0,15', 'Velmi silné zjednodušení; může vymazat důležité střešní části.'),
    ('roofer_c035_eps050', 'Roofer · 0,35 / roviny 0,50 m', 'Silnější zjednodušení a volnější detekce rovin. Nezaručuje maximální chybu 0,50 m.'),
    ('merge_8deg_025m', 'Sloučení rovin · 8° / 0,25 m', 'Sousední plochy se společně přizpůsobí jedné rovině. Limity vůči původní geometrii, nikoliv vůči skutečnosti.'),
    ('merge_15deg_050m', 'Sloučení rovin · 15° / 0,50 m', 'Volnější sloučení, maximálně půlmetrová svislá změna původní střechy. Zachovává půdorys a omezuje nové výškové schody.'),
    ('template_original', 'Původní jedna šablona', 'Dřívější přizpůsobení jedné typové střechy celému půdorysu; převzatý výpočet.'),
    ('template_whole_bounded', 'Nová jedna šablona', 'Plochá, pultová, sedlová, valbová či oblouková střecha; omezené hledání bez hodnoticích bodů.'),
    ('template_parts4_train', 'Složení až 4 objemů', 'Rozdělení půdorysu podle fitovacích bodů a skládání jednoduchých střech; penalizuje další části.'),
]


def verify_inputs(manifest):
    for rel, expected in manifest['input_sha256'].items():
        if guard.sha256(common.ROOT / rel) != expected:
            raise ValueError('Frozen input changed: ' + rel)


def add_geometric_metrics(row):
    model = row['model']
    metrics = row['metrics']
    vertices = np.asarray(model['vertices'], dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError('Invalid vertices: ' + row['id'])
    if len(model['faces']) != len(model['face_semantics']):
        raise ValueError('Missing face semantics')
    for face in model['faces']:
        if len(face) != 3 or any(i < 0 or i >= len(vertices) for i in face):
            raise ValueError('Invalid triangle index')
    roof_faces = [i for i, role in enumerate(model['face_semantics']) if role == 'roof']
    roof_vertices = vertices[np.asarray([model['faces'][i] for i in roof_faces]).ravel()]
    metrics['roof_z_min_m'] = float(roof_vertices[:, 2].min())
    metrics['roof_z_max_m'] = float(roof_vertices[:, 2].max())
    try:
        regions = extract_roof_regions(model)
        metrics['actual_roof_region_count'] = regions['region_count']
        metrics['roof_region_measurement'] = {k:v for k,v in regions.items() if k != 'regions'}
        model['comparison_roof_regions'] = regions['regions']
        # Source triangle indices refer to the roof-only face sequence.
        labels = [-1] * len(model['faces'])
        for region in regions['regions']:
            for index in region['source_roof_triangles']:
                labels[roof_faces[index]] = region['id']
        model['face_region_ids'] = labels
        polygons = [shape(r['polygon']) for r in regions['regions']]
        areas = sorted((p.area for p in polygons), reverse=True)
        metrics['roof_region_projected_areas_m2'] = areas
        metrics['largest_roof_regions_for_95pct_area'] = int(np.searchsorted(np.cumsum(areas), sum(areas)*.95)+1)
        shared = []
        for i, polygon in enumerate(polygons):
            for other in polygons[i+1:]:
                boundary = polygon.boundary.intersection(other.boundary)
                if boundary.length > 1e-7:
                    shared.append(boundary)
        network = shapely.union_all(shared) if shared else shapely.GeometryCollection()
        metrics['internal_roof_break_length_xy_m'] = float(network.length)
        metrics['internal_roof_break_scope'] = 'Projected boundaries between connected planar regions; includes valleys and height steps, not just ridges.'
    except ValueError as error:
        metrics['actual_roof_region_count'] = None
        row.setdefault('warnings', []).append('Nelze jednotně spočítat roviny: ' + str(error))


def baseline_difference(model, baseline, polygon):
    xmin, ymin, xmax, ymax = polygon.bounds
    x, y = np.meshgrid(np.linspace(xmin, xmax, 52), np.linspace(ymin, ymax, 52))
    xy = np.column_stack((x.ravel(), y.ravel()))
    xy = xy[shapely.contains_xy(polygon, xy[:,0], xy[:,1])]
    current, reference = predict_roofer_z(model, xy), predict_roofer_z(baseline, xy)
    valid = np.isfinite(current) & np.isfinite(reference)
    delta = np.abs(current[valid] - reference[valid])
    return {'baseline_grid_shared_points': int(valid.sum()),
            'baseline_grid_total_points': len(xy),
            'baseline_grid_p95_abs_change_m': float(np.percentile(delta,95)) if len(delta) else None,
            'baseline_grid_max_abs_change_m': float(delta.max()) if len(delta) else None,
            'baseline_difference_scope': 'Sampled uniform XY grid versus original c=0.888 model; not point-cloud accuracy or a continuous bound.'}


def run():
    started = time.perf_counter()
    guard.check_budget(reserve_bytes=50_000_000, force=True)
    manifest = common.read(common.MANIFEST)
    verify_inputs(manifest)
    cases = common.load_cases()
    sources = [common.DEST / f for f in ('native-results.json','planes-results.json','templates-results.json')]
    snapshots = common.snapshot([Path(__file__), common.ROOT/'scripts/roof_simplification_common.py',
                                common.ROOT/'scripts/roof_simplify_planes.py',
                                common.ROOT/'scripts/roof_pilot_roofer.py'], 'comparison')
    documents = [common.read(p) for p in sources]
    rows = common.baseline_rows()
    for document in documents:
        if document.get('status') not in (None, 'complete'):
            raise ValueError('Incomplete comparison source')
        rows.extend(deepcopy(document['runs']))
    keys = [(r['id'],r['variant']) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate comparison row')
    reference = {r['id']:r['model'] for r in rows if r['variant']=='roofer_lod22_reference'}
    for row in rows:
        case = cases[row['id']]
        row['name'] = case['name']
        row['source'] = 'dmpok'
        model = row.get('model')
        if not model or not model.get('faces'):
            row['status'] = 'unavailable'
            row['metrics'] = {}
            continue
        model['origin_epsg5514'] = [*case['centre'], case['ground_z']]
        model['comparison_coordinate_note'] = 'Local XY and Z above frozen ground; origin is metadata only, vertices unchanged.'
        row['metrics'].update(common.evaluate_model(model,case))
        add_geometric_metrics(row)
        row['metrics'].update(baseline_difference(model,reference[row['id']],case['polygon']))
        native_counts = row['metrics'].get('native_semantic_surface_counts',{})
        if 'RoofSurface' in native_counts:
            row['metrics']['native_roof_surface_count'] = native_counts['RoofSurface']
        extrusion = (model.get('attributes',{}).get('rf_extrusion_mode') or
                     row.get('parent_extrusion_mode') or row['metrics'].get('roofer_extrusion_mode'))
        if extrusion == 'lod11_fallback':
            row['status'] = 'lod11_fallback'
            row['fallback'] = True
            row.setdefault('review',{})['note'] = 'Náhradní plochý objem; zjednodušení neopravilo chybějící rekonstrukci střechy.'
        else:
            row.setdefault('status','ok')
        timing = row.setdefault('timing',{})
        if 'median_seconds' not in timing:
            timing['median_seconds'] = timing.get('median_internal_seconds',timing.get('seconds'))
        row.setdefault('review',{}).setdefault('status','pending')
        print(case['pilot_id'], row['variant'], row['metrics'].get('actual_roof_region_count'),
              round(row['metrics']['holdout_rmse_m'],3), flush=True)
    available = {r['variant'] for r in rows}
    known = {m[0] for m in METHODS}
    if available - known:
        raise ValueError('Unlabelled variant: ' + str(available-known))
    buildings = deepcopy(manifest['buildings'])
    for building in buildings:
        train = cases[building['id']]['train_relative']
        indices = np.linspace(0,len(train)-1,min(2000,len(train)),dtype=int)
        building['train_preview'] = np.round(train[indices],3).tolist()
    process_metrics = {}
    for p in [*common.WORK.glob('*.metrics.json'), *(common.WORK/'logs').glob('*.metrics.json')]:
        process_metrics[p.relative_to(common.WORK).as_posix()] = common.read(p)
    result = {'schema':'roof-simplification-comparison/1','status':'computed_review_pending',
        'created_at':datetime.now(timezone.utc).isoformat(), 'buildings':buildings,'runs':rows,
        'methods':[{'id':i,'label':l,'description':d} for i,l,d in METHODS if i in available],
        'protocol':common.read(common.DEST/'protocol.json'),
        'comparison_rules':[
            'Šest vybraných objektů, sedm půdorysů, stejné zmrazené body DMP OK a stejná výšková reference.',
            'Hodnoticí body se nepoužily k přizpůsobování ani k dělení objemů. Doporučení po tomto testu vyžadují ověření na dalších budovách.',
            'Tolerance ±0,5 m je preference pro zjednodušení. Podíl bodů v toleranci, pokrytí a zachování siluety hodnotíme zvlášť.',
            'Roviny počítáme jednotně jako sousední téměř koplanární oblasti (3 mm, 0,25°). CityJSON plochy a trojúhelníky jsou odlišná čísla.',
            'Časy se liší rozsahem: nový výpočet, samotné sloučení už hotové geometrie, nebo přizpůsobování šablon. Nevytvářejí společný žebříček rychlosti.',
            'Skrývání triangulačních hran mění pouze kresbu. Všechny metody se proto zobrazují stejným způsobem.'],
        'default_comparison_variants':['roofer_lod22_reference','roofer_c035_eps050','template_parts4_train'],
        'notes':['První geometrie z opakovaných běhů je zobrazena vždy; nevybíráme nejlépe skórující opakování.',
                 'Přísný geometrický počet může rozlišovat i drobné numerické zlomy původní triangulace. Jejich vyčištění není totéž co odstranění architektonického detailu; porovnejte siluetu a nativní plochy.',
                 'Neshodný hash opakování může znamenat jiné pořadí vrcholů, nejen jiný tvar. Jednotlivé metriky zůstávají uložené.',
                 'Nativní rekonstrukce bez střešních rovin může vrátit LoD1.1 náhradní objem i uvnitř označení LoD2.2; rozhoduje příznak rf_extrusion_mode.',
                 'Šablony skládají uzavřené části bez finálního geometrického sjednocení; vnitřní stěny a výškové švy vyžadují další zpracování.'],
        'recommendations':[], 'process_metrics':process_metrics,
        'native_batches':documents[0].get('batches',[]),
        'source_results_sha256':{str(p.relative_to(common.ROOT)):guard.sha256(p) for p in sources},
        'implementation':snapshots,'evaluation_seconds':time.perf_counter()-started,
        'production_map_modified':False}
    for rel,expected in snapshots['sha256'].items():
        if guard.sha256(common.ROOT/rel)!=expected:
            raise ValueError('Evaluation implementation changed while running')
    common.write(common.DEST/'results.json',result)
    print('Compared',len(rows),'rows in',round(result['evaluation_seconds'],3),'seconds',flush=True)


if __name__ == '__main__':
    run()
