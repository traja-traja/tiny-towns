"""Flat-area evidence must not flatten pitched roofs or a small terrace."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import numpy as np
from shapely.geometry import box
from roof_v2 import _cells
from roof_flat_majority import detect_flat_majority


CFG = {'radius_m': 1.5, 'min_neighbors': 6, 'max_slope_deg': 7.,
       'max_p80_error_m': .25, 'min_patch_area_m2': 4.,
       'min_patch_width_m': 1.2, 'min_coverage_fraction': .55, 'min_patch_area_fraction': .05, 'min_largest_patch_fraction': .20,
       'min_neighbor_axis_ratio': .08}


class FlatMajorityTests(unittest.TestCase):
    def points(self, width=20., length=14.):
        x, y = np.meshgrid(np.arange(.175, width, .35), np.arange(.175, length, .35))
        return np.c_[x.ravel(), y.ravel(), np.full(x.size, 12.)]

    def detect(self, points, poly=None):
        return detect_flat_majority(poly if poly is not None else box(0, 0, 20, 14), _cells(points, .7), .7, CFG)

    def test_small_high_nonstrucural_patch_does_not_defeat_flat_majority(self):
        points = self.points()
        points[(points[:,0] > 8) & (points[:,0] < 11) & (points[:,1] > 5) & (points[:,1] < 8), 2] += 3.
        result = self.detect(points)
        self.assertTrue(result['accepted'])
        self.assertAlmostEqual(result['height_m'], 12.)
        self.assertGreater(result['covered_area_fraction'], .65)

    def test_two_horizontal_levels_count_as_flat_but_height_is_not_between_levels(self):
        points = self.points()
        points[points[:,0] > 12, 2] = 17.
        result = self.detect(points)
        self.assertTrue(result['accepted'])
        self.assertGreaterEqual(len(result['patches']), 2)
        self.assertAlmostEqual(result['height_m'], 12.)
        self.assertFalse(result['height_levels_preserved'])

    def test_many_flat_levels_recover_only_measured_boundary_area(self):
        points = self.points()
        points[:,2] = 12+3*np.floor(points[:,0]/4.9)
        result = self.detect(points)
        self.assertTrue(result['accepted'])
        self.assertGreater(result['covered_area_fraction'], .7)
        self.assertGreater(result['boundary_completed_cells'], 0)
        self.assertGreaterEqual(len(result['patches']), 4)

    def test_boundary_completion_does_not_grow_across_pitched_roof(self):
        points = self.points()
        points[:,2] += .35*np.maximum(0, points[:,0]-8.4)
        result = self.detect(points)
        self.assertFalse(result['accepted'])
        self.assertLess(result['covered_area_fraction'], .5)

    def test_requires_one_contiguous_patch_of_at_least_twenty_percent(self):
        points = self.points(width=33.6)
        points[:,2] = 12+3*np.floor(points[:,0]/5.6)
        result = self.detect(points, box(0,0,33.6,14))
        self.assertGreater(result['covered_area_fraction'], .55)
        self.assertLess(result['largest_patch_area_fraction'], .20)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'largest_horizontal_patch_below_threshold')

    def test_patches_smaller_than_five_percent_do_not_add_to_total(self):
        points = self.points(width=117.6)
        points[:,2] = 12+3*np.floor(points[:,0]/5.6)
        result = self.detect(points, box(0,0,117.6,14))
        self.assertFalse(result['accepted'])
        self.assertEqual(result['covered_area_fraction'], 0.)
        self.assertGreaterEqual(result['rejected_small_patches'], 20)

    def test_fifty_two_percent_is_not_enough_for_fifty_five_threshold(self):
        points = self.points()
        result = self.detect(points[points[:,0] < 10.5])
        self.assertGreater(result['covered_area_fraction'], .5)
        self.assertLess(result['covered_area_fraction'], .55)
        self.assertFalse(result['accepted'])

    def test_pitched_gable_is_not_flat(self):
        points = self.points()
        points[:,2] += .7*np.minimum(points[:,1], 14-points[:,1])
        self.assertFalse(self.detect(points)['accepted'])

    def test_small_terrace_does_not_flatten_the_other_pitched_area(self):
        points = self.points()
        pitched = points[:,0] >= 4
        points[pitched,2] += .7*np.minimum(points[pitched,1], 14-points[pitched,1])
        result = self.detect(points)
        self.assertFalse(result['accepted'])
        self.assertLess(result['covered_area_fraction'], .5)

    def test_missing_points_are_not_assumed_flat(self):
        points = self.points()
        result = self.detect(points[points[:,0] < 6])
        self.assertFalse(result['accepted'])
        self.assertLess(result['observed_area_fraction'], .35)

    def test_density_does_not_outvote_area(self):
        points = self.points()
        # Align the boundary to the sampling grid: repeated samples must not
        # change the within-cell surface mixture in this density-only test.
        pitched = points[:,0] >= 4.2
        points[pitched,2] += .7*np.minimum(points[pitched,1], 14-points[pitched,1])
        dense = np.concatenate([points, np.repeat(points[~pitched], 20, axis=0)])
        first, second = self.detect(points), self.detect(dense)
        self.assertFalse(second['accepted'])
        self.assertAlmostEqual(first['covered_area_fraction'], second['covered_area_fraction'], places=8)

    def test_narrow_line_of_same_height_has_no_two_dimensional_support(self):
        points = np.c_[np.arange(.35, 20, .7), np.full(29, .35), np.full(29, 12.)]
        result = self.detect(points)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['horizontal_cells'], 0)


if __name__ == '__main__':
    unittest.main()
