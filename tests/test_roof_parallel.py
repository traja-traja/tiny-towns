"""Verify parallel ridge/valley topology numerically, without visual review."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import unittest
import numpy as np
from shapely.geometry import box
from roof_parallel import parallel_proposal, _predict
from roof_config import resolve_config
from roof_v2_geometry import build_mesh
from roof_v2 import predict_regions
from roof_eave_planes import infer_eave_roof


class ParallelRoofTests(unittest.TestCase):
    def fixture(self,count):
        span = 8*count
        poly = box(0,0,16,span)
        x,y = np.meshgrid(np.arange(.2,16,.4),np.arange(.2,span,.4))
        xy = np.c_[x.ravel(),y.ravel()]
        knots = np.linspace(0,span,2*count+1)
        heights = np.full(2*count+1,8.)
        heights[1::2] = np.linspace(12.,13.,count)
        return poly,np.c_[xy,_predict(xy[:,1],knots,heights)]

    def test_two_and_three_parallel_ridges(self):
        for count in (2,3):
            poly,points = self.fixture(count)
            p = parallel_proposal(poly,np.eye(2),[0,16,0,8*count,0,0],points,count,resolve_config())
            self.assertIsNotNone(p)
            self.assertEqual(len(p['ridge_xy']),count)
            self.assertEqual(len(p['valley_xy']),count-1)
            self.assertEqual(len(p['strip_regions']),2*count)
            self.assertLess(np.quantile(abs(predict_regions(p['strip_regions'],points[:,:2])-points[:,2]),.9),.12)
            self.assertTrue(build_mesh(poly,p['strip_regions'])['diagnostics']['valid'])

    def test_candidate_selection_and_switch(self):
        poly,points = self.fixture(2)
        cfg = {'modules':{'annex_detection':False}}
        result = infer_eave_roof(poly,points,allow_flat=True,allow_pyramidal=True,
            allow_networks=True,allow_parallel=True,config=cfg)
        self.assertEqual(result['model']['metadata']['ridge_kind'],'parallel_gables')
        self.assertEqual(result['model']['metadata']['parallel_ridge_count'],2)
        self.assertEqual(len(result['model']['ridge_lines']),2)
        heights = result['model']['metadata']['ridge_heights_m']
        for line,height in zip(result['model']['ridge_lines'],heights):
            self.assertTrue(all(abs(point[2]-height)<1e-8 for point in line))
        cfg['modules']['parallel_gables'] = False
        disabled = infer_eave_roof(poly,points,allow_parallel=True,config=cfg)
        self.assertFalse(any(c['type']=='parallel_gables' for c in disabled['candidates']))


if __name__=='__main__':
    unittest.main()
