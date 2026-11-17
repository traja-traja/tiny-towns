"""Short footprint protrusions must not dictate the only possible eave span."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import numpy as np
import shapely
from shapely.geometry import box
from roof_eave_planes import infer_eave_roof
from roof_config import resolve_config


class PrimaryEnvelopeTests(unittest.TestCase):
    def test_hip_planes_clip_protrusion_without_new_ridge(self):
        footprint = box(0, 0, 20, 12).union(box(8, 12, 12, 15))
        x, y = np.meshgrid(np.arange(.2, 20, .4), np.arange(.2, 15, .4))
        xy = np.column_stack((x.ravel(), y.ravel()))
        xy = xy[shapely.intersects_xy(footprint, xy[:, 0], xy[:, 1])]
        z = 8 + .6 * np.minimum.reduce([xy[:, 0], 20-xy[:, 0], xy[:, 1], 12-xy[:, 1]])
        result = infer_eave_roof(footprint, np.c_[xy, z], allow_flat=True,
            config={'modules': {'bent': False, 'skillion': False}})
        self.assertEqual(result['model']['type'], 'hipped')
        self.assertEqual(result['model']['metadata']['supporting_envelope'], 'main_walls')
        self.assertTrue(result['model']['mesh']['diagnostics']['watertight'])
        self.assertAlmostEqual(result['model']['mesh']['diagnostics']['coverage_fraction'], 1., places=5)
        self.assertTrue(any(c['supporting_envelope']=='main_walls' for c in result['candidates']))

    def test_options_can_restore_outer_envelope_and_original_tolerance(self):
        cfg = resolve_config({'modules': {'primary_wall_envelope': False},
                              'scoring': {'simplification_tolerance_m': .05},
                              'parallel_gables': {'min_supported_span_fraction': 0.}})
        self.assertFalse(cfg['modules']['primary_wall_envelope'])
        self.assertEqual(cfg['scoring']['simplification_tolerance_m'], .05)
        with self.assertRaises(ValueError):
            resolve_config({'parallel_gables': {'min_supported_span_fraction': 1.1}})


if __name__ == '__main__':
    unittest.main()
