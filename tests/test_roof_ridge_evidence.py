"""Regression checks for genuine crest evidence, independent of roof addresses."""
import unittest
import numpy as np
from shapely.geometry import box
from shapely.affinity import rotate
from roof_config import resolve_config
from roof_eave_planes import _network_ridge_evidence
from roof_connected_wings import _paired_symmetry_penalty,DEFAULTS


class RidgeEvidenceTests(unittest.TestCase):
    def data(self):
        x,y=np.meshgrid(np.arange(.2,20,.4),np.arange(.2,10,.4))
        xy=np.c_[x.ravel(),y.ravel()]
        return box(0,0,20,10),np.c_[xy,12-.7*abs(xy[:,1]-5)]

    def evidence(self,poly,cells,start=(0,5),end=(20,5)):
        return _network_ridge_evidence(poly,cells,start,end,12.,resolve_config()['scoring'])

    def test_two_slopes_support_crest(self):
        poly,cells=self.data();e=self.evidence(poly,cells)
        self.assertTrue(e['supported'],e)
        self.assertGreater(e['supported_span_m'],10)

    def test_flat_plateau_is_not_a_ridge(self):
        poly,cells=self.data();cells[:,2]=12
        self.assertIn('no_sustained_two_sided_drop',self.evidence(poly,cells)['reasons'])

    def test_single_sloping_plane_is_not_a_ridge(self):
        poly,cells=self.data();cells[:,2]=12-.7*(cells[:,1]-5)
        self.assertFalse(self.evidence(poly,cells)['supported'])

    def test_six_close_points_do_not_establish_a_branch(self):
        poly,cells=self.data();cells=cells[(abs(cells[:,1]-5)<.6)][:6]
        self.assertIn('too_few_crest_cells',self.evidence(poly,cells)['reasons'])

    def test_rotated_crest_is_equivalent(self):
        poly,cells=self.data();a=np.radians(31)
        matrix=np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]])
        cells[:,:2]=cells[:,:2]@matrix.T
        e=self.evidence(rotate(poly,31,origin=(0,0)),cells,matrix@np.array([0,5]),matrix@np.array([20,5]))
        self.assertTrue(e['supported'],e)

    def test_boundary_noise_does_not_supply_crest_support(self):
        poly,cells=self.data();cells[:,2]=8
        near_edge=(cells[:,1]<.8);cells[near_edge,2]=12
        e=self.evidence(poly,cells,start=(0,.4),end=(20,.4))
        self.assertFalse(e['supported'])
        self.assertEqual(e['crest_cells'],0)

    def test_small_pitch_difference_is_not_penalized(self):
        def planes(a,b):
            return [np.array([[np.tan(np.radians(a)),0,0],[-np.tan(np.radians(b)),0,0]])]
        self.assertEqual(_paired_symmetry_penalty(planes(47.5,45.3),1.,DEFAULTS),0)
        moderate=_paired_symmetry_penalty(planes(45,30),1.,DEFAULTS)
        severe=_paired_symmetry_penalty(planes(54,13),1.,DEFAULTS)
        self.assertGreater(moderate,0)
        self.assertLess(moderate,severe)
        self.assertAlmostEqual(severe,DEFAULTS['paired_asymmetry_penalty_m'])


if __name__=='__main__':unittest.main()
