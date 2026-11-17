import unittest
import numpy as np
from shapely.geometry import box,mapping
from roof_observed_ridges import detect_volume_ridges,attach_observed_ridges


def cloud(kind='gable'):
    x,y=np.meshgrid(np.arange(.2,24,.4),np.arange(.2,12,.4));x=x.ravel();y=y.ravel()
    z=14.-.6*np.maximum(7.5-y,0)-.9*np.maximum(y-7.5,0)
    if kind=='hip':z=np.minimum(z,np.minimum(10.+x,10.+24-x))
    if kind=='flat':z=np.full_like(x,11.)
    if kind=='pyramid':z=14.-.6*np.maximum(abs(x-12),abs(y-6))
    return np.c_[x,y,z]

class ObservedRidgeTests(unittest.TestCase):
    def main(self,data):
        result=detect_volume_ridges(box(0,0,24,12),data)
        self.assertTrue(result['lines'],result)
        return next(x for x in result['lines'] if x['role']=='main'),result
    def test_asymmetric_offset_and_height_are_measured_not_centered(self):
        line,_=self.main(cloud())
        self.assertAlmostEqual(line['height_m'],14.,delta=.20)
        self.assertTrue(all(abs(p[1]-7.5)<.30 for p in line['points']))
        self.assertGreater(line['length_m'],19.)
    def test_boundary_neighbor_spike_does_not_move_ridge(self):
        data=cloud();data[data[:,1]<.5,2]+=7.
        line,result=self.main(data)
        self.assertAlmostEqual(line['height_m'],14.,delta=.20)
        self.assertGreater(result['excluded_boundary_cells'],0)
    def test_hip_ridge_extent_not_stretched_to_walls(self):
        line,_=self.main(cloud('hip'))
        xs=[p[0] for p in line['points']]
        self.assertGreater(min(xs),2.5);self.assertLess(max(xs),21.5)
    def test_flat_and_apex_do_not_create_long_ridge(self):
        for kind in ('flat','pyramid'):
            result=detect_volume_ridges(box(0,0,24,12),cloud(kind))
            self.assertEqual(result['status'],'not_detected',(kind,result))
    def test_each_volume_has_independent_record(self):
        data=cloud();other=data+np.array([30.,0.,5.])
        result={'model':{'metadata':{'bodies':[{'footprint':mapping(box(0,0,24,12))},{'footprint':mapping(box(30,0,54,12))}]}},'timing':{}}
        attach_observed_ridges(result,mapping(box(0,0,54,12)),np.r_[data,other])
        volumes=result['diagnostics']['observed_ridges']['volumes']
        self.assertEqual([v['volume_id'] for v in volumes],[1,2])
        heights=[next(l['height_m'] for l in v['lines'] if l['role']=='main') for v in volumes]
        self.assertAlmostEqual(heights[1]-heights[0],5.,delta=.1)

if __name__=='__main__':unittest.main()
