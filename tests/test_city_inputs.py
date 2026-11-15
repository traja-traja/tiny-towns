import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from scripts import configure_city, fetch_city_inputs


class FetchCityInputsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.city = self.root / "cities" / "test-obec"
        self.city.mkdir(parents=True)
        self.profile = {"municipality_code": "545821", "center": [14.46, 48.83], "map": {"nazev": "Test"}}
        (self.city / "profile.json").write_text(json.dumps(self.profile), encoding="utf-8")
        self.layer = {
            "name": "ObeC",
            "id": 91,
            "fields": [{"name": "KoD"}, {"name": "Nazev"}],
            "geometryType": "esriGeometryPolygon",
        }
        self.metadata = {"layers": [
            {**self.layer, "id": 12, "geometryType": "esriGeometryPoint"},
            self.layer,
        ]}
        self.feature = {
            "type": "Feature",
            "properties": {"KOD": 545821, "nazev": "Test"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [14.44, 48.826], [14.48, 48.826], [14.48, 48.834], [14.44, 48.834], [14.44, 48.826],
            ]]},
        }
        self.boundary = {"type": "FeatureCollection", "features": [self.feature]}
        self.tiles = self.png()
        self.requests = []

    @staticmethod
    def png(size=(256, 256)):
        output = io.BytesIO()
        Image.new("RGB", size, (130, 10, 0)).save(output, format="PNG")
        return output.getvalue()

    def urlopen(self, request, *, timeout):
        self.assertEqual(timeout, 20)
        url = request.full_url
        self.requests.append(url)
        if url == f"{fetch_city_inputs.RUIAN_URL}/layers?f=json":
            return io.BytesIO(json.dumps(self.metadata).encode("utf-8"))
        if url.startswith(f"{fetch_city_inputs.RUIAN_URL}/91/query?"):
            self.assertEqual(parse_qs(urlsplit(url).query), {
                "where": ["KoD=545821"], "outFields": ["*"], "returnGeometry": ["true"],
                "outSR": ["4326"], "f": ["geojson"],
            })
            return io.BytesIO(json.dumps(self.boundary).encode("utf-8"))
        self.assertTrue(url.startswith(configure_city.TERRARIUM_URL + "/12/"), url)
        return io.BytesIO(self.tiles)

    def call(self, *args):
        error = io.StringIO()
        with patch.object(fetch_city_inputs, "urlopen", self.urlopen), contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(error):
                code = fetch_city_inputs.main(["test-obec", *args], root=self.root)
        return code, error.getvalue()

    def data(self, filename):
        return json.loads((self.city / filename).read_text(encoding="utf-8"))

    def test_import_chooses_polygon_layer_and_generates_both_profiles(self):
        code, error = self.call()
        self.assertEqual(code, 0, error)
        boundary_source = self.data("boundary-source.json")
        self.assertEqual(boundary_source["layer_id"], 91)
        self.assertEqual(boundary_source["attribution"], "© ČÚZK")
        self.assertEqual(boundary_source["sha256"], hashlib.sha256((self.city / "boundary.geojson").read_bytes()).hexdigest())
        terrain = self.data("terrain-source.json")
        self.assertEqual(terrain["attribution_reference"], "https://registry.opendata.aws/terrain-tiles/")
        self.assertEqual(len(terrain["tiles"]), len(self.requests[2:]))
        for tile in terrain["tiles"]:
            self.assertIn(tile["url"], self.requests)
            self.assertEqual(tile["sha256"], hashlib.sha256((self.city / tile["path"]).read_bytes()).hexdigest())
        full, preview = self.data("mesto.json"), self.data("mesto.preview.json")
        self.assertGreater(len(full["ctverce"]), 1)
        self.assertEqual(preview["ctverce"], [[0, 0]])
        self.assertEqual(full["href"], preview["href"])
        self.assertEqual(self.data("coverage.json")["municipality"]["omitted_area_m2"], 0)

    def test_rerun_preserves_edited_configs_and_downloads_only_missing_tiles(self):
        self.assertEqual(self.call()[0], 0)
        config = self.city / "mesto.json"
        edited = config.read_text(encoding="utf-8").replace('"nazev": "Test"', '"nazev": "Upraveno"')
        config.write_text(edited, encoding="utf-8")
        first_tile = self.data("terrain-source.json")["tiles"][0]
        (self.city / first_tile["path"]).unlink()
        self.requests.clear()
        code, error = self.call()
        self.assertEqual(code, 0, error)
        self.assertEqual(self.requests, [first_tile["url"]])
        self.assertEqual(config.read_text(encoding="utf-8"), edited)

        self.requests.clear()
        code, error = self.call("--replace")
        self.assertEqual(code, 0, error)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.data("mesto.json")["nazev"], "Test")
        self.assertEqual((self.city / "mesto.json.bak").read_text(encoding="utf-8"), edited)

    def test_cached_boundary_must_match_municipality_and_recorded_hash(self):
        self.assertEqual(self.call()[0], 0)
        self.requests.clear()
        path = self.city / "profile.json"
        path.write_text(json.dumps({**self.profile, "municipality_code": "544256"}), encoding="utf-8")
        code, error = self.call()
        self.assertEqual(code, 1)
        self.assertIn("Kód obce v hranici nesouhlasí", error)
        self.assertEqual(self.requests, [])

        path.write_text(json.dumps(self.profile), encoding="utf-8")
        boundary = self.city / "boundary.geojson"
        changed = boundary.read_bytes() + b"\n"
        boundary.write_bytes(changed)
        code, error = self.call()
        self.assertEqual(code, 1)
        self.assertIn("Otisk", error)
        self.assertEqual(boundary.read_bytes(), changed)
        self.assertEqual(self.requests, [])

    def test_terrain_retrieval_date_is_reused_only_for_identical_cached_tiles(self):
        old_time, new_time = "2026-11-15T12:00:00+00:00", "2026-11-15T12:10:00+00:00"
        with patch.object(fetch_city_inputs, "timestamp", return_value=old_time):
            self.assertEqual(self.call()[0], 0)
        before = self.data("terrain-source.json")
        first, second, third, *_ = before["tiles"]
        self.assertEqual(first["retrieved_at"], old_time)
        first["url"] += "?another_source=1"
        (self.city / "terrain-source.json").write_text(json.dumps(before), encoding="utf-8")
        (self.city / second["path"]).unlink()
        self.requests.clear()

        with patch.object(fetch_city_inputs, "timestamp", return_value=new_time):
            code, error = self.call()
        self.assertEqual(code, 0, error)
        recorded = self.data("terrain-source.json")
        self.assertEqual(recorded["verified_at"], new_time)
        entries = {entry["path"]: entry for entry in recorded["tiles"]}
        self.assertNotIn("retrieved_at", entries[first["path"]])
        self.assertEqual(entries[second["path"]]["retrieved_at"], new_time)
        self.assertEqual(entries[third["path"]]["retrieved_at"], old_time)
        self.assertEqual(self.requests, [second["url"]])

    def test_rejects_ambiguous_layer_or_mismatched_municipality(self):
        self.metadata["layers"].append({**self.layer, "id": 92, "name": "Obce"})
        code, error = self.call()
        self.assertEqual(code, 1)
        self.assertIn("polygonovou vrstvu", error)
        self.metadata["layers"].pop()
        self.feature["properties"]["KOD"] = 544256
        code, error = self.call()
        self.assertEqual(code, 1)
        self.assertIn("nesouhlasí", error)
        self.assertFalse((self.city / "boundary.geojson").exists())

    def test_unusable_terrain_is_not_written(self):
        self.tiles = self.png((16, 16))
        code, error = self.call()
        self.assertEqual(code, 1)
        self.assertIn("256 × 256", error)
        self.assertTrue((self.city / "boundary-source.json").is_file())
        self.assertFalse(any(self.city.rglob("*.png")))
        self.assertFalse((self.city / "mesto.json").exists())


if __name__ == "__main__":
    unittest.main()
