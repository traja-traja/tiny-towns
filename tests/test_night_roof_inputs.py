"""Queue, provenance and interrupted point-spool behavior for unattended runs."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
import laspy
from shapely.geometry import box, mapping
import night_roof_inputs as night


class NightInputTests(unittest.TestCase):
    def test_user_streets_are_first_and_case_punctuation_do_not_matter(self):
        self.assertEqual(night.stage_for('velesin',['NÁMĚSTÍ J V KAMARÝTA']),('streets',0))
        self.assertEqual(night.stage_for('velesin',['Školní']),('streets',2))
        self.assertEqual(night.stage_for('velesin',[]),('city',4))
        self.assertEqual(night.stage_for('ceske-budejovice',['nám. Přemysla Otakara II.']),('centre',0))
        self.assertEqual(night.stage_for('ceske-budejovice',['Jírovcova']),('extra',10))

    def test_reuse_requires_same_global_footprint(self):
        feature={'geometry':mapping(box(100,200,110,210))}
        item={'parts':[{'status':'prepared','footprint':mapping(box(-5,-5,5,5)),'origin_xy':[105,205]}]}
        self.assertTrue(night.compatible_crop(feature,item))
        item['parts'][0]['origin_xy'][0]+=1
        self.assertFalse(night.compatible_crop(feature,item))

    def test_spool_resume_discards_only_uncommitted_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            (folder/'a.bin').write_bytes(b'committedtail')
            (folder/'b.bin').write_bytes(b'uncommitted')
            night.restore_spool(folder,{'a.bin':9})
            self.assertEqual((folder/'a.bin').read_bytes(),b'committed')
            self.assertEqual((folder/'b.bin').stat().st_size,0)
            with self.assertRaises(ValueError):night.restore_spool(folder,{'a.bin':20})

    def test_no_roof_points_are_synthesized(self):
        with tempfile.TemporaryDirectory(dir=night.ROOT/'.work') as temporary:
            directory=Path(temporary);spool=directory/'spool';spool.mkdir()
            feature={'id':'test-house','geometry':mapping(box(0,0,10,10)),
                     'properties':{'name':'test','stage':'city'}}
            raw=np.zeros(6,dtype=night.RAW_DTYPE)
            raw['x']=[-2,-2,-2,12,12,12];raw['y']=[2,5,8,2,5,8];raw['z']=100;raw['c']=2
            raw.tofile(spool/'test-house.bin')
            with patch.object(night.guard,'check_budget',return_value={}):
                result=night.finish_building(feature,spool,directory/'point-clouds')
            self.assertEqual(result['parts'][0]['status'],'no_roof_points')
            self.assertEqual(result['parts'][0]['ground_z'],100)
            cache=night.ROOT/result['parts'][0]['cache']['path']
            with np.load(cache) as data:self.assertEqual(len(data['train'])+len(data['holdout']),0)

    def test_roof_points_and_ground_datum_are_preserved(self):
        with tempfile.TemporaryDirectory(dir=night.ROOT/'.work') as temporary:
            directory=Path(temporary);spool=directory/'spool';spool.mkdir()
            feature={'id':'test-house','geometry':mapping(box(0,0,10,10)),
                     'properties':{'name':'test','stage':'city'}}
            raw=np.zeros(10,dtype=night.RAW_DTYPE)
            raw['x']=[-2,-2,-2,12,12,12,2,3,4,5];raw['y']=[2,5,8,2,5,8,2,3,4,5]
            raw['z']=[100]*6+[110,111,112,113];raw['c']=[2]*6+[6]*4
            raw.tofile(spool/'test-house.bin')
            with patch.object(night.guard,'check_budget',return_value={}):result=night.finish_building(feature,spool,directory/'point-clouds')
            part=result['parts'][0]
            self.assertEqual(part['status'],'prepared')
            with np.load(night.ROOT/part['cache']['path']) as data:
                all_points=np.concatenate([data['train'],data['holdout']])
            self.assertEqual(sorted(all_points[:,2]),[10,11,12,13])

    def test_serial_las_resume_matches_uninterrupted_crop(self):
        with tempfile.TemporaryDirectory(dir=night.ROOT/'.work') as temporary:
            directory=Path(temporary);path=directory/'small.las'
            data=laspy.LasData(laspy.LasHeader(point_format=1,version='1.2'))
            data.x=np.arange(30)/10+1;data.y=np.ones(30)*2;data.z=np.arange(30)+110
            data.classification=np.ones(30,dtype=np.uint8)*6;data.write(path)
            tile={'sheet':'test','file':{'path':night.prep.rel(path),'bytes':path.stat().st_size},
                  'header':{'bounds':[[0,0,0],[10,10,200]]}}
            features=[{'id':'house','geometry':mapping(box(0,0,10,10))}]
            with patch.object(night.prep,'CHUNK',10),patch.object(night.prep,'resource_check'),patch.object(night.guard,'check_budget',return_value={}):
                with patch.object(night,'expired',side_effect=[False,False,True]):
                    complete,state=night.stream_crops(features,[tile],directory/'resumed',123)
                self.assertFalse(complete);self.assertEqual(state['processed'],20)
                with (directory/'resumed/spool/house.bin').open('ab') as out:out.write(b'uncommitted')
                complete,state=night.stream_crops(features,[tile],directory/'resumed')
                self.assertTrue(complete)
                night.stream_crops(features,[tile],directory/'direct')
            self.assertEqual((directory/'resumed/spool/house.bin').read_bytes(),
                             (directory/'direct/spool/house.bin').read_bytes())


if __name__=='__main__':unittest.main()
