"""MODULE footprint_support: optional measured support before exact point clipping.

The 2D outline supplies simple cut/fill candidates. Class-6 roof coverage,
class-2 ground coverage and local measured heights decide whether to accept
them. Missing measurements alone never justify removing an annex. No addresses,
downloads, convex-hull courtyard filling or raster-shaped output geometries.
"""
from __future__ import annotations
import time
import numpy as np
import shapely
from shapely.geometry import Polygon,LineString,mapping
from shapely.ops import split
from scipy.spatial import cKDTree

DEFAULT_SETTINGS=dict(remove_unsupported=True,fill_notches=True,cell_m=.5,
    min_roof_height_m=2.5,max_ground_height_m=1.5,min_area_m2=4.,
    max_removed_area_fraction=.20,max_removed_total_fraction=.25,
    max_roof_coverage_for_removal=.025,min_ground_coverage_for_removal=.30,
    min_cut_edge_m=1.,max_removals=3,min_remaining_area_fraction=.65,
    max_notch_area_m2=30.,max_notch_area_fraction=.08,
    max_notch_opening_m=6.,max_notch_depth_m=6.,max_notch_chain_edges=6,
    min_roof_coverage_for_fill=.65,max_ground_coverage_for_fill=.10,
    min_roof_cells=12,max_notch_fills=3,neighbor_band_m=1.,
    max_neighbor_distance_m=1.5,max_height_difference_m=.65,
    neighbor_slope_allowance=.75,min_continuity_fraction=.75)


def _polygons(geometry):
    if geometry.geom_type=='Polygon' and geometry.area>1e-6:
        yield geometry
    elif hasattr(geometry,'geoms'):
        for item in geometry.geoms:yield from _polygons(item)


def _cells(xyz,size):
    if len(xyz)==0:return np.empty((0,3))
    keys=np.floor(xyz[:,:2]/size).astype(np.int64)
    _,inverse=np.unique(keys,axis=0,return_inverse=True)
    order=np.argsort(inverse,kind='stable');groups=np.split(order,np.flatnonzero(np.diff(inverse[order]))+1)
    return np.asarray([np.median(xyz[g],axis=0) for g in groups])


def _mask(poly,points):
    return shapely.intersects_xy(poly,points[:,0],points[:,1]) if len(points) else np.zeros(0,dtype=bool)


def _coverage(poly,roof,ground,cfg):
    r=_mask(poly,roof);g=_mask(poly,ground);cell_area=cfg['cell_m']**2
    return dict(area_m2=float(poly.area),roof_cells=int(r.sum()),ground_cells=int(g.sum()),
        roof_coverage_fraction=min(1.,float(r.sum()*cell_area/poly.area)),
        ground_coverage_fraction=min(1.,float(g.sum()*cell_area/poly.area)))


def _cut_candidates(poly,cfg):
    coords=np.asarray(poly.exterior.coords)[:-1];span=max(np.ptp(coords[:,0]),np.ptp(coords[:,1]))*3+5
    seen=set()
    for index,a in enumerate(coords):
        b=coords[(index+1)%len(coords)];edge=b-a;length=np.linalg.norm(edge)
        if length<cfg['min_cut_edge_m']:continue
        u=edge/length;line=LineString([a-u*span,a+u*span])
        try:pieces=list(_polygons(split(poly,line)))
        except shapely.errors.GEOSException:continue
        if len(pieces)<2:continue
        for piece in pieces:
            if not cfg['min_area_m2']<=piece.area<=poly.area*cfg['max_removed_area_fraction']:continue
            key=tuple(np.round([*piece.bounds,piece.area],5))
            if key in seen:continue
            seen.add(key);remainder=poly.difference(piece)
            if remainder.geom_type!='Polygon' or not remainder.is_valid:continue
            if len(remainder.interiors)!=len(poly.interiors):continue
            if remainder.area<cfg['min_remaining_area_fraction']*poly.area:continue
            yield piece,remainder,dict(source_edge_index=index,source_edge_xy=[a.tolist(),b.tolist()],
                cut_line_xy=list(map(list,line.coords)))


