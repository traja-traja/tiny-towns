"""Small protocol checks; no real model fitting or network access."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.roof_simplify_roofer import (
    PROFILES, ROOT, native_model_status, native_variant_command, run_native_variant, snapshot_sources,
)


class NativeSimplificationTest(unittest.TestCase):
    def test_native_fallback_attribute_overrides_lod22_label(self):
        model = {"status": "ok", "lods": ["2.2"],
                 "attributes": {"rf_extrusion_mode": "lod11_fallback"}}
        self.assertEqual(native_model_status(model), "lod11_fallback")
        model["attributes"]["rf_extrusion_mode"] = "standard"
        self.assertEqual(native_model_status(model), "ok")
        model["status"] = "invalid_mesh"
        self.assertEqual(native_model_status(model), "invalid_mesh")

    def test_profiles_keep_sloped_roofs_and_data_quality_gate(self):
        for profile in PROFILES:
            command = native_variant_command(profile, "train.laz", "footprints.json", "out")
            self.assertIn("--lod22", command)
            self.assertIn("--no-lod13", command)
            self.assertIn("--no-lod12", command)
            self.assertNotIn("--no-clear-insufficient", command)
            self.assertEqual(command[command.index("--h-terrain-strategy") + 1], "user")
            self.assertEqual(command[-3:], ["train.laz", "footprints.json", "out"])

    def test_experiment_does_not_accept_whole_city(self):
        features = [{"type": "Feature", "properties": {"id": str(i), "centre_x": 0,
                     "centre_y": 0, "ground_z": 0},
                     "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
                    for i in range(9)]
        with self.assertRaisesRegex(ValueError, "eight"):
            run_native_variant(features, "does-not-exist.laz", "out", "roofer_c035")

    def test_source_snapshots_match_recorded_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            records = snapshot_sources(temporary)
            self.assertGreaterEqual(len(records), 5)
            for record in records:
                snapshot = Path(record["snapshot_path"]).read_bytes()
                self.assertEqual(snapshot, (ROOT / record["path"]).read_bytes())
                self.assertEqual(record["sha256"], hashlib.sha256(snapshot).hexdigest())


if __name__ == "__main__":
    unittest.main()
