"""Mathematical regression tests for three/four-wing topology, not image QA."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import unittest
import numpy as np
from shapely.geometry import Polygon
from roof_eave_planes import _network_proposal, _regions
from roof_v2 import predict_regions
from roof_v2_geometry import build_mesh


class RidgeNetworkTests(unittest.TestCase):
    def check_topology(self, missing):
        poly = Polygon([(0,0),(20,0),(20,20),(0,20)],
                       holes=[[(8,8),(12,8),(12,12),(8,12)]])
        x, y = np.meshgrid(np.arange(.3,20,.6), np.arange(.3,20,.6))
        xy = np.c_[x.ravel(), y.ravel()]
        xy = xy[~((xy[:,0]>8)&(xy[:,0]<12)&(xy[:,1]>8)&(xy[:,1]<12))]
        outside = np.c_[8+xy[:,0],28-xy[:,0],8+xy[:,1],28-xy[:,1]]
        inside = np.c_[14-.5*xy[:,0],4+.5*xy[:,0],14-.5*xy[:,1],4+.5*xy[:,1]]
        active = [i for i in range(4) if i != missing]
        z = np.minimum(outside[:,active].min(axis=1), inside[:,active].max(axis=1))
        candidate = _network_proposal(poly, np.eye(2), [0,20,0,20,0,0], np.c_[xy,z], missing)
        self.assertIsNotNone(candidate)
        regions = _regions(poly, candidate)
        self.assertLess(np.max(abs(predict_regions(regions, xy)-z)), .03)
        self.assertTrue(build_mesh(poly, regions)['diagnostics']['valid'])
        path = np.asarray(candidate['ridge_xy'][0])
        self.assertEqual(len(path)-1, 4 if missing is None else 3)
        self.assertTrue(np.all(np.min(abs(np.diff(path, axis=0)), axis=1)<1e-7))
        self.assertEqual(bool(np.allclose(path[0],path[-1])), missing is None)

    def test_three_ridges_u(self):
        self.check_topology(3)

    def test_four_ridges_closed_loop(self):
        self.check_topology(None)


if __name__ == '__main__':
    unittest.main()
