"""Actual wall directions supplement bounding-box profiles without changing evidence gates."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
import shapely
from shapely.geometry import Polygon,LineString,shape,box
from shapely.affinity import rotate
from roof_longitudinal_split import DEFAULTS,_long_profile_axes,detect_longitudinal_split


def bent_main_and_wing():
    # A broad high main roof, with the lower rear/side wings skewed by 8.5 degrees.
    outline=np.array([[0,0],[24,0],[24,10],[8,10],[8,22],[24,22],[24,30],[0,30],[0,10]])
    outline=outline.astype(float);outline[:,0]+=.15*np.maximum(outline[:,1]-10,0)
    poly=Polygon(outline)
    x,y=np.meshgrid(np.arange(.15,27,.3),np.arange(.15,30,.3))
    xy=np.c_[x.ravel(),y.ravel()]
    xy=xy[shapely.intersects_xy(poly,xy[:,0],xy[:,1])]
    x,y=xy.T;local_x=x-.15*np.maximum(y-10,0)
    lower=4.+.7*np.maximum(np.minimum(local_x,8-local_x),np.minimum(y-22,30-y))
    heights=np.where(y<10,8.+.7*np.minimum(y,10-y),lower)
    return poly,np.c_[xy,heights]


class WallProfileAxesTests(unittest.TestCase):
    def test_extra_direction_follows_actual_main_wall(self):
        poly,_=bent_main_and_wing()
        axes=_long_profile_axes(poly,DEFAULTS)
        self.assertLessEqual(len(axes),3)
        self.assertTrue(any(abs(a[0])<1e-8 for a in axes),axes)
        for a in axes:self.assertAlmostEqual(np.linalg.norm(a),1.)
        self.assertEqual(len(_long_profile_axes(poly,{**DEFAULTS,'long_profile_wall_axes':False})),1)

    def test_rectangle_does_not_duplicate_profile_work(self):
        for angle in (0,13,80):
            poly=rotate(box(0,0,12,36),angle)
            self.assertEqual(len(_long_profile_axes(poly,DEFAULTS)),1)

    def test_supported_transition_keeps_original_main_wall_cut(self):
        poly,points=bent_main_and_wing()
        # Missing ridge references must not leave a long/bent house dependent
        # solely on the direction of its bounding box.
        with patch('roof_longitudinal_split._wing_boxes',return_value=([],{})):
            result=detect_longitudinal_split(poly,points)
        snapped=[c for c in result['candidates'] if c['snapping']['applied']
                 and np.max(abs(np.asarray(c['snapping']['source_edge_xy'])[:,1]-10))<1e-7]
        self.assertTrue(snapped,result['reason'])
        parts=[shape(p) for p in snapped[0]['footprints']]
        self.assertLess(shapely.union_all(parts).symmetric_difference(poly).area,1e-7)
        self.assertLess(parts[0].intersection(parts[1]).area,1e-7)
        self.assertLess(min(p.symmetric_difference(box(0,0,24,10)).area for p in parts),1e-7)
        self.assertGreaterEqual(snapped[0]['supported_bands'],DEFAULTS['min_bands'])

    def test_no_height_change_does_not_force_wall_split(self):
        poly,points=bent_main_and_wing();points[:,2]=5.
        with patch('roof_longitudinal_split._wing_boxes',return_value=([],{})):
            result=detect_longitudinal_split(poly,points)
        self.assertEqual(result['candidates'],[])


if __name__=='__main__':unittest.main()
