"""Whole-building flat simplification must bypass annexes and preserve footprint."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import numpy as np
from shapely.geometry import box
from roof_annex import infer_modular_roof


class FlatPipelineTests(unittest.TestCase):
    def scene(self):
        x, y = np.meshgrid(np.arange(.175,20,.35), np.arange(.175,14,.35))
        points = np.c_[x.ravel(),y.ravel(),np.full(x.size,12.)]
        points[points[:,0]>12,2] = 17.
        return box(0,0,20,14), points

    def test_multiple_levels_become_one_closed_flat_volume(self):
        footprint, points = self.scene()
        result = infer_modular_roof(footprint, points, {'modules':{'flat_protrusions':False}})
        self.assertEqual(result['model']['type'], 'flat')
        self.assertEqual(result['model']['height_range_m'], [12.,12.])
        self.assertEqual(result['model']['metadata']['nominal_roof_plane_count'], 1)
        self.assertEqual(result['model']['metadata']['annex_count'], 0)
        self.assertEqual(result['diagnostics']['annex_detection']['status'], 'skipped_flat_majority')
        self.assertTrue(result['diagnostics']['complex_candidates_skipped'])
        self.assertTrue(result['model']['mesh']['diagnostics']['watertight'])
        self.assertAlmostEqual(result['model']['mesh']['diagnostics']['coverage_fraction'], 1.)

    def test_module_can_be_disabled_and_flat_module_is_respected(self):
        footprint, points = self.scene()
        for modules in ({'flat_majority':False}, {'flat':False}):
            result = infer_modular_roof(footprint, points, {'modules':modules})
            self.assertFalse(result['diagnostics']['flat_majority']['enabled'])
            self.assertNotEqual(result['diagnostics']['annex_detection']['status'], 'skipped_flat_majority')


if __name__ == '__main__':
    unittest.main()
