"""Focused evidence checks for a high main wing meeting a lower L roof."""
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import numpy as np
import shapely
from shapely.geometry import box, shape, mapping, LineString
from shapely.ops import split
from roof_longitudinal_split import detect_longitudinal_split, _ridge_references, footprint_gate, snap_partition
from roof_sections import analyze_sections


def main_and_l(main_eave=8.,low_eave=4.):
    # One front wing plus an L behind it; courtyard opens to the right.
    main=box(0,0,24,10)
    side=box(0,10,8,30)
    rear=box(0,22,24,30)
    footprint=shapely.union_all([main,side,rear])
    x,y=np.meshgrid(np.arange(.15,24,.3),np.arange(.15,30,.3))
    xy=np.c_[x.ravel(),y.ravel()]
    xy=xy[shapely.intersects_xy(footprint,xy[:,0],xy[:,1])]
    x,y=xy.T
    main_z=main_eave+.7*np.minimum(y,10-y)
    lower_z=low_eave+.7*np.maximum(np.minimum(x,8-x),np.minimum(y-22,30-y))
    z=np.maximum(main_z,lower_z) if main_eave==low_eave else np.where(y<10,main_z,lower_z)
    return footprint,np.c_[xy,z]


class LongitudinalSplitTests(unittest.TestCase):
    def test_common_eave_bent_roof_remains_one_volume(self):
        poly,points=main_and_l(main_eave=5.,low_eave=5.)
        result=detect_longitudinal_split(poly,points)
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['reason'],'one_supported_eave_level')

    def test_high_main_and_lower_l_produce_supported_transition(self):
        poly,points=main_and_l()
        result=detect_longitudinal_split(poly,points)
        self.assertTrue(result['candidates'],result['reason'])
        best=result['candidates'][0]
        self.assertGreaterEqual(best['supported_bands'],3)
        self.assertGreater(best['height_difference_m'],2.5)
        pieces=[shape(p) for p in best['footprints']]
        self.assertEqual(len(pieces),2)
        self.assertLess(shapely.union_all(pieces).symmetric_difference(poly).area,1e-6)
        self.assertLess(pieces[0].intersection(pieces[1]).area,1e-6)
        line=np.asarray(best['cut_line_xy'])
        self.assertLess(abs(np.mean(line[:,1])-10.),2.)
        json.dumps(result,allow_nan=False)

    def test_disabled_module_needs_no_input(self):
        result=detect_longitudinal_split(None,None,{'enabled':False})
        self.assertEqual(result['reason'],'disabled')
        self.assertEqual(result['candidates'],[])

    def test_two_tracks_keep_distinct_measured_areas(self):
        poly,points=main_and_l()
        record=analyze_sections(poly,points,axis=[1,0])
        record.update(domain=mapping(poly),area_m2=poly.area,wing_index=0)
        refs=_ridge_references(record)
        self.assertEqual(len(refs),2)
        self.assertTrue(all(r['area_m2']<poly.area*.8 for r in refs))
        self.assertGreater(abs(refs[0]['ridge']['eave_height_m']-refs[1]['ridge']['eave_height_m']),3.)

    def test_gate_accepts_long_or_bent_not_small_zigzag(self):
        self.assertTrue(footprint_gate(box(0,0,30,8))['accepted'])
        bent=box(0,0,30,10).union(box(0,10,10,25))
        self.assertTrue(footprint_gate(bent)['accepted'])
        square_with_tooth=box(0,0,20,20).union(box(20,8,21,12))
        self.assertFalse(footprint_gate(square_with_tooth)['accepted'])
        self.assertFalse(footprint_gate(box(0,0,23,6))['accepted'])

    def test_child_volume_cannot_split_recursively(self):
        result=detect_longitudinal_split(None,None,split_depth=1)
        self.assertEqual(result['reason'],'child_volume_splitting_disabled')
        self.assertEqual(result['candidates'],[])


