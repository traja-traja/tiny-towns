"""A resource stop must resume without dropping or duplicating selected points."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import json
import tempfile
import unittest
from unittest.mock import patch
import laspy
import numpy as np
from shapely.geometry import box
import cb_roof_v2 as prep


class StreamResumeTests(unittest.TestCase):
    def test_stop_resume_and_source_identity(self):
        with tempfile.TemporaryDirectory(dir=prep.ROOT/'.work') as directory:
            folder = Path(directory)
            cloud = laspy.create(point_format=3,file_version='1.2')
            cloud.x = np.arange(20,dtype=float)
            cloud.y = np.ones(20)
            cloud.z = np.arange(20,dtype=float)+100
            cloud.classification = np.full(20,6,dtype=np.uint8)
            path = folder/'tiny.las'; cloud.write(path)
            source = {'tiles':[{'file':{'path':prep.rel(path)},
                'header':{'bounds':[[0,1,100],[19,1,119]],'point_count':20}}]}
            region = box(-1,0,20,2)
            with patch.object(prep,'CACHE',folder),patch.object(prep,'CHUNK',4),\
                 patch.object(prep.guard,'check_budget',return_value={}):
                with patch.object(prep,'resource_check',side_effect=[None,None,prep.guard.ResourceLimit('test stop')]):
                    with self.assertRaises(prep.guard.ResourceLimit):
                        prep.extract_stream(source,region)
                with np.load(folder/'stream-checkpoint.npz') as saved:
                    self.assertEqual(json.loads(str(saved['metadata']))['processed'],4)
                with patch.object(prep,'resource_check',return_value={}):
                    xyz,classes,visited = prep.extract_stream(source,region)
                    np.testing.assert_array_equal(xyz[:,0],np.arange(20))
                    self.assertEqual(len(classes),20)
                    self.assertEqual(len(visited),1)
                    self.assertEqual(prep.STREAM_RECOVERY['resumed_points'],4)
                    again,_,_ = prep.extract_stream(source,region)
                    np.testing.assert_array_equal(again,xyz)
                    with self.assertRaisesRegex(ValueError,'different source'):
                        prep.extract_stream(source,box(-2,0,20,2))


if __name__=='__main__':
    unittest.main()
