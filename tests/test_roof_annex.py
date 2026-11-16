"""Numerical/geometry tests only; no visual assessment of real buildings."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import unittest
import numpy as np
import shapely
from shapely.geometry import box
from shapely.affinity import rotate
from roof_annex import infer_modular_roof
from roof_eave_planes import infer_eave_roof
from roof_config import resolve_config


def fixture(continuation=False):
    core = box(0,0,12,10)
    annex = box(4,10,7,14)
    poly = core.union(annex)
    x,y = np.meshgrid(np.arange(.2,12,.4), np.arange(.2,14,.4))
    xy = np.c_[x.ravel(),y.ravel()]
    xy = xy[shapely.contains_xy(poly,xy[:,0],xy[:,1])]
    z = 8+(1 if continuation else 4)*np.minimum.reduce(
        [xy[:,0]/6,(12-xy[:,0])/6,xy[:,1]/5,(10-xy[:,1])/5])
    if not continuation:
        z[xy[:,1]>10] = 3.
    return poly, np.c_[xy,z]


class AnnexTests(unittest.TestCase):
    def test_separate_lower_roof_with_two_profiles(self):
        poly, points = fixture()
        result = infer_modular_roof(poly, points)
        model = result['model']; meta = model['metadata']
        self.assertEqual(meta['annex_count'], 1)
        self.assertEqual(meta['main_roof_type'], 'pyramidal')
        self.assertTrue(model['mesh']['diagnostics']['valid'])
        self.assertAlmostEqual(model['mesh']['diagnostics']['footprint_area_m2'], poly.area, places=5)
        candidate = result['diagnostics']['annex_detection']['candidates'][0]
        self.assertEqual(len(candidate['profiles']),2)
        self.assertTrue(all(p['passed'] for p in candidate['profiles']))
        self.assertAlmostEqual(candidate['height_at_center_m'],3.,places=2)
        self.assertGreater(result['timing']['annex_profiles_seconds'],0.)

    def test_continuous_roof_is_not_a_lower_annex(self):
        poly, points = fixture(True)
        result = infer_modular_roof(poly, points)
        self.assertEqual(result['model']['metadata']['annex_count'],0)
        self.assertFalse(result['diagnostics']['annex_detection']['candidates'][0]['accepted'])

    def test_annex_may_meet_main_roof_at_eave_height(self):
        poly, points = fixture()
        points[points[:,1]>10,2] = 8.
        result = infer_modular_roof(poly, points)
        self.assertEqual(result['model']['metadata']['annex_count'],1)
        meta = result['diagnostics']['annex_detection']['candidates'][0]
        self.assertLess(abs(meta['height_step_m']),.3)
        self.assertTrue(result['model']['mesh']['diagnostics']['valid'])

    def test_rotated_footprint_remains_connected(self):
        poly, points = fixture()
        angle = .143
        matrix = np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        poly = rotate(poly, angle, origin=(0,0), use_radians=True)
        points[:,:2] = points[:,:2]@matrix.T
        result = infer_modular_roof(poly, points)
        self.assertEqual(result['model']['metadata']['annex_count'],1)
        self.assertTrue(result['model']['mesh']['diagnostics']['valid'])

    def test_switch_preserves_whole_footprint_model(self):
        poly, points = fixture()
        result = infer_modular_roof(poly, points, {'modules':{'annex_detection':False}})
        previous = infer_eave_roof(poly, points, allow_flat=True, allow_networks=True, allow_pyramidal=True, allow_parallel=True)
        self.assertEqual(result['model']['mesh'], previous['model']['mesh'])
        self.assertEqual(result['timing']['annex_profiles_seconds'],0.)
        self.assertEqual(result['diagnostics']['annex_detection']['status'],'disabled')

    def test_config_and_profile_switch(self):
        with self.assertRaises(ValueError):
            resolve_config({'annex':{'min_depth_m':-2}})
        with self.assertRaises(ValueError):
            resolve_config({'modules':{'typo':False}})
        poly, points = fixture()
        result = infer_modular_roof(poly,points,{'modules':{'annex_profiles':False}})
        self.assertEqual(result['model']['metadata']['annex_count'],1)
        self.assertTrue(result['diagnostics']['annex_detection']['candidates'][0]['profiles_disabled'])


if __name__=='__main__':
    unittest.main()
