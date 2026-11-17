import hashlib
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from shapely.geometry import box,mapping
from roof_config import resolve_config
from roof_input_refinement import refine_input_part


class RefinementInputTests(unittest.TestCase):
    def test_holdout_is_excluded_from_outline_decision_but_preserved_in_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'out';(out/'point-clouds').mkdir(parents=True)
            context=root/'context.npz'
            xyz=np.array([[1,1,4],[1.5,1.5,5],[4.5,2,4],[3,3,0]],float)
            np.savez_compressed(context,xyz=xyz,classification=np.array([6,6,6,2]),holdout=np.array([False,True,False,False]))
            digest=hashlib.sha256(context.read_bytes()).hexdigest()
            original=mapping(box(0,0,4,4))
            part=dict(footprint=original,origin_xy=[0,0],ground_z=0,
                context_cache=dict(path=str(context),sha256=digest,coordinate_reference='local_xy_relative_ground',
                    origin_xy=[0,0],ground_z=0,coverage_polygon=mapping(box(-1,-1,6,6))))
            with patch('roof_input_refinement.refine_footprint',return_value=(box(0,0,5,4),{'timing':{'total_seconds':.01}})) as refine:
                updated,train,metadata=refine_input_part(part,root,out,'part.npz',resolve_config())
            supplied=refine.call_args.args[1]
            self.assertEqual(len(supplied),3)
            self.assertFalse(np.any(np.all(supplied==xyz[1],axis=1)))
            self.assertEqual(len(train),2)
            with np.load(out/'point-clouds/part.npz') as saved:
                np.testing.assert_array_equal(saved['holdout'],xyz[1:2])
            self.assertEqual(updated['footprint'],original)
            self.assertEqual(hashlib.sha256(context.read_bytes()).hexdigest(),digest)
            self.assertTrue((out/updated['context_cache']['path']).is_file())
            self.assertEqual(metadata['effective_train_points'],2)

    def test_no_context_cannot_enable_outline_changes(self):
        with self.assertRaisesRegex(ValueError,'context_cache'):
            refine_input_part({},Path('.'),Path('.'),'unused.npz',resolve_config())


if __name__=='__main__':unittest.main()