def _notch_candidates(poly,cfg):
    coords=np.asarray(poly.exterior.coords)[:-1];n=len(coords);seen=set()
    for start in range(n):
        for count in range(3,min(cfg['max_notch_chain_edges'],n-3)+1):
            chain=np.asarray([coords[(start+k)%n] for k in range(count+1)])
            opening=np.linalg.norm(chain[-1]-chain[0])
            if opening<.4 or opening>cfg['max_notch_opening_m']:continue
            pocket=Polygon(chain)
            if not pocket.is_valid or not cfg['min_area_m2']<=pocket.area<=min(cfg['max_notch_area_m2'],poly.area*cfg['max_notch_area_fraction']):continue
            if pocket.intersection(poly).area>1e-6:continue
            chord=LineString([chain[0],chain[-1]])
            if max(shapely.distance(shapely.points(chain),chord))>cfg['max_notch_depth_m']:continue
            key=tuple(np.round([*pocket.bounds,pocket.area],5))
            if key in seen:continue
            seen.add(key);filled=poly.union(pocket)
            if filled.geom_type!='Polygon' or not filled.is_valid:continue
            if len(filled.interiors)!=len(poly.interiors):continue
            if any(Polygon(h).symmetric_difference(Polygon(k)).area>1e-6 for h,k in zip(poly.interiors,filled.interiors)):continue
            yield pocket,filled,dict(start_vertex=start,chain_edges=count,opening_m=float(opening),
                closing_edge_xy=[chain[0].tolist(),chain[-1].tolist()])


def _continuity(pocket,poly,roof,cfg):
    inside=roof[_mask(pocket,roof)]
    neighbor_region=pocket.buffer(cfg['neighbor_band_m']).intersection(poly)
    neighbors=roof[_mask(neighbor_region,roof)]
    if len(inside)<cfg['min_roof_cells'] or len(neighbors)<cfg['min_roof_cells']:
        return dict(accepted=False,reason='insufficient_neighbor_roof_cells')
    # Only the joining boundary is tested, not the distant centre of a pocket.
    distance,index=cKDTree(neighbors[:,:2]).query(inside[:,:2])
    close=distance<=cfg['max_neighbor_distance_m']
    if close.sum()<cfg['min_roof_cells']:
        return dict(accepted=False,reason='no_measured_roof_connection')
    residual=abs(inside[close,2]-neighbors[index[close],2])
    tolerance=cfg['max_height_difference_m']+cfg['neighbor_slope_allowance']*distance[close]
    fraction=float(np.mean(residual<=tolerance))
    return dict(accepted=fraction>=cfg['min_continuity_fraction'],
        tested_boundary_cells=int(close.sum()),neighbor_cells=len(neighbors),
        continuous_fraction=fraction,p50_height_difference_m=float(np.median(residual)),
        p90_height_difference_m=float(np.quantile(residual,.9)),
        reason='continuous_measured_roof' if fraction>=cfg['min_continuity_fraction'] else 'height_discontinuity')


