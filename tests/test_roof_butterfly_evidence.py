"""A visible V in global heights must also have measured local inward slopes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from roof_butterfly_support import build_local_support,evaluate_side_support


def grid_roof(height):
    x,y=np.meshgrid(np.arange(.2,18.,.4),np.arange(-6.,6.,.4))
    xy=np.c_[x.ravel(),y.ravel()]
    return np.c_[xy,height(xy[:,0],xy[:,1])]


class ButterflyEvidenceTests(unittest.TestCase):
    def test_true_v_has_measured_inward_slopes_on_both_sides(self):
        cells=grid_roof(lambda x,y:10.+.4*abs(y))
        local=build_local_support(cells)
        result=evaluate_side_support(cells,[[0,-.4,10],[0,.4,10]],local)
        self.assertTrue(all(r['accepted'] for r in result))
        self.assertTrue(all(r['directional_fraction']>.85 for r in result))

    def test_flat_terraces_are_not_two_continuously_sloping_roof_planes(self):
        # Globally rises from the centre on both sides, but local roofs are flat.
        cells=grid_roof(lambda x,y:10.+1.2*np.floor(abs(y)/3.))
        local=build_local_support(cells)
        result=evaluate_side_support(cells,[[0,-.4,10],[0,.4,10]],local)
        self.assertTrue(all(not r['accepted'] for r in result))
        self.assertTrue(all(r['directional_fraction']<.6 for r in result))

    def test_one_large_flat_side_rejects_the_butterfly(self):
        cells=grid_roof(lambda x,y:10.+np.where(y<0,-.4*y,0.))
        local=build_local_support(cells)
        result=evaluate_side_support(cells,[[0,-.4,10],[0,.1,10]],local)
        self.assertTrue(result[0]['accepted'])
        self.assertFalse(result[1]['accepted'])

    def test_cap_points_belong_to_the_cap_not_the_two_side_checks(self):
        planes=np.array([[0,-.4,10],[0,.4,10],[-.4,0,12.4]])
        cells=grid_roof(lambda x,y:np.maximum(.4*abs(y)+10,12.4-.4*x))
        local=build_local_support(cells)
        result=evaluate_side_support(cells,planes,local)
        self.assertTrue(all(r['accepted'] for r in result))
        assigned=sum(r['assigned_cells'] for r in result)
        self.assertLess(assigned,len(cells))
        owner=np.argmax(np.c_[cells[:,:2],np.ones(len(cells))]@planes.T,axis=1)
        self.assertEqual(assigned,int(np.count_nonzero(owner<2)))

    def test_no_candidate_error_filter_hides_the_flat_evidence(self):
        cells=grid_roof(lambda x,y:10.+np.where(y<0,-.4*y,0.))
        local=build_local_support(cells)
        result=evaluate_side_support(cells,[[0,-.4,10],[0,.4,10]],local)
        self.assertGreater(result[1]['local_planar_cells'],100)
        self.assertLess(result[1]['directional_fraction'],.2)


if __name__=='__main__':unittest.main()
