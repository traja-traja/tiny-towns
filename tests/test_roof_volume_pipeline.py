import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from shapely.geometry import box,mapping
from roof_volume_pipeline import infer_volume_roof, _select_volume_variant, _variant_support_penalty

POLY=box(0,0,10,10)
POINTS=np.array([[x,y,5.] for x in range(1,10) for y in range(1,10)])
def model(z):
    return dict(algorithm='fixture',model=dict(type='gabled',regions=[{'polygon':mapping(POLY),'plane':[0,0,z]}],metadata={}),
        timing={'total_seconds':.01},diagnostics={})
def detection():
    return dict(candidates=[{'footprints':[mapping(box(0,0,5,10)),mapping(box(5,0,10,10))]}],
        counts={},timing={'total_seconds':.01},settings={})

class VolumePipelineTests(unittest.TestCase):
    def test_flat_majority_does_not_bypass_volume_eligibility(self):
        whole=model(5)
        whole['model']['type']='flat'
        whole['diagnostics']['flat_majority']={'accepted':True}
        checked=detection();checked['candidates']=[]
        with patch('roof_volume_pipeline.infer_modular_roof',return_value=whole),patch('roof_volume_pipeline.detect_longitudinal_split',return_value=checked) as detect:
            result=infer_volume_roof(POLY,POINTS)
        detect.assert_called_once()
        self.assertEqual(result['model']['metadata']['volume_count'],1)
    def test_equal_fit_keeps_one_volume(self):
        with patch('roof_volume_pipeline.infer_modular_roof',return_value=model(5)),patch('roof_volume_pipeline.detect_longitudinal_split',return_value=detection()),patch('roof_volume_pipeline.fit_partition',return_value=model(5)):
            r=infer_volume_roof(POLY,POINTS)
        self.assertEqual(r['model']['metadata']['volume_count'],1)
        self.assertEqual(r['model']['metadata']['volume_decision']['selected_variant'],'whole')
    def test_supported_better_split_returns_children_without_recursion(self):
        child=model(5);split=model(5);split['_child_results']=[child,child]
        with patch('roof_volume_pipeline.infer_modular_roof',return_value=model(4)) as whole,patch('roof_volume_pipeline.detect_longitudinal_split',return_value=detection()) as detect,patch('roof_volume_pipeline.fit_partition',return_value=split) as fit:
            r=infer_volume_roof(POLY,POINTS)
        self.assertEqual((whole.call_count,detect.call_count,fit.call_count),(1,1,1))
        self.assertEqual(r['model']['metadata']['volume_count'],2)
        self.assertEqual(len(r['_child_results']),2)
        self.assertEqual(r['model']['metadata']['volume_decision']['counts']['child_split_calls'],0)
    def test_invalid_candidate_preserves_valid_whole_roof(self):
        with patch('roof_volume_pipeline.infer_modular_roof',return_value=model(5)),patch('roof_volume_pipeline.detect_longitudinal_split',return_value=detection()),patch('roof_volume_pipeline.fit_partition',side_effect=ValueError('invalid mesh')):
            r=infer_volume_roof(POLY,POINTS)
        self.assertEqual(r['model']['metadata']['volume_count'],1)
        self.assertIn('split_1',r['model']['metadata']['volume_decision']['candidate_errors'])

class VolumeSelectionSimplicityTests(unittest.TestCase):
    def score(self,value):
        return {'score':value}

    def test_small_improvement_keeps_one_body(self):
        # A flexible split has already paid the 0.10 m volume penalty.
        # Its remaining 0.07 m gain is below the simplicity tolerance.
        scores={k:self.score(v) for k,v in {'whole':.42,'split_1':.35}.items()}
        selected,decision=_select_volume_variant(scores,{'settings':{},'candidates':[]})
        self.assertEqual(selected,'whole')
        self.assertEqual(decision['raw_best_variant'],'split_1')
        self.assertAlmostEqual(decision['best_split_penalized_gain_m'],.07)
        self.assertEqual(decision['reason'],'prefer_whole_model_within_simplification_tolerance')

    def test_clear_improvement_keeps_split(self):
        scores={k:self.score(v) for k,v in {'whole':.9,'split_1':.4}.items()}
        selected,decision=_select_volume_variant(scores,{'settings':{},'candidates':[]})
        self.assertEqual(selected,'split_1')
        self.assertAlmostEqual(decision['best_split_penalized_gain_m'],.5)

    def test_tolerance_is_configurable_and_exact_boundary_prefers_whole(self):
        scores={k:self.score(v) for k,v in {'whole':.5,'split_1':.4}.items()}
        self.assertEqual(_select_volume_variant(scores,{'settings':{}})[0],'whole')
        self.assertEqual(_select_volume_variant(scores,{'settings':{'whole_selection_tolerance_m':0}})[0],'split_1')

    def test_wall_snap_cannot_turn_clear_split_into_near_tie(self):
        scores={k:self.score(v) for k,v in {'whole':.5,'split_1':.39,'split_2':.41}.items()}
        detection={'settings':{},'candidates':[{}, {'snapping':{'applied':True}}]}
        self.assertEqual(_select_volume_variant(scores,detection)[0],'split_1')
        scores['whole']['score']=.7
        self.assertEqual(_select_volume_variant(scores,detection)[0],'split_2')


