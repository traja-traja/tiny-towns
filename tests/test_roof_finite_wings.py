import unittest
import numpy as np
import shapely
from shapely.geometry import Polygon,box
from roof_connected_wings import _wing_prediction,_local_gable_evidence,_wing_planes,_envelope,DEFAULTS
from roof_v2_geometry import build_mesh

class FiniteWingTests(unittest.TestCase):
    def fixture(self,hipped=False):
        poly=box(0,0,12,6)
        wing={'u':np.array([1.,0.]),'v':np.array([0.,1.]),'lo':0.,'hi':12.,'bottom':0.,'top':6.,
            'width':6.,'inside':poly,'end_planes':[np.array([1.,0.,0.]),np.array([-1.,0.,12.])]}
        x,y=np.meshgrid(np.arange(.1,12,.2),np.arange(.1,6,.2));x=x.ravel();y=y.ravel()
        rise=np.minimum(y,6-y)
        if hipped:rise=np.minimum.reduce([rise,x,12-x])
        points=np.c_[x,y,8+.6*rise]
        return poly,wing,points

    def test_local_gable_evidence_uses_inset_and_both_ends(self):
        poly,w,cells=self.fixture()
        units=[_wing_planes(w,(True,True))]
        evidence=_local_gable_evidence(poly,cells,[w],units,8.,.6,DEFAULTS)
        self.assertEqual([e['supported'] for e in evidence],[True,True])
        contaminated=cells.copy();edge=(cells[:,0]<.8)|(cells[:,0]>11.2)
        contaminated[edge,2]+=20
        again=_local_gable_evidence(poly,contaminated,[w],units,8.,.6,DEFAULTS)
        self.assertEqual([e['supported'] for e in again],[True,True])
        self.assertEqual([e['cells'] for e in evidence],[e['cells'] for e in again])
        np.testing.assert_allclose([e['error_improvement_m'] for e in evidence],[e['error_improvement_m'] for e in again])

    def test_measured_hip_is_not_removed(self):
        poly,w,cells=self.fixture(hipped=True)
        evidence=_local_gable_evidence(poly,cells,[w],[_wing_planes(w,(True,True))],8.,.6,DEFAULTS)
        self.assertFalse(any(e['supported'] for e in evidence))

    def test_plane_cannot_cross_courtyard_to_unrelated_wing(self):
        A=np.array([[2.,2.,1.],[2.,12.,1.]])
        high=np.array([[0.,0.,8.]])
        low=np.array([[0.,0.,3.]])
        domains=[box(0,0,4,4),box(0,10,4,14)]
        np.testing.assert_array_equal(_wing_prediction(A,[high,low],domains),[8.,3.])
        poly=shapely.union_all(domains)
        # Disjoint fixture demonstrates bounded influence only, not a joined-roof candidate.
        regions=_envelope(poly,[high,low],domains=domains)
        for r in regions:
            pt=shapely.geometry.shape(r['polygon']).representative_point()
            self.assertAlmostEqual(r['plane'][2],8. if pt.y<5 else 3.)

if __name__=='__main__':unittest.main()
