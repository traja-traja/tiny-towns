"""Small offline checks for data correctness and interrupted-build recovery."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_preview_guarded as preview


class PreviewRecoveryTests(unittest.TestCase):
    def test_web_without_gtfs_skips_legacy_failure_exit(self):
        with tempfile.TemporaryDirectory(prefix="izomapa-preview-test-") as directory:
            work = Path(directory)
            (work / "mesto.json").write_text(json.dumps({"mhd": {"gtfs": None}}))
            with preview.in_workspace(work), patch("resource_guard.check_budget"), patch.object(preview, "run_python") as run:
                preview.internal_step("web", work)
                self.assertEqual([call.args for call in run.call_args_list],
                                 [("overlay.py",), ("set_status.py", "hotovo"), ("build_html.py",)])
                self.assertTrue(json.loads((work / "site/preview-build.json").read_text())["complete"])

    def test_partial_render_is_never_accepted(self):
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix="izomapa-preview-test-") as directory:
            directory = Path(directory)
            (directory / "info.json").write_text(json.dumps({"rows": 1, "cols": 2}))
            Image.new("RGBA", (16, 16)).save(directory / "0_0.png")
            self.assertFalse(preview.render_complete(directory))
            Image.new("RGBA", (16, 16)).save(directory / "1_0.png")
            self.assertTrue(preview.render_complete(directory))
            (directory / "rozpracovano").touch()
            self.assertFalse(preview.render_complete(directory))

    def test_streamed_bbox_crop_and_completed_file_reuse(self):
        import pyarrow as pa
        import pyarrow.dataset as ds
        import pyarrow.parquet as pq
        boxes = [{"xmin": x, "xmax": x + 0.5, "ymin": 0.0, "ymax": 0.5} for x in (0.0, 2.0, 4.0)]
        table = pa.table({"id": ["in", "touch", "out"], "bbox": boxes})
        with tempfile.TemporaryDirectory(prefix="izomapa-preview-test-") as directory:
            target = Path(directory) / "building.parquet"
            with patch("resource_guard.check_budget"):
                preview.stream_parquet(ds.dataset(table), target, (-1, 2, -1, 1))
                self.assertEqual(pq.read_table(target).column("id").to_pylist(), ["in"])
                original = target.read_bytes()
                preview.stream_parquet(ds.dataset(table.slice(0, 0)), target, (-1, 2, -1, 1))
                self.assertEqual(target.read_bytes(), original)
                missing = Path(directory) / "other" / "building.parquet"
                with self.assertRaisesRegex(ValueError, "No buildings"):
                    preview.stream_parquet(ds.dataset(table.slice(0, 0)), missing, (-1, 2, -1, 1))
                self.assertFalse(missing.exists())
                self.assertFalse(missing.with_name("building.parquet.partial").exists())

    def test_wfs_error_document_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="izomapa-preview-test-") as directory:
            path = Path(directory) / "response.xml"
            path.write_text('<ExceptionReport><Exception>Unavailable</Exception></ExceptionReport>')
            with self.assertRaisesRegex(ValueError, "not a feature collection"):
                preview.validate_wfs(path)
            path.write_text('<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"/>')
            preview.validate_wfs(path)  # A real successful empty response is valid.

    def test_dzi_checkpoint_checks_every_level_and_actual_webp_format(self):
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix="izomapa-preview-test-") as directory:
            directory = Path(directory)
            (directory / "site").mkdir()
            (directory / "site/tiles.json").write_text(json.dumps({"summer": {"Image": {
                "Size": {"Width": "2", "Height": "2"}, "TileSize": "2048", "Format": "webp"}}}))
            for level in (0, 1):
                target = directory / f"site/tiles/summer/{level}"
                target.mkdir(parents=True)
                Image.new("RGBA", (2 ** level, 2 ** level)).save(target / "0_0.webp", "WEBP", lossless=True)
            self.assertTrue(preview.validate_step("dzi-summer", directory))
            (directory / "site/tiles/summer/0/0_0.webp").unlink()
            self.assertFalse(preview.validate_step("dzi-summer", directory))


if __name__ == "__main__":
    unittest.main()
