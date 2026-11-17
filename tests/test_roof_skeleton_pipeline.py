"""Shared skeleton eligibility, fair scores, lazy geometry and timing semantics."""
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'.work/roof-skeleton-test/vendor')]
from unittest.mock import patch
import numpy as np
import shapely
from shapely.geometry import box
from roof_config import resolve_config,point_error
from roof_v2 import _cells,predict_regions
from roof_skeleton_candidate import eligibility,straight_skeleton_proposals
from roof_candidate_telemetry import capture,record_attempt,record_selection

class SkeletonPipelineTests(unittest.TestCase):
    def fixture(self):
        poly=box(0,0,20,16).difference(box(8,8,20,16))
        x,y=np.meshgrid(np.arange(.2,20,.7),np.arange(.2,16,.7));xy=np.c_[x.ravel(),y.ravel()]
        xy=xy[shapely.intersects_xy(poly,xy[:,0],xy[:,1])]
        points=np.c_[xy,6.+.6*np.minimum.reduce([xy[:,0],20-xy[:,0],xy[:,1],16-xy[:,1]])]
        cfg=resolve_config();cells=_cells(points,cfg['sampling']['cell_size_m'])
        return poly,points,cells,cfg
    def test_gate_selects_concave_pitched_but_not_flat_or_simple_rectangle(self):
        poly,pts,cells,cfg=self.fixture();s=cfg['straight_skeleton']
        self.assertTrue(eligibility(poly,cells,s)['eligible'])
        flat=cells.copy();flat[:,2]=6.
        self.assertFalse(eligibility(poly,flat,s)['eligible'])
        self.assertFalse(eligibility(box(0,0,20,16),cells,s)['eligible'])
    def test_candidates_use_shared_cells_and_never_build_trial_meshes(self):
        poly,pts,cells,cfg=self.fixture()
        with capture(detailed=True) as collector,patch('roof_skeleton_gables.build_mesh',side_effect=AssertionError('trial mesh must be deferred')):
            proposals,gate=straight_skeleton_proposals(poly,pts,cells,cfg)
        self.assertTrue(proposals);self.assertTrue(gate['geometry_deferred'])
        for p in proposals:
            expected=point_error(abs(predict_regions(p['strip_regions'],cells[:,:2])-cells[:,2]),cfg['scoring'])
            self.assertAlmostEqual(p['data_error_m'],expected)
        telemetry=collector.to_dict();row=next(r for r in telemetry['families'] if r['family']=='straight_skeleton')
        self.assertEqual(row['considered'],gate['enumerated'])
        self.assertGreater(row['fitting_seconds'],0.)
    def test_shared_selection_has_real_mesh_and_records_candidate_family(self):
        from roof_eave_planes import infer_eave_roof
        poly,pts,cells,cfg=self.fixture()
        for name in ('annex_detection','connected_wings','butterfly','parallel_gables','networks','pyramidal','bent','skillion'):cfg['modules'][name]=False
        with capture(detailed=True) as collector:
            result=infer_eave_roof(poly,pts,allow_flat=True,config=cfg)
        self.assertTrue(result['model']['mesh']['diagnostics']['valid'])
        self.assertTrue(result['diagnostics']['straight_skeleton']['eligible'])
        self.assertTrue(any(c['type']=='straight_skeleton' for c in result['candidates']))
        self.assertEqual(sum(f['selected'] for f in collector.to_dict()['families']),1)
    def test_capture_counts_gate_separately_and_simple_mode_omits_events(self):
        with capture(detailed=False) as parent:
            record_attempt('straight_skeleton',stage='eligibility',status='eligible',count=0)
            record_attempt('straight_skeleton',fitting_seconds=.2)
            with capture(detailed=True) as child:
                record_attempt('flat',status='skipped',stage='eligibility',count=0)
            record_selection('straight_skeleton')
        data=parent.to_dict();self.assertEqual(data['attempts'],[])
        self.assertEqual(data['families'][0]['considered'],1)
        self.assertEqual(data['families'][0]['selected'],1)
        self.assertAlmostEqual(data['total_fitting_seconds'],.2)
        self.assertEqual(child.to_dict()['families'][0]['skipped'],1)

if __name__=='__main__':unittest.main()
