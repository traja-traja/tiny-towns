"""Independent regression checks for section/height-based body splitting."""
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'.work/roof-skeleton-test/vendor')]
import numpy as np
from shapely.geometry import box, LineString, Polygon
from roof_volume_candidates import DEFAULTS, boundary_step, _partition, run_variants


def cloud(fn,length=24,width=12):
    x,y=np.meshgrid(np.arange(.15,length,.3),np.arange(.15,width,.3))
    return np.c_[x.ravel(),y.ravel(),fn(x,y).ravel()]


class RoofVolumeTests(unittest.TestCase):
    def setUp(self):
        self.poly=box(0,0,24,12)
        self.line=LineString([(12,-5),(12,17)])
        self.cfg=DEFAULTS.copy()

    def test_continuous_inclined_plane_is_not_step(self):
        points=cloud(lambda x,y:6+.25*x+.15*y)
        evidence=boundary_step(self.poly,points,self.line,self.cfg)
        self.assertFalse(evidence['accepted'])
        self.assertAlmostEqual(evidence['height_step_m'],0,delta=.01)

    def test_continuous_gable_is_not_step(self):
        points=cloud(lambda x,y:5+.7*(6-abs(y-6)))
        for line in (self.line,LineString([(-5,6),(29,6)]),LineString([(0,2),(24,10)])):
            evidence=boundary_step(self.poly,points,line,self.cfg)
            self.assertFalse(evidence['accepted'])

    def test_real_step_above_threshold_passes(self):
        points=cloud(lambda x,y:5+.2*y+(x>12)*1.4)
        evidence=boundary_step(self.poly,points,self.line,self.cfg)
        self.assertTrue(evidence['accepted'])
        self.assertAlmostEqual(abs(evidence['height_step_m']),1.4,delta=.03)
        self.assertGreaterEqual(evidence['support_fraction'],.6)

    def test_subthreshold_step_fails(self):
        points=cloud(lambda x,y:5+.2*y+(x>12)*.9)
        self.assertFalse(boundary_step(self.poly,points,self.line,self.cfg)['accepted'])

    def test_local_chimney_does_not_split(self):
        points=cloud(lambda x,y:np.full_like(x,6.))
        chimney=(points[:,0]>12)&(points[:,0]<13.8)&(points[:,1]>4)&(points[:,1]<6)
        points[chimney,2]+=5
        self.assertFalse(boundary_step(self.poly,points,self.line,self.cfg)['accepted'])

    def test_profile_cut_yields_two_covering_bodies(self):
        points=cloud(lambda x,y:6.+(x>12)*3.)
        profiles=[{'longitudinal_changes':[{'cut_line_xy':list(self.line.coords)}]}]
        parts,accepted,_=_partition(self.poly,points,profiles,self.cfg)
        self.assertEqual(len(parts),2)
        self.assertEqual(len(accepted),1)
        self.assertAlmostEqual(sum(p.area for p in parts),self.poly.area)
        self.assertAlmostEqual(parts[0].intersection(parts[1]).area,0.)

    def test_footprint_cut_splits_lower_appendage(self):
        poly=Polygon([(0,0),(16,0),(16,3),(24,3),(24,9),(16,9),(16,12),(0,12)])
        points=cloud(lambda x,y:np.where(x<16,9.,5.))
        import shapely
        points=points[shapely.intersects_xy(poly,points[:,0],points[:,1])]
        parts,accepted,_=_partition(poly,points,[],self.cfg)
        self.assertEqual(len(parts),2)
        self.assertTrue(accepted)
        self.assertAlmostEqual(sum(p.area for p in parts),poly.area)

    def test_end_to_end_step_stays_explicit_and_mesh_valid(self):
        points=cloud(lambda x,y:6.+(x>12)*3.)
        result=run_variants(self.poly,points)
        self.assertFalse(result['errors'],result['errors'])
        self.assertTrue(result['decision']['split_proposed'])
        self.assertTrue(result['decision']['split_accepted'])
        self.assertEqual(result['decision']['selected_variant'],'split_volumes')
        self.assertEqual(result['decision']['selected_volume_count'],2)
        self.assertTrue(result['variants']['split_volumes']['model']['mesh']['diagnostics']['valid'])
        json.dumps(result,allow_nan=False)

    def test_scan_finds_step_without_section_or_footprint_cut(self):
        points=cloud(lambda x,y:6.+(x>12)*3.)
        parts,accepted,_=_partition(self.poly,points,[],{**self.cfg,'scan_cuts':True,'station_spacing_m':1.})
        self.assertEqual(len(parts),2)
        self.assertTrue(accepted)
        self.assertEqual(accepted[0]['source'],'sparse_profile_scan')

    def test_square_courtyard_stays_open_in_skeleton_mesh(self):
        import shapely
        from shapely.geometry import shape
        courtyard=box(8,8,16,16)
        poly=box(0,0,24,24).difference(courtyard)
        # Independently defined offset distances of a square ring roof.
        points=cloud(lambda x,y:6.+.6*np.minimum.reduce([
            x,y,24-x,24-y,np.maximum.reduce([8-x,x-16,8-y,y-16])]),width=24)
        result=run_variants(poly,points)
        self.assertFalse(result['errors'],result['errors'])
        self.assertFalse(result['decision']['split_accepted'])
        for key in ('skeleton_shared','skeleton_sections'):
            model=result['variants'][key]['model']
            footprint=shapely.union_all([shape(r['polygon']) for r in model['regions']])
            self.assertLess(footprint.symmetric_difference(poly).area,1e-6)
            self.assertLess(footprint.intersection(courtyard).area,1e-6)
            self.assertTrue(model['mesh']['diagnostics']['valid'])
            self.assertAlmostEqual(model['mesh']['diagnostics']['projected_roof_triangle_area_m2'],poly.area,places=5)


if __name__=='__main__':unittest.main()
