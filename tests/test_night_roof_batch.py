"""Cache and time-policy checks for unattended fitting; no city downloads."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import night_roof_batch as night


class NightPolicyTests(unittest.TestCase):
    def setUp(self):
        self.building = {'id': 'sample', 'parts': [{'part_index': 0,
            'footprint': {'type': 'Polygon', 'coordinates': [[[0,0],[10,0],[10,10],[0,0]]]},
            'origin_xy': [100,200], 'ground_z': 500, 'cache': {'sha256': 'aa', 'path': 'old.npz'}}]}
        self.engine = {'code': {'fitter': 'abc'}, 'configuration': {'flat': True}}

    def test_cache_ignores_location_but_not_points_geometry_or_algorithm(self):
        original = night.fingerprint(self.building, self.engine)
        moved = copy.deepcopy(self.building); moved['parts'][0]['cache']['path'] = 'elsewhere.npz'
        self.assertEqual(original, night.fingerprint(moved, self.engine))
        for key, value in [('ground_z', 501), ('origin_xy', [101,200])]:
            changed = copy.deepcopy(self.building); changed['parts'][0][key] = value
            self.assertNotEqual(original, night.fingerprint(changed, self.engine))
        changed = copy.deepcopy(self.building); changed['parts'][0]['cache']['sha256'] = 'bb'
        self.assertNotEqual(original, night.fingerprint(changed, self.engine))
        self.assertNotEqual(original, night.fingerprint(self.building, {'code': 'new'}))

    def test_failed_or_wrong_model_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'model.json'
            for status in ('failed', 'incomplete'):
                night.write(path, {'fingerprint': 'same', 'model': {'status': status}})
                self.assertIsNone(night.cached_model(path, 'same'))
            night.write(path, {'fingerprint': 'same', 'model': {'status': 'complete'}})
            self.assertIsNone(night.cached_model(path, 'different'))
            self.assertEqual(night.cached_model(path, 'same')['status'], 'complete')

    def test_missing_point_hash_cannot_reuse(self):
        self.building['parts'][0]['cache'].pop('sha256')
        with self.assertRaises(ValueError): night.fingerprint(self.building, self.engine)

    def test_extra_time_requires_complete_initial_stages_under_two_hours(self):
        self.assertTrue(night.extra_allowed(7199, True))
        self.assertFalse(night.extra_allowed(7200, True))
        self.assertFalse(night.extra_allowed(10, False))

    def test_provider_id_cannot_escape_model_folder(self):
        folder = Path('models')
        path = night.model_file(folder, '../../outside', 'a' * 64)
        self.assertEqual(path.parent, folder)


if __name__ == '__main__': unittest.main()
