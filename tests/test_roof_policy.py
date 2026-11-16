"""Regression tests of the actual prep selection block without a full map build."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from shapely.geometry import box

from nastroje.roof_policy import resolve_roof_shape


ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'prep.py').read_text(encoding='utf-8'))


def _assigned(node, name):
    return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)


def _selection_code():
    # Execute the real integration, including DOM/SAT precedence and tile branch.
    for node in ast.walk(TREE):
        body = getattr(node, 'body', None)
        if not isinstance(body, list):
            continue
        starts = [i for i, n in enumerate(body) if _assigned(n, 'source_roof')]
        if starts:
            start = starts[0]
            end = next(i for i in range(start, len(body)) if _assigned(body[i], 'obb'))
            return compile(ast.Module(body=body[start:end], type_ignores=[]), 'prep.py:roof-selection', 'exec')
    raise AssertionError('Could not find roof selection integration in prep.py')


SELECTION = _selection_code()
HEIGHT_NODE = next(n for n in ast.walk(TREE) if isinstance(n, ast.If)
                   and any(isinstance(s, ast.Assign) and ast.unparse(s).startswith('med, top = DMP[r.id]')
                           for s in n.body))
HEIGHT = compile(ast.Module(body=[HEIGHT_NODE], type_ignores=[]), 'prep.py:dmp-height', 'exec')


def select(*, source=None, cls='residential', floors=5, height=None, dmp=(16.7, 19.2), urban=False, sat=None, dom=None):
    polygon = box(0, 0, 20, 20)
    ctx = dict(r=SimpleNamespace(id='fixture', roof_shape=source), c=cls, floors=floors, hgt=height,
               lm=None, URBAN=urban, area=polygon.area, p=polygon, cen=polygon.centroid, key='fixture',
               ROOF_MAP={s: s for s in ['flat', 'gabled', 'hipped', 'pyramidal']},
               DMP={'fixture': dmp} if dmp else {},
               btree=SimpleNamespace(query=lambda p: [0, 1]), bpolys=[polygon, polygon],
               panel_like=lambda p: False, L_obb_ok=lambda p: True, density=lambda p: 1,
               h01=lambda s: .5, DOM_BY_ID={'fixture': {'spec': dom}} if dom else {},
               SAT={'b': {'fixture': sat or {}}}, FLAT_CLS={'apartments', 'office', 'retail'},
               PITCHED_CLS={'residential', 'civic'}, resolve_roof_shape=resolve_roof_shape)
    exec(SELECTION, ctx)
    return ctx


class RoofPolicyTests(unittest.TestCase):
    def test_actual_gabled_five_floor_case_keeps_roof(self):
        # Na Mlynske stoce367, Overture4360399b-b4fe-442c-aebf-299791112d22.
        self.assertEqual(select(source='gabled')['rs'], 'gabled')

    def test_pitched_attribute_survives_apartments_and_height(self):
        self.assertEqual(select(source='hipped', cls='apartments', floors=3, height=20)['rs'], 'hipped')

    def test_source_shape_is_independent_of_center_tile(self):
        for source in ('flat', 'gabled', 'hipped', 'pyramidal'):
            self.assertEqual(select(source=source, urban=False)['rs'], select(source=source, urban=True)['rs'])

    def test_unknown_bank_stays_flat_despite_percentile_spread(self):
        self.assertEqual(select(cls='office', floors=3, dmp=(16.7, 18.1))['rs'], 'flat')

    def test_explicit_flat_high_building_stays_flat(self):
        self.assertEqual(select(source='flat', cls='civic', floors=15, dmp=(27.2, 27.4))['rs'], 'flat')

    def test_dmp_conflict_keeps_existing_flat_priority(self):
        # Ceska17: source gabled but DMP9.0/9.1m. Not claimed as surveyed truth.
        for urban in (False, True):
            self.assertEqual(select(source='gabled', floors=3, dmp=(9, 9.1), urban=urban)['rs'], 'flat')

    def test_dom_and_sat_manual_overrides_have_priority(self):
        self.assertEqual(select(source='gabled', dom={'r': 'flat'})['rs'], 'flat')
        self.assertEqual(select(source='flat', sat={'r': 'hipped'})['rs'], 'hipped')
        self.assertEqual(select(source='gabled', sat={'rs': 'flat'})['rs'], 'flat')

    def test_pitched_resolution_clears_panel_and_flat_clears_tenement(self):
        self.assertFalse(select(source='flat', urban=True)['tenement'])
        self.assertFalse(select(source='gabled', cls='apartments')['panel'])

    def test_unknown_shape_does_not_gain_a_source_override(self):
        self.assertEqual(resolve_roof_shape(None, 'flat'), 'flat')
        self.assertIsNone(resolve_roof_shape(None, None))

    def test_actual_height_branch_separates_eaves_and_ridge(self):
        context = select(source='gabled')
        context.update(roofh=7, total=0, eave=0)
        exec(HEIGHT, context)
        self.assertAlmostEqual(context['eave'], 12.2)
        self.assertAlmostEqual(context['total'], 19.2)
        self.assertAlmostEqual(context['eave'] + context['roofh'], context['total'])

    def test_synthetic_three_wall_plus_two_attic_levels(self):
        # Synthetic mass regression, not a claim of surveyed floor counts.
        context = select(source='gabled', dmp=(12, 15))
        context.update(roofh=6, total=0, eave=0)
        exec(HEIGHT, context)
        self.assertEqual(context['eave'], 9)
        self.assertEqual(context['total'], 15)
        flat = select(source='flat', dmp=(12, 15))
        flat.update(roofh=0, total=0, eave=0)
        exec(HEIGHT, flat)
        self.assertEqual(flat['eave'], 12)


if __name__ == '__main__':
    unittest.main()
