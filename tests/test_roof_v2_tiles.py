"""Numerical and integration-contract tests, without browser or visual scoring."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from roof_v2_tiles import (Projection, ROOFS, WALLS, closest_color,
    diagnostic_status, fit_crop, patch_renderer, prepare, tile_indices, validate_mesh,
    texture_preview, tile_pixel_metrics, preview_allocation_estimate, digest)


INFO = {'width': 800, 'height': 600, 'tile': 128, 'x0': 0., 'y1': 0., 'mpp': .2}


class IdentityProjection:
    def part(self, vertices, origin, ground_z):
        return np.asarray(vertices, dtype=float) + [*origin, ground_z]

    def pixels(self, vertices):
        return np.asarray(vertices, dtype=float)[:, :2] + [200, 200]


def part(origin=(0, 0), ground=0):
    vertices = [[0,0,0],[10,0,0],[10,10,0],[0,10,0],
                [0,0,6],[10,0,6],[10,10,6],[0,10,6]]
    return {'status':'inferred', 'origin_xy':list(origin), 'ground_z':ground,
        'footprint':{'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        'result':{'model':{'type':'flat','mesh':{'vertices':vertices,
            'roof_faces':[[4,5,6],[4,6,7]],
            'wall_faces':[[0,1,5],[0,5,4],[1,2,6],[1,6,5],
                          [2,3,7],[2,7,6],[3,0,4],[3,4,7]],
            'ground_faces':[[0,2,1],[0,3,2]]}},
            'diagnostics':{'status':'supported'}}}


def inputs():
    scene = {'trees':[[50,50,3]],'buildings':[
        {'id':11,'p':[[0,0],[10,0],[10,10],[0,10]],'b':0,'g':0,'e':8,'rh':3,'rc':[255,0,0],'wc':[0,0,255],'s':0},
        {'id':12,'p':[[20,0],[30,0],[30,10],[20,10]],'b':0,'g':0,'e':8,'rh':3,'rc':[255,255,0],'wc':[255,0,0],'s':0},
        {'id':13,'p':[[50,0],[60,0],[60,10],[50,10]],'b':0,'g':0,'e':8,'rh':3,'rc':[100,100,100],'wc':[210,200,180],'s':0}]}
    source = {'buildings':[{'id':11,'oid':'one'},{'id':12,'oid':'one'},{'id':13,'oid':'other'}]}
    document = {'schema':'roof-v2/1','buildings':[{'id':'one','address':'Test 1',
                'parts':[part(),part((20,0))]}]}
    return document, scene, source


class TestRoofV2Tiles(unittest.TestCase):
    def test_atomic_multicomponent_replacement_preserves_other_buildings(self):
        document, scene, source = inputs()
        original = deepcopy(scene)
        cases, replacements = prepare(document, scene, source, INFO, IdentityProjection())
        self.assertEqual(scene, original)
        self.assertEqual(cases[0]['scene_ids'], [11,12])
        self.assertTrue(cases[0]['renderable'])
        self.assertEqual(set(replacements), {'11','12'})
        self.assertEqual(len(replacements['11']), 2)
        self.assertEqual(replacements['12'], [])
        self.assertNotIn('13', replacements)
        self.assertEqual(replacements['11'][1]['vertices'][0], [20.,0.,0.])

    def test_missing_disconnected_part_keeps_whole_original(self):
        document, scene, source = inputs()
        document['buildings'][0]['parts'].pop()
        cases, replacements = prepare(document, scene, source, INFO, IdentityProjection())
        self.assertFalse(cases[0]['renderable'])
        self.assertEqual(replacements, {})
        self.assertIn('coverage', ' '.join(cases[0]['errors']))

    def test_failed_input_part_cannot_replace_old_pieces(self):
        document, scene, source = inputs()
        document['buildings'][0]['parts'][1]['status'] = 'no_roof_points'
        cases, replacements = prepare(document, scene, source, INFO, IdentityProjection())
        self.assertFalse(cases[0]['renderable'])
        self.assertEqual(replacements, {})
        self.assertIn('no_roof_points', ' '.join(cases[0]['errors']))

    def test_duplicate_oid_rejected(self):
        document, scene, source = inputs()
        document['buildings'].append(deepcopy(document['buildings'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            prepare(document, scene, source, INFO, IdentityProjection())

    def test_old_algorithm_schema_rejected(self):
        document, scene, source = inputs()
        document['schema'] = 'roof-inference/1'
        with self.assertRaisesRegex(ValueError, 'roof-v2/1'):
            prepare(document, scene, source, INFO, IdentityProjection())

    def test_malformed_mesh_is_not_sent_to_renderer(self):
        mesh = part()['result']['model']['mesh']
        for replacement in ([[0,1,800]], [[0,0,1]], [[0,1]], [[0,1,True]]):
            wrong = deepcopy(mesh)
            wrong['roof_faces'] = replacement
            with self.assertRaises(ValueError):
                validate_mesh(wrong)
        mesh['vertices'][0][0] = float('nan')
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            validate_mesh(mesh)

    def test_colors_stay_in_muted_palettes(self):
        for color in ([255,0,0],[0,0,255],[255,255,0],None,[float('nan'),2,3]):
            self.assertIn(tuple(closest_color(color, ROOFS)), ROOFS)
            self.assertIn(tuple(closest_color(color, WALLS)), WALLS)
        self.assertNotEqual(closest_color([255,0,0], ROOFS), [255,0,0])

    def test_no_confidence_is_invented(self):
        self.assertEqual(diagnostic_status({'rmse_m':.1}), 'unknown')
        self.assertEqual(diagnostic_status({'needs_review':True,'status':'supported'}), 'uncertain')
        self.assertEqual(diagnostic_status({'fallback':True}), 'fallback')
        self.assertEqual(diagnostic_status({'review_required':False,'selected_type':'gabled'}), 'supported')
        self.assertEqual(diagnostic_status({'review_required':False,'flags':['poor_template_fit']}), 'uncertain')
        self.assertEqual(diagnostic_status({'review_required':True,'flags':['insufficient_data']}), 'fallback')

    def test_projection_uses_world_ground_and_city_href_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary)
            (p / 'mesto.json').write_text(json.dumps({'stred':[14.4747,48.9746],
                'href':390,'ctverce':[[0,0]],'dno':-30}), encoding='utf-8')
            projection = Projection(p, INFO)
            origin = Transformer.from_crs(4326,5514,always_xy=True).transform(14.4747,48.9746)
            xyz = projection.part([[0,0,12],[3,4,0]], origin, 387)
            self.assertLess(abs(xyz[0,0]), .001)
            self.assertLess(abs(xyz[0,1]), .001)
            self.assertAlmostEqual(xyz[0,2], 9.)
            self.assertAlmostEqual(xyz[1,2], -3.)
            self.assertAlmostEqual(np.linalg.norm(xyz[1,:2]-xyz[0,:2]), 5., delta=.03)

    def test_tiles_stay_inside_pixel_bounds(self):
        crop = fit_crop([[-500,-500],[20,20]], INFO)
        self.assertEqual(crop[:2], [0,0])
        self.assertTrue(all(i >= 0 and j >= 0 for i,j in tile_indices(crop,128)))
        self.assertEqual(tile_indices([0,0,128,128],128),[(0,0)])
        self.assertIsNone(fit_crop([[5000,5000],[5100,5100]],INFO))

    def test_patch_removes_base_and_landmark_pass_and_locks_grid(self):
        html = '\n'.join(['const scene = await (await fetch(`${DIR}/scene.json`)).json();',
            '    if (b.only) continue;', '    if (b.lm && CUSTOM.landmarks?.[b.lm]) doThing();',
            'const IW = Math.ceil((X1 - X0) / MPP), IH = Math.ceil((Y1 - Y0) / MPP);',
            'window.READY = true;'])
        result = patch_renderer(html, INFO)
        self.assertEqual(result.count('Object.hasOwn(scene.roofV2 || {}, b.id)'),2)
        self.assertIn('const IW = 800, IH = 600;',result)
        self.assertIn('window.ROOF_V2_STATS',result)
        self.assertIn('WebGL error after tile',result)
        self.assertIn('ROOF_V2_LAST_PIXEL_QA',result)
        with self.assertRaisesRegex(ValueError,'interface changed'):
            patch_renderer(html.replace('if (b.only)', 'if (b.only2)'),INFO)

    def test_preview_texture_isolated_and_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source.png'
            output = Path(temporary) / 'staged.png'
            Image.new('RGBA',(80,46),(100,170,95,255)).save(source)
            before = digest(source)
            entry = texture_preview(source,output,40)
            self.assertEqual(entry['preview_size'],[40,23])
            self.assertEqual(entry['reduction_factor'],2)
            self.assertEqual(digest(source),before)
            self.assertEqual(entry['source_sha256'],before)
            with self.assertRaisesRegex(ValueError,'overwrite source'):
                texture_preview(source,source,40)
            estimate = preview_allocation_estimate({'ground':entry},2048,1024)
            self.assertEqual(estimate['texture_rgba_bytes'],40*23*4)
            self.assertEqual(estimate['shadow_color_depth_bytes'],2048*2048*8)

    def test_numeric_pixel_metrics_detect_blank_and_varied_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'tile.png'
            Image.new('RGBA',(128,128),(0,0,0,0)).save(source)
            blank = tile_pixel_metrics(source)
            self.assertEqual(blank['opaque_fraction'],0)
            self.assertEqual(blank['unique_rgb'],0)
            data = np.random.default_rng(123).integers(0,256,(128,128,4),dtype=np.uint8)
            data[:,:,3] = 255
            Image.fromarray(data).save(source)
            varied = tile_pixel_metrics(source)
            self.assertEqual(varied['opaque_fraction'],1)
            self.assertGreater(varied['unique_rgb'],100)
            self.assertGreater(varied['luma_variance'],2)


if __name__ == '__main__':
    unittest.main()
