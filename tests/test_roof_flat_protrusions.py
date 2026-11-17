"""Synthetic evidence checks for one robust flat top per elevated component."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import numpy as np
import shapely
from shapely.affinity import rotate
from shapely.geometry import Polygon, box, shape, mapping

from roof_flat_protrusions import detect_flat_protrusions
from roof_v2_geometry import build_mesh


CELL = .35
BASE = 8.


def block(ix, iy, nx, ny, height=12.):
    x, y = np.meshgrid(np.arange(ix, ix + nx), np.arange(iy, iy + ny))
    return np.c_[(x.ravel() + .5) * CELL,
                 (y.ravel() + .5) * CELL, np.full(x.size, height)]


class FlatProtrusionTests(unittest.TestCase):
    def detect(self, points, poly=None, cfg=None):
        return detect_flat_protrusions(poly if poly is not None else box(0, 0, 12, 12),
                                       points, BASE, cfg)

    def test_two_distinct_blocks_one_top_per_component_from_cell_p90(self):
        first = block(2, 2, 5, 5)
        first[-1, 2] = 80.  # One high median cell must not become the raw maximum.
        second = block(12, 2, 5, 5)
        second[:15, 2] = 15.  # Connected internal tiers still produce ONE top.
        regions, diag = self.detect(np.r_[first, second])
        self.assertEqual(len(regions), 2)
        self.assertEqual(sorted(r['plane'][2] for r in regions), [12., 15.])
        self.assertEqual(diag['accepted_count'], 2)
        self.assertTrue(all(r['plane'][:2] == [0., 0.] for r in regions))
        self.assertEqual(shape(regions[0]['polygon']).intersection(shape(regions[1]['polygon'])).area, 0.)

    def test_isolated_raw_outlier_and_single_elevated_cell_are_rejected(self):
        normal = block(1, 1, 8, 8, BASE)
        stable_cell = np.repeat(normal[:1], 4, axis=0)
        raw_outlier = normal[:1].copy()
        raw_outlier[:, 2] = 100.
        regions, diag = self.detect(np.r_[normal, stable_cell, raw_outlier,
                                            block(20, 20, 1, 1, 50.)])
        self.assertEqual(regions, [])
        self.assertEqual(diag['high_cells'], 1)
        self.assertEqual(diag['rejected_count'], 1)
        self.assertIn('too_few_cells', diag['components'][0]['reasons'])

    def test_minimum_height_is_strict_not_inclusive(self):
        regions, diag = self.detect(block(1, 1, 4, 4, BASE + 2.))
        self.assertEqual(regions, [])
        self.assertEqual(diag['high_cells'], 0)
        regions, _ = self.detect(block(1, 1, 4, 4, BASE + 2.01))
        self.assertEqual(len(regions), 1)
        self.assertAlmostEqual(regions[0]['plane'][2], BASE + 2.01)

    def test_area_uses_occupied_cells_and_includes_exact_one_square_metre(self):
        regions, diag = self.detect(block(1, 1, 2, 4))  # Eight .35 m cells: .98 m2.
        self.assertEqual(regions, [])
        self.assertAlmostEqual(diag['components'][0]['observed_area_m2'], .98)
        self.assertIn('insufficient_observed_area', diag['components'][0]['reasons'])
        regions, diag = self.detect(block(0, 0, 3, 3), box(.025, .025, 1.025, 1.025))
        self.assertEqual(len(regions), 1)
        self.assertAlmostEqual(diag['observed_area_m2'], 1.)
        self.assertAlmostEqual(shape(regions[0]['polygon']).area, 1.)

    def test_long_straight_and_diagonal_pixel_lines_do_not_pass_width_filter(self):
        line = block(1, 1, 24, 1)
        stair = np.array([[(i + dx + .5) * CELL, (i + .5) * CELL, 12.]
                          for i in range(2, 22) for dx in (0, 1)])
        for points in (line, stair):
            with self.subTest(cells=len(points)):
                regions, diag = self.detect(points)
                self.assertEqual(regions, [])
                self.assertGreater(diag['components'][0]['observed_area_m2'], 1.)
                self.assertIn('too_narrow', diag['components'][0]['reasons'])

    def test_rotated_building_edge_clips_every_output_region(self):
        poly = rotate(box(1, 1, 5, 4), 28, origin='centroid')
        points = block(0, 0, 20, 20)
        regions, diag = self.detect(points, poly)
        self.assertEqual(len(regions), 1)
        output = shape(regions[0]['polygon'])
        self.assertTrue(output.is_valid)
        self.assertLess(output.difference(poly).area, 1e-10)
        self.assertLess(diag['inside_points'], len(points))
        self.assertLessEqual(diag['simplified_area_m2'], diag['observed_area_m2'] * 1.15 + 1e-10)
        self.assertLessEqual(diag['components'][0]['added_area_fraction'], .15 + 1e-10)

    def test_courtyard_and_nonfinite_or_outside_points_are_preserved_or_ignored(self):
        hole = box(1.4, 1.4, 4.2, 4.2)
        poly = Polygon(box(0, 0, 5.6, 5.6).exterior.coords, [hole.exterior.coords])
        points = np.r_[block(0, 0, 16, 16), [[np.nan, 1., 80.], [1., 1., np.inf],
                                                   [20., 20., 100.]]]
        regions, diag = self.detect(points, poly)
        self.assertEqual(len(regions), 1)
        output = shape(regions[0]['polygon'])
        self.assertTrue(output.is_valid)
        self.assertEqual(output.intersection(hole).area, 0.)
        self.assertEqual(len(output.interiors), 1)
        self.assertEqual(diag['finite_points'], len(points) - 2)
        self.assertLess(diag['inside_points'], diag['finite_points'])
        json.dumps({'regions': regions, 'diagnostics': diag}, allow_nan=False)

    def test_nonuniform_density_and_input_order_do_not_change_volume(self):
        points = block(2, 2, 5, 5)
        points[-5:, 2] = 14.
        repeat = np.arange(1, len(points) + 1)
        dense = np.repeat(points, repeat, axis=0)[::-1]
        regions, diag = self.detect(points)
        dense_regions, dense_diag = self.detect(dense)
        self.assertEqual(regions, dense_regions)
        self.assertEqual(diag['high_cells'], dense_diag['high_cells'])
        self.assertEqual(diag['observed_area_m2'], dense_diag['observed_area_m2'])
        self.assertGreater(dense_diag['components'][0]['source_points_in_cells'],
                           diag['components'][0]['source_points_in_cells'])

    def test_simplification_does_not_join_adjacent_towers_across_empty_gap(self):
        regions, diag = self.detect(np.r_[block(1, 1, 4, 4), block(6, 1, 4, 4)])
        self.assertEqual(len(regions), 2)
        a, b = [shape(r['polygon']) for r in regions]
        self.assertAlmostEqual(a.distance(b), CELL)
        self.assertEqual(a.intersection(b).area, 0.)
        self.assertEqual(diag['connected_components'], 2)

    def test_raster_corner_pinch_builds_watertight_simple_volume(self):
        # A translated 6x6 occupied-cell excerpt around a real failure: the
        # diagonal notch produced four vertical faces along a single edge when
        # a simplified outline was intersected back with the raster cells.
        indices = np.array([(x, y) for x in range(6) for y in range(6)
                            if (x, y) not in {(2, 3), (2, 4), (3, 2), (5, 5)}])
        points = np.c_[(indices + .5) * CELL, np.full(len(indices), 12.)]
        poly = box(-1, -1, 4, 4)
        regions, diag = self.detect(points, poly, {'regularize_footprints': False})
        self.assertEqual(len(regions), 1)
        raised = shape(regions[0]['polygon'])
        residual = poly.difference(raised)
        base_parts = [residual] if residual.geom_type == 'Polygon' else list(residual.geoms)
        mesh = build_mesh(poly, regions + [{'polygon': mapping(p), 'plane': [0, 0, BASE]}
                                          for p in base_parts])
        self.assertTrue(mesh['diagnostics']['valid'], mesh['diagnostics'])
        self.assertEqual(mesh['diagnostics']['nonmanifold_edge_count'], 0)
        self.assertLessEqual(diag['components'][0]['added_area_fraction'], .15)
        self.assertLess(diag['components'][0]['exterior_vertices'], 20)

    def test_regularized_rectangle_follows_building_walls_and_fills_small_raster_holes(self):
        poly = rotate(box(0, 0, 12, 10), 28, origin=(6, 5))
        feature = rotate(box(3, 3, 8, 6), 28, origin=(6, 5))
        points = block(-10, -10, 60, 60, BASE)
        supported = shapely.intersects_xy(feature, points[:, 0], points[:, 1])
        points[supported, 2] = 12.
        supported_indices = np.flatnonzero(supported)
        points[supported_indices[len(supported_indices) // 2], 2] = BASE
        regions, diag = self.detect(points, poly)
        self.assertEqual(len(regions), 1)
        component = next(c for c in diag['components'] if c['accepted'])
        self.assertEqual(component['simplification'], 'building_aligned_rectangle')
        self.assertEqual(component['exterior_vertices'], 4)
        self.assertEqual(component['interior_vertices'], 0)
        aligned = rotate(shape(regions[0]['polygon']), -28, origin=(6, 5))
        edges = np.diff(np.asarray(aligned.exterior.coords), axis=0)
        self.assertTrue(np.all(np.min(np.abs(edges), axis=1) < 1e-8))
        self.assertGreaterEqual(component['retained_observed_area_fraction'], .8)
        self.assertLessEqual(component['added_area_fraction'], .15)

    def test_l_shaped_support_gets_small_orthogonal_outline_not_inflated_rectangle(self):
        indices = np.array([(x, y) for x in range(8) for y in range(8) if x < 3 or y < 3])
        points = np.c_[(indices + .5) * CELL, np.full(len(indices), 12.)]
        regions, diag = self.detect(points)
        self.assertEqual(len(regions), 1)
        component = next(c for c in diag['components'] if c['accepted'])
        self.assertEqual(component['simplification'], 'building_aligned_orthogonal')
        self.assertLessEqual(component['exterior_vertices'], 8)
        self.assertLessEqual(component['added_area_fraction'], .15)
        self.assertGreaterEqual(component['retained_observed_area_fraction'], .8)
        self.assertLess(shape(regions[0]['polygon']).area, (8 * CELL) ** 2 * .8)

    def test_regularization_can_be_disabled_without_changing_measured_height(self):
        indices = np.array([(x, y) for x in range(6) for y in range(6) if (x, y) != (3, 3)])
        points = np.c_[(indices + .5) * CELL, np.full(len(indices), 12.)]
        regular, enabled = self.detect(points)
        old, disabled = self.detect(points, cfg={'regularize_footprints': False})
        self.assertEqual(regular[0]['plane'], old[0]['plane'])
        self.assertEqual(enabled['high_cells'], disabled['high_cells'])
        self.assertEqual(enabled['observed_area_m2'], disabled['observed_area_m2'])
        self.assertEqual(len(shape(regular[0]['polygon']).interiors), 0)
        self.assertEqual(len(shape(old[0]['polygon']).interiors), 1)
        self.assertNotIn('regularization_seconds', disabled['components'][0])


if __name__ == '__main__':
    unittest.main()
