"""Mathematical roof checks, without optical assessment of user buildings."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import unittest
import numpy as np
from shapely.geometry import box
from roof_eave_planes import _proposal, _regions, _primary_extent, infer_eave_roof
from roof_v2 import predict_regions
from roof_v2_geometry import build_mesh


class PyramidalTests(unittest.TestCase):
    def points(self, apex=(6., 4.)):
        x, y = np.meshgrid(np.arange(.2, 12, .4), np.arange(.2, 10, .4))
        xy = np.c_[x.ravel(), y.ravel()]
        u, v = apex
        z = 8+4*np.minimum.reduce([xy[:,0]/u, (12-xy[:,0])/(12-u),
                                  xy[:,1]/v, (10-xy[:,1])/(10-v)])
        return np.c_[xy, z]

    def test_free_apex_four_planes_and_clipped_protrusion(self):
        points = self.points((4.8, 6.))
        proposal = _proposal('pyramidal', (), np.eye(2), [0,12,0,10,0,0], points)
        self.assertEqual(proposal['ridge_xy'], [])
        np.testing.assert_allclose(proposal['apex_xy'], [4.8,6.], atol=.02)
        poly = box(0,0,12,10).union(box(4,10,7,12))
        regions = _regions(poly, proposal)
        self.assertEqual(len(regions), 4)
        self.assertLess(np.max(abs(predict_regions(regions, points[:,:2])-points[:,2])), .02)
        self.assertTrue(build_mesh(poly, regions)['diagnostics']['valid'])
        for plane in proposal['wings'][0]:
            self.assertAlmostEqual(np.dot(plane[:2], proposal['apex_xy'])+plane[2], 12., places=2)

    def test_selection_and_main_walls(self):
        self.assertEqual(_primary_extent([[(0,10),(12,10)],[(0,12),(10,8),(16,4)]]),
                         [0.,12.,0.,10.,0.,0.])
        result = infer_eave_roof(box(0,0,12,10), self.points(),
            allow_flat=True, allow_networks=True, allow_pyramidal=True)
        self.assertEqual(result['model']['type'], 'pyramidal')
        self.assertEqual(result['model']['ridge_lines'], [])
        self.assertEqual(len(result['model']['apex_points']), 1)

    def test_missing_ridge_does_not_force_pyramid(self):
        points = self.points()
        points[:,2] = 8.
        result = infer_eave_roof(box(0,0,12,10), points,
            allow_flat=True, allow_networks=True, allow_pyramidal=True)
        self.assertEqual(result['model']['type'], 'flat')


if __name__ == '__main__':
    unittest.main()
