"""General geometry/evidence checks for the isolated local gable adapter."""
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'.work/roof-skeleton-test/vendor')]
import numpy as np
import shapely
from shapely.geometry import box,shape
from roof_skeleton_gables import infer_skeleton_gables,virtual_footprint,DEFAULTS,_evidence_masks


def points(poly,kind):
    x,y=np.meshgrid(np.arange(.2,20,.4),np.arange(.2,8,.4))
    xy=np.c_[x.ravel(),y.ravel()]
    xy=xy[shapely.intersects_xy(poly,xy[:,0],xy[:,1])]
    distances=np.minimum(xy[:,1],8-xy[:,1])
    if kind=='hipped':distances=np.minimum(distances,np.minimum(xy[:,0],20-xy[:,0]))
    return np.c_[xy,6.+.7*distances]


class SkeletonGableTests(unittest.TestCase):
    def test_gable_pair_continues_two_side_planes_to_both_ends(self):
        poly=box(0,0,20,8);result=infer_skeleton_gables(poly,points(poly,'gabled'))
        self.assertEqual(result['model']['metadata']['gable_count'],2)
        self.assertEqual(result['model']['metadata']['nominal_roof_plane_count'],2)
        self.assertTrue(result['model']['mesh']['diagnostics']['valid'])
        self.assertLess(result['diagnostics']['training_score'],.10)
        self.assertTrue(all(e['accepted'] for e in result['diagnostics']['end_evidence']))
    def test_actual_hips_are_not_replaced_without_local_point_support(self):
        poly=box(0,0,20,8);result=infer_skeleton_gables(poly,points(poly,'hipped'))
        self.assertEqual(result['model']['metadata']['gable_count'],0)
        self.assertTrue(any(not c['accepted'] for c in result['candidates'] if c['gable_edge_ids']))
    def test_virtual_reference_does_not_move_long_real_walls_or_leave_gaps(self):
        poly=box(0,0,20,8).difference(box(8,0,9,.15))
        reference,meta=virtual_footprint(poly,DEFAULTS)
        self.assertLess(poly.difference(reference).area,1e-7)
        self.assertLessEqual(meta['changed_area_fraction'],DEFAULTS['max_reference_area_change'])
        result=infer_skeleton_gables(poly,points(poly,'gabled'))
        coverage=shapely.union_all([shape(r['polygon']) for r in result['model']['regions']])
        self.assertLess(coverage.symmetric_difference(poly).area,1e-6)
        self.assertTrue(result['model']['mesh']['diagnostics']['valid'])

    def test_inset_evidence_uses_real_wall_even_when_virtual_wall_is_shifted(self):
        poly=box(0,0,10,10)
        cells=np.array([[x,5.,10.] for x in [-.1,.1,.79,.8,1.,1.5,1.51]])
        cap=dict(edge_xy=[[-.65,0.],[-.65,10.]],edge_length_m=10.,polygon=box(-1,0,5,10))
        masks,details=_evidence_masks(cells,[cap],DEFAULTS,poly)
        self.assertEqual(cells[masks[0],0].tolist(),[.8,1.,1.5])
        self.assertEqual(details[0]['distance_reference'],'actual_footprint_boundary')
        self.assertEqual(details[0]['evidence_inset_m'],.8)
    def test_invalid_inset_band_is_rejected(self):
        poly=box(0,0,20,8)
        with self.assertRaisesRegex(ValueError,'inset'):
            infer_skeleton_gables(poly,points(poly,'gabled'),settings={'evidence_inset_m':1.5})

if __name__=='__main__':unittest.main()
