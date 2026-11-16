"""City routing must not mix source records or labels between CB and Velesin."""
import contextlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from shapely.geometry import Point, box
import cb_roof_v2 as prep
import roof_address_inputs as address_inputs
import roof_batch


class RoofCityInputsTests(unittest.TestCase):
    def tearDown(self):
        prep.configure_city()

    def test_address_cli_reads_velesin_data_all_and_preserves_city(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / '.work/.preview/velesin/data_all'
            data.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist([{
                'id': 'vel-building', 'geometry': shapely.to_wkb(box(14.46, 48.83, 14.461, 48.831)),
                'is_underground': False,
            }]), data / 'building.parquet')
            pq.write_table(pa.Table.from_pylist([{
                'street': 'Školní', 'number': '521', 'unit': None,
                'geometry': shapely.to_wkb(Point(14.4605, 48.8305)),
            }]), data / 'address.parquet')
            requests = root / 'requests.json'
            requests.write_text(json.dumps([{'street': 'Školní', 'number': '521'}]), encoding='utf-8')
            output = root / 'inputs'
            captured = {}

            def fake_prepare(sample, destination):
                captured.update(sample)
                return {'city': sample['city'], 'buildings': [{'id': sample['features'][0]['id']}]}

            source = {'tiles': [{'header': {'bounds': [[-2000000, -2000000], [0, 0]]}}]}
            with patch.object(prep, 'ROOT', root), patch.object(prep, 'prepare', side_effect=fake_prepare), \
                 patch.object(prep, 'source_inventory', return_value=({}, source)), \
                 patch.object(prep, 'resource_check', return_value={}), \
                 patch.object(prep.guard, 'check_budget', return_value={}), \
                 patch.object(prep.guard, 'keep_awake', side_effect=contextlib.nullcontext):
                address_inputs.main(['--city', 'velesin', '--requests', str(requests), '--output', str(output)])
                self.assertEqual(prep.SOURCE_MANIFEST, root / '.work/roof-pilot/sources/sources.json')
                self.assertEqual(prep.PILOT_SAMPLE, root / 'cities/velesin/roof-pilot/sample.json')
                with self.assertRaisesRegex(ValueError, 'CB-only'):
                    prep.make_sample()
                self.assertEqual(captured['city'], 'velesin')
                self.assertEqual(captured['features'][0]['id'], 'vel-building')
                self.assertEqual(json.loads((output / 'inputs.json').read_text())['city'], 'velesin')
                prep.configure_city()
                self.assertEqual(prep.DATA, root / '.work/.preview/ceske-budejovice/data')
                self.assertEqual(prep.SOURCE_MANIFEST, root / '.work/cb-roof-pilot/sources/sources.json')

    def test_prepare_attributes_city_and_rejects_cross_city_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(prep, 'ROOT', root), \
                 patch.object(prep, 'source_inventory', return_value=({}, {'tiles': []})), \
                 patch.object(prep, 'resource_check', return_value={}), \
                 patch.object(prep.guard, 'check_budget', return_value={}):
                prep.configure_city('velesin')
                prep.PILOT_SAMPLE.parent.mkdir(parents=True)
                prep.PILOT_SAMPLE.write_text('{"features":[]}', encoding='utf-8')
                result = prep.prepare({'city': 'velesin', 'features': []}, root / 'inputs.json')
                self.assertEqual(result['city'], 'velesin')
                self.assertEqual(result['input_data_directory'], '.work/.preview/velesin/data_all')
                self.assertEqual(result['source_manifest'], '.work/roof-pilot/sources/sources.json')
                with self.assertRaisesRegex(ValueError, 'Sample city'):
                    prep.prepare({'city': 'ceske-budejovice', 'features': []}, root / 'other.json')

    def test_batch_uses_manifest_city_and_supplied_records_win(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for city, data_name, height in [('velesin', 'data_all', 12), ('ceske-budejovice', 'data', 99)]:
                data = root / '.work/.preview' / city / data_name
                data.mkdir(parents=True)
                pq.write_table(pa.Table.from_pylist([{'id': 'shared-test-id', 'height': height}]), data / 'building.parquet')
            inputs = root / 'inputs.json'
            inputs.write_text('{"city":"velesin"}', encoding='utf-8')
            with patch.object(roof_batch, 'ROOT', root):
                record = roof_batch.source_records(inputs, {'shared-test-id'})['shared-test-id']
                self.assertEqual(record['overture_building']['height'], 12)
                self.assertIn('velesin', record['building_record_origin'])
                (root / 'source_records.json').write_text('{"shared-test-id":{"frozen":true}}', encoding='utf-8')
                self.assertEqual(roof_batch.source_records(inputs, {'shared-test-id'}),
                                 {'shared-test-id': {'frozen': True}})

    def test_reuse_from_other_city_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / 'prior.json'
            prior.write_text('{"city":"ceske-budejovice","buildings":[]}', encoding='utf-8')
            with patch.object(prep, 'prepare') as prepare:
                with self.assertRaises(SystemExit):
                    address_inputs.main(['--city', 'velesin', '--requests', str(root / 'unused.json'),
                                         '--output', str(root / 'output'), '--reuse-inputs', str(prior)])
                prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