def refine_footprint(poly,xyz,classes,settings=None):
    """Return the derived Polygon and JSON-safe decisions/timing; keep inputs intact.

    XYZ must be in the same local coordinates as poly, with Z relative to local
    ground. The caller supplies the wider (unclipped) cloud and owns its source
    coverage/provenance and training/holdout policy; this routine deliberately
    cannot reconstruct those. Supply training class-6 points when preserving
    an untouched held-out geometry evaluation set.
    """
    tick=time.perf_counter();settings=settings or {}
    unknown=set(settings)-set(DEFAULT_SETTINGS)
    if unknown:raise ValueError('Unknown footprint-support setting: '+', '.join(sorted(unknown)))
    cfg={**DEFAULT_SETTINGS,**settings};original=poly
    for key,value in cfg.items():
        expected=DEFAULT_SETTINGS[key]
        if isinstance(expected,bool):
            if not isinstance(value,bool):raise ValueError(key+' must be boolean')
        elif isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or value<0:
            raise ValueError(key+' must be finite and nonnegative')
        elif isinstance(expected,int) and (not isinstance(value,int) or value<1):
            raise ValueError(key+' must be a positive integer')
    if min(cfg[k] for k in ('cell_m','min_area_m2','max_notch_area_m2','max_notch_opening_m','max_notch_depth_m','neighbor_band_m','max_neighbor_distance_m'))<=0:
        raise ValueError('Footprint-support dimensions must be positive')
    for key in ('max_removed_area_fraction','max_removed_total_fraction','max_roof_coverage_for_removal',
                'min_ground_coverage_for_removal','min_remaining_area_fraction','max_notch_area_fraction',
                'min_roof_coverage_for_fill','max_ground_coverage_for_fill','min_continuity_fraction'):
        if not 0<=cfg[key]<=1:raise ValueError(key+' must be in [0,1]')
    if cfg['max_notch_chain_edges']<3 or cfg['min_roof_cells']<3:raise ValueError('At least three notch edges and roof cells required')
    if poly.geom_type!='Polygon' or not poly.is_valid or poly.area<=0:raise ValueError('Expected a valid Polygon')
    xyz=np.asarray(xyz,float);classes=np.asarray(classes)
    if xyz.ndim!=2 or xyz.shape[1]!=3 or len(xyz)!=len(classes):raise ValueError('Expected matching XYZ and classification arrays')
    valid=np.isfinite(xyz).all(axis=1);xyz=xyz[valid];classes=classes[valid]
    # Discard unrelated wider-cache buildings cheaply before grid aggregation.
    bounds=poly.buffer(max(cfg['max_notch_depth_m'],cfg['max_notch_opening_m'])+2).bounds
    nearby=(xyz[:,0]>=bounds[0])&(xyz[:,0]<=bounds[2])&(xyz[:,1]>=bounds[1])&(xyz[:,1]<=bounds[3])
    xyz=xyz[nearby];classes=classes[nearby]
    roof=_cells(xyz[(classes==6)&(xyz[:,2]>=cfg['min_roof_height_m'])],cfg['cell_m'])
    ground=_cells(xyz[(classes==2)&(abs(xyz[:,2])<=cfg['max_ground_height_m'])],cfg['cell_m'])
    prep_seconds=time.perf_counter()-tick;decisions=[];removed=0.;added=0.;counts={'removal_candidates':0,'fill_candidates':0}
    removal_tick=time.perf_counter()
    if cfg['remove_unsupported']:
        for _ in range(cfg['max_removals']):
            accepted=[]
            for pocket,remainder,detail in _cut_candidates(poly,cfg):
                counts['removal_candidates']+=1;coverage=_coverage(pocket,roof,ground,cfg)
                reason='roof_points_present' if coverage['roof_coverage_fraction']>cfg['max_roof_coverage_for_removal'] else 'insufficient_ground_evidence' if coverage['ground_coverage_fraction']<cfg['min_ground_coverage_for_removal'] else 'supported_ground_replaces_missing_roof'
                ok=reason=='supported_ground_replaces_missing_roof' and removed+pocket.area<=cfg['max_removed_total_fraction']*original.area
                decision=dict(action='remove',accepted=False,eligible=ok,reason=reason,coverage=coverage,**detail)
                decisions.append(decision)
                if ok:accepted.append((pocket,remainder,decision))
            if not accepted:break
            pocket,poly,decision=max(accepted,key=lambda c:c[0].area)
            decision.update(accepted=True,polygon=mapping(pocket));removed+=pocket.area
    removal_seconds=time.perf_counter()-removal_tick;fill_tick=time.perf_counter()
    if cfg['fill_notches']:
        for _ in range(cfg['max_notch_fills']):
            accepted=[]
            for pocket,filled,detail in _notch_candidates(poly,cfg):
                counts['fill_candidates']+=1;coverage=_coverage(pocket,roof,ground,cfg)
                continuity=dict(accepted=False,reason='coverage_not_sufficient')
                enough=coverage['roof_coverage_fraction']>=cfg['min_roof_coverage_for_fill'] and coverage['ground_coverage_fraction']<=cfg['max_ground_coverage_for_fill'] and coverage['roof_cells']>=cfg['min_roof_cells']
                if enough:continuity=_continuity(pocket,poly,roof,cfg)
                decision=dict(action='fill',accepted=False,eligible=bool(enough and continuity['accepted']),
                    reason=continuity['reason'],coverage=coverage,continuity=continuity,**detail)
                decisions.append(decision)
                if decision['eligible']:accepted.append((pocket,filled,decision))
            if not accepted:break
            pocket,poly,decision=max(accepted,key=lambda c:c[0].area)
            decision.update(accepted=True,polygon=mapping(pocket));added+=pocket.area
    meta=dict(enabled=True,changed=bool(removed or added),settings=cfg,decisions=decisions,counts=counts,
        accepted_removals=sum(d['accepted'] and d['action']=='remove' for d in decisions),
        accepted_fills=sum(d['accepted'] and d['action']=='fill' for d in decisions),
        original_footprint=mapping(original),effective_footprint=mapping(poly),
        area_before_m2=float(original.area),area_after_m2=float(poly.area),
        removed_area_m2=float(removed),added_area_m2=float(added),
        coverage_before=_coverage(original,roof,ground,cfg),coverage_after=_coverage(poly,roof,ground,cfg),
        nearby_input_points=len(xyz),roof_cells=len(roof),ground_cells=len(ground),
        source_requirements='Wider unclipped class-2/class-6 crop; class-6 roof must be above local ground. No absence-only removal.',
        timing=dict(grid_seconds=prep_seconds,removal_seconds=removal_seconds,
            fill_seconds=time.perf_counter()-fill_tick,total_seconds=time.perf_counter()-tick))
    return poly,meta
