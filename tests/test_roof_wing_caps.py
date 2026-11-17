"""End-cap regularization preserves genuine wing directions and closed roofs."""
import unittest
import numpy as np
from shapely.geometry import Polygon,shape
import shapely
from roof_connected_wings import _canonicalize_caps,_envelope,cap_rollback_candidates,DEFAULTS
from roof_v2_geometry import build_mesh
from roof_config import resolve_config,point_error

class WingCapTests(unittest.TestCase):
    def test_near_cap_uses_existing_long_roof_plane(self):
        poly=Polygon([(0,0),(10,0),(10,8),(0,8)])
        wings=[np.array([[.6,0.,0.],[-.6,0.,6.],[0.,.6,0.]]),
               np.array([[0.,.6,0.],[0.,-.6,4.8],[.6001,.001,.02]])]
        original=[p.copy() for p in wings]
        new,meta=_canonicalize_caps(poly,wings,[{'length':20.},{'length':10.}],DEFAULTS)
        self.assertEqual(meta['merged_cap_count'],1)
        np.testing.assert_array_equal(new[1][2],wings[0][0])
        for before,after in zip(original,new):np.testing.assert_array_equal(before[:2],after[:2])
        self.assertLessEqual(meta['maximum_plane_change_m'],.25)
        for a,b in zip(original,wings):np.testing.assert_array_equal(a,b)
        regions=_envelope(poly,new)
        for r in regions:r['plane'][2]+=8.
        mesh=build_mesh(poly,regions)
        self.assertTrue(mesh['diagnostics']['valid'])
        self.assertEqual(mesh['diagnostics']['height_step_edge_count'],0)

    def test_true_angle_or_height_difference_is_not_merged(self):
        poly=Polygon([(0,0),(10,0),(10,8),(0,8)])
        wings=[np.array([[.6,0.,0.],[-.6,0.,6.]]),
               np.array([[0.,.6,0.],[0.,-.6,4.8],[.6,.12,0.],[.6,0.,.4]])]
        new,meta=_canonicalize_caps(poly,wings,[{'length':20.},{'length':10.}],DEFAULTS)
        self.assertEqual(meta['merged_cap_count'],0)
        for before,after in zip(wings,new):np.testing.assert_array_equal(before,after)

    def test_can_be_disabled(self):
        p=Polygon([(0,0),(10,0),(10,8),(0,8)])
        wings=[np.array([[.6,0.,0.],[-.6,0.,6.],[.6,.001,.02]])]
        new,meta=_canonicalize_caps(p,wings,[{'length':20.}],{**DEFAULTS,'canonicalize_caps':False})
        np.testing.assert_array_equal(new[0],wings[0])
        self.assertFalse(meta['enabled'])


    def test_rollback_rescores_the_exact_restored_planes(self):
        poly=Polygon([(0,0),(10,0),(10,8),(0,8)])
        original=[np.array([[.6,0.,0.],[-.6,0.,6.],[0.,.6,0.]]),
                  np.array([[0.,.6,0.],[0.,-.6,4.8],[.6001,.001,.02]])]
        _,meta=_canonicalize_caps(poly,original,[{'length':20.},{'length':10.}],DEFAULTS)
        cells=np.array([[1.,2.,9.],[3.,4.,10.],[7.,6.,9.]])
        scoring=resolve_config()['scoring']
        candidate={'_cap_original_wings':original,'_cap_base_height_m':8.,'_cap_scoring':scoring,
            'connected_wings':{'cap_simplification':meta},'complexity_penalty_m':.065,'support_penalty_m':.01}
        variants=list(cap_rollback_candidates(poly,cells,candidate))
        self.assertEqual(len(variants),1)
        recovered=variants[0]
        A=np.c_[cells[:,:2],np.ones(len(cells))]
        expected=8+np.maximum(0,np.max([np.min(A@w.T,axis=1) for w in original],axis=0))
        self.assertAlmostEqual(recovered['score'],float(point_error(abs(expected-cells[:,2]),scoring))+.075)
        info=recovered['connected_wings']['cap_simplification']
        self.assertTrue(info['original_geometry_restored'])
        self.assertEqual(info['rolled_back_merge_indices'],[0])
        self.assertTrue(build_mesh(poly,recovered['_regions'])['diagnostics']['valid'])

if __name__=='__main__':unittest.main()
