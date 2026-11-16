"""Geometry checks for the isolated point-cloud pilot, not renderer snapshots."""

import json
import unittest
from collections import Counter

import numpy as np
from shapely.geometry import Point, Polygon

from scripts.roof_pilot_methods import baseline_roof_model, fit_roof_models, predict_roof_z


def cloud_in(poly, height, n=1200, seed=7, noise=0.02):
    rng = np.random.default_rng(seed)
    lo = np.asarray(poly.bounds[:2])
    hi = np.asarray(poly.bounds[2:])
    xy = rng.uniform(lo, hi, size=(n * 3, 2))
    xy = np.asarray([p for p in xy if poly.contains(Point(p))])[:n]
    z = height(xy) + rng.normal(0, noise, len(xy))
    return np.column_stack((xy, z))


class RoofPilotGeometryTest(unittest.TestCase):
    def setUp(self):
        self.poly = Polygon([[-10, -4], [10, -4], [10, 4], [-10, 4]])

    def assert_closed(self, model):
        edges = Counter()
        for a, b, c in model["faces"]:
            for e in ((a, b), (b, c), (c, a)):
                edges[tuple(sorted(e))] += 1
        self.assertTrue(edges)
        self.assertTrue(all(n == 2 for n in edges.values()), Counter(edges.values()))

    def test_flat_selected_over_more_complex_models(self):
        xyz = cloud_in(self.poly, lambda xy: np.full(len(xy), 108.0))
        result = fit_roof_models(self.poly, xyz, 100.0)
        self.assertEqual(result["best"]["shape"], "flat")
        self.assertAlmostEqual(result["best"]["params"]["height_z"], 108, delta=0.02)
        self.assertLess(result["best"]["metrics"]["rmse_m"], 0.04)
        self.assert_closed(result["best"])
        json.dumps(result, allow_nan=False)

    def test_rotated_gable_recovers_ridge_and_slopes(self):
        angle = np.radians(31)
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        origin = np.array([140.0, -270.0])
        poly = Polygon(np.asarray(self.poly.exterior.coords) @ rotation.T + origin)
        def height(xy):
            v = ((xy - origin) @ rotation)[:, 1]
            return 112 - 0.8 * np.abs(v - 0.45)
        xyz = cloud_in(poly, height, n=1700)
        # A few extreme returns should not rotate or flatten the main roof.
        xyz[::30, 2] += 5
        result = fit_roof_models(poly, xyz, 100.0)
        best = result["best"]
        self.assertEqual(best["shape"], "gabled")
        self.assertLess(np.median(np.abs(predict_roof_z(best, xyz[:, :2]) - height(xyz[:, :2]))), 0.03)
        got = best["params"]["ridge_angle_rad"]
        axis_error = abs((got - angle + np.pi / 2) % np.pi - np.pi / 2)
        self.assertLess(axis_error, np.radians(0.5))
        self.assert_closed(best)

    def test_concave_footprint_and_courtyard_not_filled(self):
        poly = Polygon([(0, 0), (14, 0), (14, 5), (9, 5), (9, 12), (0, 12)],
                       [[(2, 2), (5, 2), (5, 5), (2, 5)]])
        xyz = cloud_in(poly, lambda xy: np.full(len(xy), 8.0))
        model = fit_roof_models(poly, xyz, 0)["best"]
        vertices = np.asarray(model["vertices"])
        roof_area = 0.0
        for face, kind in zip(model["faces"], model["face_semantics"]):
            if kind == "roof":
                triangle = Polygon(vertices[face, :2])
                self.assertTrue(poly.covers(triangle))
                roof_area += triangle.area
        self.assertAlmostEqual(roof_area, poly.area, places=6)
        self.assert_closed(model)

    def test_degenerate_and_missing_points_do_not_invent_roof(self):
        self.assertEqual(fit_roof_models(self.poly, [], 0)["status"], "insufficient_data")
        line = np.column_stack((np.linspace(-5, 5, 20), np.zeros(20), np.ones(20) * 8))
        self.assertEqual(fit_roof_models(self.poly, line, 0)["status"], "insufficient_data")
        line[:, 1] = 2  # Collinear even when offset from the footprint centroid.
        self.assertEqual(fit_roof_models(self.poly, line, 0)["status"], "insufficient_data")
        invalid = [(0, 0), (1, 0), (2, 0)]
        self.assertEqual(fit_roof_models(invalid, line, 0)["status"], "invalid_input")
        xyz = cloud_in(self.poly, lambda xy: np.full(len(xy), 8.0), n=50)
        self.assertEqual(fit_roof_models(self.poly, xyz, 10)["status"], "invalid_heights")

    def test_input_order_does_not_change_fitted_geometry(self):
        xyz = cloud_in(self.poly, lambda xy: 12 - 0.6 * np.abs(xy[:, 1]), n=800)
        a = fit_roof_models(self.poly, xyz, 0, max_fit_points=300)["best"]
        b = fit_roof_models(self.poly, xyz[::-1], 0, max_fit_points=300)["best"]
        self.assertEqual(a["shape"], b["shape"])
        self.assertEqual(a["params"], b["params"])
        self.assertEqual(a["vertices"], b["vertices"])

    def test_baseline_is_explicitly_an_approximation(self):
        xyz = cloud_in(self.poly, lambda xy: 12 - 0.5 * np.abs(xy[:, 1]), n=100)
        result = baseline_roof_model(self.poly, xyz, 0)
        self.assertEqual(result["method"], "baseline_approximation")
        self.assertFalse(result["exact_renderer_replay"])
        self.assert_closed(result)


if __name__ == "__main__":
    unittest.main()
