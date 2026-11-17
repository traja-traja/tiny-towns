"""Bounded virtual roof outlines, without changing the building footprint.

Replace short stair-step chains by an enclosing straight supporting line,
and short convex bevels by the intersection of their adjacent long walls.
The adjacent wall lines locate its endpoints. Every replacement must cover
all original geometry, preserve holes, and obey area/boundary-displacement
budgets. No hull or rectangle is substituted for an L/U courtyard building.
"""
from __future__ import annotations
import math,time
from collections import Counter
import numpy as np
from shapely.geometry import Polygon,shape,mapping
from shapely.geometry.polygon import orient

DEFAULTS=dict(fine_shift_m=.35,max_shift_m=2.,max_added_area_fraction=.12,
    parallel_angle_deg=12.,max_chain_edges=7,max_passes=8,max_references=3,
    min_wall_length_m=1.,max_connector_length_m=3.,max_backward_m=.10,
    remove_short_bevels=True,bevel_max_length_m=2.5,bevel_min_adjacent_m=3.,
    bevel_adjacent_length_ratio=2.,bevel_min_turn_deg=20.,bevel_max_turn_deg=160.)


def _edges(poly):
    return len(poly.exterior.coords)-1


def _budget(original,proposed,max_shift,cfg):
    if proposed.geom_type!='Polygon' or not proposed.is_valid or proposed.is_empty:return 'invalid_polygon'
    if len(proposed.interiors)!=len(original.interiors):return 'hole_topology'
    for a,b in zip(original.interiors,proposed.interiors):
        if Polygon(a).symmetric_difference(Polygon(b)).area>1e-7:return 'hole_changed'
    if original.difference(proposed).area>1e-7:return 'does_not_enclose_original'
    if (proposed.area-original.area)/original.area>cfg['max_added_area_fraction']+1e-10:return 'area_budget'
    if proposed.boundary.hausdorff_distance(original.boundary)>max_shift+1e-8:return 'boundary_budget'
    return None


def _replacement(poly,start,count,tangent):
    q=np.asarray(poly.exterior.coords)[:-1]
    q=np.roll(q,-start,axis=0);chain=q[:count+1]
    normal=np.array([tangent[1],-tangent[0]])
    offset=float(np.max(chain@normal))
    before=q[0]-q[-1];after=q[count+1]-q[count]
    denominators=[float(normal@before),float(normal@after)]
    if min(abs(x) for x in denominators)<1e-8:return None
    a=q[0]+(offset-normal@q[0])/denominators[0]*before
    b=q[count]+(offset-normal@q[count])/denominators[1]*after
    if (b-a)@tangent<.1:return None
    proposed=Polygon(np.vstack([a,b,q[count+1:]]),[list(r.coords) for r in poly.interiors])
    if not proposed.is_valid:return None
    # Only remove truly redundant collinear vertices here; do not let a second
    # approximate operation reintroduce uncovered original corners.
    proposed=orient(proposed.simplify(1e-8,preserve_topology=True),sign=1.)
    return proposed,dict(original_chain_xy=chain.tolist(),supporting_edge_xy=[a.tolist(),b.tolist()],
        removed_edges=count-1,wall_direction_xy=tangent.tolist())


def _bevel_replacement(poly,start,cfg):
    """Extend two long walls over a short CONVEX bevel, not a courtyard corner."""
    q=np.roll(np.asarray(poly.exterior.coords)[:-1],-start,axis=0)
    if len(q)<5:return None
    a,b,c,d=q[-1],q[0],q[1],q[2]
    before=b-a;short=c-b;after=d-c
    lengths=np.array([np.linalg.norm(before),np.linalg.norm(short),np.linalg.norm(after)])
    if lengths[1]<1e-8 or lengths[1]>cfg['bevel_max_length_m']:return None
    if min(lengths[0],lengths[2])<max(cfg['bevel_min_adjacent_m'],cfg['bevel_adjacent_length_ratio']*lengths[1]):return None
    cross=lambda x,y:float(x[0]*y[1]-x[1]*y[0])
    if cross(before,short)<=1e-8 or cross(short,after)<=1e-8:return None
    turn=math.degrees(math.acos(float(np.clip(before@after/(lengths[0]*lengths[2]),-1.,1.))))
    if not cfg['bevel_min_turn_deg']<=turn<=cfg['bevel_max_turn_deg']:return None
    coefficients=np.column_stack([before,-after])
    if abs(np.linalg.det(coefficients))<1e-8:return None
    t,u=np.linalg.solve(coefficients,c-a)
    # The intersection must extend both walls outward across the bevel.
    # Trimming a long wall would change a substantial architectural feature.
    if t<1.-1e-8 or u>1e-8:return None
    corner=a+t*before
    proposed=Polygon(np.vstack([corner,q[2:]]),[list(r.coords) for r in poly.interiors])
    if not proposed.is_valid:return None
    proposed=orient(proposed,sign=1.)
    return proposed,dict(operation='short_convex_bevel',original_chain_xy=[a.tolist(),b.tolist(),c.tolist(),d.tolist()],
        replacement_corner_xy=corner.tolist(),supporting_wall_lines_xy=[[a.tolist(),b.tolist()],[c.tolist(),d.tolist()]],
        removed_edges=1,bevel_length_m=float(lengths[1]),adjacent_wall_lengths_m=[float(lengths[0]),float(lengths[2])],
        wall_turn_degrees=turn)


