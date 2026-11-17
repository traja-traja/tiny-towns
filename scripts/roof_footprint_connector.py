"""Pure 2D module: two substantial bodies connected by one narrow passage.

Only short cuts extending existing edges at reflex corners are considered.
Each cut stops at the first opposite boundary; it never slices a parallel wing.
No roof points, building identifiers, height assumptions or cloud reads are used.
"""
from __future__ import annotations
import itertools
import math
import time
import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import split

DEFAULTS = dict(enabled=True,min_area_m2=240.,min_body_area_m2=80.,
    min_body_area_fraction=.18,min_body_to_connector_area_ratio=1.4,
    min_connector_width_m=1.5,max_connector_width_m=7.,
    min_connector_length_m=6.,min_connector_aspect=2.,
    min_body_width_ratio=1.65,max_connector_area_fraction=.25,
    min_connector_rectangularity=.80,min_body_rectangularity=.50,
    min_source_edge_m=2.,max_cut_angle_difference_deg=30.,max_cut_candidates=32,
    bend_tolerance_deg=15.,min_arm_edge_m=3.,min_width_ratio=1.65,
    max_cut_width_m=14.,max_cut_to_narrow_width_ratio=1.35)


def _polygons(geometry):
    if geometry.geom_type=='Polygon':
        if geometry.area>1e-7:yield geometry
    elif hasattr(geometry,'geoms'):
        for child in geometry.geoms:yield from _polygons(child)


def _lines(geometry):
    if geometry.geom_type=='LineString':yield geometry
    elif hasattr(geometry,'geoms'):
        for child in geometry.geoms:yield from _lines(child)


def _box_metrics(poly):
    box=poly.minimum_rotated_rectangle
    xy=np.asarray(box.exterior.coords)[:4]
    edges=np.linalg.norm(np.roll(xy,-1,axis=0)-xy,axis=1)
    return dict(length_m=float(edges.max()),width_m=float(edges.min()),
        rectangularity=float(poly.area/box.area))


def _corner_widths(poly,vertex,previous,following,cfg):
    """Compare adjacent arms locally, perpendicular to each arm's own wall."""
    a=vertex-previous;b=following-vertex
    lengths=np.array([np.linalg.norm(a),np.linalg.norm(b)])
    if lengths.min()<cfg['min_arm_edge_m']:return None
    angle=math.degrees(math.acos(float(np.clip(a@b/np.prod(lengths),-1,1))))
    if abs(angle-90.)>cfg['bend_tolerance_deg']:return None
    extent=max(poly.bounds[2]-poly.bounds[0],poly.bounds[3]-poly.bounds[1])*3+10
    records=[]
    for other,edge,length in ((previous,a,lengths[0]),(following,b,lengths[1])):
        axis=edge/length;normal=np.array([-axis[1],axis[0]]);samples=[]
        for fraction in (.25,.5,.75):
            point=vertex+(other-vertex)*fraction
            if not poly.contains(Point(point+.02*normal)):continue
            probe=point+.001*normal
            ray=LineString([probe,point+extent*normal])
            segments=[line for line in _lines(poly.intersection(ray)) if line.length>.01 and line.distance(Point(probe))<1e-6]
            if not segments:continue
            width=min(line.length for line in segments)+.001
            if width>=cfg['min_connector_width_m']:samples.append(float(width))
        if len(samples)<2:return None
        records.append(dict(width_m=float(np.median(samples)),width_samples_m=samples,
            wall_axis_xy=axis.tolist(),source_edge_length_m=float(length)))
    widths=[r['width_m'] for r in records];ratio=max(widths)/min(widths)
    if ratio<cfg['min_width_ratio']:return None
    return dict(turn_angle_deg=angle,arms=records,width_ratio=ratio,narrow_width_m=min(widths))


