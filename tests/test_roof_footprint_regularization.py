"""Geometry contracts for shallow repeated facade teeth, independent of addresses."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))

from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, box
from roof_footprint_regularization import regularize_footprint


def toothed_wall(depth=.8, repeats=4):
    """One long facade has short outer piers and much longer recessed segments."""
    vertices = [(0., 0.), (20., 0.)]
    for index in range(repeats):
        y = index*3.5
        vertices.extend([(20., y+.5), (20.-depth, y+.5),
                         (20.-depth, y+3.5), (20., y+3.5)])
    # Finish with a vertical outer pier; otherwise the last horizontal return
    # would overlap the top wall and the synthetic input would be invalid.
    vertices.extend([(20., repeats*3.5+.5), (0., repeats*3.5+.5)])
    return Polygon(vertices)


class FootprintRegularizationTests(unittest.TestCase):
    def assertSameGeometry(self, a, b, tolerance=1e-7):
        self.assertLess(a.symmetric_difference(b).area, tolerance)
        self.assertLess(a.hausdorff_distance(b), tolerance)

    def assertPreserved(self, polygon):
        result, metadata = regularize_footprint(polygon)
        self.assertSameGeometry(result, polygon)
        self.assertFalse(metadata['changed'])
        self.assertTrue(result.is_valid)
        self.assertGreater(result.area, 0.)

    def test_repeated_shallow_teeth_become_a_simple_wall(self):
        original = toothed_wall()
        result, metadata = regularize_footprint(original)
        self.assertTrue(metadata['changed'])
        self.assertTrue(result.is_valid)
        self.assertEqual(result.geom_type, 'Polygon')
        self.assertGreater(result.area, 0.)
        self.assertLessEqual(len(result.exterior.coords)-1, 6)
        self.assertLess(len(result.exterior.coords), len(original.exterior.coords))
        self.assertLessEqual(original.boundary.hausdorff_distance(result.boundary), .8+1e-7)
        self.assertAlmostEqual(result.bounds[0], 0., places=6)
        self.assertAlmostEqual(result.bounds[1], 0., places=6)
        self.assertAlmostEqual(result.bounds[3], 14.5, places=6)
        self.assertEqual(metadata['vertices_before'], len(original.exterior.coords)-1)
        self.assertEqual(metadata['vertices_after'], len(result.exterior.coords)-1)
        self.assertAlmostEqual(metadata['area_change_m2'], result.area-original.area, places=6)
        self.assertGreaterEqual(metadata['max_displacement_m'], 0.)
        self.assertLessEqual(metadata['max_displacement_m'], 1.25+1e-7)

    def test_rotation_and_translation_do_not_change_the_decision(self):
        original = toothed_wall()
        expected, _ = regularize_footprint(original)
        for angle in (27., 83., 171.):
            with self.subTest(angle=angle):
                transformed = translate(rotate(original, angle, origin=(0, 0)), 123.4, -67.2)
                result, metadata = regularize_footprint(transformed)
                target = translate(rotate(expected, angle, origin=(0, 0)), 123.4, -67.2)
                self.assertTrue(metadata['changed'])
                self.assertSameGeometry(result, target, tolerance=1e-6)

    def test_ring_start_and_winding_do_not_change_geometry(self):
        original = toothed_wall()
        expected, _ = regularize_footprint(original)
        vertices = list(original.exterior.coords)[:-1]
        for offset in (1, 4, 9, len(vertices)-1):
            for reverse in (False, True):
                with self.subTest(offset=offset, reverse=reverse):
                    shifted = vertices[offset:]+vertices[:offset]
                    if reverse:
                        shifted.reverse()
                    result, metadata = regularize_footprint(Polygon(shifted))
                    self.assertTrue(metadata['changed'])
                    self.assertSameGeometry(result, expected)

    def test_real_wings_and_single_annex_remain(self):
        shapes = {
            'L':box(0, 0, 24, 8).union(box(0, 0, 8, 22)),
            'U':box(0, 0, 24, 8).union(box(0, 0, 6, 24)).union(box(18, 0, 24, 24)),
            'single_annex':box(0, 0, 20, 15).union(box(20, 5, 24, 10)),
            'single_notch':box(0, 0, 20, 15).difference(box(16, 4, 21, 10)),
            'trapezoid':Polygon([(0, 0), (20, 0), (17, 15), (2, 15)]),
        }
        for name, polygon in shapes.items():
            with self.subTest(shape=name):
                self.assertPreserved(polygon)

    def test_courtyard_hole_survives_outer_wall_simplification(self):
        courtyard = box(4, 4, 12, 10)
        original = toothed_wall().difference(courtyard)
        result, metadata = regularize_footprint(original)
        self.assertTrue(metadata['changed'])
        self.assertEqual(len(result.interiors), 1)
        self.assertSameGeometry(Polygon(result.interiors[0]), courtyard)
        self.assertAlmostEqual(result.intersection(courtyard).area, 0., places=7)

    def test_deep_teeth_and_too_few_repetitions_remain(self):
        self.assertPreserved(toothed_wall(depth=2.2))
        self.assertPreserved(toothed_wall(repeats=2))


if __name__ == '__main__':
    unittest.main()
