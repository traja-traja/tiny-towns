"""Higher-data-fidelity sensitivity on the same seven frozen roof footprints.

Only in-memory adapter configuration is replaced. The original adapter source,
old results, point density and inputs remain unchanged. Three fidelity profiles
keep previous native caps; one explicit diagnostic allows a larger capped budget.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import time

import roof_simplification_common as common
import roof_simplify_roofer as native
import resource_guard as guard

DEST = common.ROOT/'cities/ceske-budejovice/experiments/roof-components'
WORK = common.ROOT/'.work/cb-roof-components'
PROFILES = {
    'roofer_c095': {'lod':'2.2','complexity_factor':0.95,'plane_detect_epsilon_m':0.30,
        'label':'Roofer 0,95 / roviny 0,30 m',
        'purpose':'Higher data weight, unchanged plane detection'},
    'roofer_c099': {'lod':'2.2','complexity_factor':0.99,'plane_detect_epsilon_m':0.30,
        'label':'Roofer 0,99 / roviny 0,30 m',
        'purpose':'Very high data weight, unchanged plane detection'},
    'roofer_c095_eps015': {'lod':'2.2','complexity_factor':0.95,'plane_detect_epsilon_m':0.15,
        'label':'Roofer 0,95 / roviny 0,15 m',
        'purpose':'Same0.95 data weight with stricter plane inlier tolerance'},
    'roofer_c095_caps240_30s': {'lod':'2.2','complexity_factor':0.95,'plane_detect_epsilon_m':0.30,
        'fallback_planes':240,'fallback_time_ms':30000,
        'label':'Roofer 0,95 / větší limit detekce',
        'purpose':'Diagnostic: same0.95/0.30 profile with240-plane and30-second caps'},
}
EXTRA_SOURCES = ('scripts/roof_fidelity3.py','scripts/roof_simplification_common.py')


@contextmanager
def configured_adapter():
    """Override globals only inside this process and always restore originals."""
    profiles, sources, command_builder = native.PROFILES, native.SOURCE_FILES, native.native_variant_command
    def configured_command(profile_id, train_path, footprints_path, output_path):
        command=command_builder(profile_id,train_path,footprints_path,output_path)
        profile=native.PROFILES[profile_id]
        if 'fallback_planes' in profile:
            command[command.index('--lod11-fallback-planes')+1]=str(profile['fallback_planes'])
            command[command.index('--lod11-fallback-time')+1]=str(profile['fallback_time_ms'])
        return command
    try:
        native.PROFILES = deepcopy(PROFILES)
        native.SOURCE_FILES = tuple(dict.fromkeys((*sources,*EXTRA_SOURCES)))
        native.native_variant_command = configured_command
        yield native
    finally:
        native.PROFILES, native.SOURCE_FILES = profiles, sources
        native.native_variant_command = command_builder


def run(repeats=2, start_budget_seconds=600):
    if repeats not in (1,2):
        raise ValueError('This sensitivity test permits one or two repeats')
    if not 0 < start_budget_seconds <= 600:
        raise ValueError('New batch start budget must be in (0,600] seconds')
    DEST.mkdir(parents=True,exist_ok=True)
    WORK.mkdir(parents=True,exist_ok=True)
    result_path = DEST/'fidelity-results.json'
    if result_path.exists():
        raise FileExistsError('Preserve completed measured result; use a new explicit revision for another run')
    started=time.perf_counter()
    settings = {'schema':'roof-fidelity3-protocol/1',
        'created_at':datetime.now(timezone.utc).isoformat(),
        'manifest':str(common.MANIFEST),'manifest_sha256':guard.sha256(common.MANIFEST),
        'profiles':PROFILES,'requested_repeats':repeats,
        'start_budget_seconds':start_budget_seconds,
        'displayed_repeat_index':0,'heldout_used_for_fitting':False,
        'common_parameters':{'ceil_point_density':20,'plane_detect_k':15,
            'plane_detect_min_points':15,'lod11_fallback_time_ms':10000,
            'lod11_fallback_planes':120,'native_worker_jobs':1},
        'diagnostic_override':{'variant':'roofer_c095_caps240_30s','lod11_fallback_planes':240,
            'lod11_fallback_time_ms':30000,'memory_limit_unchanged':True},
        'interpretation':{
            'complexity':'E = lambda * data_term + (1-lambda) * smoothness_term; lambda is not an accuracy percentage.',
            'epsilon':'Plane inlier tolerance, not maximum final reconstruction error.',
            'higher_fidelity':'Higher weight on fitting the input data, not guaranteed accuracy or preservation of every feature.',
            'same_caps':'The first3 profiles use the previous120-plane/10-second caps; the fourth isolates a larger240-plane/30-second budget.'},
        'source':'https://github.com/3DBAG/roofer/blob/main/docs/reconstruct_params.md'}
    common.write(WORK/'fidelity-launch-protocol.json',settings)
    with configured_adapter() as adapter:
        source_hashes={rel:guard.sha256(common.ROOT/rel) for rel in adapter.SOURCE_FILES}
        result=adapter.run_selected_comparison(common.MANIFEST,
            WORK/'fidelity-adapter-summary.json',WORK/'native',
            repeats=repeats,start_budget_seconds=start_budget_seconds)
        for rel,expected in source_hashes.items():
            if guard.sha256(common.ROOT/rel)!=expected:
                raise RuntimeError('Measured implementation changed during execution: '+rel)
    cases=common.load_cases()
    for row in result['runs']:
        if row.get('model'):
            original_hash=native.geometry_sha256(row['model'])
            row['metrics'].update(common.evaluate_model(row['model'],cases[row['id']]))
            if native.geometry_sha256(row['model'])!=original_hash:
                raise RuntimeError('Evaluation changed native geometry')
            row['status']=native.native_model_status(row['model'])
        row['timing']['median_seconds']=row['timing'].get('median_internal_seconds')
        row['review']={'status':'pending','note':'Vyšší váha shody s body; užitečný detail a případný šum je nutné porovnat vizuálně.'}
    result.update({'schema':'roof-fidelity3-comparison/1','protocol':settings,
        'implementation_sha256':source_hashes,'total_worker_seconds':time.perf_counter()-started,
        'original_adapter_globals_restored':True,
        'resource_after':guard.check_budget(force=True)})
    result['notes'].extend([
        'Higher lambda prioritises data fit but does not promise a lower external error or a more faithful semantic building.',
        'The stricter epsilon changes detected candidate planes; lambda alone only changes optimisation over available candidates.',
        'All point-density limits match the previous profiles. First3 profiles keep old fallback caps; the fourth explicitly tests a larger detection budget at the same0.95/0.30 settings.',
        'First meshes are retained; repeated geometry hashes include vertex/face order, so unequal hashes need not imply different shapes.',
        'The common displayed-mesh evaluator runs after fitting and does not choose a profile or repeat.'])
    common.write(result_path,result)
    print('Saved',result_path,'rows',len(result['runs']),'batches',len(result['batches']),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--start-budget-seconds',type=float,default=600)
    args=parser.parse_args()
    if args.execute:
        run(args.repeats,args.start_budget_seconds)
    else:
        print(PROFILES)
