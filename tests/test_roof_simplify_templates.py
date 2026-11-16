import sys
import unittest
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from roof_simplify_templates import fit_simple_candidates


def points(poly, height, nx=29, ny=21):
    x0, y0, x1, y1 = poly.bounds
    xy = np.array([(x, y) for x in np.linspace(x0+.1, x1-.1, nx)
                   for y in np.linspace(y0+.1, y1-.1, ny)])
    xy = xy[shapely.contains_xy(poly, xy[:, 0], xy[:, 1])]
    return np.column_stack((xy, height(xy)))


class NoHoldoutCase(dict):
    def __getitem__(self, key):
        if 'test' in key or 'hold' in key:
            raise AssertionError('Holdout leakage')
        return super().__getitem__(key)


class TemplatePartsTest(unittest.TestCase):
    def test_two_height_volumes_are_recovered_and_cover_footprint(self):
        poly = box(-20, -10, 20, 10)
        train = points(poly, lambda xy: np.where(xy[:, 0] <= 0, 6., 10.))
        result = fit_simple_candidates(NoHoldoutCase(id='steps', polygon=poly, train_relative=train),
                                       max_parts=2, max_candidate_cuts=3)
        model = result['candidates'][1]
        self.assertEqual(model['template_part_count'], 2)
        self.assertTrue(result['partition_log'][0]['accepted'])
        self.assertTrue(all(p['shape'] == 'flat' for p in model['parts']))
        self.assertLess(model['partition_coverage']['missing_area_m2'], 1e-6)
        self.assertGreater(max(s['maximum_height_jump_m'] for s in model['internal_seams']), 3.9)
        self.assertFalse(model['selection']['holdout_used'])

    def test_simple_gable_is_not_needlessly_partitioned(self):
        poly = box(-10, -6, 10, 6)
        train = points(poly, lambda xy: 10.-.5*np.abs(xy[:, 1]))
        result = fit_simple_candidates({'id':'gable','polygon':poly,'train_relative':train},
                                       max_parts=2,max_candidate_cuts=2)
        self.assertEqual(result['candidates'][0]['shape'], 'gabled')
        self.assertEqual(result['candidates'][1]['template_part_count'], 1)

    def test_courtyard_is_not_filled(self):
        poly = Polygon([[-15,-15],[15,-15],[15,15],[-15,15]],
                       [[[-5,-5],[-5,5],[5,5],[5,-5]]])
        result = fit_simple_candidates({'id':'court','polygon':poly,
                                       'train_relative':points(poly,lambda xy:np.full(len(xy),8.))},
                                       max_parts=1)
        model=result['candidates'][1]
        v=np.asarray(model['vertices'])
        roofs=[Polygon(v[f,:2]) for f,k in zip(model['faces'],model['face_semantics']) if k=='roof']
        union=unary_union(roofs)
        self.assertLess(union.symmetric_difference(poly).area, 1e-6)

    def test_declared_budget_rejects_unbounded_configuration(self):
        with self.assertRaises(ValueError):
            fit_simple_candidates({},max_parts=5)


if __name__=='__main__':
    unittest.main()
