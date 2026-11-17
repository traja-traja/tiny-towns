"""Preserve supported courtyard branches while allowing ordinary simplification."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from shapely.geometry import box, Polygon
from roof_config import resolve_config
from roof_eave_planes import _near_candidates, _visible_mesh_ridges
from roof_v2_geometry import plane_regions, build_mesh


class TopologySelectionTests(unittest.TestCase):
    def test_courtyard_network_not_erased_for_fewer_planes(self):
        poly = Polygon(box(0,0,30,20).exterior.coords, [box(10,6,18,14).exterior.coords])
        options = [{'kind':'u_shaped','score':.75}, {'kind':'u_shaped','score':.80},
                   {'kind':'parallel_gables','score':.83}, {'kind':'ring','score':.77}]
        near, protected = _near_candidates(options, poly, resolve_config()['scoring'])
        self.assertTrue(protected)
        self.assertEqual([p['kind'] for p in near], ['u_shaped','u_shaped','ring'])

    def test_ordinary_footprint_keeps_existing_tolerance(self):
        options = [{'kind':'u_shaped','score':.75}, {'kind':'parallel_gables','score':.83}]
        near, protected = _near_candidates(options, box(0,0,30,20), resolve_config()['scoring'])
        self.assertFalse(protected)
        self.assertEqual(len(near),2)

    def test_tiny_opening_does_not_force_courtyard_network(self):
        poly = Polygon(box(0,0,30,20).exterior.coords, [box(10,6,11,7).exterior.coords])
        options = [{'kind':'u_shaped','score':.75}, {'kind':'parallel_gables','score':.83}]
        near, protected = _near_candidates(options, poly, resolve_config()['scoring'])
        self.assertFalse(protected)
        self.assertEqual(len(near),2)

    def test_mesh_crest_survives_triangulation_and_welding(self):
        poly = box(0,0,20,10)
        mesh = build_mesh(poly, plane_regions(poly, [[0,1,10],[0,-1,20]]))
        ridges = _visible_mesh_ridges(mesh)
        self.assertEqual(len(ridges),1)
        self.assertAlmostEqual(sum(abs(b[0]-a[0]) for a,b in zip(ridges[0],ridges[0][1:])),20.)
        self.assertTrue(all(abs(p[1]-5.)<1e-6 and abs(p[2]-15.)<1e-6 for p in ridges[0]))

    def test_valley_and_flat_seams_are_not_ridges(self):
        poly = box(0,0,20,10)
        valley = build_mesh(poly, plane_regions(poly, [[0,-1,20],[0,1,10]], mode='max'))
        flat = build_mesh(poly, plane_regions(poly, [[0,0,10]]))
        self.assertEqual(_visible_mesh_ridges(valley),[])
        self.assertEqual(_visible_mesh_ridges(flat),[])


if __name__ == '__main__':
    unittest.main()
