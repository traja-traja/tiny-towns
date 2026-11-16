from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from overture_stac_subset import select_paths


class SpatialFileSelectionTests(unittest.TestCase):
    def test_city_crop_keeps_overlap_and_unknown_bounds(self):
        index = {'files': [
            {'path': 'city', 'bbox': [14,48,15,49]},
            {'path': 'far', 'bbox': [-120,30,-100,50]},
            {'path': 'continent', 'bbox': [-10,35,40,60]},
            {'path': 'unknown', 'bbox': None}]}
        self.assertEqual(select_paths(index,(14.4,14.5,48.9,49)),['city','continent','unknown'])

    def test_touching_boundary_is_not_dropped_by_coarse_filter(self):
        index = {'files': [{'path': 'edge', 'bbox': [14,48,14.4,49]}]}
        self.assertEqual(select_paths(index,(14.4,14.5,48.9,49)),['edge'])

    def test_empty_region_keeps_only_a_schema_source(self):
        index = {'files': [{'path': 'a', 'bbox': [-120,30,-100,50]},
                           {'path': 'b', 'bbox': [-130,30,-120,50]}]}
        self.assertEqual(select_paths(index,(14.4,14.5,48.9,49)),['a'])


if __name__ == '__main__': unittest.main()
