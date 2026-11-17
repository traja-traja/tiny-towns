"""Generalized skeleton end planes: geometry-only, no real point clouds."""
import unittest
import numpy as np
from shapely.geometry import box,shape
from shapely.ops import unary_union
from roof_skeleton_gables import skeleton_faces,DEFAULTS
from roof_skeleton_caps import terminal_caps,clipped_regions
from roof_v2_geometry import build_mesh

class GeneralSkeletonCapTests(unittest.TestCase):
    def test_nontriangular_end_face_can_be_a_gable_candidate(self):
        poly=box(0,0,20,8);faces=skeleton_faces(poly)
        caps,audit=terminal_caps(poly,faces,DEFAULTS)
        eligible=[a for a in audit if a['eligible'] and a['face_vertex_count']>3]
        self.assertTrue(eligible,'A trapezoidal end roof plane must not be excluded merely for having four corners')
        index=next(i for i,c in enumerate(caps) if c['face_index']==eligible[0]['face_index'])
        unit=clipped_regions(faces,caps,[index],poly,DEFAULTS)
        self.assertLess(poly.symmetric_difference(unary_union([shape(r['polygon']) for r in unit])).area,1e-6)
        mesh=build_mesh(poly,[dict(polygon=r['polygon'],plane=(.6*np.asarray(r['plane'])+[0,0,6]).tolist()) for r in unit])
        self.assertTrue(mesh['diagnostics']['valid'])
    def test_joint_removal_cannot_turn_a_side_into_one_sided_ramp(self):
        poly=box(0,0,20,8);faces=skeleton_faces(poly);caps,_=terminal_caps(poly,faces,DEFAULTS)
        pair=next((i,j) for i,a in enumerate(caps) for j,b in enumerate(caps) if i<j and b['face_index'] in a['side_face_indices'] and abs(np.dot(np.diff(a['edge_xy'],axis=0)[0],np.diff(b['edge_xy'],axis=0)[0]))<.5*a['edge_length_m']*b['edge_length_m'])
        with self.assertRaisesRegex(ValueError,'no_interior_gable_peak'):
            clipped_regions(faces,caps,pair,poly,DEFAULTS)

if __name__=='__main__':unittest.main()
