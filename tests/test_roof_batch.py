import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from roof_batch import compare_documents


class BatchComparisonTests(unittest.TestCase):
    def test_repeated_comparison_uses_only_latest_previous_parts(self):
        previous = {'comparison_mode':'level-ridge', 'buildings':[{'id':'a', 'parts':[
            {'part_index':0, 'result':{'algorithm':'obsolete'}},
            {'part_index':0, 'result':{'algorithm':'previous-current'}}]}]}
        current = {'buildings':[{'id':'a', 'parts':[{'part_index':0, 'result':{'algorithm':'new'}}]}]}
        untouched = copy.deepcopy(current)
        result = compare_documents(current, previous, 'old')
        self.assertEqual([p['result']['algorithm'] for p in result['buildings'][0]['parts']], ['previous-current','new'])
        self.assertEqual(current, untouched)

    def test_missing_previous_preserves_new_and_part_identity(self):
        current = {'buildings':[{'id':'new-only', 'parts':[{'part_index':2}, {'part_index':5}]}]}
        result = compare_documents(current, {'buildings':[]}, 'old')
        building = result['buildings'][0]
        self.assertFalse(building['comparison']['previous_available'])
        self.assertEqual([p['part_index'] for p in building['parts']], [2,5])
        self.assertTrue(all(p['display_offset_m']==[0.,0.,0.] for p in building['parts']))


if __name__ == '__main__':
    unittest.main()