def _simplify(original,max_shift,cfg,allow_bevels=False):
    current=original;accepted=[];rejections=Counter();evaluated=0
    cosine=math.cos(math.radians(cfg['parallel_angle_deg']))
    for _ in range(int(cfg['max_passes'])):
        q=np.asarray(current.exterior.coords)[:-1];n=len(q);options=[]
        for start in range(n):
            if allow_bevels and cfg['remove_short_bevels']:
                bevel=_bevel_replacement(current,start,cfg)
                if bevel is not None:
                    evaluated+=1;proposed,meta=bevel
                    reason=_budget(original,proposed,max_shift,cfg)
                    if reason:rejections['bevel_'+reason]+=1
                    else:
                        reduction=_edges(current)-_edges(proposed)
                        if reduction>0:
                            options.append(((proposed.area-current.area)/reduction,-reduction,proposed,meta))
            qq=np.roll(q,-start,axis=0)
            for count in range(2,min(int(cfg['max_chain_edges']),n-2)+1):
                chain=qq[:count+1];vectors=np.diff(chain,axis=0);lengths=np.linalg.norm(vectors,axis=1)
                if min(lengths[0],lengths[-1])<cfg['min_wall_length_m']:continue
                first,last=vectors[0]/lengths[0],vectors[-1]/lengths[-1]
                if first@last<cosine:continue
                average=first*lengths[0]+last*lengths[-1];average/=np.linalg.norm(average)
                # Do not bridge a U-shaped return where a wall doubles back.
                if np.min(vectors@average)<-cfg['max_backward_m']:continue
                connectors=abs(vectors@average)<.5*lengths
                if np.any(lengths[connectors]>cfg['max_connector_length_m']):continue
                tangents=[first,last,average]
                seen=[]
                for tangent in tangents:
                    if any(np.linalg.norm(tangent-other)<1e-7 for other in seen):continue
                    seen.append(tangent);evaluated+=1
                    result=_replacement(current,start,count,tangent)
                    if result is None:rejections['parallel_adjacent_or_invalid']+=1;continue
                    proposed,meta=result
                    reason=_budget(original,proposed,max_shift,cfg)
                    if reason:rejections[reason]+=1;continue
                    reduction=_edges(current)-_edges(proposed)
                    if reduction<=0:continue
                    added=proposed.area-current.area
                    # Prefer removing many redundant vertices, at a low area
                    # cost; never choose a bigger footprint just for its size.
                    cost=added/max(reduction,1)
                    options.append((cost,-reduction,proposed,meta))
        if not options:break
        _,_,current,meta=min(options,key=lambda item:(item[0],item[1]))
        meta.update(reference_edges=_edges(current),added_area_total_m2=current.area-original.area)
        accepted.append(meta)
    return current,dict(operations=accepted,rejection_counts=dict(rejections),evaluated_replacements=evaluated)


def propose_virtual_outlines(original,settings=None):
    """Return <=3 {polygon, metadata} alternatives including unchanged outline.

    Settings affect only virtual roof construction. Geometry is local xy in m.
    The caller clips the finished roof onto the unchanged real footprint.
    """
    tick=time.perf_counter();cfg={**DEFAULTS,**(settings or {})}
    if set(cfg)-set(DEFAULTS):raise ValueError('Unknown virtual-outline setting')
    original=shape(original) if isinstance(original,dict) else original
    if original.geom_type!='Polygon' or not original.is_valid or original.area<=0:raise ValueError('Valid Polygon required')
    original=orient(original,sign=1.)
    def record(poly,label,audit):
        return dict(polygon=poly,metadata=dict(label=label,method='enclosing_wall_chains_and_convex_bevels',
            original_edges=_edges(original),reference_edges=_edges(poly),
            added_area_m2=poly.area-original.area,changed_area_fraction=(poly.area-original.area)/original.area,
            max_boundary_shift_m=poly.boundary.hausdorff_distance(original.boundary),
            covers_original=original.difference(poly).area<=1e-7,real_wall_footprint_preserved=True,
            original_footprint=mapping(original),reference_footprint=mapping(poly),settings=dict(cfg),**audit))
    result=[record(original,'raw',dict(operations=[],evaluated_replacements=0,rejection_counts={}))]
    for shift,label in ((cfg['fine_shift_m'],'collinear'),(cfg['max_shift_m'],'small_steps')):
        if len(result)>=int(cfg['max_references']):break
        poly,audit=_simplify(original,float(shift),cfg,allow_bevels=label=='small_steps')
        if _edges(poly)>=_edges(original):continue
        if any(poly.equals(item['polygon']) for item in result):continue
        audit['allowed_boundary_shift_m']=float(shift)
        result.append(record(poly,label,audit))
    for item in result:item['metadata']['proposal_total_seconds']=time.perf_counter()-tick
    return result
