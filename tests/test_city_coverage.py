import contextlib
import io
import json
import math
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import shapely
from shapely.geometry import MultiPolygon, mapping

from scripts import configure_city


class CityCoverageTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.city = self.root / 'cities' / 'velesin'
        self.city.mkdir(parents=True)
        self.profile = {
            'center': [14.462376891234, 48.83194254321],
            'map': {
                'nazev': 'Velešín',
                'titulek': 'Tiny Towns – Velešín',
                'potoky': True,
            },
        }
        self.write_json('profile.json', self.profile)
        self.boundary = self.write_boundary(
            shapely.box(-500, -300, 1150.4, 400),
            shapely.box(4580, -2340, 4620, -2260),
        )

    def write_json(self, name, value):
        (self.city / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def write_boundary(self, *parts):
        lon, lat = self.profile['center']
        scale = np.array([math.cos(math.radians(lat)) * 111320.0, 110574.0])
        geometry = MultiPolygon(parts)
        boundary = shapely.transform(geometry, lambda coordinates: coordinates / scale + [lon, lat])
        self.write_json('boundary.geojson', {'type': 'Feature', 'properties': {}, 'geometry': mapping(boundary)})
        return boundary

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = configure_city.main(args, root=self.root)
            except SystemExit as result:
                code = result.code
        return code, out.getvalue(), err.getvalue()

    def plan(self):
        code, out, err = self.cli('plan', 'velesin')
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def cache_tiles(self):
        result = self.plan()
        for tile in result['terrain_tiles']:
            path = self.root / tile['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (256, 256), (129, 234, 128)).save(path)  # 490.5 m
        return result

    def generate(self, *options):
        code, _, err = self.cli('generate', 'velesin', *options)
        self.assertEqual(code, 0, err)

    def test_disconnected_municipality_and_subpercent_sliver(self):
        planned = self.cache_tiles()
        self.assertEqual(planned['cells'], [[0, 0], [1, 0], [2, -1]])
        self.assertEqual(planned['municipality']['omitted_area_m2'], 0)
        self.generate()
        path = self.city / 'mesto.json'
        with patch.dict(os.environ, {'IZO_MESTO': str(path)}):
            engine = runpy.run_path(str(configure_city.ROOT / 'geo.py'))

        def engine_projection(coordinates):
            x, y = engine['to_local'](coordinates[:, 0], coordinates[:, 1])
            return np.column_stack((x, y))

        municipality = shapely.transform(self.boundary, engine_projection)
        tiles = []
        for cell in engine['CHUNKS']:
            x, y = engine['chunk_center'](cell)
            half = engine['HALF']
            tiles.append(shapely.box(x - half, y - half, x + half, y + half))
        self.assertEqual(municipality.difference(shapely.union_all(tiles)).area, 0)
        self.assertAlmostEqual(municipality.intersection(tiles[1]).area, 280)
        self.assertEqual(list(engine['MESTO']['stred']), self.profile['center'])
        self.assertEqual(engine['MESTO']['titulek'], self.profile['map']['titulek'])
        self.assertTrue(engine['MESTO']['potoky'])

    def test_castle_adds_the_neighboring_cell(self):
        self.write_boundary(shapely.box(-500, -500, 500, 500))
        self.assertEqual(self.plan()['cells'], [[0, 0]])
        self.profile['extensions'] = [{
            'name': 'Hrad Velešín',
            'center': [14.479460, 48.831942],
            'radius_m': 300,
        }]
        self.write_json('profile.json', self.profile)
        plan = self.plan()
        self.assertEqual(plan['cells'], [[0, 0], [1, 0]])
        self.assertEqual(plan['extensions'][0]['omitted_area_m2'], 0)
        self.assertAlmostEqual(plan['extensions'][0]['area_m2'], math.pi * 300**2, delta=30)
        self.assertEqual(plan['target']['omitted_area_m2'], 0)

    def test_preview_keeps_full_config_and_terrain_reference(self):
        self.cache_tiles()
        self.generate()
        path = self.city / 'mesto.json'
        coverage_path = self.city / 'coverage.json'
        original = path.read_bytes()
        full_coverage = coverage_path.read_bytes()
        self.generate('--preview', '2')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(coverage_path.read_bytes(), full_coverage)
        full = json.loads(original)
        preview = configure_city.read_json(self.city / 'mesto.preview.json')
        self.assertEqual(preview.pop('ctverce'), [[0, 0], [1, 0]])
        full.pop('ctverce')
        self.assertEqual(preview, full)
        report = configure_city.read_json(self.city / 'coverage.preview.json')
        self.assertEqual(report['mode'], 'preview')
        self.assertEqual(report['full_cell_count'], 3)
        self.assertAlmostEqual(report['municipality']['omitted_area_m2'], 3200)

    def test_terrain_statistics_exclude_pixels_outside_map_extent(self):
        result = self.cache_tiles()
        modified_inside = False
        modified_outside = False
        west, south, east, north = result['bounds_lon_lat']
        # Independently locate one pixel on either side of the map's extent.
        for tile in result['terrain_tiles']:
            path = self.root / tile['path']
            x, y = int(path.parent.name), int(path.stem)
            with Image.open(path) as tile_image:
                image = tile_image.copy()
            for column, row in ((128, 128), (0, 0), (255, 255)):
                lon = (x + (column + 0.5) / 256) / 4096 * 360 - 180
                v = (y + (row + 0.5) / 256) / 4096
                lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * v))))
                if west <= lon <= east and south <= lat <= north:
                    image.putpixel((column, row), (129, 154, 64))  # 410.25 m
                    modified_inside = True
                else:
                    image.putpixel((column, row), (128, 200, 0))  # 200 m
                    modified_outside = True
            image.save(path)
        self.assertTrue(modified_inside and modified_outside)
        self.generate()
        config = configure_city.read_json(self.city / 'mesto.json')
        report = configure_city.read_json(self.city / 'coverage.json')
        self.assertEqual(report['terrain']['minimum_m'], 410.25)
        self.assertEqual(config['href'], 490.5)
        self.assertEqual(config['dno'], -111)

    def test_missing_terrain_never_writes_config(self):
        code, _, err = self.cli('generate', 'velesin')
        self.assertEqual(code, 1)
        self.assertIn('Missing', err)
        self.assertIn('Terrarium', err)
        self.assertFalse((self.city / 'mesto.json').exists())
        self.assertFalse((self.city / 'coverage.json').exists())

    def test_explicit_replacement_preserves_original_config(self):
        self.cache_tiles()
        self.generate()
        path = self.city / 'mesto.json'
        original = path.read_bytes()
        self.profile['map']['titulek'] = 'Updated heading'
        self.write_json('profile.json', self.profile)
        code, _, err = self.cli('generate', 'velesin')
        self.assertEqual(code, 1)
        self.assertIn('--replace', err)
        self.assertEqual(path.read_bytes(), original)
        self.generate('--replace')
        self.assertEqual((self.city / 'mesto.json.bak').read_bytes(), original)
        self.assertEqual(configure_city.read_json(path)['titulek'], 'Updated heading')

    def test_failed_report_write_leaves_config_available_for_retry(self):
        self.cache_tiles()
        coverage = self.city / 'coverage.json'
        coverage.mkdir()
        code, _, _ = self.cli('generate', 'velesin')
        self.assertEqual(code, 1)
        self.assertFalse((self.city / 'mesto.json').exists())
        coverage.rmdir()
        self.generate()


if __name__ == '__main__':
    unittest.main()