class PartitionSnapTests(unittest.TestCase):
    def setUp(self):
        self.poly=box(0,0,30,10).union(box(0,10,10,25))
        self.refresh_cells()

    def refresh_cells(self):
        x,y=np.meshgrid(np.arange(.125,30,.25),np.arange(.125,25,.25))
        cells=np.c_[x.ravel(),y.ravel(),np.zeros(x.size)]
        self.cells=cells[shapely.intersects_xy(self.poly,cells[:,0],cells[:,1])]

    def proposal(self,line,score=0.):
        a,b=np.asarray(line.coords)[[0,-1]]
        tangent=(b-a)/np.linalg.norm(b-a);normal=np.array([tangent[1],-tangent[0]])
        pieces=list(split(self.poly,line).geoms)
        pieces.sort(key=lambda p:np.asarray(p.centroid.coords[0])@normal)
        return dict(score=score,cut_line_xy=list(map(list,line.coords)),
                    footprints=[mapping(p) for p in pieces],area_m2=[p.area for p in pieces])

    def test_nearby_original_edge_snap_keeps_exact_outline(self):
        proposal=self.proposal(LineString([(40,9.8),(-10,9.8)]))
        high=np.where(self.cells[:,1]<=10,0.,2.);low=2.-high
        result=snap_partition(self.poly,proposal,self.cells,high,low)
        self.assertTrue(result['snapping']['applied'])
        self.assertAlmostEqual(result['snapping']['max_line_move_m'],.2,places=6)
        pieces=[shape(p) for p in result['footprints']]
        self.assertEqual(len(pieces),2)
        self.assertTrue(all(p.is_valid for p in pieces))
        self.assertLess(shapely.union_all(pieces).symmetric_difference(self.poly).area,1e-8)
        self.assertLess(pieces[0].intersection(pieces[1]).area,1e-8)
        source=LineString(result['snapping']['source_edge_xy'])
        cut=LineString(result['cut_line_xy'])
        self.assertLess(source.difference(cut.buffer(1e-8)).length,1e-8)
        direction=np.asarray(cut.coords[-1])-np.asarray(cut.coords[0])
        direction/=np.linalg.norm(direction)
        np.testing.assert_allclose(result['normal_xy'],[direction[1],-direction[0]],atol=1e-9)

    def test_snap_rejects_worse_height_fit(self):
        proposal=self.proposal(LineString([(40,9.2),(-10,9.2)]))
        high=np.where(self.cells[:,1]<=9.2,0.,2.);low=2.-high
        result=snap_partition(self.poly,proposal,self.cells,high,low)
        self.assertFalse(result['snapping']['applied'])
        self.assertEqual(result['cut_line_xy'],proposal['cut_line_xy'])

    def test_snap_rejects_distant_or_perpendicular_edge(self):
        zero=np.zeros(len(self.cells))
        for line in (LineString([(40,7),(-10,7)]),LineString([(20.1,-5),(20.1,30)])):
            proposal=self.proposal(line)
            result=snap_partition(self.poly,proposal,self.cells,zero,zero)
            self.assertFalse(result['snapping']['applied'])
            self.assertEqual(result['footprints'],proposal['footprints'])

    def test_snap_can_be_disabled(self):
        proposal=self.proposal(LineString([(40,9.8),(-10,9.8)]))
        zero=np.zeros(len(self.cells))
        result=snap_partition(self.poly,proposal,self.cells,zero,zero,{'snap_enabled':False})
        self.assertFalse(result['snapping']['applied'])
        self.assertEqual(result['snapping']['reason'],'disabled')
        self.assertEqual(result['footprints'],proposal['footprints'])

    def test_small_projection_is_reattached_without_losing_area(self):
        tooth=box(20,10,23,13)
        self.poly=self.poly.union(tooth)
        self.refresh_cells()
        proposal=self.proposal(LineString([(40,9.8),(-10,9.8)]))
        self.assertEqual(len(proposal['footprints']),2)
        zero=np.zeros(len(self.cells))
        result=snap_partition(self.poly,proposal,self.cells,zero,zero)
        self.assertTrue(result['snapping']['applied'])
        pieces=[shape(p) for p in result['footprints']]
        self.assertEqual(len(pieces),2)
        self.assertAlmostEqual(sum(p.area for p in pieces),self.poly.area)
        self.assertLess(shapely.union_all(pieces).symmetric_difference(self.poly).area,1e-8)
        self.assertAlmostEqual(sum(p.intersection(tooth).area for p in pieces),tooth.area)
        self.assertLess(pieces[0].intersection(pieces[1]).area,1e-8)
        rejoined=result['snapping']['small_fragments_rejoined']
        self.assertEqual(len(rejoined),1)
        self.assertAlmostEqual(rejoined[0]['area_m2'],9.)
        self.assertGreaterEqual(rejoined[0]['shared_boundary_m'],3.)

    def test_large_projection_cannot_be_hidden_in_two_bodies(self):
        # First exceeds fragment budget; second would be a third major body.
        for tooth in (box(18,10,28,15),box(20,10,30,20)):
            with self.subTest(area=tooth.area):
                self.poly=box(0,0,30,10).union(box(0,10,10,25)).union(tooth)
                self.refresh_cells()
                proposal=self.proposal(LineString([(40,9.8),(-10,9.8)]))
                zero=np.zeros(len(self.cells))
                result=snap_partition(self.poly,proposal,self.cells,zero,zero)
                self.assertFalse(result['snapping']['applied'])
                self.assertEqual(result['footprints'],proposal['footprints'])


if __name__=='__main__':unittest.main()
