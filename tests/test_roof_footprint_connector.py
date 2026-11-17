"""2D connector/width-junction regression tests; no cloud or roof fitting."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import shapely
from shapely.geometry import box,shape
from shapely.affinity import rotate,affine_transform
from roof_footprint_connector import detect_footprint_connector

class FootprintConnectorTests(unittest.TestCase):
    def verify_partition(self,poly,result,count):
        self.assertTrue(result['accepted'],result)
        parts=[shape(g) for g in result['candidates'][0]['footprints']]
        self.assertEqual(len(parts),count)
        self.assertTrue(all(p.is_valid for p in parts))
        self.assertLess(shapely.union_all(parts).symmetric_difference(poly).area,1e-6)
        for i,a in enumerate(parts):
            for b in parts[i+1:]:self.assertLess(a.intersection(b).area,1e-6)

    def connected_bodies(self):
        return shapely.union_all([box(0,0,18,16),box(18,6,36,10),box(36,0,54,16)])

    def test_two_large_bodies_and_narrow_passage_are_three_parts(self):
        poly=self.connected_bodies();self.verify_partition(poly,detect_footprint_connector(poly),3)

    def test_rotated_axes_do_not_change_partition(self):
        poly=rotate(self.connected_bodies(),31.7,origin=(0,0));r=detect_footprint_connector(poly)
        self.verify_partition(poly,r,3)
        self.assertAlmostEqual(r['candidates'][0]['metrics']['connector_width_m'],4.,places=6)

    def test_wider_main_body_and_narrow_l_are_two_parts(self):
        poly=shapely.union_all([box(0,0,20,16),box(20,0,26,40),box(20,34,42,40)])
        r=detect_footprint_connector(poly);self.verify_partition(poly,r,2)
        self.assertGreater(r['candidates'][0]['local_width_evidence'][0]['width_ratio'],2.)

    def test_equal_width_l_stays_whole(self):
        poly=box(0,0,32,8).union(box(0,0,8,32))
        self.assertFalse(detect_footprint_connector(poly)['accepted'])

    def test_equal_width_u_stays_whole(self):
        poly=shapely.union_all([box(0,0,40,8),box(0,0,8,32),box(32,0,40,32)])
        self.assertFalse(detect_footprint_connector(poly)['accepted'])

    def test_small_annex_does_not_make_an_independent_major_body(self):
        poly=box(0,0,20,16).union(box(20,5,26,9))
        self.assertFalse(detect_footprint_connector(poly)['accepted'])

    def test_insufficient_width_difference_stays_whole(self):
        poly=box(0,0,24,12).union(box(24,0,34,30))
        self.assertFalse(detect_footprint_connector(poly)['accepted'])

    def test_closed_courtyard_does_not_become_a_passage(self):
        poly=box(0,0,32,32).difference(box(8,8,24,24))
        self.assertFalse(detect_footprint_connector(poly)['accepted'])

    def test_disabled_module_does_not_need_geometry(self):
        self.assertEqual(detect_footprint_connector(None,{'enabled':False})['reason'],'disabled')

    def test_gently_oblique_bends_still_work(self):
        poly=affine_transform(self.connected_bodies(),[1,.1,0,1,0,0])
        self.verify_partition(poly,detect_footprint_connector(poly),3)

    def test_strongly_oblique_bends_are_not_forced_into_right_angle_rule(self):
        poly=affine_transform(self.connected_bodies(),[1,.8,0,1,0,0])
        self.assertFalse(detect_footprint_connector(poly)['accepted'])

    def test_width_ratio_is_configurable(self):
        self.assertFalse(detect_footprint_connector(self.connected_bodies(),{'min_width_ratio':10})['accepted'])

if __name__=='__main__':unittest.main()
