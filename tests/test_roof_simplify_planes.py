import unittest

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import triangulate

from scripts.roof_simplify_planes import simplify_roof, extract_roof_regions
from scripts.roof_pilot_roofer import predict_roofer_z


def model_for(regions):
    vertices,faces=[],[]
    for polygon,plane in regions:
        for triangle in triangulate(polygon):
            if not polygon.covers(triangle):continue
            face=[]
            for x,y in list(triangle.exterior.coords)[:3]:
                face.append(len(vertices));vertices.append([x,y,plane[0]*x+plane[1]*y+plane[2]])
            faces.append(face)
    return {'vertices':vertices,'faces':faces,'face_semantics':['roof']*len(faces)}


class PlaneMergeTests(unittest.TestCase):
    def test_two_near_coplanar_patches_become_one_real_plane(self):
        left=Polygon([(0,0),(5,0),(5,5),(0,5)])
        right=Polygon([(5,0),(10,0),(10,5),(5,5)])
        model=model_for([(left,[.2,0,5]),(right,[.23,0,4.85])])
        result=simplify_roof(model,None,left.union(right),max_vertical_change_m=.25,max_normal_angle_deg=8)
        self.assertEqual(result['metrics']['actual_roof_region_count'],1)
        self.assertEqual(result['metrics']['roof_triangle_count'],2)
        self.assertLess(result['metrics']['max_vertical_change_from_baseline_m'],.05)
        self.assertNotEqual(predict_roofer_z(result,[[2,2]])[0],predict_roofer_z(model,[[2,2]])[0])

    def test_opposed_gable_slopes_preserve_main_ridge(self):
        left=Polygon([(0,0),(5,0),(5,5),(0,5)])
        right=Polygon([(5,0),(10,0),(10,5),(5,5)])
        result=simplify_roof(model_for([(left,[.7,0,5]),(right,[-.7,0,12])]),None,left.union(right))
        self.assertEqual(result['metrics']['actual_roof_region_count'],2)
        np.testing.assert_allclose(predict_roofer_z(result,[[0,2],[5,2],[10,2]]),[5,8.5,5],atol=1e-7)

    def test_two_metre_height_step_is_not_merged(self):
        left=Polygon([(0,0),(5,0),(5,5),(0,5)])
        right=Polygon([(5,0),(10,0),(10,5),(5,5)])
        result=simplify_roof(model_for([(left,[0,0,5]),(right,[0,0,7])]),None,left.union(right))
        self.assertEqual(result['metrics']['actual_roof_region_count'],2)
        self.assertAlmostEqual(result['metrics']['max_interface_jump_m'],2)
        np.testing.assert_allclose(predict_roofer_z(result,[[2,2],[8,2]]),[5,7])

    def test_courtyard_is_preserved_and_outside_predictions_remain_nan(self):
        polygon=Polygon([(0,0),(12,0),(12,12),(0,12)],holes=[[(4,4),(8,4),(8,8),(4,8)]])
        result=simplify_roof(model_for([(polygon,[.1,0,6])]),None,polygon)
        self.assertEqual(result['metrics']['actual_roof_region_count'],1)
        self.assertAlmostEqual(result['metrics']['roof_footprint_coverage_fraction'],1)
        self.assertTrue(np.isnan(predict_roofer_z(result,[[6,6]])[0]))

    def test_disconnected_patches_stay_separate(self):
        left=Polygon([(0,0),(2,0),(2,2),(0,2)])
        right=Polygon([(4,0),(6,0),(6,2),(4,2)])
        result=simplify_roof(model_for([(left,[0,0,5]),(right,[0,0,5])]),None,left.union(right))
        self.assertEqual(result['metrics']['actual_roof_region_count'],2)

    def test_overlap_cannot_be_silently_discarded(self):
        polygon=Polygon([(0,0),(5,0),(5,5),(0,5)])
        with self.assertRaisesRegex(ValueError,'Overlapping'):
            simplify_roof(model_for([(polygon,[0,0,5]),(polygon,[0,0,7])]),None,polygon)

    def test_new_steps_respect_explicit_small_limit(self):
        a=Polygon([(0,0),(3,0),(3,5),(0,5)])
        b=Polygon([(3,0),(6,0),(6,5),(3,5)])
        c=Polygon([(6,0),(9,0),(9,5),(6,5)])
        model=model_for([(a,[.2,0,5]),(b,[.3,0,4.7]),(c,[0,0,6.5])])
        result=simplify_roof(model,None,a.union(b).union(c),max_interface_jump_increase_m=.01)
        self.assertLessEqual(result['metrics']['max_interface_jump_increase_m'],.01+1e-8)

    def test_holdout_argument_is_not_read(self):
        polygon=Polygon([(0,0),(5,0),(5,5),(0,5)])
        result=simplify_roof(model_for([(polygon,[0,0,5])]),object(),polygon)
        self.assertEqual(result['metrics']['actual_roof_region_count'],1)

    def test_t_junction_and_duplicate_vertices_have_shared_region(self):
        a=Polygon([(0,0),(5,0),(5,10),(0,10)])
        b=Polygon([(5,0),(10,0),(10,5),(5,5)])
        c=Polygon([(5,5),(10,5),(10,10),(5,10)])
        model=model_for([(p,[.2,.1,5]) for p in [a,b,c]])
        self.assertEqual(extract_roof_regions(model)['region_count'],1)
        result=simplify_roof(model,None,a.union(b).union(c))
        self.assertEqual(result['metrics']['roof_triangle_count'],2)

    def test_coplanar_metric_does_not_chain_through_curved_roof(self):
        regions=[];height=5
        for i in range(20):
            slope=np.tan(np.deg2rad(i*.1))
            polygon=Polygon([(i,0),(i+1,0),(i+1,5),(i,5)])
            regions.append((polygon,[slope,0,height-slope*i]))
            height+=slope
        self.assertGreater(extract_roof_regions(model_for(regions))['region_count'],1)


if __name__=='__main__':unittest.main()
