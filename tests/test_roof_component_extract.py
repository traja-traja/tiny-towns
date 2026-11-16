import unittest
import numpy as np
from shapely.geometry import box, Polygon
from shapely.ops import triangulate

from scripts.roof_component_extract import extract_components, detect_components, PROFILES
from scripts.roof_pilot_roofer import predict_roofer_z


def roof(regions):
    vertices=[];faces=[]
    for polygon,plane in regions:
        for t in triangulate(polygon):
            if not polygon.covers(t):continue
            face=[]
            for x,y in list(t.exterior.coords)[:3]:
                face.append(len(vertices));vertices.append([x,y,plane[0]*x+plane[1]*y+plane[2]])
            faces.append(face)
    return {'status':'ok','vertices':vertices,'faces':faces,'face_semantics':['roof']*len(faces)}


def points(model,polygon,spacing=.20):
    x0,y0,x1,y1=polygon.bounds
    x,y=np.meshgrid(np.arange(x0+spacing/2,x1,spacing),np.arange(y0+spacing/2,y1,spacing))
    xy=np.column_stack((x.ravel(),y.ravel()));z=predict_roofer_z(model,xy)
    return np.column_stack((xy[np.isfinite(z)],z[np.isfinite(z)]))


class ExtractionTests(unittest.TestCase):
    def test_tower_removed_infilled_then_returned_without_hole(self):
        domain=box(0,0,24,16);tower=box(11,7,13,9)
        source=roof([(domain.difference(tower),[0,0,8]),(tower,[0,0,12])])
        result=extract_components(source,points(source,domain),domain,PROFILES['compact15'])
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['models']['restored']['metrics']['restored_component_count'],1)
        self.assertAlmostEqual(predict_roofer_z(result['models']['patched'],[[12,8]])[0],8,places=4)
        self.assertAlmostEqual(predict_roofer_z(result['models']['restored'],[[12,8]])[0],12,places=3)
        self.assertLess(result['models']['restored']['metrics']['roof_domain_change_m2'],1e-6)

    def test_long_gable_ridge_is_not_extracted_as_chimney(self):
        domain=box(0,0,30,12)
        source=roof([(box(0,0,30,6),[0,.8,7]),(box(0,6,30,12),[0,-.8,16.6])])
        result=detect_components(source,points(source,domain),domain,PROFILES['compact25'])
        self.assertEqual(result['detected_count'],0)

    def test_tower_on_gable_is_infilled_with_original_main_ridge(self):
        domain=box(0,0,24,12);tower=box(11,5,13,7)
        source=roof([(box(0,0,24,6).difference(tower),[0,.6,8]),
                     (box(0,6,24,12).difference(tower),[0,-.6,15.2]),
                     (tower,[0,0,15])])
        result=extract_components(source,points(source,domain),domain,PROFILES['compact15'])
        self.assertEqual(result['status'],'ok')
        expected=[11.3,11.6,11.3]
        np.testing.assert_allclose(predict_roofer_z(result['models']['patched'],[[12,5.5],[12,6],[12,6.5]]),expected,atol=.1)
        self.assertAlmostEqual(predict_roofer_z(result['models']['restored'],[[12,6]])[0],15,places=2)

    def test_large_high_wing_is_not_a_small_protrusion(self):
        domain=box(0,0,24,16);wing=box(0,0,6,12)
        source=roof([(domain.difference(wing),[0,0,8]),(wing,[0,0,15])])
        result=detect_components(source,points(source,domain),domain,PROFILES['compact25'])
        self.assertEqual(result['detected_count'],0)

    def test_courtyard_stays_open_after_restoration(self):
        domain=Polygon([(0,0),(24,0),(24,20),(0,20)],holes=[[(3,3),(8,3),(8,8),(3,8)]])
        tower=box(15,11,17,13)
        source=roof([(domain.difference(tower),[0,0,8]),(tower,[0,0,12])])
        result=extract_components(source,points(source,domain),domain,PROFILES['compact15'])
        self.assertEqual(result['status'],'ok')
        for model in result['models'].values():
            self.assertTrue(np.isnan(predict_roofer_z(model,[[5,5]])[0]))

    def test_noise_bump_below_prominence_is_ignored(self):
        domain=box(0,0,24,16);bump=box(11,7,13,9)
        source=roof([(domain.difference(bump),[0,0,8]),(bump,[0,0,8.4])])
        result=detect_components(source,points(source,domain),domain,PROFILES['compact15'])
        self.assertEqual(result['detected_count'],0)

    def test_geometric_tower_without_train_support_is_rejected(self):
        domain=box(0,0,24,16);tower=box(11,7,13,9)
        source=roof([(domain.difference(tower),[0,0,8]),(tower,[0,0,12])])
        data=points(source,domain);data=data[data[:,2]<10]
        result=detect_components(source,data,domain,PROFILES['compact15'])
        self.assertEqual(result['detected_count'],0)
        self.assertTrue(any('insufficient_roof_train_support' in c['rejection_reasons'] for c in result['candidates']))


if __name__=='__main__':unittest.main()
