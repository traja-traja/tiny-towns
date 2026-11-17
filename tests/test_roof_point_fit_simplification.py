"""Simplicity must not hide a large regression in the measured point fit."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from roof_config import resolve_config
from roof_eave_planes import _guard_point_fit_simplification

class PointFitSimplicityTests(unittest.TestCase):
    def setUp(self):
        self.cfg=resolve_config()['scoring']
    def candidate(self,kind,error,score,planes):
        return dict(kind=kind,data_error_m=error,score=score,plane_count=planes,candidate_label=kind)
    def test_cheaper_simple_roof_cannot_spend_score_tolerance_on_large_fit_loss(self):
        measured=self.candidate('straight_skeleton',.54,.656,10)
        simple=self.candidate('straight',.70,.747,3)
        near,meta=_guard_point_fit_simplification(measured,[measured,simple],self.cfg)
        self.assertEqual(near,[measured])
        self.assertAlmostEqual(meta['candidates_not_promoted'][0]['increase_m'],.16)
        self.assertNotIn('rejected',simple)
    def test_rule_is_independent_of_roof_family(self):
        measured=self.candidate('connected_wings',.2,.3,6)
        simple=self.candidate('straight_skeleton',.36,.39,3)
        near,_=_guard_point_fit_simplification(measured,[measured,simple],self.cfg)
        self.assertEqual(near,[measured])
    def test_small_loss_at_limit_can_still_simplify(self):
        measured=self.candidate('straight_skeleton',.54,.656,10)
        simple=self.candidate('straight',.64,.687,3)
        near,meta=_guard_point_fit_simplification(measured,[measured,simple],self.cfg)
        self.assertEqual(near,[measured,simple])
        self.assertFalse(meta['candidates_not_promoted'])
    def test_configuration_can_restore_previous_policy(self):
        measured=self.candidate('straight_skeleton',.54,.656,10)
        simple=self.candidate('straight',.70,.747,3)
        cfg={**self.cfg,'protect_point_fit':False}
        near,meta=_guard_point_fit_simplification(measured,[measured,simple],cfg)
        self.assertEqual(near,[measured,simple])
        self.assertFalse(meta['enabled'])
    def test_better_point_fit_is_never_blocked(self):
        measured=self.candidate('straight_skeleton',.54,.656,10)
        alternative=self.candidate('straight',.50,.69,3)
        near,_=_guard_point_fit_simplification(measured,[measured,alternative],self.cfg)
        self.assertEqual(near,[measured,alternative])
if __name__=='__main__':unittest.main()
