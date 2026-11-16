"""Small geometry/protocol tests; no Roofer invocation or real city data."""

import unittest

import numpy as np
from shapely.geometry import Polygon, mapping

from scripts.roof_detail_variants import (
    variant_command, run_roofer_variant, evaluate_holdout,
    fit_partwise_templates, predict_partwise_z,
    fit_hypar_part, predict_hypar_z,
    run_detail_comparison,
)


class DetailVariantTest(unittest.TestCase):
    def test_requested_lod_flags_are_exclusive(self):
        command = variant_command("roofer_lod13_volumes", "train.laz", "input.geojson", "output")
        self.assertIn("--lod13", command)
        self.assertIn("--no-lod22", command)
        self.assertEqual(command[command.index("--lod13-step-height") + 1], "3.0")
        simple = variant_command("roofer_lod22_regular", "train.laz", "input.geojson", "output")
        self.assertEqual(simple[simple.index("--complexity-factor") + 1], "0.6")
        self.assertIn("--no-lod13", simple)

    def test_tower_diagnostic_does_not_change_regular_profiles(self):
        diagnostic = variant_command("roofer_tower_allow_insufficient", "train.laz", "input.geojson", "output")
        self.assertIn("--no-clear-insufficient", diagnostic)
        regular = variant_command("roofer_lod22_reference", "train.laz", "input.geojson", "output")
        self.assertNotIn("--no-clear-insufficient", regular)

    def test_real_run_waits_for_basic_preview(self):
        with self.assertRaisesRegex(RuntimeError, "basic"):
            run_roofer_variant("dmpok", [], "missing.laz", "out", "roofer_lod22_regular")

    def test_repeat_budget_rejects_invalid_limits_before_io(self):
        for budget in [0, -1, 3601, float("nan")]:
            with self.subTest(budget=budget):
                with self.assertRaisesRegex(ValueError, "3600"):
                    run_detail_comparison("dmpok", [], "missing.laz", "out", "missing.json", {},
                                          baseline_preview_complete=True, max_wall_seconds=budget)

    def test_holdout_coverage_is_not_hidden_by_small_rmse(self):
        model = {"vertices": [[0, 0, 5], [10, 0, 5], [0, 10, 5]],
                 "faces": [[0, 1, 2]], "face_semantics": ["roof"]}
        metrics = evaluate_holdout(model, [[1, 1, 5], [2, 2, 5.2], [20, 20, 9]])
        self.assertEqual(metrics["predicted_points"], 2)
        self.assertAlmostEqual(metrics["coverage_fraction"], 2 / 3)
        self.assertAlmostEqual(metrics["holdout_mae_m"], 0.1)

    def test_explicit_parts_preserve_two_distinct_height_volumes(self):
        footprint = Polygon([(0, 0), (12, 0), (12, 8), (0, 8)])
        polygons = [Polygon([(0, 0), (6, 0), (6, 8), (0, 8)]),
                    Polygon([(6, 0), (12, 0), (12, 8), (6, 8)])]
        parts = [{"type": "Feature", "properties": {"id": str(i), "source": "synthetic_geometry"},
                  "geometry": mapping(p)} for i, p in enumerate(polygons)]
        rng = np.random.default_rng(9)
        xy = rng.uniform([0, 0], [12, 8], (600, 2))
        z = 100 + np.where(xy[:, 0] < 6, 5.0, 11.0)
        model = fit_partwise_templates(footprint, np.column_stack((xy, z)), 100, parts)
        self.assertEqual(model["status"], "ok")
        self.assertEqual(model["metrics"]["reconstructed_part_count"], 2)
        np.testing.assert_allclose(predict_partwise_z(model, [[2, 2], [9, 2]]), [5, 11], atol=0.01)
        self.assertFalse(model["mesh_is_boolean_union"])

    def test_parts_cannot_silently_fill_a_courtyard(self):
        outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
        footprint = Polygon(outer, [[(3, 3), (7, 3), (7, 7), (3, 7)]])
        parts = [{"geometry": mapping(Polygon(outer)), "properties": {"id": "bad"}}]
        with self.assertRaisesRegex(ValueError, "holes"):
            fit_partwise_templates(footprint, np.zeros((20, 3)), 0, parts)

    def test_hypar_part_recovers_saddle_despite_outliers(self):
        polygon = Polygon([(-10, -6), (10, -6), (10, 6), (-10, 6)])
        rng = np.random.default_rng(31)
        xy = rng.uniform([-10, -6], [10, 6], (600, 2))
        z = 110 + 0.025 * xy[:, 0] ** 2 - 0.04 * xy[:, 1] ** 2
        contaminated = z.copy()
        contaminated[::15] += 6
        result = fit_hypar_part(polygon, np.column_stack((xy, contaminated)), 100,
                                part_evidence={"source": "synthetic explicit rectangle"})
        self.assertEqual(result["status"], "ok")
        model = result["model"]
        self.assertFalse(model["complete_building"])
        self.assertLessEqual(len(model["faces"]), 600)
        predicted = predict_hypar_z(model, xy)
        self.assertLess(float(np.sqrt(np.mean((predicted - (z - 100)) ** 2))), 0.04)
        self.assertTrue(np.isnan(predict_hypar_z(model, [[40, 40]])[0]))

    def test_flat_part_is_not_forced_into_hypar(self):
        polygon = Polygon([(0, 0), (12, 0), (12, 8), (0, 8)])
        rng = np.random.default_rng(8)
        xy = rng.uniform([0, 0], [12, 8], (120, 2))
        result = fit_hypar_part(polygon, np.column_stack((xy, np.full(120, 110))), 100,
                                part_evidence={"source": "synthetic explicit rectangle"})
        self.assertEqual(result["status"], "quadratic_not_supported_as_saddle")


if __name__ == "__main__":
    unittest.main()
