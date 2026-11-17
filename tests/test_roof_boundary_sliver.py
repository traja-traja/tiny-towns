"""Grid-roundoff gaps must not extrapolate a roof plane into a tall facade fin."""
import unittest
import numpy as np
from shapely.geometry import Polygon, box, mapping
from roof_v2_geometry import build_mesh, XY_GRID


class BoundarySliverTests(unittest.TestCase):
    def test_empty_boundary_sliver_spanning_ridge_does_not_create_fin(self):
        footprint = box(0,0,10,10)
        regions = [
            {'polygon':mapping(Polygon([(0,0),(5,XY_GRID),(5,10),(0,10)])),
             'plane':[1,0,5]},
            {'polygon':mapping(Polygon([(5,XY_GRID),(10,0),(10,10),(5,10)])),
             'plane':[-1,0,15]}]
        mesh = build_mesh(footprint,regions)
        diagnostics = mesh['diagnostics']
        self.assertTrue(diagnostics['valid'])
        self.assertEqual(diagnostics['partition_cell_count'],2)
        self.assertEqual(diagnostics['height_step_edge_count'],0)
        self.assertEqual(diagnostics['numerical_boundary_gap_cells'],1)
        self.assertLess(diagnostics['numerical_boundary_gap_area_m2'],1e-6)
        self.assertLessEqual(max(v[2] for v in mesh['vertices']),10+1e-6)
        self.assertAlmostEqual(diagnostics['projected_roof_triangle_area_m2'],100,places=5)

    def test_real_roof_step_is_kept(self):
        footprint = box(0,0,10,10)
        regions = [{'polygon':mapping(box(0,0,5,10)),'plane':[0,0,5]},
                   {'polygon':mapping(box(5,0,10,10)),'plane':[0,0,8]}]
        mesh = build_mesh(footprint,regions)
        self.assertTrue(mesh['diagnostics']['valid'])
        self.assertEqual(mesh['diagnostics']['height_step_edge_count'],1)
        self.assertEqual(mesh['diagnostics']['numerical_boundary_gap_cells'],0)
        self.assertEqual(max(v[2] for v in mesh['vertices']),8)

    def test_architectural_missing_strip_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'do not cover'):
            build_mesh(box(0,0,10,10),[
                {'polygon':mapping(box(0,.01,10,10)),'plane':[0,0,5]}])

    def test_interior_numerical_gap_is_not_treated_as_boundary_roundoff(self):
        footprint = box(0,0,20,10)
        regions = [{'polygon':mapping(box(0,0,5,10)),'plane':[0,0,5]},
                   {'polygon':mapping(box(5+XY_GRID,0,20,10)),'plane':[0,0,8]}]
        mesh = build_mesh(footprint,regions)
        self.assertEqual(mesh['diagnostics']['numerical_boundary_gap_cells'],0)
        self.assertGreater(mesh['diagnostics']['numerical_partition_repair_cells'],0)
        self.assertGreater(mesh['diagnostics']['height_step_edge_count'],0)


if __name__=='__main__':
    unittest.main()
