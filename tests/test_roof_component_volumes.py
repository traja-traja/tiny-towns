import sys
import unittest
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from roof_component_volumes import partition_roof,fit_volume_candidate
from roof_simplify_planes import _mesh_regions
from roof_pilot_roofer import predict_roofer_z


def mesh(regions):
    values=[{'id':i,'geometry':poly,'plane':np.asarray(plane,float)}
            for i,(poly,plane) in enumerate(regions)]
    domain=unary_union([r['geometry'] for r in values])
    v,f,s,*_= _mesh_regions(values,domain,0.0)
    return {'vertices':v,'faces':f,'face_semantics':s,'status':'ok'}


def points(poly,height):
    x0,y0,x1,y1=poly.bounds
    xy=np.asarray([(x,y) for x in np.linspace(x0+.1,x1-.1,23)
                           for y in np.linspace(y0+.1,y1-.1,19)])
    xy=xy[shapely.contains_xy(poly,xy[:,0],xy[:,1])]
    return np.column_stack((xy,height(xy)))


class NoHoldout(dict):
    def __getitem__(self,key):
        if 'test' in key or 'hold' in key:
            raise AssertionError('Holdout accessed by fitter')
        return super().__getitem__(key)


class VolumeGraphTest(unittest.TestCase):
    def test_continuous_gable_stays_one_volume(self):
        poly=box(-10,-6,10,6)
        original=mesh([(box(-10,-6,0,6),[.5,0,10]),(box(0,-6,10,6),[-.5,0,10])])
        partition=partition_roof(original,poly)
        self.assertEqual(len(partition['components']),1)
        output=fit_volume_candidate(NoHoldout(polygon=poly,train_relative=points(poly,lambda xy:10-.5*np.abs(xy[:,0]))),original)
        self.assertEqual(output['model']['metrics']['main_volume_count'],1)
        self.assertEqual(output['model']['volume_components'][0]['shape'],'gabled')

    def test_vertical_terraces_are_two_volumes_and_height_is_retained(self):
        poly=box(-10,-6,10,6)
        original=mesh([(box(-10,-6,0,6),[0,0,7]),(box(0,-6,10,6),[0,0,12])])
        train=points(poly,lambda xy:np.where(xy[:,0]<0,7,12))
        output=fit_volume_candidate(NoHoldout(polygon=poly,train_relative=train),original)['model']
        self.assertEqual(output['metrics']['main_volume_count'],2)
        np.testing.assert_allclose(predict_roofer_z(output,np.array([[-5,0],[5,0]])),[7,12],atol=.01)
        self.assertLess(output['metrics']['roof_overlap_area_m2'],1e-6)
        self.assertLess(output['metrics']['roof_missing_area_m2'],1e-6)
        # Internal interface walls start at the lower roof, not at the ground.
        vertices=np.asarray(output['vertices'])
        interfaces=[vertices[f] for f,s in zip(output['faces'],output['face_semantics'])
                    if s=='wall' and np.all(np.abs(vertices[f,0])<1e-7)]
        self.assertTrue(interfaces)
        self.assertGreaterEqual(min(t[:,2].min() for t in interfaces),6.99)

    def test_declared_step_thresholds_have_different_meaning(self):
        poly=box(-10,-6,10,6)
        original=mesh([(box(-10,-6,0,6),[0,0,7]),(box(0,-6,10,6),[0,0,8])])
        self.assertEqual(len(partition_roof(original,poly,step_threshold_m=.75)['components']),2)
        self.assertEqual(len(partition_roof(original,poly,step_threshold_m=1.5)['components']),1)

    def test_small_tower_is_kept_as_source_not_absorbed(self):
        poly=box(-10,-10,10,10)
        tower=box(-1,-1,1,1)
        original=mesh([(poly.difference(tower),[0,0,8]),(tower,[0,0,16])])
        train=points(poly,lambda xy:np.where((np.abs(xy[:,0])<=1)&(np.abs(xy[:,1])<=1),16,8))
        output=fit_volume_candidate(NoHoldout(polygon=poly,train_relative=train),original)['model']
        self.assertEqual(output['metrics']['preserved_small_component_count'],1)
        self.assertAlmostEqual(predict_roofer_z(output,np.array([[0.,0.]]))[0],16.)

    def test_courtyard_remains_empty(self):
        poly=Polygon([[-10,-10],[10,-10],[10,10],[-10,10]],
                     [[[-3,-3],[-3,3],[3,3],[3,-3]]])
        original=mesh([(poly,[0,0,8])])
        output=fit_volume_candidate(NoHoldout(polygon=poly,train_relative=points(poly,lambda xy:np.full(len(xy),8.))),original)['model']
        self.assertTrue(np.isnan(predict_roofer_z(output,np.array([[0.,0.]]))[0]))
        self.assertLess(output['metrics']['roof_missing_area_m2'],1e-6)

    def test_sparse_component_keeps_original_geometry(self):
        poly=box(-5,-5,5,5)
        original=mesh([(poly,[0,0,9])])
        train=np.array([[0,0,9],[1,1,9],[1,-1,9]],float)
        output=fit_volume_candidate(NoHoldout(polygon=poly,train_relative=train),original)['model']
        self.assertEqual(output['metrics']['fitted_volume_count'],0)
        self.assertEqual(output['volume_components'][0]['preserve_reason'],'sparse_training_points')
        self.assertAlmostEqual(predict_roofer_z(output,np.array([[0.,0.]]))[0],9.)

    def test_more_than_eight_main_parts_preserves_source_without_forced_merging(self):
        poly=box(0,0,90,10)
        original=mesh([(box(i*10,0,(i+1)*10,10),[0,0,8+i*2]) for i in range(9)])
        train=points(poly,lambda xy:8+2*np.floor(xy[:,0]/10))
        output=fit_volume_candidate(NoHoldout(polygon=poly,train_relative=train),original)
        self.assertEqual(output['status'],'preserved_budget_exceeded')
        self.assertEqual(output['model']['metrics']['main_volume_count'],9)
        self.assertEqual(output['model']['metrics']['fitted_volume_count'],0)
        self.assertEqual(output['model']['metrics']['component_count'],9)


if __name__=='__main__':
    unittest.main()
