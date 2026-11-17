import unittest
import math
from shapely.geometry import Polygon,box
from shapely.affinity import rotate
from roof_virtual_outline import propose_virtual_outlines

class VirtualOutlineTests(unittest.TestCase):
    def check_bounds(self,poly,items):
        self.assertLessEqual(len(items),3)
        self.assertTrue(items[0]['polygon'].equals(poly))
        for item in items:
            ref=item['polygon']
            self.assertTrue(ref.is_valid)
            self.assertLess(poly.difference(ref).area,1e-7)
            self.assertLessEqual(ref.boundary.hausdorff_distance(poly.boundary),2.+1e-7)
            self.assertLessEqual((ref.area-poly.area)/poly.area,.12+1e-7)
    def test_near_collinear_facade_becomes_full_edge(self):
        poly=Polygon([(0,0),(15,0),(15.02,4),(15,8),(15,12),(0,12)])
        items=propose_virtual_outlines(poly);self.check_bounds(poly,items)
        self.assertLess(min(i['metadata']['reference_edges'] for i in items),6)
        self.assertTrue(any(i['metadata']['operations'] for i in items))
    def test_shallow_notch_can_be_filled_without_replacing_real_outline(self):
        poly=box(0,0,20,12).difference(box(8,-1,12,1))
        items=propose_virtual_outlines(poly);self.check_bounds(poly,items)
        self.assertLess(min(i['metadata']['reference_edges'] for i in items),len(poly.exterior.coords)-1)
        self.assertEqual(round(poly.area),236)
    def test_major_u_return_and_holes_are_preserved(self):
        poly=box(0,0,20,20).difference(box(6,6,14,21))
        items=propose_virtual_outlines(poly);self.check_bounds(poly,items)
        for i in items:self.assertFalse(i['polygon'].covers(box(7,10,13,19)))
        holed=box(0,0,20,20).difference(box(7,7,13,13))
        for i in propose_virtual_outlines(holed):
            self.assertEqual(len(i['polygon'].interiors),1)
            self.assertTrue(Polygon(i['polygon'].interiors[0]).equals(box(7,7,13,13)))
    def test_rotated_geometry_has_same_complexity_and_added_area(self):
        poly=box(0,0,20,12).difference(box(8,-1,12,1))
        a=propose_virtual_outlines(poly)[-1];b=propose_virtual_outlines(rotate(poly,23,origin=(0,0)))[-1]
        self.assertEqual(a['metadata']['reference_edges'],b['metadata']['reference_edges'])
        self.assertAlmostEqual(a['metadata']['added_area_m2'],b['metadata']['added_area_m2'],places=5)
    def test_short_convex_bevel_extends_adjacent_long_walls(self):
        poly=Polygon([(0,0),(12,0),(12,8),(11,9),(0,9)])
        items=propose_virtual_outlines(poly);self.check_bounds(poly,items)
        small=next(i for i in items if i['metadata']['label']=='small_steps')
        self.assertTrue(small['polygon'].equals(box(0,0,12,9)))
        bevels=[o for o in small['metadata']['operations'] if o.get('operation')=='short_convex_bevel']
        self.assertEqual(len(bevels),1)
        self.assertAlmostEqual(small['metadata']['added_area_m2'],.5)
        self.assertEqual(len(poly.exterior.coords)-1,5)
    def test_bevel_switch_and_area_budget_protect_original(self):
        poly=Polygon([(0,0),(12,0),(12,8),(11,9),(0,9)])
        for settings in ({'remove_short_bevels':False},{'max_added_area_fraction':.001}):
            items=propose_virtual_outlines(poly,settings)
            self.assertTrue(all(i['polygon'].equals(poly) for i in items))
    def test_concave_diagonal_and_large_chamfer_are_not_bevel_candidates(self):
        concave=Polygon([(0,0),(20,0),(20,12),(12,12),(12,6),(11,5),(0,5)])
        large=Polygon([(0,0),(20,0),(20,7),(15,12),(0,12)])
        for poly in (concave,large):
            items=propose_virtual_outlines(poly);self.check_bounds(poly,items)
            self.assertFalse(any(o.get('operation')=='short_convex_bevel' for i in items for o in i['metadata']['operations']))
    def test_bevel_replacement_is_rotation_invariant_and_preserves_hole(self):
        poly=Polygon([(0,0),(12,0),(12,8),(11,9),(0,9)],holes=[[(3,3),(6,3),(6,6),(3,6)]])
        a=propose_virtual_outlines(poly)[-1]
        rotated=rotate(poly,37,origin=(0,0));b=propose_virtual_outlines(rotated)[-1]
        self.assertEqual(a['metadata']['reference_edges'],b['metadata']['reference_edges'])
        self.assertAlmostEqual(a['metadata']['added_area_m2'],b['metadata']['added_area_m2'],places=5)
        self.assertTrue(Polygon(a['polygon'].interiors[0]).equals(Polygon(poly.interiors[0])))
        self.assertTrue(Polygon(b['polygon'].interiors[0]).equals(Polygon(rotated.interiors[0])))
if __name__=='__main__':unittest.main()
