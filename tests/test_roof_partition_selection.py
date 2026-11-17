import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from roof_volume_pipeline import _select_volume_variant

class PartitionSelectionTests(unittest.TestCase):
    def select(self,whole,raw,aligned,tolerance=.03):
        scores={name:{'score':value} for name,value in [('whole',whole),('split_1',raw),('split_2',aligned)]}
        detection={'settings':{'snap_selection_tolerance_m':tolerance},'candidates':[{'snapping':{'applied':False}},{'snapping':{'applied':True}}]}
        return _select_volume_variant(scores,detection)
    def test_near_equal_fit_prefers_measured_original_edge(self):
        selected,info=self.select(.9,.25,.257)
        self.assertEqual(selected,'split_2')
        self.assertEqual(info['raw_best_variant'],'split_1')
        self.assertAlmostEqual(info['score_increase_m'],.007)
    def test_worse_aligned_cut_cannot_displace_better_fit(self):
        self.assertEqual(self.select(.9,.25,.31)[0],'split_1')
    def test_never_turn_whole_winner_into_two_volumes(self):
        self.assertEqual(self.select(.24,.25,.257)[0],'whole')
    def test_tolerance_zero_restores_strict_score_order(self):
        self.assertEqual(self.select(.9,.25,.257,0)[0],'split_1')
    def test_invalid_snapped_candidate_is_not_selected(self):
        scores={'whole':{'score':.9},'split_1':{'score':.25}}
        detection={'candidates':[{}, {'snapping':{'applied':True}}]}
        self.assertEqual(_select_volume_variant(scores,detection)[0],'split_1')

if __name__=='__main__':unittest.main()
