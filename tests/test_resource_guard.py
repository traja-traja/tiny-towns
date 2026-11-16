import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('guard', Path(__file__).resolve().parents[1] / 'scripts/resource_guard.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class ResourceGuardTests(unittest.TestCase):
    def test_zip_cannot_escape_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with zipfile.ZipFile(root / 'source.zip', 'w') as archive:
                archive.writestr('../outside.txt', 'must not escape')
            with patch.object(guard, 'check_budget'), self.assertRaises(ValueError):
                guard.safe_extract_zip(root / 'source.zip', root / 'output')
            self.assertFalse((root / 'outside.txt').exists())

    def test_interrupted_extract_does_not_leave_final_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with zipfile.ZipFile(root / 'source.zip', 'w') as archive:
                archive.writestr('tile.laz', b'input points')
            with patch.object(guard, 'check_budget', side_effect=[None, guard.ResourceLimit('disk stop')]):
                with self.assertRaises(guard.ResourceLimit):
                    guard.safe_extract_zip(root / 'source.zip', root / 'output')
            self.assertFalse((root / 'output/tile.laz').exists())
            self.assertFalse((root / 'output/tile.laz.resource-guard-part').exists())
            with patch.object(guard, 'check_budget'):
                guard.safe_extract_zip(root / 'source.zip', root / 'output')
            self.assertEqual((root / 'output/tile.laz').read_bytes(), b'input points')

    def test_disk_floor_stops_before_write(self):
        with patch.object(guard.shutil, 'disk_usage') as usage:
            usage.return_value.free = 24_999_999_999
            with self.assertRaises(guard.ResourceLimit): guard.check_budget()

    def test_project_limit_reserves_next_download(self):
        with patch.object(guard.shutil, 'disk_usage') as usage, patch.object(guard, 'project_size', return_value=19_000_000_000):
            usage.return_value.free = 50_000_000_000
            with self.assertRaises(guard.ResourceLimit): guard.check_budget(reserve_bytes=800_000_000, force=True)


if __name__ == '__main__':
    unittest.main()
