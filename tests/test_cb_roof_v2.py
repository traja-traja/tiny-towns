"""Input-split and independent held-out evaluation invariants."""
import sys
from pathlib import Path
import unittest

import numpy as np
from shapely.geometry import box, mapping

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from cb_roof_v2 import split_points, external_metrics


class RoofV2InputsTests(unittest.TestCase):
    def test_split_does_not_depend_on_order_or_z(self):
        rng=np.random.default_rng(5)
        points=rng.normal(size=(10000,3))*100+[-755700,-1165900,400]
        held=split_points(points)
        self.assertTrue(.17 < held.mean() < .23)
        order=rng.permutation(len(points))
        np.testing.assert_array_equal(split_points(points[order]),held[order])
        points[:,2]+=rng.normal(size=len(points))*10
        np.testing.assert_array_equal(split_points(points),held)

    def test_same_xy_stays_in_one_partition(self):
        points=np.array([[-755700.1,-1165900.3,400],[-755700.1,-1165900.3,402]])
        self.assertEqual(*split_points(points))

    def test_heldout_residual_keeps_rooftop_protrusions(self):
        result={'model':{'regions':[{'polygon':mapping(box(0,0,10,10)),'plane':[.5,0,3]}]}}
        points=np.array([[1,1,3.5],[3,2,4.5],[2,4,8]])
        metrics=external_metrics(result,points)
        self.assertEqual(metrics['evaluated'],3)
        self.assertAlmostEqual(metrics['mae_m'],4/3)
        self.assertAlmostEqual(metrics['within_05m'],2/3)

    def test_uncovered_points_are_reported(self):
        result={'model':{'regions':[{'polygon':mapping(box(0,0,10,10)),'plane':[0,0,3]}]}}
        metrics=external_metrics(result,np.array([[1,1,3],[20,20,3]]))
        self.assertEqual(metrics['n'],2)
        self.assertEqual(metrics['evaluated'],1)
        self.assertEqual(metrics['coverage_fraction'],.5)

    def test_empty_holdout_has_no_fabricated_metrics(self):
        self.assertEqual(external_metrics({},np.empty((0,3))),{'n':0,'status':'no_holdout_points'})


if __name__=='__main__':
    unittest.main()
