"""Local wing errors cannot be hidden by the whole-building average."""
import copy
import unittest
import numpy as np
import shapely
from shapely.geometry import box,mapping
from roof_config import resolve_config
from roof_eave_planes import _guard_wing_fit_simplification
from roof_connected_wings import _envelope
from roof_v2 import predict_regions

class WingFitSimplicityTests(unittest.TestCase):
    def setUp(self):
        self.main=box(0,0,24,6);self.side=box(0,0,4,11)
        self.poly=self.main.union(self.side)
        # Two analytic gables on perpendicular wings, joined continuously.
        roofs=[np.array([[0,1,10],[0,-1,16]],float),
               np.array([[1.5,0,10],[-1.5,0,16]],float)]
        regions=_envelope(self.poly,roofs,clamp_base=False)
        x,y=np.meshgrid(np.arange(.25,24,.5),np.arange(.25,11,.5))
        xy=np.c_[x.ravel(),y.ravel()];xy=xy[shapely.contains_xy(self.poly,xy[:,0],xy[:,1])]
        self.cells=np.c_[xy,predict_regions(regions,xy)]
        self.best=dict(kind='connected_wings',candidate_label='two_wings',_regions=regions,
            connected_wings=dict(wing_domains_xy=[mapping(self.main),mapping(self.side)],settings={}),
            branch_support=[dict(wing_index=i,supported_cells=30,nearby_cells=30) for i in (0,1)])
        self.cfg=resolve_config()['scoring']
    def biased_candidate(self,delta):
        # Same main roof, but a locally lower secondary roof. This is a
        # numerical scoring fixture; no meshes or visual fixtures are needed.
        regions=[]
        for region in self.best['_regions']:
            shape=shapely.geometry.shape(region['polygon'])
            for area,offset in ((shape.intersection(self.main),0),
                                (shape.difference(self.main),delta)):
                if area.is_empty:continue
                plane=list(region['plane']);plane[2]+=offset
                regions.append(dict(polygon=mapping(area),plane=plane))
        return dict(kind='straight',candidate_label='simpler',_regions=regions)
    def test_local_regression_prevents_simplicity_promotion(self):
        other=self.biased_candidate(-.7)
        near,meta=_guard_wing_fit_simplification(self.poly,self.best,[self.best,other],self.cells,self.cfg)
        self.assertEqual(len(near),1)
        self.assertIs(near[0],self.best)
        loss=meta['candidates_not_promoted'][0]['wings'][0]
        self.assertEqual(loss['wing_index'],1)
        self.assertGreater(loss['increase_m'],.6)
        self.assertNotIn('rejected',other)  # Still a geometric fallback.
    def test_small_local_loss_can_still_simplify(self):
        other=self.biased_candidate(-.05)
        near,meta=_guard_wing_fit_simplification(self.poly,self.best,[self.best,other],self.cells,self.cfg)
        self.assertEqual(len(near),2)
        self.assertFalse(meta['candidates_not_promoted'])
    def test_unconfirmed_wing_does_not_block_simplification(self):
        self.best['branch_support'][1]['supported_cells']=0
        other=self.biased_candidate(-.7)
        near,_=_guard_wing_fit_simplification(self.poly,self.best,[self.best,other],self.cells,self.cfg)
        self.assertEqual(len(near),2)
    def test_module_can_be_disabled(self):
        other=self.biased_candidate(-.7)
        near,meta=_guard_wing_fit_simplification(self.poly,self.best,[self.best,other],self.cells,
            {**self.cfg,'protect_wing_fit':False})
        self.assertEqual(len(near),2)
        self.assertFalse(meta['enabled'])
    def test_boundary_noise_does_not_define_exclusive_wing_fit(self):
        other=self.biased_candidate(-.7)
        noisy=self.cells.copy()
        edge=shapely.distance(shapely.points(noisy[:,:2]),self.poly.boundary)<.8
        noisy[edge,2]+=20
        _,meta=_guard_wing_fit_simplification(self.poly,self.best,[self.best,other],noisy,self.cfg)
        self.assertTrue(all(w['data_error_m']<1e-8 for w in meta['reference_wings']))

if __name__=='__main__':unittest.main()