def _cut_proposals(poly,cfg):
    """Extend original incident edges across a neck, up to its first boundary."""
    q=np.asarray(orient(poly,sign=1.).exterior.coords)[:-1]
    extent=max(poly.bounds[2]-poly.bounds[0],poly.bounds[3]-poly.bounds[1])*3+10
    cuts=[];keys=set();reflex=0
    for index,vertex in enumerate(q):
        previous=q[(index-1)%len(q)];following=q[(index+1)%len(q)]
        a=vertex-previous;b=following-vertex
        if float(a[0]*b[1]-a[1]*b[0])>=-1e-8:continue
        reflex+=1
        width_evidence=_corner_widths(poly,vertex,previous,following,cfg)
        if width_evidence is None:continue
        for other in (previous,following):
            direction=vertex-other;source_length=float(np.linalg.norm(direction))
            if source_length<cfg['min_source_edge_m']:continue
            direction/=source_length
            if not poly.contains(Point(vertex+.02*direction)):continue
            probe=vertex+.001*direction
            ray=LineString([probe,vertex+extent*direction])
            segments=[line for line in _lines(poly.intersection(ray)) if line.length>.01 and line.distance(Point(probe))<1e-6]
            if not segments:continue
            segment=min(segments,key=lambda line:line.length)
            xy=np.asarray(segment.coords);end=xy[np.argmax((xy-vertex)@direction)]
            length=float(np.linalg.norm(end-vertex))
            if not cfg['min_connector_width_m']<=length<=cfg['max_cut_width_m']:continue
            if length>width_evidence['narrow_width_m']*cfg['max_cut_to_narrow_width_ratio']:continue
            key=tuple(sorted((tuple(np.round(vertex,5)),tuple(np.round(end,5)))))
            if key in keys:continue
            operative=LineString([other,vertex,end,end+.01*direction])
            pieces=list(_polygons(split(poly,operative)))
            if len(pieces)!=2:continue
            if min(p.area for p in pieces)<cfg['min_body_area_m2']:continue
            keys.add(key)
            cuts.append(dict(line=operative,segment=LineString([vertex,end]),
                direction=direction,source_vertex_index=index,source_edge_xy=[other.tolist(),vertex.tolist()],
                length_m=length,source_edge_length_m=source_length,width_evidence=width_evidence))
    # Deterministic strict budget: prefer clear necks supported by long original walls.
    cuts.sort(key=lambda cut:(cut['length_m'],-cut['source_edge_length_m'],cut['source_vertex_index']))
    return cuts[:int(cfg['max_cut_candidates'])],reflex,len(cuts)


def _pair(poly,left,right,cfg):
    if max(left['length_m'],right['length_m'])>cfg['max_connector_width_m']:return None,'connector_too_wide'
    angle=math.degrees(math.acos(float(np.clip(abs(left['direction']@right['direction']),0,1))))
    if angle>cfg['max_cut_angle_difference_deg']:return None,'cuts_not_parallel_enough'
    if left['segment'].intersects(right['segment']):return None,'cuts_intersect'
    pieces=[poly]
    for cut in (left,right):
        pieces=[part for p in pieces for part in _polygons(split(p,cut['line']))]
    if len(pieces)!=3:return None,'not_three_connected_parts'
    # The connector is the unique part sharing both whole cut segments.
    central=[]
    for i,p in enumerate(pieces):
        if all(p.boundary.buffer(1e-6).intersection(c['segment']).length>=.99*c['length_m'] for c in (left,right)):
            central.append(i)
    if len(central)!=1:return None,'no_unique_middle_part'
    connector=pieces.pop(central[0]);bodies=pieces
    c=_box_metrics(connector);bm=[_box_metrics(p) for p in bodies]
    measured_width=max(c['width_m'],left['length_m'],right['length_m'])
    if c['length_m']<cfg['min_connector_length_m'] or c['length_m']/measured_width<cfg['min_connector_aspect']:
        return None,'connector_not_elongated'
    if c['rectangularity']<cfg['min_connector_rectangularity']:
        return None,'connector_not_simple'
    if connector.area>poly.area*cfg['max_connector_area_fraction']:
        return None,'connector_too_large'
    minimum_area=max(cfg['min_body_area_m2'],poly.area*cfg['min_body_area_fraction'],
        connector.area*cfg['min_body_to_connector_area_ratio'])
    if min(p.area for p in bodies)<minimum_area:return None,'two_large_bodies_not_supported'
    if min(m['width_m'] for m in bm)<measured_width*cfg['min_body_width_ratio']:
        return None,'end_bodies_not_wide_enough'
    if min(m['rectangularity'] for m in bm)<cfg['min_body_rectangularity']:
        return None,'end_bodies_too_fragmented'
    # Exact source partition, checked independently of the construction method.
    union=shapely.union_all([*bodies,connector]);missing=poly.symmetric_difference(union).area
    overlap=sum(a.intersection(b).area for a,b in itertools.combinations([*bodies,connector],2))
    if missing>1e-6 or overlap>1e-6:return None,'invalid_partition'
    bodies.sort(key=lambda p:-p.area)
    ordered=[bodies[0],connector,bodies[1]]
    metrics=dict(connector_area_m2=float(connector.area),connector_length_m=c['length_m'],
        connector_width_m=measured_width,connector_aspect=c['length_m']/measured_width,
        connector_rectangularity=c['rectangularity'],body_areas_m2=[float(p.area) for p in bodies],
        body_widths_m=sorted([m['width_m'] for m in bm],reverse=True),
        cut_angle_difference_deg=angle,partition_difference_m2=float(missing),overlap_m2=float(overlap))
    return dict(method='two_reflex_edge_neck_cuts',footprints=[mapping(p) for p in ordered],
        roles=['main_body','connector','rear_body'],area_m2=[float(p.area) for p in ordered],
        cut_lines_xy=[list(map(list,x['segment'].coords)) for x in (left,right)],
        cut_source_edges_xy=[x['source_edge_xy'] for x in (left,right)],
        local_width_evidence=[x['width_evidence'] for x in (left,right)],metrics=metrics),None


