import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import towns


class TownsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write("geo.py", "engine")
        self.write("web/app.html", "web")
        self.write(".dev.vars", "secret")
        self.write("web/.env", "secret")
        self.write("assets/dominanty.json", "old root-level project")
        for slug, name, lon in (
            ("velesin", "Velešín", 14.463),
            ("ceske-budejovice", "České Budějovice", 14.475),
        ):
            self.write(f"cities/{slug}/mesto.json", json.dumps({
                "nazev": name, "stred": [lon, 48.83], "polovina": 1150,
                "ctverce": [[0, 0]], "href": 520, "dno": -40,
            }, ensure_ascii=False))
            self.write(f"cities/{slug}/assets/upresneni.json", slug)
        self.write("cities/velesin/mista.json", "[]")

    def write(self, relative_path, data):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
        return path

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = towns.main(args, root=self.root)
        return code, stdout.getvalue(), stderr.getvalue()

    def prepare(self, slug="velesin"):
        code, _, error = self.cli("prepare", slug)
        self.assertEqual(code, 0, error)
        return self.root / ".work" / slug

    def test_two_cities_get_separate_workspaces(self):
        left = self.prepare("velesin")
        right = self.prepare("ceske-budejovice")
        for work, city in ((left, "Velešín"), (right, "České Budějovice")):
            self.assertIn(city, (work / "mesto.json").read_text(encoding="utf-8"))
            self.assertEqual((work / "assets/upresneni.json").read_text(), work.name)
            self.assertEqual((work / "geo.py").read_text(), "engine")
            for relative_path in (".dev.vars", "web/.env", "assets/dominanty.json"):
                self.assertFalse((work / relative_path).exists())
        self.assertTrue((left / "mista.json").is_file())
        self.assertFalse((right / "mista.json").exists())

        self.write(".work/velesin/data/building.parquet", "only Velešín")
        self.assertFalse((right / "data/building.parquet").exists())

    def test_refresh_preserves_caches_and_removes_stale_managed_inputs(self):
        work = self.prepare()
        cache = self.write(".work/velesin/data_c0_1/segment.parquet", "cache")
        generated = self.write(".work/velesin/assets/dmp_vysky.json", "generated")
        self.write("geo.py", "updated engine")
        self.write("cities/velesin/assets/upresneni.json", "updated city asset")
        (self.root / "cities/velesin/mista.json").unlink()
        self.prepare()
        self.assertEqual((work / "geo.py").read_text(), "updated engine")
        self.assertEqual((work / "assets/upresneni.json").read_text(), "updated city asset")
        self.assertFalse((work / "mista.json").exists())
        self.assertEqual(cache.read_text(), "cache")
        self.assertEqual(generated.read_text(), "generated")

    def test_refresh_preserves_local_edits_when_a_managed_input_is_removed(self):
        work = self.prepare()
        (self.root / "cities/velesin/assets/upresneni.json").unlink()
        edited = self.write(".work/velesin/assets/upresneni.json", "local edit")
        self.write("geo.py", "updated engine")

        code, _, error = self.cli("prepare", "velesin")
        self.assertEqual(code, 1)
        self.assertIn("upresneni.json", error)
        self.assertEqual(edited.read_text(), "local edit")
        self.assertEqual((work / "geo.py").read_text(), "engine")

    def test_cache_is_not_reused_after_geometry_change(self):
        work = self.prepare()
        cache = self.write(".work/velesin/data/building.parquet", "old area")
        profile = self.root / "cities/velesin/mesto.json"
        config = json.loads(profile.read_text(encoding="utf-8"))
        config["ctverce"].append([0, 1])
        self.write("cities/velesin/mesto.json", json.dumps(config))

        code, _, error = self.cli("prepare", "velesin")
        self.assertEqual(code, 1)
        self.assertIn("Geometrie", error)
        self.assertEqual(cache.read_text(), "old area")
        self.assertEqual(json.loads((work / "mesto.json").read_text(encoding="utf-8"))["ctverce"], [[0, 0]])

    def test_invalid_city_names_do_not_create_workspaces(self):
        for slug in ("../velesin", "../ceske-budejovice", "velesin\\..", "C:somewhere", "con", "unknown"):
            with self.subTest(slug=slug):
                code, _, error = self.cli("prepare", slug)
                self.assertEqual(code, 1)
                self.assertTrue(error)
        self.assertFalse((self.root / ".work").exists())

    def test_manifest_cannot_claim_a_cache_file(self):
        work = self.prepare()
        cache = self.write(".work/velesin/data/building.parquet", "cache")
        self.write(".work/velesin/.towns-inputs.json", json.dumps({
            "files": {"data/building.parquet": towns.digest(cache)},
        }))
        code, _, error = self.cli("prepare", "velesin")
        self.assertEqual(code, 1)
        self.assertIn("seznam připravených souborů", error)
        self.assertIn(cache, work.rglob("*.parquet"))

    def test_dependencies_are_shared(self):
        python = towns.venv_python(self.root)
        self.write(python.relative_to(self.root), "stub")
        self.write("node_modules/three/build/three.module.js", "module")
        self.write("node_modules/playwright/shared", "shared runtime")
        for slug in ("velesin", "ceske-budejovice", "velesin"):
            work = self.prepare(slug)
            self.assertEqual((work / "node_modules/three/build/three.module.js").read_text(), "module")
            if os.name == "nt":
                self.assertTrue((work / ".venv/Scripts/activate").is_file())
                self.assertFalse((work / "node_modules/playwright").exists())
                self.assertFalse((work / ".venv/Scripts/python.exe").exists())
            else:
                for name in towns.DEPS:
                    self.assertEqual((work / name).resolve(), (self.root / name).resolve())

    def test_preview_profile_does_not_replace_full_city_or_its_data(self):
        full = self.prepare()
        cache = self.write(".work/velesin/data/building.parquet", "full map")
        preview_config = json.loads((full / "mesto.json").read_text(encoding="utf-8"))
        preview_config["stred"][0] += 0.01
        self.write("cities/velesin/mesto.preview.json", json.dumps(preview_config))
        code, _, error = self.cli("prepare", "velesin", "--profile", "preview")
        self.assertEqual(code, 0, error)
        preview = self.root / ".work/.preview/velesin"
        self.assertEqual(json.loads((preview / "mesto.json").read_text()), preview_config)
        self.assertNotEqual((full / "mesto.json").read_bytes(), (preview / "mesto.json").read_bytes())
        self.assertEqual(cache.read_text(), "full map")
        self.assertFalse((preview / "data").exists())

    def test_build_calls_upstream_in_the_selected_workspace(self):
        python = towns.venv_python(self.root)
        self.write(python.relative_to(self.root), "stub")
        self.write("node_modules/three/build/three.module.js", "module")
        self.write("node_modules/playwright/shared", "shared runtime")
        script = self.write("postav.sh", "build script")
        with patch.object(towns, "run_command") as run:
            code, _, error = self.cli("build", "ceske-budejovice", "--render-only")
        self.assertEqual(code, 0, error)
        work = self.root / ".work/ceske-budejovice"
        self.assertEqual((work / script.name).read_bytes(), script.read_bytes())
        run.assert_called_once_with(self.root, work, ["sh", "./postav.sh", "render"])

    def test_running_command_locks_one_workspace_only(self):
        work = self.prepare()
        with towns.workspace_lock(work):
            code, _, error = self.cli("prepare", "velesin")
            self.assertEqual(code, 1)
            self.assertIn("právě používá", error)
            self.prepare("ceske-budejovice")
        self.prepare()

    def test_run_in_one_city_ignores_external_city_config_and_reports_failure(self):
        program = (
            "import os; from pathlib import Path; "
            "assert 'IZO_MESTO' not in os.environ; "
            "Path('build').mkdir(); "
            "Path('build/proof').write_bytes(Path('mesto.json').read_bytes()); "
            "raise SystemExit(23)"
        )
        with patch.dict(os.environ, {"IZO_MESTO": "../velesin/mesto.json"}):
            code, _, error = self.cli("run", "ceske-budejovice", sys.executable, "-c", program)
        self.assertEqual(code, 1)
        self.assertIn("23", error)
        proof = self.root / ".work/ceske-budejovice/build/proof"
        self.assertIn("České Budějovice", proof.read_text(encoding="utf-8"))
        self.assertFalse((self.root / ".work/velesin").exists())

    def test_status_and_preview_use_the_selected_city(self):
        self.prepare()
        code, output, error = self.cli("status")
        self.assertEqual(code, 0, error)
        self.assertIn("velesin: Velešín, čtverců 1, připraveno", output)
        self.assertIn("ceske-budejovice: České Budějovice, čtverců 1, nepřipraveno", output)
        site = self.write(".work/velesin/site/index.html", "test web").parent
        with patch.object(towns, "run_command") as run:
            code, output, error = self.cli("preview", "velesin", "--port", "8001")
        self.assertEqual(code, 0, error)
        self.assertIn("127.0.0.1:8001", output)
        run.assert_called_once_with(self.root, site.parent, [
            sys.executable, "-m", "http.server", "--bind", "127.0.0.1",
            "--directory", str(site), "8001",
        ])


if __name__ == "__main__":
    unittest.main()
