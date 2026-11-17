"""Execution mode tests: analytical profiles must not enter city production."""
import contextlib,copy,io,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import numpy as np
from shapely.geometry import box,mapping
from roof_config import resolve_config,resolve_execution_config
from roof_annex import infer_modular_roof
import roof_batch
import night_roof_batch


def fixture_result():
    return {'algorithm':'test-fixture','model':{'type':'gabled','metadata':{},
        'mesh':{'vertices':[[0.,0.,0.],[10.,0.,0.],[10.,10.,8.]],'diagnostics':{'valid':True}},
        'regions':[{'polygon':mapping(box(0,0,10,10)),'plane':[0.,0.,8.]}]},
        'diagnostics':{},'timing':{'total_seconds':.01}}


class StopAfterConfig(Exception):pass


class RoofExecutionModeTests(unittest.TestCase):
    def test_default_geometry_does_not_request_analytical_profiles(self):
        self.assertFalse(resolve_config()['modules']['observed_ridges'])

    def test_mode_overrides_reused_settings_without_mutating_them(self):
        old={'modules':{'observed_ridges':True}}
        self.assertFalse(resolve_execution_config(old,mode='map')['modules']['observed_ridges'])
        self.assertTrue(old['modules']['observed_ridges'])
        self.assertTrue(resolve_execution_config({'modules':{'observed_ridges':False}},mode='report')['modules']['observed_ridges'])
        with self.assertRaises(ValueError):resolve_execution_config(mode='typo')

    def test_real_public_inference_calls_diagnostic_only_in_report_mode(self):
        pts=np.array([[x,y,8.] for x in range(1,10) for y in range(1,10)])
        for mode in ('map','report'):
            config=resolve_execution_config(mode=mode)
            def diagnostic(result,*args):
                result['diagnostics']['observed_ridges']={'volumes':[],'seconds':.125}
                result['timing']['observed_ridges_seconds']=.125
                return result
            with patch('roof_annex._infer_modular_roof',side_effect=lambda *a:fixture_result()),patch('roof_observed_ridges.attach_observed_ridges',side_effect=diagnostic) as detect:
                result=infer_modular_roof(box(0,0,10,10),pts,config=config)
            self.assertEqual(detect.call_count,1 if mode=='report' else 0)
            self.assertEqual('observed_ridges_seconds' in result['timing'],mode=='report')
            self.assertEqual(result['model']['mesh'],fixture_result()['model']['mesh'])

    def test_all_html_batch_modes_enable_profiles_after_building_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);cache=base/'points.npz'
            np.savez(cache,train=np.array([[1.,1.,8.],[2.,2.,8.]]),holdout=np.empty((0,3)))
            building={'id':'fixture','address':'Synthetic','roof_config_overrides':{'modules':{'observed_ridges':False}},
                'parts':[{'part_index':0,'footprint':mapping(box(0,0,10,10)),
                    'origin_xy':[0.,0.],'ground_z':0.,'cache':{'path':str(cache)}}]}
            inputs={'city':'ceske-budejovice','source':'test','crs':'local','vertical_datum':'local','buildings':[building]}
            source=base/'inputs.json';source.write_text(json.dumps(inputs),encoding='utf-8')
            prior=base/'prior';prior.mkdir()
            old=copy.deepcopy(building);old['parts'][0]['result']=fixture_result()
            (prior/'results.json').write_text(json.dumps({'buildings':[old]}),encoding='utf-8')
            for compare in (False,True):
                output=base/('compare' if compare else 'report');configs=[]
                def fit(footprint,points,config):configs.append(copy.deepcopy(config));return fixture_result()
                args=['--inputs',str(source),'--output',str(output)]
                if compare:args+=['--test','--previous',str(prior)]
                with patch('roof_batch.infer_modular_roof',side_effect=fit),patch('roof_batch.render_report'),patch('roof_batch.source_records',return_value={'fixture':{}}),patch('roof_batch.guard.check_budget'),patch('roof_batch.guard.keep_awake',return_value=contextlib.nullcontext()),patch('roof_batch.guard.memory_status',return_value={'available':2_000_000_000}),contextlib.redirect_stdout(io.StringIO()):
                    result=roof_batch.main(args)
                self.assertEqual(result,0)
                self.assertEqual(len(configs),1)
                self.assertTrue(configs[0]['modules']['observed_ridges'])
                run=json.loads((output/'run.json').read_text(encoding='utf-8'))
                self.assertEqual(run['configuration']['execution_mode'],'report')
                self.assertTrue(run['configuration']['analytical_ridges'])
                self.assertEqual(run['configuration']['comparison_mode'],compare)

    def test_both_night_entry_points_force_profiles_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for entry in (night_roof_batch.run,night_roof_batch.worker):
                args=SimpleNamespace(output=root/entry.__name__,inputs=root/'inputs.json',cache=root/'cache',config=root/'old-report-config.json')
                seen=[]
                def read(path):return {'modules':{'observed_ridges':True}} if path==args.config else {'city':'velesin','buildings':[]}
                def identify(config):seen.append(config);raise StopAfterConfig()
                with patch('night_roof_batch.read',side_effect=read),patch('night_roof_batch.identity',side_effect=identify):
                    with self.assertRaises(StopAfterConfig):entry(args)
                self.assertFalse(seen[0]['modules']['observed_ridges'])


if __name__=='__main__':unittest.main()
