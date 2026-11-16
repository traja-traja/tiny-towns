import sys
from pathlib import Path
import unittest

import numpy as np
from shapely.geometry import Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from roof_inference import infer_roof


class RoofInferenceTest(unittest.TestCase):
    def fitting_grid(self):
        x, y = np.meshgrid(np.arange(.2, 20, .4), np.arange(.2, 10, .4))
        return x.ravel(), y.ravel()

    def test_ridge_offset_and_chimney_residuals(self):
        x, y = self.fitting_grid()
        z = 410 + 5 * np.minimum(y / 4, (10 - y) / 6)
        chimney = (x > 7) & (x < 9) & (y > 2) & (y < 4)
        z[chimney] += 3
        roof = infer_roof(box(0, 0, 20, 10), np.c_[x, y, z], 403)
        self.assertEqual(roof["type"], "gabled")
        ridge = np.array(roof["ridge"][0])
        np.testing.assert_allclose(ridge[:, 1], 4, atol=.12)
        np.testing.assert_allclose(ridge[:, 2], 415, atol=.12)
        self.assertEqual(len(roof["eaves"]), 2)
        stats = roof["diagnostics"]["residuals"]
        self.assertLess(stats["median_abs_m"], .06)
        self.assertEqual(stats["above_model_1m_count"], int(chimney.sum()))
        self.assertGreater(stats["p99_abs_m"], 2.8)
        self.assertTrue(roof["wall_faces"])

    def test_distinguishes_a_hipped_roof_from_a_pyramid(self):
        x, y = self.fitting_grid()
        for start, end, kind in ((4, 15, "hipped"), (8, 8, "pyramidal")):
            with self.subTest(kind=kind):
                z = 415 + 6 * np.minimum.reduce([x / start, (20 - x) / (20 - end),
                                                 y / 6, (10 - y) / 4])
                roof = infer_roof(box(0, 0, 20, 10), np.c_[x, y, z], 403)
                self.assertEqual(roof["type"], kind)
                self.assertLess(roof["diagnostics"]["residuals"]["p90_abs_m"], .10)
                if kind == "pyramidal":
                    np.testing.assert_allclose(roof["apex"], [8, 6, 421], atol=.13)
                else:
                    self.assertAlmostEqual(np.ptp(np.array(roof["ridge"][0])[:, 0]), 11, delta=.21)

    def test_barrel_residual_uses_the_same_piecewise_profile_as_the_mesh(self):
        x, y = self.fitting_grid()
        z = 410 + 5 * np.sqrt(1 - ((y - 5) / 5) ** 2)
        xyz = np.c_[x, y, z]
        roof = infer_roof(box(0, 0, 20, 10), xyz, 403)
        self.assertEqual(roof["type"], "barrel")
        triangles = np.asarray(roof["vertices"])[roof["roof_faces"]]
        predicted = np.full(len(xyz), np.nan)
        for triangle in triangles:
            start, left, right = triangle
            uv = np.linalg.solve(np.array([left - start, right - start])[:, :2].T,
                                 (xyz[:, :2] - start[:2]).T).T
            inside = (uv >= -1e-7).all(axis=1) & (uv.sum(axis=1) <= 1.0000001)
            predicted[inside] = start[2] + uv[inside] @ np.array([left[2] - start[2], right[2] - start[2]])
        self.assertTrue(np.isfinite(predicted).all())
        self.assertAlmostEqual(np.median(np.abs(predicted - z)),
                               roof["diagnostics"]["residuals"]["median_abs_m"], places=6)

    def test_flat_roof_preserves_courtyard_and_can_omit_walls(self):
        x, y = self.fitting_grid()
        footprint = Polygon(box(0, 0, 20, 10).exterior.coords,
                            [box(7, 3, 12, 6).exterior.coords])
        roof = infer_roof(footprint, np.c_[x, y, np.full(len(x), 410)])
        self.assertEqual(roof["type"], "flat")
        self.assertEqual(roof["status"], "review")
        self.assertEqual(roof["wall_faces"], [])
        mesh = np.asarray(roof["vertices"])
        self.assertAlmostEqual(sum(Polygon(mesh[f, :2]).area for f in roof["roof_faces"]),
                               footprint.area)
        self.assertIn("pitched", roof["diagnostics"]["prefilter"])

    def test_insufficient_points_produce_no_model(self):
        roof = infer_roof(box(0, 0, 20, 10), np.empty((0, 3)), 403)
        self.assertEqual(roof["status"], "insufficient_data")
        self.assertEqual(roof["roof_faces"], [])

    def test_butterfly_separates_valley_from_ridge(self):
        x, y = self.fitting_grid()
        z = 412 + .7 * np.abs(y - 5)
        roof = infer_roof(box(0, 0, 20, 10), np.c_[x, y, z], 403)
        self.assertEqual(roof["type"], "butterfly")
        self.assertEqual(roof["ridge"], [])
        np.testing.assert_allclose(np.array(roof["valley"][0])[:, 1:], [[5, 412], [5, 412]], atol=.1)

    def test_separates_two_flat_levels_and_marks_split_for_review(self):
        x, y = self.fitting_grid()
        z = np.where(x < 10, 412, 417)
        roof = infer_roof(box(0, 0, 20, 10), np.c_[x, y, z], 403)
        self.assertEqual(roof["type"], "multi_flat")
        self.assertEqual(roof["status"], "review")
        self.assertEqual([part["type"] for part in roof["parts"]], ["flat", "flat"])
        self.assertLess(roof["diagnostics"]["residuals"]["p90_abs_m"], .1)

    def test_separates_two_sawtooth_bays(self):
        x, y = self.fitting_grid()
        z = 412 + .6 * (x % 10)
        roof = infer_roof(box(0, 0, 20, 10), np.c_[x, y, z], 403)
        self.assertEqual(roof["type"], "sawtooth")
        self.assertLess(roof["diagnostics"]["residuals"]["p90_abs_m"], .1)


if __name__ == "__main__":
    unittest.main()
