"""Simplifying a roof must preserve its supported long horizontal eaves."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))

import numpy as np
from shapely.geometry import box, mapping, shape
from shapely.affinity import rotate
from roof_config import resolve_config
from roof_connected_wings import _envelope
from roof_eave_planes import _guard_main_eave_simplification


def example():
    poly = box(0, 0, 30, 8).union(box(0, 0, 8, 30))
    tents = [np.array([[0., 1., 0.], [0., -1., 8.], [1., 0., 0.], [-1., 0., 30.]]),
             np.array([[1., 0., 0.], [-1., 0., 8.], [0., 1., 0.], [0., -1., 30.]])]
    regions = _envelope(poly, tents)
    for region in regions:
        region['plane'][2] += 10.
    best = {'kind':'connected_wings', 'score':.3, '_regions':regions,
            'branch_support':[{'wing_index':i, 'nearby_cells':40, 'supported_cells':38} for i in range(2)],
            'connected_wings':{'wing_frames_xy':[[[1., 0.], [0., 1.]], [[0., -1.], [1., 0.]]],
                               'wing_eaves_m':[10., 10.], 'settings':{}}}
    return poly, best


def tilted(best, gradient=(.06, .02), offset=0.):
    candidate = copy.deepcopy(best)
    candidate.update(kind='bent', score=.38)
    for region in candidate['_regions']:
        region['plane'] = (np.array(region['plane'])+[*gradient, offset]).tolist()
    return candidate


class MainEaveProtectionTests(unittest.TestCase):
    def setUp(self):
        self.scoring = resolve_config()['scoring']

    def test_warped_main_eaves_cannot_win_only_by_simplicity(self):
        poly, best = example(); alternative = tilted(best)
        near, meta = _guard_main_eave_simplification(poly, best, [best, alternative], self.scoring)
        self.assertEqual(len(near), 1)
        self.assertIs(near[0], best)
        self.assertGreaterEqual(len(meta['reference_edges']), 2)
        self.assertEqual(alternative['simplification_guard']['reason'], 'main_eave_deformation')
        # It remains a scored fallback; it is not incorrectly marked invalid.
        self.assertNotIn('rejected', alternative)

    def test_small_simplification_and_uniform_height_shift_are_allowed(self):
        poly, best = example(); alternative = tilted(best, (.003, .002), .15)
        near, meta = _guard_main_eave_simplification(poly, best, [best, alternative], self.scoring)
        self.assertEqual(len(near), 2)
        self.assertFalse(meta['candidates_not_promoted'])

    def test_no_protection_without_ridge_evidence(self):
        poly, best = example(); best['branch_support'] = []
        alternative = tilted(best)
        near, meta = _guard_main_eave_simplification(poly, best, [best, alternative], self.scoring)
        self.assertEqual(len(near), 2)
        self.assertFalse(meta['reference_edges'])

    def test_switch_off_restores_existing_simplicity_policy(self):
        poly, best = example(); alternative = tilted(best)
        cfg = {**self.scoring, 'protect_main_eaves':False}
        near, meta = _guard_main_eave_simplification(poly, best, [best, alternative], cfg)
        self.assertEqual(len(near), 2)
        self.assertFalse(meta['enabled'])

    def test_gable_sides_are_not_horizontal_eave_references(self):
        poly = box(0, 0, 30, 8)
        regions = _envelope(poly, [np.array([[0., 1., 0.], [0., -1., 8.]])])
        for region in regions:
            region['plane'][2] += 10.
        _, best = example()
        best['_regions'] = regions
        best['branch_support'] = best['branch_support'][:1]
        near, meta = _guard_main_eave_simplification(poly, best, [best], self.scoring)
        self.assertEqual(len(meta['reference_edges']), 2)
        for edge in meta['reference_edges']:
            a, b = np.array(edge['xy'])
            self.assertAlmostEqual(a[1], b[1])
            self.assertGreater(abs(a[0]-b[0]), 29.)

    def test_remote_parallel_wings_do_not_protect_a_local_gable(self):
        poly, best = example()
        best['connected_wings']['wing_domains_xy'] = [mapping(box(100,100,130,108)), mapping(box(100,100,108,130))]
        alternative = tilted(best)
        near, meta = _guard_main_eave_simplification(poly, best, [best, alternative], self.scoring)
        self.assertEqual(len(near), 2)
        self.assertEqual(meta['reference_edges'], [])

    def test_horizontal_filler_is_not_eave_evidence(self):
        poly, best = example()
        best['_regions'] = [{'polygon':mapping(poly), 'plane':[0.,0.,10.]}]
        alternative = tilted(best)
        near, meta = _guard_main_eave_simplification(poly, best, [best, alternative], self.scoring)
        self.assertEqual(len(near), 2)
        self.assertEqual(meta['reference_edges'], [])

    def test_verified_gable_replaces_only_its_own_low_end(self):
        poly, best = example()
        alternative = copy.deepcopy(best)
        alternative['score'] = .35
        tents = [np.array([[0.,1.,0.],[0.,-1.,8.],[1.,0.,0.]]),
                 np.array([[1.,0.,0.],[-1.,0.,8.],[0.,1.,0.],[0.,-1.,30.]])]
        alternative['_regions'] = _envelope(poly, tents)
        for region in alternative['_regions']:
            region['plane'][2] += 10.
        near, _ = _guard_main_eave_simplification(poly, best, [best, alternative], self.scoring)
        self.assertEqual(len(near), 1)
        # End evidence on another facade cannot excuse the changed end.
        alternative['connected_wings']['accepted_gable_edges'] = [{'supported':True,'edge_xy':[[0.,0.],[0.,8.]]}]
        near, _ = _guard_main_eave_simplification(poly, best, [best, alternative], self.scoring)
        self.assertEqual(len(near), 1)
        alternative['connected_wings']['accepted_gable_edges'] = [{'supported':True,'edge_xy':[[30.,0.],[30.,8.]]}]
        near, meta = _guard_main_eave_simplification(poly, best, [best, alternative], self.scoring)
        self.assertEqual(len(near), 2)
        self.assertTrue(meta['supported_gable_exemptions'])

    def test_rotating_the_roof_preserves_the_decision(self):
        poly, best = example(); bad = tilted(best)
        angle = np.deg2rad(37.)
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        poly = rotate(poly, 37., origin=(0, 0))
        for candidate in [best, bad]:
            for region in candidate['_regions']:
                region['polygon'] = mapping(rotate(shape(region['polygon']), 37., origin=(0, 0)))
                plane = region['plane']
                region['plane'] = [*(rotation@plane[:2]), plane[2]]
            candidate['connected_wings']['wing_frames_xy'] = [(rotation@np.array(frame)).tolist()
                for frame in candidate['connected_wings']['wing_frames_xy']]
        near, meta = _guard_main_eave_simplification(poly, best, [best, bad], self.scoring)
        self.assertEqual(len(near), 1)
        self.assertGreaterEqual(len(meta['reference_edges']), 2)


if __name__ == '__main__':
    unittest.main()
