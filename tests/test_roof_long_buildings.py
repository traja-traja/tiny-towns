"""Longitudinal change evidence without preidentified separate roof ridges."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
import shapely
from shapely.geometry import box,shape
from shapely.affinity import rotate,translate
from roof_longitudinal_split import detect_longitudinal_split,footprint_gate


def sample(height):
    poly=box(0,0,36,9)
    x,y=np.meshgrid(np.arange(.15,36,.3),np.arange(.15,9,.3))
    xy=np.c_[x.ravel(),y.ravel()]
    return poly,np.c_[xy,height(xy[:,0],xy[:,1])]


class LongBuildingTests(unittest.TestCase):
    def test_high_transverse_main_roof_and_low_long_wing(self):
        poly,points=sample(lambda x,y:np.where(x<12,7.+.7*np.minimum(x,12-x),3.+.5*np.minimum(y,9-y)))
        result=detect_longitudinal_split(poly,points)
        self.assertEqual(result['reason'],'supported_long_profile_model_change')
        self.assertTrue(result['candidates'])
        candidate=result['candidates'][0]
        self.assertGreaterEqual(candidate['supported_bands'],3)
        line=np.array(candidate['cut_line_xy'])
        self.assertLess(abs(float(line[:,0].mean())-12),2.)
        parts=[shape(p) for p in candidate['footprints']]
        self.assertEqual(len(parts),2)
        self.assertTrue(all(p.is_valid for p in parts))
        self.assertLess(shapely.union_all(parts).symmetric_difference(poly).area,1e-7)
        self.assertLess(parts[0].intersection(parts[1]).area,1e-7)

    def test_parallel_roofs_with_a_sustained_height_step(self):
        poly,points=sample(lambda x,y:np.where(x<16,9.,4.)+.6*np.minimum(y,9-y))
        result=detect_longitudinal_split(poly,points)
        self.assertTrue(result['candidates'],result['reason'])
        line=np.array(result['candidates'][0]['cut_line_xy'])
        self.assertLess(abs(float(line[:,0].mean())-16),1.5)

    def test_single_sloping_roof_and_single_gable_do_not_split(self):
        for height in (lambda x,y:5.+.25*x,lambda x,y:4.+.6*np.minimum(x,36-x)):
            with self.subTest(height=height):
                poly,points=sample(height)
                self.assertEqual(detect_longitudinal_split(poly,points)['candidates'],[])

    def test_local_chimney_is_not_a_second_volume(self):
        poly,points=sample(lambda x,y:5.+.6*np.minimum(y,9-y)+4*((x>17)&(x<19)&(y>4)&(y<6)))
        self.assertEqual(detect_longitudinal_split(poly,points)['candidates'],[])

    def test_fallback_can_be_disabled(self):
        poly,points=sample(lambda x,y:np.where(x<12,7.+.7*np.minimum(x,12-x),3.+.5*np.minimum(y,9-y)))
        result=detect_longitudinal_split(poly,points,{'long_profile_fallback':False})
        self.assertEqual(result['candidates'],[])

    def test_bent_but_not_long_footprint_gets_profiles_without_forced_split(self):
        poly=box(0,0,24,10).union(box(0,10,8,28))
        x,y=np.meshgrid(np.arange(.15,24,.3),np.arange(.15,28,.3))
        xy=np.c_[x.ravel(),y.ravel()]
        xy=xy[shapely.intersects_xy(poly,xy[:,0],xy[:,1])]
        x,y=xy.T
        z=5.+.6*np.maximum(np.minimum(y,10-y),np.minimum(x,8-x))
        result=detect_longitudinal_split(poly,np.c_[xy,z])
        self.assertIn('bent_or_large_annex',result['eligibility']['reasons'])
        self.assertNotIn('long_building',result['eligibility']['reasons'])
        self.assertTrue(result['eligibility']['shape_candidate'])
        self.assertTrue(result['eligibility']['area_sufficient_for_split'])
        self.assertGreater(result['long_profile_fallback']['bands'],0)
        self.assertGreater(result['counts']['longitudinal_bands_evaluated'],0)
        self.assertEqual(result['candidates'],[])

    def test_small_bent_shape_is_candidate_but_cannot_make_two_large_volumes(self):
        result=footprint_gate(box(0,0,10,4).union(box(0,4,3,10)))
        self.assertTrue(result['shape_candidate'])
        self.assertFalse(result['area_sufficient_for_split'])
        self.assertFalse(result['accepted'])


if __name__=='__main__':unittest.main()
