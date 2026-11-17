"""Oblique connected wings: measured axes, horizontal eaves and evidence gates."""
import copy
import math
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

import numpy as np
import shapely
from shapely.geometry import Polygon,shape
from roof_config import resolve_config
from roof_connected_wings import (DEFAULTS,_walls,_box,_wing_planes,
    _supported_subset,connected_wing_proposals)
from roof_v2 import predict_regions
from roof_v2_geometry import build_mesh


def wing(origin,angle,length=32.,width=8.):
    theta=math.radians(angle)
    u=np.array([math.cos(theta),math.sin(theta)])
    v=np.array([-u[1],u[0]])
    origin=np.asarray(origin,float)
    lo=float(origin@u);bottom=float(origin@v-width/2)
    polygon=_box(u,v,lo,lo+length,bottom,bottom+width)
    return {'u':u,'v':v,'lo':lo,'hi':lo+length,'bottom':bottom,'top':bottom+width,
        'width':width,'length':length,'polygon':polygon,'inside':polygon,
        'physical_ends':[True,True],'area':polygon.area,'source_span_m':[lo,lo+length]}


def scene(wings,observed=None):
    poly=shapely.union_all([w['polygon'] for w in wings])
    observed=wings if observed is None else observed
    observed_poly=shapely.union_all([w['polygon'] for w in observed])
    x0,y0,x1,y1=observed_poly.bounds
    x,y=np.meshgrid(np.arange(x0+.23,x1,.7),np.arange(y0+.23,y1,.7))
    xy=np.c_[x.ravel(),y.ravel()]
    xy=xy[shapely.intersects_xy(observed_poly,xy[:,0],xy[:,1])]
    A=np.c_[xy,np.ones(len(xy))]
    heights=10+.7*np.maximum(0,np.max([np.min(A@_wing_planes(w,(True,True)).T,axis=1) for w in observed],axis=0))
    return poly,np.c_[xy,heights]


def config(**overrides):
    result=resolve_config();result['connected_wings']={**DEFAULTS,**overrides}
    return result


