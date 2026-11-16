"""Geometric invariants for the independent roof-v2 mesher."""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[name]='1'
import sys
from pathlib import Path
import unittest
import math
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from shapely.geometry import Polygon,box,mapping
from shapely.affinity import rotate
from shapely import set_precision
from roof_v2_geometry import build_mesh,plane_regions,normalize_regions


def region(poly,plane):
    return {'polygon':mapping(poly),'plane':plane}


class RoofGeometryTests(unittest.TestCase):
    def check(self,poly,regions,volume):
        mesh=build_mesh(poly,regions)
        d=mesh['diagnostics']
        self.assertTrue(d['valid'],d)
        self.assertTrue(np.isfinite(mesh['vertices']).all())
        self.assertEqual(d['open_edge_count'],0)
        self.assertEqual(d['nonmanifold_edge_count'],0)
        self.assertEqual(d['inconsistent_orientation_edge_count'],0)
        self.assertAlmostEqual(d['coverage_fraction'],1,places=7)
        self.assertAlmostEqual(d['projected_roof_triangle_area_m2'],poly.area,places=5)
        self.assertAlmostEqual(d['signed_volume_m3'],volume,places=4)
        # Every projected roof triangle belongs to the real footprint, not its
        # convex hull. This catches filling courtyards and concave notches.
        v=np.asarray(mesh['vertices'])
        for face in mesh['roof_faces']:
            tri=Polygon(v[face,:2])
            self.assertLess(tri.difference(poly).area,1e-7)
        return mesh

    def test_gable_has_correct_gable_walls_and_volume(self):
        p=box(0,0,10,8)
        m=self.check(p,plane_regions(p,[[0,1,6],[0,-1,14]]),640)
        self.assertAlmostEqual(max(v[2] for v in m['vertices']),10)
        self.assertEqual(len(plane_regions(p,[[0,1,6],[0,-1,14]])),2)

    def test_rotated_gable_preserves_shared_ridge_edges(self):
        for degrees in (13.7,23.17,47.3,86.9,126.4,179.13):
            with self.subTest(degrees=degrees):
                p=set_precision(rotate(box(0,0,10,8),degrees,origin=(0,0)),1e-7)
                angle=math.radians(degrees)
                s,c=math.sin(angle),math.cos(angle)
                self.check(p,plane_regions(p,[[-s,c,6],[s,-c,14]]),640)

    def test_pyramid_four_planes_share_single_apex(self):
        p=box(0,0,10,10)
        m=self.check(p,plane_regions(p,[[1,0,10],[-1,0,20],[0,1,10],[0,-1,20]]),1000+500/3)
        self.assertEqual(sum(abs(v[2]-15)<1e-6 for v in m['vertices']),1)

    def test_adjacent_grid_vertices_at_plane_junction_are_welded(self):
        # Real fitted-plane coefficients caused 12 open edges separated by only
        # 0.1 micrometres at a four-plane apex and a footprint boundary.
        p=Polygon([[5.48698782781139,2.408805741928518],
                   [6.152372156386264,4.787164671113715],[-2.306911495164968,8.088773000286892],
                   [-3.43583681283053,4.4830197636038065],[-6.315349509823136,-4.787313972599804],
                   [2.593287950847298,-7.937154196202755]])
        planes=[[-.25974110842090237,-.02000733665393656,9.691447818541802],
                [.38265807578359035,.029475384131893368,12.62317222356985],
                [-.011270139855149304,.14631225878128568,11.099888593372327],
                [.04712755749059363,-.6118237640274878,9.94408789788851]]
        m=build_mesh(p,plane_regions(p,planes));d=m['diagnostics']
        self.assertTrue(d['valid'],d)
        self.assertEqual(d['open_edge_count'],0)
        self.assertGreater(d['numerical_vertex_weld_count'],0)
        self.assertLess(abs(d['projected_roof_triangle_area_m2']-p.area),1e-5)
        self.assertLess(d['vertex_xy_weld_tolerance_m'],1e-6)

    def test_asymmetric_gable_has_offset_ridge_and_unequal_eaves(self):
        p=box(0,0,10,8)
        m=self.check(p,plane_regions(p,[[0,2,5],[0,-1,14]]),665)
        peak=[v for v in m['vertices'] if abs(v[2]-11)<1e-6]
        self.assertEqual(len(peak),2)
        self.assertTrue(all(abs(v[1]-3)<1e-6 for v in peak))

    def test_concave_footprint(self):
        p=Polygon([(0,0),(10,0),(10,4),(4,4),(4,10),(0,10)])
        self.check(p,[region(p,[0,0,10])],640)

    def test_courtyard_has_inner_vertical_walls(self):
        p=Polygon([(0,0),(10,0),(10,10),(0,10)],
                  [[(3,3),(7,3),(7,7),(3,7)]])
        self.check(p,[region(p,[0,0,10])],840)
        # A two-plane roof must preserve the same courtyard.
        m=build_mesh(p,plane_regions(p,[[0,1,5],[0,-1,15]]))
        self.assertTrue(m['diagnostics']['valid'],m['diagnostics'])
        self.assertAlmostEqual(m['diagnostics']['projected_roof_triangle_area_m2'],84)

    def test_two_flat_levels_are_closed_by_step_wall(self):
        p=box(0,0,10,10)
        m=self.check(p,[region(box(0,0,5,10),[0,0,10]),
                        region(box(5,0,10,10),[0,0,7])],850)
        self.assertEqual(m['diagnostics']['height_step_edge_count'],1)

    def test_three_levels_at_t_junction_split_vertical_edges(self):
        p=box(0,0,10,10)
        self.check(p,[region(box(0,0,5,10),[0,0,10]),
                      region(box(5,0,10,5),[0,0,8]),
                      region(box(5,5,10,10),[0,0,6])],850)

    def test_step_planes_cross_along_shared_edge(self):
        p=box(0,0,10,10)
        m=self.check(p,[region(box(0,0,5,10),[0,1,5]),
                        region(box(5,0,10,10),[0,-1,15])],1000)
        self.assertEqual(m['diagnostics']['height_step_edge_count'],2)

    def test_coincident_planes_do_not_duplicate_roof(self):
        p=box(0,0,10,10)
        r=plane_regions(p,[[0,0,7],[0,0,7],[0,0,9]])
        self.assertEqual(len(r),1)
        self.check(p,r,700)
        self.check(p,plane_regions(p,[[0,0,7],[0,0,9]],'max'),900)

    def test_overlap_missing_and_outside_are_rejected(self):
        p=box(0,0,10,10)
        with self.assertRaisesRegex(ValueError,'overlap'):
            build_mesh(p,[region(p,[0,0,8]),region(box(2,2,3,3),[0,0,10])])
        with self.assertRaisesRegex(ValueError,'cover'):
            build_mesh(p,[region(box(0,0,8,10),[0,0,8])])
        with self.assertRaisesRegex(ValueError,'outside'):
            build_mesh(p,[region(box(0,0,11,10),[0,0,8])])

    def test_roof_below_base_and_nonfinite_plane_rejected(self):
        p=box(0,0,10,10)
        with self.assertRaisesRegex(ValueError,'base'):
            build_mesh(p,[region(p,[0,0,-1])])
        with self.assertRaisesRegex(ValueError,'finite'):
            build_mesh(p,[region(p,[math.nan,0,8])])


if __name__=='__main__':
    unittest.main()
