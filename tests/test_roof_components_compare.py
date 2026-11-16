import math
from pathlib import Path
import sys
import unittest

import numpy as np
from shapely.geometry import box, mapping

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from roof_components_compare import evaluate_components, subset_metrics


class ComponentEvaluationTests(unittest.TestCase):
    def model(self):
        return {'vertices':[[0,0,10],[10,0,10],[10,10,10],[0,10,10]],
                'faces':[[0,1,2],[0,2,3]],'face_semantics':['roof','roof']}

    def mask(self, identifier, status='accepted'):
        return {'id':identifier,'kind':'protrusion','status':status,
                'polygon':mapping(box(0,0,5,5))}

    def test_local_feature_error_is_separate_from_background(self):
        row={'model':self.model(),'metrics':{},'component_masks':[self.mask('tower')]}
        case={'test_relative':np.asarray([[2,2,14],[3,2,12],[8,8,10]],float)}
        evaluate_components(row,case)
        self.assertEqual(row['metrics']['feature_holdout_points'],2)
        self.assertAlmostEqual(row['metrics']['feature_holdout_rmse_m'],math.sqrt(10))
        self.assertEqual(row['metrics']['background_holdout_rmse_m'],0)

    def test_overlapping_masks_do_not_double_count_and_rejected_is_excluded(self):
        rejected=self.mask('not_a_tower','rejected')
        rejected['polygon']=mapping(box(6,6,10,10))
        row={'model':self.model(),'metrics':{},'component_masks':[
            self.mask('tower'),self.mask('overlap'),rejected]}
        case={'test_relative':np.asarray([[2,2,14],[8,8,10]],float)}
        evaluate_components(row,case)
        self.assertEqual(row['metrics']['feature_holdout_points'],1)
        self.assertEqual(row['metrics']['background_holdout_points'],1)
        self.assertEqual(len(row['component_evaluation']),3)

    def test_missing_predictions_are_not_zero_error(self):
        stats=subset_metrics(np.asarray([np.nan]),np.asarray([12.]),np.asarray([True]))
        self.assertEqual(stats['holdout_points'],1)
        self.assertEqual(stats['coverage_fraction'],0)
        self.assertIsNone(stats['rmse_m'])


if __name__=='__main__':
    unittest.main()