class ObliqueWingTests(unittest.TestCase):
    def best_valid(self,poly,points,cfg):
        proposals=connected_wing_proposals(poly,points,cfg)
        self.assertTrue(proposals)
        for proposal in sorted(proposals,key=lambda p:p['score']):
            try:
                mesh=build_mesh(poly,proposal['strip_regions'])
            except ValueError:
                continue
            if mesh['diagnostics']['valid']:
                return proposal
        self.fail('No candidate gives a closed roof for the synthetic footprint')

    def assert_axes_and_eaves(self,model,wings):
        matrices=[np.asarray(f) for f in model['connected_wings']['wing_frames_xy']]
        for w in wings:
            # Directions are undirected. The two arms must not be rounded into
            # a common right-angle frame merely because each differs by <8 deg.
            error=min(math.degrees(math.acos(np.clip(abs(w['u']@m[:,0]),0,1))) for m in matrices)
            self.assertLess(error,.7)
            for side in (-1,1):
                t=np.linspace(w['lo']+10,w['hi']-6,8)
                xy=t[:,None]*w['u']+(w['bottom']+.02 if side<0 else w['top']-.02)*w['v']
                z=predict_regions(model['strip_regions'],xy)
                self.assertTrue(np.isfinite(z).all())
                self.assertLess(float(np.ptp(z)),.30)

    def test_acute_and_obtuse_l_keep_measured_axes(self):
        for angle in (80.,100.):
            with self.subTest(angle=angle):
                wings=[wing((0,0),0),wing((0,0),angle)]
                poly,points=scene(wings)
                model=self.best_valid(poly,points,config())
                self.assertLess(model['data_error_m'],.35)
                self.assert_axes_and_eaves(model,wings)

    def test_right_angle_l_does_not_regress(self):
        wings=[wing((0,0),0),wing((0,0),90)]
        poly,points=scene(wings)
        model=self.best_valid(poly,points,config())
        self.assertLess(model['data_error_m'],.10)
        self.assert_axes_and_eaves(model,wings)

    def test_u_with_two_oblique_sides_keeps_three_main_directions(self):
        wings=[wing((0,28),0,length=32),wing((0,0),80,length=28),
               wing((32,0),100,length=28)]
        poly,points=scene(wings)
        model=self.best_valid(poly,points,config())
        self.assertLess(model['data_error_m'],.40)
        matrices=[np.asarray(f) for f in model['connected_wings']['wing_frames_xy']]
        for w in wings:
            error=min(math.degrees(math.acos(np.clip(abs(w['u']@m[:,0]),0,1))) for m in matrices)
            self.assertLess(error,.7)
        # Only the exposed back eave is asserted: an internal side meeting a
        # neighbouring wing is a roof junction, not an exterior eave.
        xy=np.c_[np.linspace(10,22,8),np.repeat(31.98,8)]
        z=predict_regions(model['strip_regions'],xy)
        self.assertTrue(np.isfinite(z).all())
        self.assertLess(float(np.ptp(z)),.30)

    def test_long_wall_drift_prevents_small_angle_snap(self):
        # 80 degrees differs only five degrees per axis from a best-fit
        # perpendicular frame, but changes the ends of a 32 m wall by >1 m.
        poly,_=scene([wing((0,0),0),wing((0,0),80)])
        _,retained=_walls(poly,{**DEFAULTS,'snap_frame_max_shift_m':.30})
        _,forced=_walls(poly,{**DEFAULTS,'snap_frame_max_shift_m':100.})
        horizontal=np.array([1.,0.])
        kept_error=min(math.degrees(math.acos(np.clip(abs(w['u']@horizontal),0,1))) for w in retained if w['length']>20)
        forced_error=min(math.degrees(math.acos(np.clip(abs(w['u']@horizontal),0,1))) for w in forced if w['length']>20)
        self.assertLess(kept_error,.01)
        self.assertGreater(forced_error,2.)

    def test_supported_subset_is_an_alternative_and_preserves_uncertainty(self):
        real=[wing((0,0),0),wing((0,0),80)]
        missing=wing((25,0),80,length=25,width=4)
        poly,points=scene(real+[missing],observed=real)
        false=wing((0,4),0,length=25,width=14)
        boxes=real+[false,missing]
        for w in boxes:w['inside']=w['polygon'].intersection(poly)
        units=[_wing_planes(w,(True,True)) for w in boxes]
        # The third ridge is contradicted by returns; the fourth has no returns.
        support=[{'wing_index':0,'nearby_cells':40,'supported_cells':35},
                 {'wing_index':1,'nearby_cells':40,'supported_cells':35},
                 {'wing_index':2,'nearby_cells':20,'supported_cells':0},
                 {'wing_index':3,'nearby_cells':0,'supported_cells':0}]
        full={'parameters':np.array([10.,.7]),'branch_support':support}
        before=copy.deepcopy(support)
        cfg=config();limits=cfg['connected_wings']
        subset=_supported_subset(poly,points,cfg,limits,boxes,{'wing_count':4},units,
            [(True,True)]*4,'hipped',full,[150,150,80,0],time.perf_counter())
        self.assertIsNotNone(subset)
        self.assertEqual(full['branch_support'],before)
        self.assertEqual(len(boxes),4)
        meta=subset['connected_wings']
        self.assertTrue(meta['supported_subset'])
        self.assertEqual(meta['kept_wing_indices'],[0,1])
        self.assertEqual(meta['omitted_wing_indices'],[2,3])
        self.assertEqual(meta['original_branch_support'][-1]['nearby_cells'],0)
        self.assertIn('do not prove absence',meta['omission_policy'])
        roof=shapely.union_all([shape(r['polygon']) for r in subset['strip_regions']])
        self.assertLess(poly.difference(roof).area,1e-5)


if __name__=='__main__':unittest.main()
