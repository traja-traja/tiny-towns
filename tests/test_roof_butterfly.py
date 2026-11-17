"""Numerical contracts for inward roofs, horizontal wall anchors and an end cap."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))

import numpy as np
import shapely
from shapely.geometry import Polygon, box, shape
from roof_butterfly import butterfly_proposal
from roof_config import resolve_config
from roof_eave_planes import infer_eave_roof
from roof_v2 import predict_regions


EXTENT = [0., 20., 0., 10., 0., 0.]


def legacy_settings():
    return resolve_config({'butterfly':{'end_cap_required':False}})


def fixture(valley_y=3.2, end_cap=False):
    x, y = np.meshgrid(np.arange(.2, 20., .4), np.arange(.2, 10., .4))
    xy = np.c_[x.ravel(), y.ravel()]
    z = 8.+4.*np.where(xy[:, 1] <= valley_y,
        (valley_y-xy[:, 1])/valley_y,
        (xy[:, 1]-valley_y)/(10.-valley_y))
    if end_cap:
        # Closing plane has the arithmetic mean of the two side tangents.
        slope = .5*(4./valley_y+4./(10.-valley_y))
        z = np.maximum(z, 12.-slope*xy[:, 0])
    return box(0., 0., 20., 10.), np.c_[xy, z]


def predict(candidate, xy):
    planes = np.asarray(candidate['upper_planes'])
    return np.max(np.c_[xy, np.ones(len(xy))]@planes.T, axis=1)


class ButterflyRoofTests(unittest.TestCase):
    def test_asymmetric_valley_survives_sparse_high_outliers(self):
        poly, clean = fixture()
        points = clean.copy()
        points[::47, 2] += 5.  # Sparse chimneys should not raise the whole roof.
        candidate = butterfly_proposal(poly, np.eye(2), EXTENT, points, legacy_settings())
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate['kind'], 'butterfly')
        self.assertFalse(candidate['evidence_rejections'])
        self.assertEqual(len(candidate['upper_planes']), 2)
        self.assertAlmostEqual(candidate['valley_height_m'], 8., delta=.15)
        self.assertAlmostEqual(candidate['high_edge_height_m'], 12., delta=.15)
        # The valley is the intersection of the fitted planes, not an exported
        # constant-height line (nonparallel walls can produce a sloping valley).
        delta = np.diff(np.asarray(candidate['upper_planes']), axis=0)[0]
        valley_y = -(delta[0]*np.array([0., 20.])+delta[2])/delta[1]
        np.testing.assert_allclose(valley_y, 3.2, atol=.15)
        error = abs(predict(candidate, clean[:, :2])-clean[:, 2])
        self.assertLess(np.quantile(error, .9), .15)

    def test_both_roof_planes_fall_toward_the_valley(self):
        poly, points = fixture()
        candidate = butterfly_proposal(poly, np.eye(2), EXTENT, points, legacy_settings())
        slopes = sorted(p[1] for p in candidate['upper_planes'])
        self.assertLess(slopes[0], -.1)
        self.assertGreater(slopes[1], .1)
        query = np.array([[10., 0.], [10., 3.2], [10., 10.]])
        np.testing.assert_allclose(predict(candidate, query), [12., 8., 12.], atol=.10)

    def test_rotating_the_reference_frame_preserves_the_roof(self):
        poly, points = fixture()
        base = butterfly_proposal(poly, np.eye(2), EXTENT, points, legacy_settings())
        for angle in (23., 81.):
            with self.subTest(angle=angle):
                theta = np.deg2rad(angle)
                matrix = np.array([[np.cos(theta), -np.sin(theta)],
                                   [np.sin(theta), np.cos(theta)]])
                xy = points[:, :2]@matrix.T
                rotated_poly = Polygon(np.asarray(poly.exterior.coords)@matrix.T)
                candidate = butterfly_proposal(rotated_poly, matrix, EXTENT,
                    np.c_[xy, points[:, 2]], legacy_settings())
                self.assertIsNotNone(candidate)
                self.assertFalse(candidate['evidence_rejections'])
                np.testing.assert_allclose(predict(candidate, xy), predict(base, points[:, :2]), atol=.02)

    def test_flat_and_one_way_sloped_roofs_do_not_support_a_valley(self):
        poly, template = fixture()
        for kind in ('flat', 'skillion'):
            with self.subTest(kind=kind):
                points = template.copy()
                points[:, 2] = 10. if kind == 'flat' else 8.+.4*points[:, 1]
                candidate = butterfly_proposal(poly, np.eye(2), EXTENT, points, legacy_settings())
                self.assertTrue(candidate is None or candidate['evidence_rejections'])

    def test_default_selection_builds_three_planes_and_a_clipped_valley(self):
        poly, points = fixture(end_cap=True)
        result = infer_eave_roof(poly, points, allow_flat=True, allow_networks=True,
            allow_pyramidal=True, allow_parallel=True)
        model = result['model']
        self.assertEqual(model['type'], 'butterfly')
        self.assertEqual(len({tuple(np.round(r['plane'], 8)) for r in model['regions']}), 3)
        self.assertTrue(model['mesh']['diagnostics']['valid'])
        self.assertEqual(model['ridge_lines'], [])
        self.assertTrue(model['valley_lines'])
        for line in model['valley_lines']:
            np.testing.assert_allclose(np.asarray(line)[:, 2], 8., atol=.15)
        valley = np.concatenate([np.asarray(line) for line in model['valley_lines']])
        cap_slope = .5*(4./3.2+4./6.8)
        self.assertAlmostEqual(float(valley[:, 0].min()), 4./cap_slope, delta=.15)
        self.assertAlmostEqual(float(valley[:, 0].max()), 20., delta=.15)
        self.assertTrue(model['metadata']['butterfly']['end_cap'])
        # All three selected facade edges stay at one common height.
        high = model['metadata']['high_edge_height_m']
        for query in (np.array([[0., 0.], [20., 0.]]),
                      np.array([[0., 10.], [20., 10.]]),
                      np.array([[0., 0.], [0., 10.]])):
            np.testing.assert_allclose(predict_regions(model['regions'], query), high, atol=.10)
        # Check continuity of every seam, not just overall mesh validity.
        for i, first in enumerate(model['regions']):
            for second in model['regions'][i+1:]:
                seam = shape(first['polygon']).boundary.intersection(shape(second['polygon']).boundary)
                xy = shapely.get_coordinates(seam)
                if len(xy):
                    a = np.c_[xy, np.ones(len(xy))]
                    np.testing.assert_allclose(a@first['plane'], a@second['plane'], atol=1e-6)
        error = abs(predict_regions(model['regions'], points[:, :2])-points[:, 2])
        self.assertLess(np.quantile(error, .9), .15)
        self.assertTrue(any(c['type'] == 'butterfly' and c['selected'] for c in result['candidates']))

    def test_nonparallel_wall_anchors_stay_horizontal(self):
        poly = Polygon([(0., 0.), (20., 0.), (20., 12.), (0., 10.)])
        x, y = np.meshgrid(np.arange(.2, 20., .4), np.arange(.2, 12., .4))
        xy = np.c_[x.ravel(), y.ravel()]
        xy = xy[shapely.contains_xy(poly, xy[:, 0], xy[:, 1])]
        # Independently specified planes: horizontal high edges at y=0,
        # y=10+.1*x and x=0. Their side intersection is allowed to slope.
        side_slopes = [.8, (3.2/7.)*np.sqrt(1.01)]
        planes = np.array([[0., -.8, 12.],
                           [-.1*3.2/7., 3.2/7., 12.-10.*3.2/7.],
                           [-np.mean(side_slopes), 0., 12.]])
        z = np.max(np.c_[xy, np.ones(len(xy))]@planes.T, axis=1)
        candidate = butterfly_proposal(poly, np.eye(2), [0., 20., 0., 11., 0., 0.],
            np.c_[xy, z], resolve_config())
        self.assertIsNotNone(candidate)
        self.assertFalse(candidate['evidence_rejections'])
        self.assertEqual(len(candidate['upper_planes']), 3)
        high = candidate['high_edge_height_m']
        anchors = candidate['butterfly']['wall_anchors']
        self.assertEqual(len(anchors), 3)
        for anchor, plane in zip(anchors, candidate['upper_planes']):
            self.assertEqual(anchor['source'], 'actual_dominant_wall')
            edge = np.asarray(anchor['line'])
            np.testing.assert_allclose(np.c_[edge, np.ones(len(edge))]@plane, high, atol=1e-8)
        self.assertLess(np.quantile(abs(predict(candidate, xy)-z), .9), .10)
        delta = np.asarray(candidate['upper_planes'][0])-candidate['upper_planes'][1]
        vx = np.array([7., 17.]); vy = -(delta[0]*vx+delta[2])/delta[1]
        vz = np.c_[vx, vy, np.ones(len(vx))]@candidate['upper_planes'][0]
        self.assertGreater(abs(vz[1]-vz[0]), .1)

    def test_candidate_can_be_disabled(self):
        poly, points = fixture()
        result = infer_eave_roof(poly, points, allow_flat=True, allow_networks=True,
            allow_pyramidal=True, config={'modules':{'butterfly':False}})
        self.assertFalse(any(c['type'] == 'butterfly' for c in result['candidates']))
        self.assertNotEqual(result['model']['type'], 'butterfly')


if __name__ == '__main__':
    unittest.main()
