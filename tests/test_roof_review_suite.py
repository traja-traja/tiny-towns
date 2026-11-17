import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from roof_review_suite import prepare_suite

class ReviewSuiteTests(unittest.TestCase):
    def source(self,base,name,ids):
        folder=base/name;folder.mkdir();data=b'frozen-test-cache'
        (folder/'points.npz').write_bytes(data)
        cache={'path':'points.npz','sha256':hashlib.sha256(data).hexdigest()}
        buildings=[{'id':oid,'address':oid,'parts':[{'part_index':0,'footprint':{},'cache':dict(cache)}]} for oid in ids]
        header={'source':'synthetic','crs':'test','vertical_datum':'test'}
        (folder/'inputs.json').write_text(json.dumps({**header,'cache_path_base':'manifest_directory','buildings':buildings}))
        (folder/'results.json').write_text(json.dumps({**header,'algorithm':name,'buildings':buildings}))
        (folder/'source_records.json').write_text(json.dumps({oid:{'source':name} for oid in ids}))
        return folder
    def test_latest_override_retains_other_houses_and_real_cache_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);old=self.source(base,'old',['a','b']);new=self.source(base,'new',['a','c']);out=base/'out'
            inputs,previous=prepare_suite([old,new],out)
            self.assertEqual([b['id'] for b in inputs['buildings']],['a','b','c'])
            self.assertEqual(previous['buildings'][0]['parts'][0]['previous_source_run'],'new')
            self.assertEqual(Path(inputs['buildings'][0]['parts'][0]['cache']['path']),new/'points.npz')
            self.assertEqual(json.loads((out/'source_records.json').read_text())['b']['source'],'old')
            self.assertFalse(Path(json.loads((old/'inputs.json').read_text())['buildings'][0]['parts'][0]['cache']['path']).is_absolute())
    def test_mutated_frozen_input_fails_before_output_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);old=self.source(base,'old',['a']);(old/'points.npz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):prepare_suite([old],base/'out')
            self.assertFalse((base/'out').exists())

if __name__=='__main__':unittest.main()
