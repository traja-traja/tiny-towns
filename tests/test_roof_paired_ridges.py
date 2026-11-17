"""Numerical regressions for connected ridges without an orthogonal L template."""
import unittest
import numpy as np
import shapely
from shapely.geometry import Polygon,shape,box
from shapely.affinity import rotate
from roof_connected_wings import _paired_ridge_proposals,_paired_layout_evidence,_wing_boxes,DEFAULTS
from roof_config import resolve_config
from roof_v2_geometry import build_mesh

class PairedRidgeTests(unittest.TestCase):
    def cloud(self,shear=.0):
        base=Polygon([(0,0),(18,0),(18,8),(6,8),(6,20),(0,20)])
        x,y=np.meshgrid(np.arange(.2,18,.35),np.arange(.2,20,.35))
        x=x.ravel();y=y.ravel();m=shapely.intersects_xy(base,x,y);x=x[m];y=y[m]
        # Two analytic gables with unequal widths, meeting at (3,4).
        a=np.minimum.reduce([y/4,(8-y)/4,x/3])
        b=np.minimum.reduce([x/3,(6-x)/3,y/4])
        z=8+4*np.maximum(a,b)
        cells=np.c_[x+shear*y,y,z]
        poly=Polygon([(px+shear*py,py) for px,py in base.exterior.coords])
        return poly,cells

    def test_shared_level_ridge_with_different_widths(self):
        poly,cells=self.cloud()
        proposals=_paired_ridge_proposals(poly,cells,resolve_config(),DEFAULTS)
        best=min(proposals,key=lambda p:p['score'])
        self.assertLess(best['data_error_m'],.02)
        self.assertAlmostEqual(best['ridge_height_m'],12.,delta=.03)
        self.assertAlmostEqual(best['eave_height_m'],8.,delta=.03)
        self.assertEqual(len(set(np.round(best['ridge_heights_m'],6))),1)
        self.assertTrue(best['connected_wings']['common_ridge'])
        self.assertTrue(best['connected_wings']['opposing_slopes_symmetric'])
        self.assertFalse(best['connected_wings']['ridge_offsets_fitted'])
        mesh=build_mesh(poly,best['strip_regions'])
        self.assertTrue(mesh['diagnostics']['valid'])

    def test_acute_bend_keeps_independent_axes_and_continuity(self):
        poly,cells=self.cloud(.30)
        best=min(_paired_ridge_proposals(poly,cells,resolve_config(),DEFAULTS),key=lambda p:p['score'])
        self.assertLess(best['data_error_m'],.08)
        frames=best['connected_wings']['wing_frames_xy']
        axes=[np.asarray(f)[:,0] for f in frames]
        self.assertGreater(abs(axes[0]@axes[1]),.1)
        self.assertLess(abs(axes[0]@axes[1]),.5)
        regions=best['strip_regions']
        coverage=shapely.union_all([shape(r['polygon']) for r in regions])
        self.assertLess(coverage.symmetric_difference(poly).area,.0001)
        for i,r in enumerate(regions):
            for q in regions[i+1:]:
                shared=shape(r['polygon']).boundary.intersection(shape(q['polygon']).boundary)
                pts=shapely.get_coordinates(shared)
                if len(pts):
                    error=np.c_[pts,np.ones(len(pts))]@(np.asarray(r['plane'])-np.asarray(q['plane']))
                    self.assertLess(float(np.max(np.abs(error))),1e-4)

    def test_rectangular_footprint_not_forced_into_bent_roof(self):
        poly=Polygon([(0,0),(18,0),(18,8),(0,8)])
        _,cells=self.cloud()
        self.assertEqual(_paired_ridge_proposals(poly,cells,resolve_config(),DEFAULTS),[])

    def test_local_pairs_do_not_use_two_whole_building_strips(self):
        poly=box(0,0,20,5).union(box(8,0,20,17))
        for angle in (0,27):
            current=rotate(poly,angle,origin=(0,0))
            boxes,_=_wing_boxes(current,{**DEFAULTS,'_outer_ends':True},all_candidates=True)
            local=[min(boxes,key=lambda w:abs(w['width']-width)) for width in (5,12)]
            broad=[min(boxes,key=lambda w:abs(w['width']-width)) for width in (17,20)]
            self.assertTrue(_paired_layout_evidence(current,local,DEFAULTS)['accepted'])
            rejected=_paired_layout_evidence(current,broad,DEFAULTS)
            self.assertFalse(rejected['accepted'])
            self.assertEqual(rejected['reason'],'redundant_wing_width')

    def test_small_facade_tab_does_not_set_wing_width(self):
        poly=box(0,0,20,5).union(box(8,0,20,17)).union(box(7,9,9,10))
        boxes,_=_wing_boxes(poly,{**DEFAULTS,'_outer_ends':True},all_candidates=True)
        local=[min(boxes,key=lambda w:abs(w['width']-width)) for width in (5,12)]
        evidence=_paired_layout_evidence(poly,local,DEFAULTS)
        self.assertTrue(evidence['accepted'])
        self.assertTrue(all(len(w['probes'])>=2 for w in evidence['wings']))

    def test_strong_point_evidence_can_keep_asymmetric_slopes(self):
        poly,cells=self.cloud()
        x,y=cells[:,0],cells[:,1]
        a=np.minimum.reduce([y/2.4,(8-y)/5.6,x/1.8])
        b=np.minimum.reduce([x/1.8,(6-x)/4.2,y/2.4])
        cells[:,2]=8+4*np.maximum(a,b)
        best=min(_paired_ridge_proposals(poly,cells,resolve_config(),DEFAULTS),key=lambda p:p['score'])
        self.assertLess(best['data_error_m'],.03)
        self.assertTrue(best['connected_wings']['ridge_offsets_fitted'])
        self.assertGreater(best['connected_wings']['symmetry_preference_penalty_m'],0)

    def test_width_guard_can_be_disabled_for_reproduction(self):
        poly=box(0,0,20,5).union(box(8,0,20,17))
        boxes,_=_wing_boxes(poly,{**DEFAULTS,'_outer_ends':True},all_candidates=True)
        broad=[min(boxes,key=lambda w:abs(w['width']-width)) for width in (17,20)]
        self.assertTrue(_paired_layout_evidence(poly,broad,{**DEFAULTS,'paired_local_widths':False})['accepted'])

if __name__=='__main__':unittest.main()
