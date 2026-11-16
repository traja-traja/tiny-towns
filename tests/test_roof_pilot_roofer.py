"""CityJSON geometry semantics tests; these do not run Roofer or load real LAS."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.roof_pilot_roofer import parse_cityjsonseq, predict_roofer_z


class RooferAdapterTest(unittest.TestCase):
    def parse(self, header, feature, origin=(0, 0, 0)):
        input_feature = {"type": "Feature", "properties": {
            "id": "house", "centre_x": origin[0], "centre_y": origin[1], "ground_z": origin[2]},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.city.jsonl"
            path.write_text(json.dumps(header) + "\n" + json.dumps(feature) + "\n", encoding="utf-8")
            return parse_cityjsonseq(path, [input_feature])["house"]

    def test_transform_children_semantics_and_millisecond_timing(self):
        header = {"type": "CityJSON", "CityObjects": {}, "vertices": [],
                  "transform": {"scale": [0.5, 0.5, 0.25], "translate": [-1000, -2000, 500]}}
        feature = {"type": "CityJSONFeature", "id": "house",
                   "vertices": [[0, 0, 20], [20, 0, 20], [20, 20, 28], [0, 20, 28],
                                [0, 0, 0], [20, 0, 0], [20, 20, 0], [0, 20, 0]],
                   "CityObjects": {
                       "house": {"type": "Building", "children": ["part"],
                                 "attributes": {"rf_t_run": 125, "rf_roof_type": "slanted"}},
                       "part": {"type": "BuildingPart", "parents": ["house"], "geometry": [{
                           "type": "Solid", "lod": "2.2",
                           "boundaries": [[[[0, 1, 2, 3]], [[4, 5, 6, 7]]]],
                           "semantics": {"surfaces": [{"type": "RoofSurface"}, {"type": "GroundSurface"}],
                                         "values": [[0, 1]]}}]}}}
        model = self.parse(header, feature, (-1000, -2000, 500))
        prediction = predict_roofer_z(model, [[5, 5], [5, 0], [11, 0]])
        np.testing.assert_allclose(prediction[:2], [6, 5])
        self.assertTrue(np.isnan(prediction[2]))
        self.assertEqual(model["timing"]["reconstruction_seconds"], 0.125)
        self.assertEqual(model["metrics"]["roof_triangle_count"], 2)
        self.assertEqual(model["shape"], "slanted")
        json.dumps(model, allow_nan=False)

    def test_multisolid_courtyard_and_lod_selection(self):
        vertices = [[0, 0, 5], [10, 0, 5], [10, 10, 5], [0, 10, 5],
                    [3, 3, 5], [3, 7, 5], [7, 7, 5], [7, 3, 5]]
        surface = [[0, 1, 2, 3], [4, 5, 6, 7]]
        geometry = {"type": "MultiSolid", "lod": "2.2", "boundaries": [[[surface]]],
                    "semantics": {"surfaces": [{"type": "RoofSurface"}], "values": [[[0]]]}}
        lower = {"type": "MultiSurface", "lod": "1.2", "boundaries": [[[0, 1, 2, 3]]],
                 "semantics": {"surfaces": [{"type": "RoofSurface"}], "values": [0]}}
        feature = {"type": "CityJSONFeature", "id": "house", "vertices": vertices,
                   "CityObjects": {"house": {"type": "Building", "geometry": [lower, geometry]}}}
        model = self.parse({"type": "CityJSON"}, feature)
        prediction = predict_roofer_z(model, [[1, 1], [5, 5], [9, 9]])
        self.assertEqual(model["lods"], ["2.2"])
        np.testing.assert_allclose(prediction[[0, 2]], [5, 5])
        self.assertTrue(np.isnan(prediction[1]), "Courtyard must remain unmodelled")

    def test_missing_semantics_and_invalid_faces_not_used_as_roof(self):
        feature = {"type": "CityJSONFeature", "id": "house",
                   "vertices": [[0, 0, 5], [10, 0, 5], [0, 10, 5]],
                   "CityObjects": {"house": {"type": "Building", "geometry": [{
                       "type": "MultiSurface", "lod": "2.2",
                       "boundaries": [[[0, 1, 2]], [[0, 1, 99]]]}]}}}
        model = self.parse({"type": "CityJSON"}, feature)
        self.assertTrue(np.isnan(predict_roofer_z(model, [[1, 1]])[0]))
        self.assertEqual(model["metrics"]["invalid_faces_skipped"], 1)
        self.assertIn("no_semantic_roof_surface", model["warnings"])


if __name__ == "__main__":
    unittest.main()