def _single_cut(poly,cut,cfg):
    pieces=list(_polygons(split(poly,cut['line'])))
    if len(pieces)!=2:return None
    if min(p.area for p in pieces)<max(cfg['min_body_area_m2'],poly.area*cfg['min_body_area_fraction']):return None
    pieces.sort(key=lambda p:-p.area)
    difference=poly.symmetric_difference(shapely.union_all(pieces)).area
    overlap=pieces[0].intersection(pieces[1]).area
    if difference>1e-6 or overlap>1e-6:return None
    return dict(method='reflex_bend_local_arm_width_change',footprints=[mapping(p) for p in pieces],
        roles=['main_body','secondary_body'],area_m2=[float(p.area) for p in pieces],
        cut_lines_xy=[list(map(list,cut['segment'].coords))],cut_source_edges_xy=[cut['source_edge_xy']],
        local_width_evidence=[cut['width_evidence']],metrics=dict(
            local_width_ratio=cut['width_evidence']['width_ratio'],cut_length_m=cut['length_m'],
            body_areas_m2=[float(p.area) for p in pieces],partition_difference_m2=float(difference),overlap_m2=float(overlap)))


def detect_footprint_connector(poly,config=None):
    """Return at most one conservative two- or three-part footprint candidate."""
    tick=time.perf_counter();cfg={**DEFAULTS,**(config or {})}
    unknown=set(cfg)-set(DEFAULTS)
    if unknown:raise ValueError('Unknown footprint connector settings: '+', '.join(sorted(unknown)))
    result=dict(accepted=False,candidates=[],settings=cfg,counts=dict(reflex_vertices=0,
        cut_candidates=0,cut_candidates_before_budget=0,pairs_tested=0,accepted_pairs=0),
        rejected_reasons={})
    def finish(reason):
        result['reason']=reason;result['timing']={'total_seconds':time.perf_counter()-tick};return result
    if not cfg['enabled']:return finish('disabled')
    poly=shape(poly) if isinstance(poly,dict) else poly
    if not isinstance(poly,Polygon) or not poly.is_valid or poly.is_empty:return finish('requires_valid_single_polygon')
    if poly.interiors:return finish('closed_courtyard_not_a_single_connector')
    if poly.area<cfg['min_area_m2']:return finish('footprint_too_small')
    cuts,reflex,raw_count=_cut_proposals(poly,cfg)
    result['counts'].update(reflex_vertices=reflex,cut_candidates=len(cuts),cut_candidates_before_budget=raw_count)
    if not cuts:return finish('no_right_angle_bend_with_large_local_width_contrast')
    accepted=[]
    for left,right in itertools.combinations(cuts,2):
        result['counts']['pairs_tested']+=1
        proposal,reason=_pair(poly,left,right,cfg)
        if proposal:accepted.append(proposal)
        else:result['rejected_reasons'][reason]=result['rejected_reasons'].get(reason,0)+1
    result['counts']['accepted_pairs']=len(accepted)
    if not accepted:
        singles=[candidate for cut in cuts if (candidate:=_single_cut(poly,cut,cfg)) is not None]
        result['counts']['accepted_single_cuts']=len(singles)
        if not singles:return finish('no_supported_partition_at_width_change')
        singles.sort(key=lambda c:(-c['metrics']['local_width_ratio'],c['metrics']['cut_length_m']))
        result['accepted']=True;result['candidates']=[singles[0]]
        return finish('near_right_angle_bend_with_different_local_arm_widths')
    # Favor the narrowest supported connector; no address-dependent tie-break.
    accepted.sort(key=lambda c:(c['metrics']['connector_width_m'],-c['metrics']['connector_aspect']))
    result['accepted']=True;result['candidates']=[accepted[0]]
    return finish('two_large_bodies_connected_by_narrow_elongated_footprint')