class FootprintConnectorPipelineTests(unittest.TestCase):
    def accepted(self):
        return dict(accepted=True,reason='strict_test_neck',settings={},counts={},timing={'total_seconds':.002},
            candidates=[{'footprints':[mapping(box(0,0,3,10)),mapping(box(3,0,6,10)),mapping(box(6,0,10,10))]}])

    def test_strict_shape_partition_skips_whole_and_height_profiles(self):
        fitted=model(5);fitted['_child_results']=[model(5) for _ in range(3)]
        with patch('roof_volume_pipeline.detect_footprint_connector',return_value=self.accepted()), \
             patch('roof_volume_pipeline.infer_modular_roof') as whole, \
             patch('roof_volume_pipeline.detect_longitudinal_split') as profiles, \
             patch('roof_volume_pipeline.fit_partition',return_value=fitted) as fit:
            r=infer_volume_roof(POLY,POINTS)
        whole.assert_not_called();profiles.assert_not_called();fit.assert_called_once()
        self.assertEqual(r['model']['metadata']['volume_count'],3)
        c=r['model']['metadata']['volume_decision']['counts']
        self.assertEqual((c['geometry_cuts_applied'],c['child_split_calls'],c['child_roof_fits']),(2,0,3))
        self.assertFalse(fit.call_args.kwargs['config']['modules']['footprint_connector'])
        self.assertEqual(r['timing']['whole_roof_seconds'],0.)
        self.assertEqual(r['timing']['longitudinal_detection_seconds'],0.)

    def test_strict_shape_may_return_two_bodies_without_forcing_corridor(self):
        proposal=self.accepted()
        proposal['candidates']=[{'footprints':[mapping(box(0,0,5,10)),mapping(box(5,0,10,10))]}]
        fitted=model(5);fitted['_child_results']=[model(5),model(5)]
        with patch('roof_volume_pipeline.detect_footprint_connector',return_value=proposal), \
             patch('roof_volume_pipeline.infer_modular_roof') as whole, \
             patch('roof_volume_pipeline.detect_longitudinal_split') as profiles, \
             patch('roof_volume_pipeline.fit_partition',return_value=fitted):
            r=infer_volume_roof(POLY,POINTS)
        whole.assert_not_called();profiles.assert_not_called()
        c=r['model']['metadata']['volume_decision']['counts']
        self.assertEqual((c['selected_volume_count'],c['geometry_cuts_applied'],c['child_roof_fits']),(2,1,2))

    def test_invalid_partition_falls_back_to_original_detection(self):
        checked=detection();checked['candidates']=[]
        with patch('roof_volume_pipeline.detect_footprint_connector',return_value=self.accepted()), \
             patch('roof_volume_pipeline.infer_modular_roof',return_value=model(5)) as whole, \
             patch('roof_volume_pipeline.detect_longitudinal_split',return_value=checked) as profiles, \
             patch('roof_volume_pipeline.fit_partition',side_effect=ValueError('invalid mesh')):
            r=infer_volume_roof(POLY,POINTS)
        whole.assert_called_once();profiles.assert_called_once()
        self.assertEqual(r['model']['metadata']['volume_count'],1)
        self.assertIn('footprint_connector',r['model']['metadata']['volume_decision']['candidate_errors'])

    def test_unsupported_child_preserves_profile_fallback(self):
        checked=detection();checked['candidates']=[]
        sparse=POINTS[POINTS[:,0]<6]
        with patch('roof_volume_pipeline.detect_footprint_connector',return_value=self.accepted()), \
             patch('roof_volume_pipeline.infer_modular_roof',return_value=model(5)), \
             patch('roof_volume_pipeline.detect_longitudinal_split',return_value=checked) as profiles, \
             patch('roof_volume_pipeline.fit_partition') as fit:
            r=infer_volume_roof(POLY,sparse)
        profiles.assert_called_once();fit.assert_not_called()
        self.assertEqual(r['diagnostics']['volume_detection']['footprint_connector']['fallback_reason'],
                         'insufficient_roof_cells_in_partition')

    def test_module_off_preserves_existing_route(self):
        checked=detection();checked['candidates']=[]
        with patch('roof_volume_pipeline.detect_footprint_connector') as connector, \
             patch('roof_volume_pipeline.infer_modular_roof',return_value=model(5)), \
             patch('roof_volume_pipeline.detect_longitudinal_split',return_value=checked) as profiles:
            infer_volume_roof(POLY,POINTS,config={'modules':{'footprint_connector':False}})
        connector.assert_not_called();profiles.assert_called_once()

class VolumeSupportPenaltyTests(unittest.TestCase):
    def child(self,penalty):
        r=model(5);r['candidates']=[dict(selected=True,support_penalty_m=penalty),
            dict(selected=False,support_penalty_m=50.)]
        return r
    def test_selected_penalties_are_area_weighted_not_summed(self):
        split=model(5);split['_child_results']=[self.child(.2),self.child(0.)]
        split['model']['metadata']['bodies']=[dict(area_m2=75.),dict(area_m2=25.)]
        self.assertAlmostEqual(_variant_support_penalty(split),.15)
        self.assertAlmostEqual(_variant_support_penalty(self.child(.1)),.1)
    def test_split_does_not_bypass_uncertain_roof_penalty(self):
        for enabled,expected in ((True,1),(False,2)):
            split=model(5);split['_child_results']=[self.child(.3),self.child(.3)]
            with patch('roof_volume_pipeline.infer_modular_roof',return_value=model(4.6)), \
                 patch('roof_volume_pipeline.detect_longitudinal_split',return_value=detection()), \
                 patch('roof_volume_pipeline.fit_partition',return_value=split):
                r=infer_volume_roof(POLY,POINTS,config={'scoring':{'volume_inherit_support_penalty':enabled}})
            self.assertEqual(r['model']['metadata']['volume_count'],expected)
            score=r['model']['metadata']['volume_decision']['scores']['split_1']
            self.assertAlmostEqual(score['roof_support_penalty_m'],.3 if enabled else 0.)

if __name__=='__main__':unittest.main()
