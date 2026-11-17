import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
import shapely
from shapely.geometry import box,Polygon
from shapely.affinity import rotate
from roof_footprint_support import refine_footprint


def samples(poly,z,classification):
    a,b,c,d=poly.bounds
    xy=np.array([(x,y) for x in np.arange(a+.125,c,.25) for y in np.arange(b+.125,d,.25)])
    xy=xy[shapely.contains_xy(poly,xy[:,0],xy[:,1])]
    return np.c_[xy,np.full(len(xy),z)],np.full(len(xy),classification,dtype=np.uint8)


def cloud(*parts):
    return np.concatenate([p[0] for p in parts]),np.concatenate([p[1] for p in parts])


class FootprintSupportTests(unittest.TestCase):
    def test_ground_supported_annex_is_removed_by_original_wall_line(self):
        main=box(0,0,20,15);annex=box(20,5,24,10);poly=main.union(annex)
        xyz,cls=cloud(samples(main,10,6),samples(annex,0,2))
        out,meta=refine_footprint(poly,xyz,cls)
        self.assertLess(out.symmetric_difference(main).area,1e-7)
        self.assertEqual(meta['accepted_removals'],1)
        self.assertTrue(out.is_valid)

    def test_missing_points_without_ground_do_not_remove_annex(self):
        main=box(0,0,20,15);poly=main.union(box(20,5,24,10))
        out,meta=refine_footprint(poly,*samples(main,10,6))
        self.assertFalse(meta['changed']);self.assertTrue(out.equals(poly))

    def test_measured_roof_prevents_annex_removal(self):
        poly=box(0,0,20,15).union(box(20,5,24,10))
        out,meta=refine_footprint(poly,*samples(poly,10,6))
        self.assertFalse(meta['changed']);self.assertTrue(out.equals(poly))

    def test_continuous_roof_fills_small_notch_but_not_hole(self):
        whole=box(0,0,20,20);notch=box(0,7,4,12);hole=box(10,8,14,12)
        poly=whole.difference(notch).difference(hole)
        out,meta=refine_footprint(poly,*samples(whole,10,6))
        self.assertTrue(out.equals(whole.difference(hole)))
        self.assertEqual(meta['accepted_fills'],1);self.assertEqual(len(out.interiors),1)

    def test_high_neighbor_does_not_fill_notch(self):
        whole=box(0,0,20,20);notch=box(0,7,4,12);poly=whole.difference(notch)
        xyz,cls=cloud(samples(poly,10,6),samples(notch,18,6))
        out,meta=refine_footprint(poly,xyz,cls)
        self.assertFalse(meta['changed']);self.assertTrue(out.equals(poly))

    def test_large_courtyard_is_preserved(self):
        poly=box(0,0,30,30).difference(box(6,6,24,31))
        out,meta=refine_footprint(poly,*samples(box(0,0,30,30),10,6))
        self.assertFalse(meta['changed']);self.assertTrue(out.equals(poly))

    def test_rotation_and_second_pass_preserve_decision(self):
        main=box(0,0,20,15);annex=box(20,5,24,10);poly=main.union(annex)
        xyz,cls=cloud(samples(main,10,6),samples(annex,0,2))
        angle=np.deg2rad(27.);rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        xyz[:,:2]=xyz[:,:2]@rotation.T
        rotated=rotate(poly,27.,origin=(0,0));expected=rotate(main,27.,origin=(0,0))
        out,meta=refine_footprint(rotated,xyz,cls)
        self.assertLess(out.symmetric_difference(expected).area,1e-7)
        second,meta2=refine_footprint(out,xyz,cls)
        self.assertFalse(meta2['changed']);self.assertTrue(second.equals(out))

    def test_invalid_settings_fail_before_geometry_changes(self):
        poly=box(0,0,10,10);xyz,cls=samples(poly,10,6)
        for patch in ({'cell_m':0},{'fill_notches':1},{'unexpected':True},{'max_notch_chain_edges':2}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                refine_footprint(poly,xyz,cls,patch)

    def test_module_switches_preserve_the_input(self):
        main=box(0,0,20,15);annex=box(20,5,24,10);poly=main.union(annex)
        xyz,cls=cloud(samples(main,10,6),samples(annex,0,2))
        out,meta=refine_footprint(poly,xyz,cls,{'remove_unsupported':False,'fill_notches':False})
        self.assertFalse(meta['changed']);self.assertTrue(out.equals(poly))


if __name__=='__main__':unittest.main()
