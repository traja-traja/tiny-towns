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

    def test_short_patch_cannot_support_a_whole_parallel_ridge(self):
        poly,points = self.fixture(2)
        # Both transverse peaks exist, with many matching cells. Only a
        # quarter of the longitudinal span supports the first peak, however.
        sparse = points[(points[:,1]>=8.) | (points[:,0]<4.)]
        cfg = resolve_config({'parallel_gables':{'min_supported_span_fraction':0.}})
        candidate = parallel_proposal(poly,np.eye(2),[0,16,0,16,0,0],sparse,2,cfg)
        self.assertIsNotNone(candidate)
        self.assertFalse(candidate['evidence_rejections'])
        self.assertGreater(candidate['branch_support'][0]['supported_cells'],5)
        self.assertLess(candidate['branch_support'][0]['supported_span_fraction'],.3)
        cfg['parallel_gables']['min_supported_span_fraction'] = .5
        rejected = parallel_proposal(poly,np.eye(2),[0,16,0,16,0,0],sparse,2,cfg)
        self.assertIn('parallel_ridge_0_short_longitudinal_support',rejected['evidence_rejections'])

    def test_legacy_asymmetric_profile_requires_explicit_switch(self):
        poly,points = self.fixture(2)
        points[:,2] = _predict(points[:,1],np.array([0.,2.5,8.,13.,16.]),np.array([8.,12.,8.,13.,8.]))
        candidate = parallel_proposal(poly,np.eye(2),[0,16,0,16,0,0],points,2,resolve_config({'parallel_gables':{'symmetric_bays':False}}))
        self.assertIsNotNone(candidate)
        self.assertFalse(candidate['evidence_rejections'])
        self.assertFalse(candidate['symmetric_bays'])
        self.assertLess(candidate['cross_section_uvz'][1][0],3.)
        self.assertTrue(all(s['supported_span_fraction']>=.5 for s in candidate['branch_support']))

    def test_asymmetric_points_do_not_create_one_steep_flank_or_raised_valley(self):
        poly,points = self.fixture(2)
        points[:,2] = _predict(points[:,1],np.array([0.,3.,8.,15.,16.]),
                               np.array([6.,10.,8.,9.5,6.]))
        candidate = parallel_proposal(poly,np.eye(2),[0,16,0,16,0,0],points,2,resolve_config())
        section = np.array(candidate['cross_section_uvz'])
        self.assertTrue(candidate['symmetric_bays'])
        np.testing.assert_allclose(section[1::2,0],(section[:-1:2,0]+section[2::2,0])/2,atol=1e-10)
        np.testing.assert_allclose(section[::2,1],section[0,1],atol=1e-10)
        slopes = np.array(candidate['bay_slopes_deg'])
        np.testing.assert_allclose(slopes[:,0],slopes[:,1],atol=1e-9)
        self.assertTrue(build_mesh(poly,candidate['strip_regions'])['diagnostics']['valid'])

    def test_nearly_vertical_gable_flanks_are_rejected(self):
        poly,points = self.fixture(2)
        points[:,2] = _predict(points[:,1],np.array([0.,4.,8.,12.,16.]),
                               np.array([8.,22.,8.,22.,8.]))
        candidate = parallel_proposal(poly,np.eye(2),[0,16,0,16,0,0],points,2,resolve_config())
        self.assertIn('parallel_flank_exceeds_max_slope',candidate['evidence_rejections'])

    def test_unequal_bay_widths_still_allow_symmetric_roofs(self):
        poly,points = self.fixture(2)
        points[:,2] = _predict(points[:,1],np.array([0.,3.,6.,11.,16.]),
                               np.array([8.,11.,8.,12.5,8.]))
        candidate = parallel_proposal(poly,np.eye(2),[0,16,0,16,0,0],points,2,resolve_config())
        self.assertLess(candidate['data_error_m'],.08)
        np.testing.assert_allclose(candidate['bay_widths_m'],[6.,10.],atol=.1)
        self.assertFalse(candidate['evidence_rejections'])


if __name__=='__main__':
    unittest.main()
