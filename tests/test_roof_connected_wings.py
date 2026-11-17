"""Synthetic generalization checks for connected roof volumes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
import shapely
from shapely.geometry import box,Polygon,shape
from shapely.affinity import rotate
from roof_config import resolve_config
from roof_connected_wings import connected_wing_proposals,_envelope,_wing_boxes,DEFAULTS
from roof_v2_geometry import build_mesh


def cloud(poly,predict,cell=.7):
    xmin,ymin,xmax,ymax=poly.bounds
    x,y=np.meshgrid(np.arange(xmin+.23,xmax,cell),np.arange(ymin+.23,ymax,cell))
    xy=np.c_[x.ravel(),y.ravel()]
    xy=xy[shapely.intersects_xy(poly,xy[:,0],xy[:,1])]
    return np.c_[xy,predict(xy)]


def rect_height(xy,bounds):
    x0,y0,x1,y1=bounds
    return np.min(np.c_[xy[:,0]-x0,x1-xy[:,0],xy[:,1]-y0,y1-xy[:,1]],axis=1)


class ConnectedWingTests(unittest.TestCase):
    def config(self,**extra):
        cfg=resolve_config();cfg['connected_wings']={**DEFAULTS,**extra}
        return cfg

    def test_simple_rectangle_is_not_a_connected_candidate(self):
        poly=box(0,0,25,10)
        points=cloud(poly,lambda xy:10+.7*rect_height(xy,(0,0,25,10)))
        self.assertEqual(connected_wing_proposals(poly,points,self.config()),[])

    def test_module_can_be_disabled(self):
        poly=box(0,0,25,8).union(box(0,0,8,22))
        points=cloud(poly,lambda xy:10+np.zeros(len(xy)))
        cfg=self.config();cfg['modules']['connected_wings']=False
        self.assertEqual(connected_wing_proposals(poly,points,cfg),[])

    def test_l_roof_keeps_two_continuous_wings(self):
        bounds=[(0,0,25,8),(0,0,8,22)]
        poly=box(*bounds[0]).union(box(*bounds[1]))
        points=cloud(poly,lambda xy:10+.7*np.max([rect_height(xy,b) for b in bounds],axis=0))
        result=min(connected_wing_proposals(poly,points,self.config()),key=lambda p:p['score'])
        self.assertEqual(result['connected_wings']['wing_count'],2)
        self.assertLess(result['data_error_m'],.08)
        self.assertAlmostEqual(result['eave_height_m'],10.,delta=.15)
        self.assertAlmostEqual(result['connected_wings']['pitch_tangent'],.7,delta=.05)
        mesh=build_mesh(poly,result['strip_regions'])
        self.assertTrue(mesh['diagnostics']['valid'])
        self.assertAlmostEqual(mesh['diagnostics']['coverage_fraction'],1.,places=6)

    def test_ring_keeps_courtyard_open(self):
        poly=box(0,0,40,32).difference(box(10,8,30,24))
        bounds=[(0,0,40,8),(0,24,40,32),(0,0,10,32),(30,0,40,32)]
        points=cloud(poly,lambda xy:11+.65*np.max([rect_height(xy,b) for b in bounds],axis=0))
        proposals=connected_wing_proposals(poly,points,self.config())
        result=min(proposals,key=lambda p:p['score'])
        self.assertGreaterEqual(result['connected_wings']['wing_count'],4)
        roof=shapely.union_all([shape(r['polygon']) for r in result['strip_regions']])
        self.assertLess(roof.intersection(box(10,8,30,24)).area,1e-6)
        self.assertLess(result['data_error_m'],.10)
        self.assertTrue(build_mesh(poly,result['strip_regions'])['diagnostics']['valid'])

    def test_measurements_can_support_distinct_eave_levels(self):
        bounds=[(0,0,30,12),(0,0,8,32),(0,24,30,32)]
        heights=[13.,9.,9.]
        poly=shapely.union_all([box(*b) for b in bounds])
        points=cloud(poly,lambda xy:np.maximum(9.,np.max([h+.75*rect_height(xy,b) for h,b in zip(heights,bounds)],axis=0)))
        proposals=connected_wing_proposals(poly,points,self.config())
        separate=[p for p in proposals if not p['connected_wings']['common_eave']]
        common=[p for p in proposals if p['connected_wings']['common_eave']]
        self.assertTrue(separate)
        result=min(separate,key=lambda p:p['score'])
        self.assertLess(result['data_error_m'],min(p['data_error_m'] for p in common)-.25)
        self.assertGreater(np.ptp(result['connected_wings']['wing_eaves_m']),2.)
        self.assertTrue(build_mesh(poly,result['strip_regions'])['diagnostics']['valid'])

    def test_rotated_l_has_same_fit(self):
        bounds=[(0,0,25,8),(0,0,8,22)]
        original=box(*bounds[0]).union(box(*bounds[1]))
        angle=np.radians(27);matrix=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        points=cloud(original,lambda xy:10+.7*np.max([rect_height(xy,b) for b in bounds],axis=0))
        points[:,:2]=points[:,:2]@matrix.T
        poly=rotate(original,27,origin=(0,0))
        best=min(connected_wing_proposals(poly,points,self.config()),key=lambda p:p['score'])
        self.assertLess(best['data_error_m'],.08)
        self.assertTrue(build_mesh(poly,best['strip_regions'])['diagnostics']['valid'])

    def test_regions_never_extrapolate_below_base(self):
        poly=box(-12,-10,18,16).difference(box(-4,-2,7,8))
        wings=[np.array([[0,1,10],[0,-1,2],[1,0,12],[-1,0,18]]),
               np.array([[1,0,12],[-1,0,-4],[0,1,10],[0,-1,16]])]
        for region in _envelope(poly,wings):
            xy=shapely.get_coordinates(shape(region['polygon']))
            z=np.c_[xy,np.ones(len(xy))]@np.asarray(region['plane'])
            self.assertGreaterEqual(float(z.min()),-1e-6)


if __name__=='__main__':unittest.main()
