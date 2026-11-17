"""Integration: add measured blocks without changing base roof decisions."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from shapely.geometry import box, shape, mapping
from roof_annex import infer_modular_roof, _finish_flat_protrusions
from roof_config import resolve_config


class FlatProtrusionPipelineTests(unittest.TestCase):
    def scene(self):
        x,y=np.meshgrid(np.arange(.175,20,.35),np.arange(.175,14,.35))
        points=np.c_[x.ravel(),y.ravel(),np.full(x.size,12.)]
        mask=(points[:,0]>7)&(points[:,0]<10)&(points[:,1]>5)&(points[:,1]<8)
        points[mask,2]=16.
        return box(0,0,20,14),points

    def test_raised_block_keeps_base_and_closes_vertical_walls(self):
        poly,points=self.scene()
        result=infer_modular_roof(poly,points)
        model=result['model']
        self.assertEqual(model['type'],'flat')
        self.assertEqual(model['metadata']['protrusion_count'],1)
        self.assertEqual(model['metadata']['flat_base_height_m'],12.)
        self.assertEqual(model['height_range_m'],[12.,16.])
        self.assertEqual(result['diagnostics']['flat_protrusions']['status'],'added')
        self.assertTrue(model['mesh']['diagnostics']['watertight'])
        self.assertAlmostEqual(model['mesh']['diagnostics']['coverage_fraction'],1.)
        self.assertGreater(model['mesh']['diagnostics']['height_step_edge_count'],0)
        self.assertGreater(result['timing']['flat_protrusions_detection_seconds'],0.)

    def test_switch_disables_blocks_and_restores_one_plane(self):
        poly,points=self.scene()
        result=infer_modular_roof(poly,points,{'modules':{'flat_protrusions':False}})
        self.assertEqual(result['model']['height_range_m'],[12.,12.])
        self.assertEqual(result['model']['metadata']['protrusion_count'],0)
        self.assertEqual(result['diagnostics']['flat_protrusions']['status'],'disabled')

    def test_pitched_roof_does_not_run_flat_block_detector(self):
        poly,points=self.scene()
        points[:,2]=10.+.6*np.minimum(points[:,1],14-points[:,1])
        with patch('roof_annex.detect_flat_protrusions') as detector:
            result=infer_modular_roof(poly,points,{'modules':{'flat':False,'annex_detection':False}})
        detector.assert_not_called()
        self.assertNotEqual(result['model']['type'],'flat')
        self.assertEqual(result['diagnostics']['flat_protrusions']['status'],'skipped_non_flat_base')

    def test_invalid_assembly_preserves_the_original_base_mesh(self):
        poly,points=self.scene()
        baseline=infer_modular_roof(poly,points,{'modules':{'flat_protrusions':False}})
        before=copy.deepcopy(baseline['model'])
        with patch('roof_annex.build_mesh',side_effect=ValueError('synthetic assembly rejection')):
            result=_finish_flat_protrusions(baseline,poly,points,resolve_config())
        self.assertEqual(result['model'],before)
        self.assertEqual(result['diagnostics']['flat_protrusions']['accepted_count'],0)
        self.assertEqual(result['diagnostics']['flat_protrusions']['status'],'geometry_fallback')

    def test_custom_height_threshold_is_respected(self):
        poly,points=self.scene()
        result=infer_modular_roof(poly,points,{'flat_protrusions':{'min_height_m':5.}})
        self.assertEqual(result['model']['height_range_m'],[12.,12.])
        self.assertEqual(result['model']['metadata']['protrusion_count'],0)


if __name__=='__main__':
    unittest.main()
