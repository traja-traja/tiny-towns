"""MODULE footprint_regularization: replace repeated shallow wall teeth by a line.

Pure 2D preprocessing, no address rules and no point-cloud expansion. Long wall
segments determine the line; intersections with adjoining walls anchor its ends.
Isolated annexes, deep recesses and interior courtyard rings remain unchanged.
"""
import time
import numpy as np
from shapely.geometry import Polygon, mapping

DEFAULT_SETTINGS = dict(max_depth_m=1.25, min_repeats=3, min_span_m=6.,
    min_parallel_segment_m=.25, max_angle_deg=8., max_area_change_fraction=.10,
    max_boundary_shift_m=1.5, max_passes=8)


def _weighted_median(values, weights):
    order=np.argsort(values); values=np.asarray(values)[order]; weights=np.asarray(weights)[order]
    cumulative=np.cumsum(weights); half=cumulative[-1]/2
    i=int(np.searchsorted(cumulative,half))
    if i+1<len(values) and abs(cumulative[i]-half)<1e-8:
        return float((values[i]+values[i+1])/2)
    return float(values[i])


def _intersection(a,b,normal,offset):
    direction=b-a; denominator=float(direction@normal)
    if abs(denominator)<1e-8:
        return None
    return a+direction*((offset-float(a@normal))/denominator)


def _candidates(poly,cfg):
    points=np.asarray(poly.exterior.coords[:-1],float); n=len(points)
    edges=np.roll(points,-1,axis=0)-points; lengths=np.linalg.norm(edges,axis=1)
    cos=float(np.cos(np.deg2rad(cfg['max_angle_deg'])))
    sin=float(np.sin(np.deg2rad(cfg['max_angle_deg'])))
    for start in range(n):
        if lengths[start]<cfg['min_parallel_segment_m']:
            continue
        axis=edges[start]/lengths[start]; normal=np.array([-axis[1],axis[0]])
        chain=[points[start]]; parallel=[]; cross=[]
        for count in range(1,n-2):
            edge_index=(start+count-1)%n; edge=edges[edge_index]; length=lengths[edge_index]
            if length<1e-8:
                break
            advance=float(edge@axis); transverse=float(edge@normal)
            if advance>=cos*length and length>=cfg['min_parallel_segment_m']:
                parallel.append(edge_index)
            elif abs(advance)<=sin*length and length<=cfg['max_depth_m']*1.1:
                cross.append(transverse)
            else:
                break
            chain.append(points[(start+count)%n])
            vertices=np.asarray(chain)
            if np.ptp(vertices@normal)>cfg['max_depth_m']+1e-8:
                break
            # Three repeated excursions, rather than a single structural step.
            if len(cross)<2*cfg['min_repeats'] or len(parallel)<cfg['min_repeats']+1:
                continue
            if np.count_nonzero(np.sign(cross[1:])!=np.sign(cross[:-1]))<2*cfg['min_repeats']-1:
                continue
            direction=edges[parallel].sum(axis=0); direction/=np.linalg.norm(direction)
            norm=np.array([-direction[1],direction[0]])
            if np.ptp(vertices@direction)<cfg['min_span_m']:
                continue
            if np.ptp(vertices@norm)>cfg['max_depth_m']+1e-8:
                continue
            mid=points[parallel]+edges[parallel]/2
            offset=_weighted_median(mid@norm,lengths[parallel])
            end=(start+count)%n
            a=_intersection(points[(start-1)%n],points[start],norm,offset)
            b=_intersection(points[end],points[(end+1)%n],norm,offset)
            if a is None or b is None or (b-a)@direction<cfg['min_span_m']:
                continue
            if max(np.linalg.norm(a-points[start]),np.linalg.norm(b-points[end]))>cfg['max_boundary_shift_m']:
                continue
            # Preserve direction of both adjoining walls; no crossing a corner.
            if (a-points[(start-1)%n])@edges[(start-1)%n]<=0 or (points[(end+1)%n]-b)@edges[end]<=0:
                continue
            remainder=[points[(start+k)%n] for k in range(count+1,n)]
            proposal=Polygon([a,b,*remainder],holes=[list(r.coords) for r in poly.interiors])
            if not proposal.is_valid or proposal.area<=0:
                continue
            change=poly.symmetric_difference(proposal).area
            if change>cfg['max_area_change_fraction']*poly.area:
                continue
            shift=poly.exterior.hausdorff_distance(proposal.exterior)
            if shift>cfg['max_boundary_shift_m']:
                continue
            yield proposal,dict(removed_vertices=count-1,span_m=float(np.linalg.norm(b-a)),
                tooth_depth_m=float(np.ptp(vertices@norm)),transverse_steps=len(cross),
                line=[a.tolist(),b.tolist()],boundary_shift_m=float(shift),
                symmetric_difference_m2=float(change))


def regularize_footprint(poly,settings=None):
    """Return a valid polygon plus an auditable record of accepted wall chains."""
    tick=time.perf_counter(); cfg={**DEFAULT_SETTINGS,**(settings or {})}
    original=poly; changes=[]
    if poly.geom_type=='Polygon' and poly.is_valid:
        for _ in range(cfg['max_passes']):
            candidates=list(_candidates(poly,cfg))
            if not candidates:
                break
            candidates.sort(key=lambda item:(-item[1]['removed_vertices'],
                -round(item[1]['span_m'],6),round(item[1]['symmetric_difference_m2'],6)))
            accepted=None
            for proposal,detail in candidates:
                if original.symmetric_difference(proposal).area>cfg['max_area_change_fraction']*original.area:
                    continue
                if original.exterior.hausdorff_distance(proposal.exterior)>cfg['max_boundary_shift_m']:
                    continue
                accepted=(proposal,detail);break
            if accepted is None:
                break
            poly,detail=accepted; changes.append(detail)
    meta=dict(enabled=True,changed=bool(changes),settings=cfg,chains=changes,
        vertices_before=len(original.exterior.coords)-1,vertices_after=len(poly.exterior.coords)-1,
        area_change_m2=float(poly.area-original.area),
        symmetric_difference_m2=float(poly.symmetric_difference(original).area),
        max_displacement_m=float(original.exterior.hausdorff_distance(poly.exterior)),
        original_footprint=mapping(original),effective_footprint=mapping(poly),
        total_seconds=time.perf_counter()-tick)
    return poly,meta


def prepare_footprint(poly,config):
    if config['modules']['footprint_regularization']:
        return regularize_footprint(poly,config['footprint_regularization'])
    return poly,dict(enabled=False,changed=False,total_seconds=0.)


def attach_footprint_metadata(result,metadata):
    result.setdefault('diagnostics',{})['footprint_regularization']=metadata
    model_meta=result['model'].setdefault('metadata',{})
    if metadata['changed']:
        model_meta.update(footprint_modified=True,source_footprint=metadata['original_footprint'],
            effective_footprint=metadata['effective_footprint'],footprint_modification='repeated_shallow_wall_teeth')
    result.setdefault('timing',{})['footprint_regularization_seconds']=metadata['total_seconds']
    return result
