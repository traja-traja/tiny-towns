"""Evidence tests: chimneys, steps, changing widths and isolated apex noise."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from shapely.geometry import box, Polygon
from roof_sections import analyze_sections


def cloud(zfunction, length=24, width=12):
    x,y=np.meshgrid(np.arange(.2,length,.35),np.arange(.2,width,.35))
    z=zfunction(x,y)
    return np.c_[x.ravel(),y.ravel(),z.ravel()]


class RoofSectionsTests(unittest.TestCase):
    def test_repeated_gable_ignores_local_chimney(self):
        points=cloud(lambda x,y:5+.7*(6-abs(y-6)))
        chimney=(points[:,0]>10)&(points[:,0]<11.2)&(points[:,1]>5.4)&(points[:,1]<6.7)
        points[chimney,2]+=5
        result=analyze_sections(box(0,0,24,12),points,axis=[1,0])
        self.assertTrue(result['ridge']['horizontal_supported'])
        self.assertAlmostEqual(result['ridge']['ridge_height_m'],9.2,delta=.15)
        self.assertAlmostEqual(result['eaves']['eave_left_m'],5,delta=.15)
        self.assertEqual(result['longitudinal_changes'],[])
        json.dumps(result,allow_nan=False)

    def test_two_pitched_volumes_produce_eave_step(self):
        points=cloud(lambda x,y:5+.7*(6-abs(y-6))+(x>12)*3)
        result=analyze_sections(box(0,0,24,12),points,axis=[1,0])
        changes=result['longitudinal_changes']
        self.assertTrue(changes)
        # Domain centroid is x=12, so a split near u=0 is expected.
        self.assertLess(min(abs(c['u_m']) for c in changes),2)
        self.assertAlmostEqual(changes[0]['height_step_m'],3,delta=.3)
        self.assertFalse(result['ridge']['horizontal_supported'])

    def test_flat_steps_have_no_fake_ridge(self):
        points=cloud(lambda x,y:np.where(x<12,6.,9.))
        result=analyze_sections(box(0,0,24,12),points,axis=[1,0])
        self.assertIsNone(result['ridge'])
        self.assertTrue(result['longitudinal_changes'])

    def test_normal_width_change_is_not_volume_step(self):
        # Widening gable changes ridge height while the two eaves stay at z=5.
        poly=Polygon([(0,0),(24,0),(24,12),(0,8)])
        points=cloud(lambda x,y:5+.7*((8+x/6)/2-abs(y-(8+x/6)/2)))
        result=analyze_sections(poly,points,axis=[1,0])
        self.assertTrue(result['ridge']['supported'])
        self.assertEqual(result['longitudinal_changes'],[])

    def test_flat_roof_with_chimney_is_not_gable(self):
        points=cloud(lambda x,y:np.full_like(x,7.))
        high=(points[:,0]>10)&(points[:,0]<12)&(points[:,1]>5)&(points[:,1]<7)
        points[high,2]+=6
        result=analyze_sections(box(0,0,24,12),points,axis=[1,0])
        self.assertIsNone(result['ridge'])
        self.assertEqual(result['longitudinal_changes'],[])

    def test_domain_and_switch(self):
        points=cloud(lambda x,y:5+.7*(6-abs(y-6)))
        result=analyze_sections(box(0,0,24,12),points,domain=box(0,0,12,12),axis=[1,0])
        self.assertTrue(result['ridge']['supported'])
        self.assertLess(result['input_points'],len(points))
        disabled=analyze_sections(None,[],config={'enabled':False})
        self.assertFalse(disabled['enabled'])

    def test_courtyard_intervals_remain_separate(self):
        poly=box(0,0,24,24).difference(box(4,7,25,17))
        points=cloud(lambda x,y:5+.7*np.where(y<12,3.5-abs(y-3.5),3.5-abs(y-20.5)),width=24)
        result=analyze_sections(poly,points,axis=[1,0])
        supported=[r for r in result['ridge_tracks'] if r['supported']]
        self.assertGreaterEqual(len(supported),2)
        self.assertEqual(result['longitudinal_changes'],[])


if __name__=='__main__':unittest.main()
