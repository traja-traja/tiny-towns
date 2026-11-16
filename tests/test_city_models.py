import io
import json
import math
import struct
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import Polygon

from scripts.build_sportcentrum import SOURCE, build_model, glb_bytes


HOOK = Path(__file__).resolve().parents[1] / 'cities/velesin/assets/custom_prep.py'
SOURCE_ID = '78e32d1e-ecfa-4e1b-a00f-db417ea5af1b'


def component(identifier, east, height, eave):
    return {
        'id': identifier, 'name': identifier,
        'footprint': [[east, 0], [east + 2, 0], [east + 2, 2], [east, 2]],
        'height_m': height, 'eave_height_m': eave,
        'mesh': {
            'vertices': [[east, 0, -2], [east + 2, 0, -2], [east + 2, 0, height], [east, 2, height]],
            'faces': [[0, 1, 2, 0], [1, 3, 2, 1]],
        },
    }


class SportcentrumAdapterTest(unittest.TestCase):
    def setUp(self):
        self.hook = compile(HOOK.read_text(encoding='utf-8'), str(HOOK), 'exec')
        self.scene = [{'id': 0}, {'id': 1, 'wc': [0, 0, 0], 'rc': [0, 0, 0]}, {'id': 2}]
        self.overlays = [
            {'id': 1, 'oid': SOURCE_ID, 'addr': ['Strahovská 661'], 'roof_geometry': {}},
            {'id': 2, 'oid': 'unrelated'},
        ]
        self.chimneys = [[0, 0, 0, 1], [0, 0, 0, 2]]
        self.context = {
            'HOOK': 'props', 'json': json, 'Polygon': Polygon,
            'buildings': self.scene, 'binfo': self.overlays, 'chimneys': self.chimneys,
            'to_local': lambda lon, lat: (50, 560),
            'to_lonlat': lambda x, y: (x / 100, y / 100),
            'ground': lambda x, y: 15.5,
        }

    def test_split_retains_primary_address_and_uses_shared_ground(self):
        model = {
            'schema_version': 1, 'id': 'sportcentrum-velesin', 'source_building_id': SOURCE_ID,
            'units': 'metres', 'coordinate_system': 'local-east-north-up', 'anchor': {'lon': 1, 'lat': 2},
            'materials': [{'color': [200, 210, 215], 'kind': 'wall'}, {'color': [80, 90, 95], 'kind': 'roof'}],
            'components': [component('tennis', 0, 8, 4), component('squash', 3, 4, 4)],
        }
        with patch.object(Path, 'open', return_value=io.StringIO(json.dumps(model))):
            exec(self.hook, self.context)

        primary, secondary = self.scene[1], self.scene[3]
        self.assertEqual([building['id'] for building in self.scene], [0, 1, 2, 3])
        self.assertEqual([building['only'] for building in (primary, secondary)], [1, 1])
        self.assertEqual(Polygon(primary['p']).distance(Polygon(secondary['p'])), 1)
        self.assertEqual(primary['tt_mesh']['vertices'][0], [50, 560, 13.5])
        self.assertEqual(primary['e'] + primary['rh'], 23.5)

        tennis, unrelated, squash = self.overlays
        self.assertEqual((tennis['id'], tennis['oid'], tennis['addr']), (1, SOURCE_ID, ['Strahovská 661']))
        self.assertEqual((squash['id'], squash['oid'], squash['addr']), (3, 'sportcentrum-velesin/squash', []))
        self.assertEqual((tennis['ring'], squash['ring']), (primary['p'], secondary['p']))
        self.assertEqual((tennis['top'], squash['top']), (23.5, 19.5))
        self.assertNotIn('roof_geometry', tennis)
        self.assertEqual(unrelated, {'id': 2, 'oid': 'unrelated'})
        self.assertEqual(self.chimneys, [[0, 0, 0, 2]])

    def test_missing_source_skips_model_and_missing_model_raises(self):
        with patch.object(Path, 'open', side_effect=FileNotFoundError) as read_model:
            with self.assertRaises(FileNotFoundError):
                exec(self.hook, self.context)
            read_model.reset_mock()
            self.overlays.pop(0)
            exec(self.hook, self.context)
            read_model.assert_not_called()
        self.assertEqual([building['id'] for building in self.scene], [0, 1, 2])


class SportcentrumGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(SOURCE.read_text(encoding='utf-8'))
        cls.model = build_model(cls.source)

    def test_closed_outward_meshes_and_separate_passage(self):
        polygons = []
        for part in self.model['components']:
            vertices = part['mesh']['vertices']
            edges = Counter()
            volume = 0
            for a, b, c, material in part['mesh']['faces']:
                for i, j in ((a, b), (b, c), (c, a)):
                    edges[tuple(sorted((i, j)))] += 1
                p, q, r = vertices[a], vertices[b], vertices[c]
                cross = (q[1]*r[2]-q[2]*r[1], q[2]*r[0]-q[0]*r[2], q[0]*r[1]-q[1]*r[0])
                volume += sum(p[i]*cross[i] for i in range(3)) / 6
            self.assertTrue(all(math.isfinite(c) for v in vertices for c in v))
            self.assertEqual(set(edges.values()), {2}, part['id'])
            self.assertGreater(volume, 1, part['id'])
            self.assertAlmostEqual(max(v[2] for v in vertices), part['height_m'], places=4)
            polygons.append(Polygon(part['footprint']))
        for i, polygon in enumerate(polygons):
            for other in polygons[:i]:
                self.assertLess(polygon.intersection(other).area, .01)
        self.assertGreater(polygons[0].distance(polygons[3]), 3.0)

    def test_portable_glb_buffer_and_source_anchor(self):
        content = glb_bytes(self.model)
        magic, version, length = struct.unpack_from('<III', content)
        self.assertEqual((magic, version, length), (0x46546C67, 2, len(content)))
        json_length, json_type = struct.unpack_from('<II', content, 12)
        self.assertEqual(json_type, 0x4E4F534A)
        document = json.loads(content[20:20 + json_length])
        binary_length, binary_type = struct.unpack_from('<II', content, 20 + json_length)
        self.assertEqual(binary_type, 0x004E4942)
        self.assertEqual(binary_length, document['buffers'][0]['byteLength'])
        self.assertEqual(document['extras']['anchorWGS84'], self.model['anchor'])
        self.assertEqual(len(document['meshes']), 5)
        for view in document['bufferViews']:
            self.assertLessEqual(view['byteOffset'] + view['byteLength'], binary_length)
