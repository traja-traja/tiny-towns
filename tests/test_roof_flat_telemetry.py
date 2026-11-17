import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from shapely.geometry import box
from roof_annex import infer_modular_roof
from roof_candidate_telemetry import capture

class FlatTelemetryTests(unittest.TestCase):
    def run_flat(self,detailed):
        x,y=np.meshgrid(np.arange(.35,10.,.5),np.arange(.35,8.,.5))
        xyz=np.c_[x.ravel(),y.ravel(),np.full(x.size,8.)]
        with capture(detailed=detailed) as trace:
            result=infer_modular_roof(box(0,0,10,8),xyz,{'modules':{'flat_protrusions':False}})
        return result,trace.to_dict()
    def test_flat_shortcut_counts_one_model_and_skipped_skeleton(self):
        result,data=self.run_flat(True)
        self.assertEqual(result['model']['type'],'flat')
        families={r['family']:r for r in data['families']}
        self.assertEqual(families['flat']['considered'],1)
        self.assertEqual(families['flat']['selected'],1)
        self.assertEqual(families['straight_skeleton']['considered'],0)
        self.assertEqual(families['straight_skeleton']['skipped'],1)
        self.assertTrue(any(a['family']=='straight_skeleton' and a['reason']=='flat_majority' for a in data['attempts']))
    def test_lightweight_capture_has_only_aggregates(self):
        result,data=self.run_flat(False)
        self.assertEqual(data['attempts'],[])
        self.assertTrue(data['families'])
        self.assertNotIn('observed_ridges',result['diagnostics'])

if __name__=='__main__':unittest.main()
