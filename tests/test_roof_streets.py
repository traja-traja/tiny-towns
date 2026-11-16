import sys
import unittest
from pathlib import Path
import shapely
from shapely.geometry import Point, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from select_roof_streets import select


class StreetSelectionTests(unittest.TestCase):
    def test_deduplicates_building_ids_but_preserves_addresses_and_unresolved(self):
        buildings = [{'id': 'main', 'geometry': shapely.to_wkb(box(0, 0, 4, 4))}]
        addresses = [{'id': str(i), 'street': 'Školní', 'number': str(i), 'unit': None,
                      'geometry': shapely.to_wkb(Point(x, 1))}
                     for i, x in enumerate((1, 2, 10), 1)]
        requests, report = select(['školní'], addresses, buildings)
        self.assertEqual(len(requests), 2)
        self.assertEqual(report['unique_buildings'], 1)
        self.assertEqual(report['unresolved'][0]['reason'], 'missing_footprint')
        self.assertEqual(report['streets']['školní']['addresses'], 3)

    def test_ambiguous_footprint_is_not_chosen_and_unrelated_street_is_ignored(self):
        buildings = [{'id': n, 'geometry': shapely.to_wkb(box(0, 0, 4, 4))} for n in ('a', 'b')]
        addresses = [{'id': 'x', 'street': s, 'number': '1', 'unit': None,
                      'geometry': shapely.to_wkb(Point(1, 1))} for s in ('Školní', 'Jiná')]
        requests, report = select(['Školní'], addresses, buildings)
        self.assertEqual(requests, [])
        self.assertEqual(len(report['unresolved']), 1)
        self.assertEqual(report['unresolved'][0]['reason'], 'ambiguous_footprint')


if __name__ == '__main__':
    unittest.main()
