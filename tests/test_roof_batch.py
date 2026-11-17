import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from roof_batch import compare_documents, restore_checkpoint


class BatchResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        cache = b'frozen points'
        (self.folder/'points.npz').write_bytes(cache)
        self.part = {'part_index':0, 'footprint':[[0,0],[1,0],[0,1]], 'origin_xy':[0,0],
                     'ground_z':1, 'cache':{'path':'points.npz', 'sha256':hashlib.sha256(cache).hexdigest()}}
        self.selected = [{'id':'a', 'parts':[self.part]}, {'id':'b', 'parts':[self.part]}]
        self.run = {'algorithm':'test', 'input_manifest':'source', 'previous':'previous',
                    'configuration':{'split_volumes':True}, 'expected_buildings':2,
                    'source_code':{'roof_batch.py':'old-runner', 'roof_config.py':'same'}}
        for filename, data in [('run.json',self.run), ('results.json',{'buildings':self.selected[:1]}),
                               ('inputs.json',{'buildings':self.selected[:1]})]:
            (self.folder/filename).write_text(json.dumps(data), encoding='utf-8')

    def test_saved_prefix_can_resume_after_runner_fix(self):
        expected = copy.deepcopy(self.run)
        expected['source_code']['roof_batch.py'] = 'new-runner'
        run, document, _ = restore_checkpoint(self.folder, expected, self.selected)
        self.assertEqual(len(document['buildings']), 1)
        self.assertEqual(run['resumes'][-1]['skipped_buildings'], 1)

    def test_changed_numerical_code_is_rejected(self):
        expected = copy.deepcopy(self.run)
        expected['source_code']['roof_config.py'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'algorithm changed'):
            restore_checkpoint(self.folder, expected, self.selected)

    def test_changed_geometry_and_damaged_cache_are_rejected(self):
        changed = copy.deepcopy(self.selected)
        changed[0]['parts'][0]['ground_z'] = 2
        with self.assertRaisesRegex(ValueError, 'input changed'):
            restore_checkpoint(self.folder, self.run, changed)
        (self.folder/'points.npz').write_bytes(b'damaged')
        with self.assertRaisesRegex(ValueError, 'cache damaged'):
            restore_checkpoint(self.folder, self.run, self.selected)


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
