"""Synthetic truth tests for roof-v2; no visual/model-based judgements.

The point generator is independent of the fitting implementation. Accuracy is
measured on a separate, noise-free grid, never on the fitting points.
"""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
import sys
from pathlib import Path
import unittest
import math
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
import shapely
from shapely.geometry import Polygon,box,mapping
from shapely.affinity import rotate
from roof_v2 import infer_roof_v2,predict_regions,_lines

CONFIG=dict(cell_m=.7,max_cells=700,max_nfev=55)


def grid(poly, step=.7, offset=.37):
    a,b,c,d=poly.bounds
    x,y=np.meshgrid(np.arange(a+offset*step,c,step),np.arange(b+offset*step,d,step))
    xy=np.c_[x.ravel(),y.ravel()]
    return xy[shapely.contains_xy(poly,xy[:,0],xy[:,1])]


def cloud(poly, height, noise=.025, seed=713):
    xy=grid(poly)
    z=height(xy)+np.random.default_rng(seed).normal(0,noise,len(xy))
    return np.c_[xy,z]


def envelope(planes):
    p=np.asarray(planes,float)
    return lambda xy: np.min(np.c_[xy,np.ones(len(xy))]@p.T,axis=1)


class RoofInferenceTests(unittest.TestCase):
    def check_fit(self,poly,points,height,types,p90=.30,config=None):
        result=infer_roof_v2(poly,points,config={**CONFIG,**(config or {})})
        model=result['model']
        self.assertIn(model['type'],types,[(c['type'],c['score'],c['rejected']) for c in result['candidates']])
        self.assertTrue(model['mesh']['diagnostics']['valid'],model['mesh']['diagnostics'])
        self.assertEqual(model['mesh']['diagnostics']['open_edge_count'],0)
        self.assertAlmostEqual(model['mesh']['diagnostics']['coverage_fraction'],1,places=6)
        check_xy=grid(poly,step=.59,offset=.79)
        pred=predict_regions(model['regions'],check_xy)
        self.assertTrue(np.isfinite(pred).all())
        self.assertLess(np.quantile(np.abs(pred-height(check_xy)),.90),p90)
        return result

    def test_noisy_flat_ignores_sparse_chimneys(self):
        poly=box(0,0,18,14)
        h=lambda xy: np.full(len(xy),8.)
        points=cloud(poly,h,noise=.065)
        points[np.random.default_rng(19).choice(len(points),size=len(points)//25,replace=False),2]+=3.8
        r=self.check_fit(poly,points,h,{'flat'},p90=.12)
        self.assertFalse(r['diagnostics']['score_is_probability'])

    def test_rotated_asymmetric_gable(self):
        angle=math.radians(31.)
        s,c=math.sin(angle),math.cos(angle)
        poly=rotate(box(0,0,20,12),31.,origin=(0,0))
        h=envelope([[-.8*s,.8*c,7.],[.5*s,-.5*c,14.8]])
        r=self.check_fit(poly,cloud(poly,h),h,{'gabled'},p90=.22)
        self.assertGreater(len(r['model']['ridge_lines']),0)
        normals=np.asarray([p['plane'][:2] for p in r['model']['regions']])
        self.assertGreater(np.ptp(np.linalg.norm(normals,axis=1)),.15)

    def test_broad_shallow_side_remains_real_pitched_roof(self):
        # A 9-percent slope over thirty metres rises 2.7 m and is not flat.
        poly=box(0,0,24,44)
        h=envelope([[0,.09,8],[0,-.3,19.7]])
        r=self.check_fit(poly,cloud(poly,h),h,{'gabled','compound'},p90=.30)
        self.assertGreater(r['model']['height_range_m'][1]-r['model']['height_range_m'][0],3.)

    def test_shed(self):
        poly=box(0,0,16,12)
        h=lambda xy: 7.+.3*xy[:,0]+.12*xy[:,1]
        self.check_fit(poly,cloud(poly,h),h,{'skillion'},p90=.12)

    def test_hipped(self):
        poly=box(0,0,24,14)
        h=envelope([[0,.6,8],[0,-.6,16.4],[.7,0,8],[-.7,0,24.8]])
        self.check_fit(poly,cloud(poly,h),h,{'hipped'},p90=.22)

    def test_pyramidal(self):
        poly=box(0,0,16,16)
        h=envelope([[.6,0,8],[-.6,0,17.6],[0,.6,8],[0,-.6,17.6]])
        self.check_fit(poly,cloud(poly,h),h,{'pyramidal'},p90=.22)

    def test_distinct_flat_levels_are_not_sloping_bridge(self):
        poly=box(0,0,24,16)
        h=lambda xy: np.where(xy[:,0]<11,8.,13.)
        r=self.check_fit(poly,cloud(poly,h),h,{'flat_levels'},p90=.16)
        for region in r['model']['regions']:
            self.assertLess(np.linalg.norm(region['plane'][:2]),1e-10)
        self.assertIn('part_boundaries_need_review',r['diagnostics']['flags'])

    def test_courtyard_is_never_filled(self):
        poly=Polygon([(0,0),(20,0),(20,18),(0,18)],
                     [[(6,6),(14,6),(14,12),(6,12)]])
        h=lambda xy: np.full(len(xy),9.)
        r=self.check_fit(poly,cloud(poly,h),h,{'flat'},p90=.12)
        v=np.asarray(r['model']['mesh']['vertices'])
        for face in r['model']['mesh']['roof_faces']:
            self.assertLess(Polygon(v[face,:2]).difference(poly).area,1e-7)

    def test_l_footprint_uses_two_simple_roofs(self):
        poly=Polygon([(0,0),(24,0),(24,8),(8,8),(8,24),(0,24)])
        def h(xy):
            return 8.+.8*np.where(xy[:,1]<8,np.minimum(xy[:,1],8-xy[:,1]),
                                 np.minimum(xy[:,0],8-xy[:,0]))
        r=self.check_fit(poly,cloud(poly,h),h,{'compound'},p90=.28)
        self.assertEqual(r['model']['mesh']['diagnostics']['missing_area_m2'],0.)

    def test_rectangle_can_contain_two_different_roof_masses(self):
        poly=box(0,0,24,12)
        def h(xy):
            rise=np.minimum(xy[:,1],12-xy[:,1])
            return np.where(xy[:,0]<12,7.+.6*rise,12.+.4*rise)
        self.check_fit(poly,cloud(poly,h),h,{'compound'},p90=.30)

    def test_sparse_fallback_is_explicit(self):
        poly=box(0,0,12,9)
        h=lambda xy: np.full(len(xy),7.)
        r=self.check_fit(poly,cloud(poly,h)[:9],h,{'flat'},p90=.12)
        self.assertIn('insufficient_data',r['diagnostics']['flags'])
        self.assertIn('fallback_geometry_not_roof_classification',r['diagnostics']['flags'])
        self.assertIsNone(r['diagnostics']['selection_score'])

    def test_empty_cloud_uses_configured_height(self):
        poly=box(0,0,12,9)
        h=lambda xy: np.full(len(xy),6.5)
        r=self.check_fit(poly,np.empty((0,3)),h,{'flat'},p90=.01,config={'fallback_height':6.5})
        self.assertEqual(r['diagnostics']['usable_points'],0)

    def test_valley_is_not_exported_as_ridge(self):
        poly=box(0,0,10,10)
        def lines(planes):
            model={'regions':[{'polygon':mapping(part),'plane':plane}
                              for part,plane in zip([box(0,0,10,5),box(0,5,10,10)],planes)]}
            return _lines(model,poly)[0]
        self.assertEqual(len(lines([[0,.6,5],[0,-.6,11]])),1)
        self.assertEqual(lines([[0,-.6,11],[0,.6,5]]),[])

    def test_many_points_in_one_cell_are_still_sparse_evidence(self):
        poly=box(0,0,18,14)
        points=np.tile([1.1,1.1,8.],(400,1))
        r=infer_roof_v2(poly,points,config=CONFIG)
        self.assertIn('insufficient_data',r['diagnostics']['flags'])
        self.assertIn('fallback_geometry_not_roof_classification',r['diagnostics']['flags'])
        self.assertIsNone(r['diagnostics']['selection_score'])

    def test_point_order_is_deterministic(self):
        poly=box(0,0,16,10)
        h=envelope([[0,.6,7],[0,-.6,13]])
        points=cloud(poly,h)
        a=infer_roof_v2(poly,points,config=CONFIG)
        b=infer_roof_v2(poly,points[np.random.default_rng(9).permutation(len(points))],config=CONFIG)
        self.assertEqual(a['model'],b['model'])
        self.assertEqual(a['diagnostics']['flags'],b['diagnostics']['flags'])
        self.assertAlmostEqual(a['diagnostics']['selection_score'],b['diagnostics']['selection_score'],places=12)


if __name__=='__main__':
    unittest.main()
