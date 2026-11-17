"""MODULE longitudinal_split: separate major roof-height groups by repeated profiles.
Uses the original wing/profile code; no straight-skeleton dependency or address rules.
"""
from __future__ import annotations
import math,time
import numpy as np
import shapely
from shapely.geometry import shape,mapping,LineString,Polygon
from shapely.ops import split
from roof_v2 import _cells
from roof_connected_wings import _wing_boxes,DEFAULTS as WINGS
from roof_sections import analyze_sections

DEFAULTS=dict(enabled=True,cell_m=.5,min_eave_difference_m=1.5,min_group_area_fraction=.12,
    min_profile_fraction=.50,min_volume_fraction=.15,min_volume_area_m2=40.,
    band_width_m=2.5,profile_bin_m=.6,min_side_bins=4,min_bands=3,
    min_fit_improvement_m=.15,max_position_spread_m=2.,max_reference_error_m=1.3,
    max_candidates=5,fallback_min_wing_aspect=1.,
    gate_enabled=True,gate_min_length_m=24.,gate_min_aspect=2.2,gate_min_concavity=.06,
    snap_enabled=True,snap_min_edge_m=3.,snap_max_angle_deg=8.,snap_max_move_m=1.,
    snap_max_loss_increase_m=.05,snap_selection_tolerance_m=.03,whole_selection_tolerance_m=.10,snap_max_fragment_area_m2=25.,snap_max_fragment_fraction=.05,
    long_profile_fallback=True,long_profile_band_width_m=1.5,long_profile_max_bands=11,long_profile_step_m=1.,
    long_profile_max_positions=50,long_profile_min_side_m=4.,
    long_profile_min_improvement_m=.20,long_profile_max_band_error_m=.75,
    long_profile_wall_axes=True,long_profile_min_wall_m=6.,long_profile_max_axes=3,
    long_profile_wall_axis_deviation_deg=12.,long_profile_distinct_axis_deg=1.5)


def _polygons(g):
    if g.geom_type=='Polygon' and g.area>1e-6:yield g
    elif hasattr(g,'geoms'):
        for p in g.geoms:yield from _polygons(p)


def _reference(record,xy):
    r=record['ridge'];u=np.array(record['axis_xy']);v=np.array([-u[1],u[0]])
    mid=np.mean(np.asarray(r['ridge_line_xyz'])[:,:2],axis=0)
    offset=(xy-mid)@v
    return r['ridge_height_m']-r['slope_left_tangent']*np.maximum(-offset,0)-r['slope_right_tangent']*np.maximum(offset,0)


def _loss(residual):return np.minimum(abs(residual),2.)


def _profile_prediction(model,x):
    x=np.asarray(x)-model['origin_m']
    if model['kind']=='tent':
        apex=model['apex_m'];a=np.c_[np.ones(len(x)),np.maximum(apex-x,0),np.maximum(x-apex,0)]
    else:a=np.c_[np.ones(len(x)),x]
    return a@np.asarray(model['coefficients'])


def _simple_long_profile(x,z):
    """Small robust flat/linear/tent fit, independent of a prior ridge label."""
    origin=float(np.median(x));xx=x-origin;models=[]
    def fit(a,kind,apex=None):
        beta=np.linalg.lstsq(a,z,rcond=None)[0]
        for _ in range(3):
            residual=a@beta-z
            scale=max(.15,1.4826*float(np.median(abs(residual-np.median(residual)))))
            w=np.sqrt(np.minimum(1.,scale/np.maximum(abs(residual),1e-9)))
            beta=np.linalg.lstsq(a*w[:,None],z*w,rcond=None)[0]
        if kind=='tent' and not (np.all(beta[1:]<-.05) and np.all(beta[1:]>-3.)):
            return
        model=dict(kind=kind,origin_m=origin,coefficients=beta.tolist())
        if apex is not None:model['apex_m']=float(apex)
        model['loss_m']=float(np.mean(_loss(a@beta-z)))
        models.append(model)
    fit(np.c_[np.ones(len(xx)),xx],'line')
    for apex in np.linspace(xx.min()+.15*np.ptp(xx),xx.max()-.15*np.ptp(xx),9):
        fit(np.c_[np.ones(len(xx)),np.maximum(apex-xx,0),np.maximum(xx-apex,0)],'tent',apex)
    return min(models,key=lambda m:m['loss_m'])


def _long_profile_axes(poly,cfg):
    """Keep the whole-outline direction and a few actual transverse wall normals.

    On a bent footprint the bounding box follows one wing, not necessarily the
    higher main body. Extra directions change only how evidence is sampled;
    existing height, support, snapping and two-body checks still apply.
    """
    q=np.asarray(poly.minimum_rotated_rectangle.exterior.coords)[:4]
    edges=np.roll(q,-1,axis=0)-q
    primary=edges[np.argmax(np.linalg.norm(edges,axis=1))]
    primary=primary/np.linalg.norm(primary)
    if primary[np.argmax(abs(primary))]<0:primary=-primary
    axes=[primary]
    if not cfg['long_profile_wall_axes']:return axes
    choices=[]
    for ring in [poly.exterior,*poly.interiors]:
        coords=np.asarray(ring.coords)
        for p,q in zip(coords[:-1],coords[1:]):
            edge=q-p;length=float(np.linalg.norm(edge))
            if length<cfg['long_profile_min_wall_m']:continue
            normal=np.array([-edge[1],edge[0]])/length
            if normal@primary<0:normal=-normal
            angle=math.degrees(math.acos(float(np.clip(normal@primary,-1,1))))
            if angle<=cfg['long_profile_wall_axis_deviation_deg']:
                choices.append((length,normal))
    for _,axis in sorted(choices,key=lambda item:-item[0]):
        if all(math.degrees(math.acos(float(np.clip(abs(axis@other),0,1))))>=cfg['long_profile_distinct_axis_deg'] for other in axes):
            axes.append(axis)
        if len(axes)>=cfg['long_profile_max_axes']:break
    return axes


def _long_building_fallback(poly,cells,cfg,base,tick):
    if not cfg['long_profile_fallback'] or not base['eligibility']['accepted'] or len(cells)<40:
        return None
    initial_counts=dict(base['counts']);totals=dict(initial_counts)
    audits=[];candidates=[];axes=_long_profile_axes(poly,cfg)
    for axis in axes:
        local=dict(base,counts=dict(initial_counts))
        result=_long_profile_for_axis(poly,cells,cfg,local,tick,axis)
        audit=local.get('long_profile_fallback',{})
        audits.append(audit)
        for key in ('longitudinal_bands_examined','longitudinal_bands_evaluated',
                    'cut_positions_tested','snapped_edge_alternatives_tested'):
            totals[key]+=local['counts'][key]-initial_counts[key]
        totals['longitudinal_bands_with_transition']=max(totals['longitudinal_bands_with_transition'],local['counts']['longitudinal_bands_with_transition'])
        if result:
            for proposal in result['candidates']:
                proposal['profile_axis_xy']=axis.tolist()
                candidates.append(proposal)
    chosen=[]
    for proposal in sorted(candidates,key=lambda p:p['score']):
        pieces=[shape(p) for p in proposal['footprints']]
        duplicate=False
        for other in chosen:
            previous=[shape(p) for p in other['footprints']]
            difference=min(sum(a.symmetric_difference(b).area for a,b in zip(pieces,previous)),
                           sum(a.symmetric_difference(b).area for a,b in zip(pieces,reversed(previous))))
            if difference<1e-5:
                duplicate=True;break
        if not duplicate:chosen.append(proposal)
        if len(chosen)>=cfg['max_candidates']:break
    # Retain legacy first-axis fields for consumers, and expose all extra work.
    audit=dict(audits[0]) if audits else {}
    audit.update(axes_examined=len(axes),axis_trials=audits,
        status='supported_change' if chosen else audit.get('status','no_supported_change'))
    base['long_profile_fallback']=audit
    totals.update(profile_axes_examined=len(axes),distinct_cut_candidates=len(chosen),
        supporting_bands=max((p['supported_bands'] for p in chosen),default=0))
    base['counts']=totals
    if not chosen:return None
    return dict(base,candidates=chosen,reason='supported_long_profile_model_change',
                timing={'total_seconds':time.perf_counter()-tick})


def _long_profile_for_axis(poly,cells,cfg,base,tick,u):
    """Repeated profiles of an eligible long/bent house, before roof types.

    A transverse main roof followed by a low longitudinal wing has no pair of
    whole-wing ridge references. Compare one simple profile with two locally
    fitted profiles instead. Only repeated large level changes generate cuts;
    the full roof pipeline still decides whether to accept the two volumes.
    """
    u=np.asarray(u,float)
    v=np.array([-u[1],u[0]]);x=cells[:,:2]@u;y=cells[:,:2]@v;z=cells[:,2]
    width=cfg['long_profile_band_width_m'];bands=[]
    centers=np.arange(y.min()+width/2,y.max(),width)
    if len(centers)>cfg['long_profile_max_bands']:
        centers=centers[np.linspace(0,len(centers)-1,cfg['long_profile_max_bands']).astype(int)]
    for center in centers:
        mask=abs(y-center)<=width/2
        if mask.sum()<20:continue
        buckets=np.floor(x[mask]/cfg['profile_bin_m']).astype(int);idx=np.flatnonzero(mask)
        rows=np.array([[np.median(x[idx[buckets==b]]),np.median(z[idx[buckets==b]])] for b in np.unique(buckets)])
        if len(rows)<2*cfg['min_side_bins']:continue
        bands.append(dict(center=float(center),x=rows[:,0],z=rows[:,1],whole=_simple_long_profile(rows[:,0],rows[:,1])))
    counts=base['counts']
    counts['longitudinal_bands_examined']+=len(bands)
    counts['longitudinal_bands_evaluated']+=len(bands)
    audit=dict(axis_xy=u.tolist(),bands=len(bands),tested_positions=0,supported_positions=[],status='insufficient_bands')
    base['long_profile_fallback']=audit
    if len(bands)<cfg['min_bands']:return None
    coordinates=np.arange(x.min()+cfg['long_profile_min_side_m'],x.max()-cfg['long_profile_min_side_m'],cfg['long_profile_step_m'])
    if len(coordinates)>cfg['long_profile_max_positions']:
        coordinates=coordinates[np.linspace(0,len(coordinates)-1,cfg['long_profile_max_positions']).astype(int)]
    audit.update(tested_positions=len(coordinates),status='no_supported_change')
    counts['cut_positions_tested']+=len(coordinates)
    candidates=[];tested=[];extent=float(max(np.ptp(x),np.ptp(y))*3+5)
    for coordinate in coordinates:
        fits=[];support=[]
        for band in bands:
            xx,zz=band['x'],band['z'];left=xx<=coordinate
            if min(int(left.sum()),int((~left).sum()))<cfg['min_side_bins']:continue
            if min(np.ptp(xx[left]),np.ptp(xx[~left]))<cfg['long_profile_min_side_m']:continue
            # A courtyard gap cannot by itself locate a transition.
            if xx[~left].min()-xx[left].max()>2.:continue
            a=_simple_long_profile(xx[left],zz[left]);b=_simple_long_profile(xx[~left],zz[~left])
            residual=np.r_[_loss(_profile_prediction(a,xx[left])-zz[left]),_loss(_profile_prediction(b,xx[~left])-zz[~left])]
            loss=float(np.mean(residual));gain=band['whole']['loss_m']-loss
            difference=float(np.quantile(zz[left],.1)-np.quantile(zz[~left],.1))
            fits.append((band,a,b))
            if gain>=cfg['long_profile_min_improvement_m'] and loss<=cfg['long_profile_max_band_error_m'] and abs(difference)>=cfg['min_eave_difference_m']:
                support.append(dict(cross_m=band['center'],gain_m=gain,loss_m=loss,height_difference_m=difference))
        if len(support)<cfg['min_bands']:continue
        counts['longitudinal_bands_with_transition']=max(counts['longitudinal_bands_with_transition'],len(support))
        signs=np.sign([r['height_difference_m'] for r in support])
        if max(np.count_nonzero(signs>0),np.count_nonzero(signs<0))<max(cfg['min_bands'],math.ceil(.75*len(support))):continue
        line=LineString([coordinate*u-extent*v,coordinate*u+extent*v])
        pieces=list(_polygons(split(poly,line)))
        pieces,merged=_join_small_cut_fragments(poly,pieces,cfg)
        if len(pieces)!=2:continue
        pieces.sort(key=lambda p:np.asarray(p.centroid.coords[0])@u)
        if shapely.union_all(pieces).symmetric_difference(poly).area>1e-6:continue
        # Nearest measured strip supplies predictions only for locating/snapping
        # the cut. It is not exported as the final roof surface.
        nearest=np.argmin(abs(y[:,None]-np.array([f[0]['center'] for f in fits])),axis=1)
        errors=[]
        for side in (1,2):
            prediction=np.empty(len(cells))
            for i,f in enumerate(fits):
                mask=nearest==i;prediction[mask]=_profile_prediction(f[side],x[mask])
            errors.append(_loss(prediction-z))
        score=float(np.mean(np.where(x<=coordinate,errors[0],errors[1])))
        proposal=dict(score=score,cut_line_xy=list(map(list,line.coords)),coordinate_m=float(coordinate),normal_xy=u.tolist(),
            footprints=[mapping(p) for p in pieces],area_m2=[p.area for p in pieces],supported_bands=len(support),
            transition_spread_m=0.,height_difference_m=float(np.median(abs(np.array([r['height_difference_m'] for r in support])))),
            method='repeated_long_profile_model_change',supporting_profiles=support,
            small_fragments_rejoined=merged)
        proposal=snap_partition(poly,proposal,cells,*errors,cfg)
        counts['snapped_edge_alternatives_tested']+=proposal['snapping']['tested_edges']
        candidates.append(proposal);tested.append(dict(coordinate_m=float(coordinate),supporting_bands=len(support),score=score))
    candidates.sort(key=lambda p:p['score']);chosen=[]
    for candidate in candidates:
        if all(abs(candidate['coordinate_m']-p['coordinate_m'])>=.75 for p in chosen):chosen.append(candidate)
        if len(chosen)>=cfg['max_candidates']:break
    audit['supported_positions']=tested
    if not chosen:return None
    audit['status']='supported_change'
    counts.update(supporting_bands=max(p['supported_bands'] for p in chosen),distinct_cut_candidates=len(chosen))
    base=dict(base,candidates=chosen)
    return dict(**base,reason='supported_long_profile_model_change',timing={'total_seconds':time.perf_counter()-tick})


def footprint_gate(poly,config=None):
    """MODULE eligibility: cheap 2D gate before reading/measuring roof profiles."""
    cfg={**DEFAULTS,**(config or {})}
    if not cfg['gate_enabled']:return dict(accepted=True,reasons=['gate_disabled'],
        shape_candidate=True,area_sufficient_for_split=poly.area>=2*cfg['min_volume_area_m2'])
    q=np.asarray(poly.minimum_rotated_rectangle.exterior.coords)[:4]
    lengths=np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)
    long,short=float(lengths.max()),float(lengths.min())
    aspect=long/max(short,1e-9);concavity=1-poly.area/poly.convex_hull.area
    reasons=[]
    if long>=cfg['gate_min_length_m'] and aspect>=cfg['gate_min_aspect']:reasons.append('long_building')
    if concavity>=cfg['gate_min_concavity']:reasons.append('bent_or_large_annex')
    if sum(Polygon(r).area for r in poly.interiors)>=cfg['min_volume_area_m2']:reasons.append('courtyard')
    enough_area=poly.area>=2*cfg['min_volume_area_m2']
    return dict(accepted=bool(reasons and enough_area),shape_candidate=bool(reasons),area_sufficient_for_split=enough_area,
        reasons=reasons if enough_area else ['too_small_for_two_volumes'],
        length_m=long,aspect=aspect,concavity=concavity,area_m2=poly.area)


def snap_partition(poly,proposal,cells,high_error,low_error,config=None):
    """MODULE cut alignment: extend an original wall edge, preserve total outline.

    Only change an internal partition. Never independently simplify both child
    polygons: that can create overlaps/gaps and move the public-facing outline.
    The extension contains the exact original edge endpoints to avoid slivers
    caused solely by extending a nearly collinear line in floating arithmetic.
    """
    cfg={**DEFAULTS,**(config or {})}
    original=dict(proposal)
    fallback=dict(applied=False,reason='disabled' if not cfg['snap_enabled'] else 'no_supported_nearby_edge',tested_edges=0)
    original['snapping']=fallback
    if not cfg['snap_enabled']:return original
    a,b=np.asarray(proposal['cut_line_xy'])[[0,-1]]
    tangent=(b-a)/np.linalg.norm(b-a);normal=np.array([tangent[1],-tangent[0]])
    coordinate=float(a@normal)
    actual=shapely.get_coordinates(LineString([a,b]).intersection(poly))
    extent=max(poly.bounds[2]-poly.bounds[0],poly.bounds[3]-poly.bounds[1])*3+5
    choices=[];checks=0
    for ring_index,ring in enumerate([poly.exterior,*poly.interiors]):
        coords=np.asarray(ring.coords)
        for edge_index,(p,q) in enumerate(zip(coords[:-1],coords[1:])):
            length=float(np.linalg.norm(q-p))
            if length<cfg['snap_min_edge_m']:continue
            direction=(q-p)/length
            angle=math.degrees(math.acos(float(np.clip(abs(direction@tangent),0,1))))
            if angle>cfg['snap_max_angle_deg']:continue
            if abs(float(((p+q)/2)@normal-coordinate))>cfg['snap_max_move_m']:continue
            n=np.array([direction[1],-direction[0]])
            if n@normal<0:n=-n
            offset=float(p@n)
            move=float(np.max(abs(actual@n-offset))) if len(actual) else float('inf')
            if move>cfg['snap_max_move_m']:continue
            checks+=1
            line_coords=[p-extent*direction,p,q,q+extent*direction]
            if np.array([direction[1],-direction[0]])@n<0:line_coords.reverse()
            line=LineString(line_coords)
            pieces=list(_polygons(split(poly,line)))
            pieces,merged=_join_small_cut_fragments(poly,pieces,cfg)
            if len(pieces)!=2:continue
            union=shapely.union_all(pieces)
            if union.symmetric_difference(poly).area>1e-6 or pieces[0].intersection(pieces[1]).area>1e-6:continue
            pieces.sort(key=lambda x:np.asarray(x.centroid.coords[0])@n)
            high_side=shapely.intersects_xy(pieces[0],cells[:,0],cells[:,1])
            loss=float(np.mean(np.where(high_side,high_error,low_error)))
            if loss>proposal['score']+cfg['snap_max_loss_increase_m']:continue
            # Prefer the dominant original wall among equally plausible edges.
            choices.append((length,-loss,dict(proposal,score=loss,cut_line_xy=list(map(list,line.coords)),
                normal_xy=n.tolist(),coordinate_m=offset,footprints=[mapping(x) for x in pieces],area_m2=[x.area for x in pieces],
                snapping=dict(applied=True,reason='nearby_original_footprint_edge',source_ring_index=ring_index,
                    source_edge_index=edge_index,source_edge_xy=[p.tolist(),q.tolist()],source_edge_length_m=length,
                    angle_change_deg=angle,max_line_move_m=move,loss_before_m=proposal['score'],loss_after_m=loss,
                    original_cut_line_xy=proposal['cut_line_xy'],small_fragments_rejoined=merged,
                    outline_symmetric_difference_m2=union.symmetric_difference(poly).area))))
    if not choices:
        fallback['tested_edges']=checks
        return original
    selected=max(choices,key=lambda x:x[:2])[2]
    selected['snapping']['tested_edges']=checks
    return selected


def _join_small_cut_fragments(poly,pieces,cfg):
    """Keep small cut-off projections attached by a real shared boundary.

    Do not invent bridges or discard area. More than two substantial bodies,
    point-only contacts or an excessive fragment budget reject this snap.
    """
    threshold=max(cfg['min_volume_area_m2'],poly.area*cfg['min_volume_fraction'])
    major=[p for p in pieces if p.area>=threshold]
    small=[p for p in pieces if p.area<threshold]
    limit=min(cfg['snap_max_fragment_area_m2'],poly.area*cfg['snap_max_fragment_fraction'])
    if len(major)!=2 or sum(p.area for p in small)>limit:return [],[]
    joined=[]
    for fragment in sorted(small,key=lambda p:-p.area):
        options=[]
        for i,body in enumerate(major):
            shared=fragment.boundary.intersection(body.boundary).length
            if shared<=.05:continue
            union=body.union(fragment)
            if union.geom_type=='Polygon' and union.is_valid:options.append((shared,i,union))
        if not options:return [],[]
        shared,index,union=max(options,key=lambda x:x[0]);major[index]=union
        joined.append(dict(area_m2=fragment.area,shared_boundary_m=shared,footprint=mapping(fragment)))
    return major,joined


def _ridge_references(record):
    """Do not discard a second supported roof track across a courtyard.

    If a broad provisional wing sees several distinct roof strips, each track
    gets only its measured strip as an area reference. Reusing the complete
    provisional domain would let a tiny roof claim the whole building's area.
    """
    tracks=[r for r in record.get('ridge_tracks',[]) if r.get('supported')]
    if len(tracks)<=1:
        if record.get('ridge'):return [record]
        return []
    u=np.asarray(record['axis_xy']);v=np.asarray(record['cross_axis_xy'])
    origin=np.asarray(record['origin_xy']);domain=shape(record['domain'])
    references=[]
    for ridge in tracks:
        measured=np.asarray(ridge.get('ridge_measurements_xyz',[]),float)
        if not len(measured):continue
        sections=[]
        for section in record['sections']:
            fit=section['fit']
            if fit['kind']!='pitched':continue
            xy=origin+u*section['u_m']+v*fit['ridge_v_m']
            if np.min(np.linalg.norm(measured[:,:2]-xy,axis=1))<1e-5:
                sections.append(section)
        if len(sections)<2:continue
        along=np.array([s['u_m'] for s in sections]);margin=float(np.median(np.diff(np.sort(along))))/2
        lo,hi=float(along.min()-margin),float(along.max()+margin)
        left=min(s['v_range_m'][0] for s in sections);right=max(s['v_range_m'][1] for s in sections)
        rectangle=Polygon([origin+u*a+v*b for a,b in ((lo,left),(hi,left),(hi,right),(lo,right))])
        local=domain.intersection(rectangle)
        if local.is_empty:continue
        references.append({**record,'ridge':ridge,'domain':mapping(local),'area_m2':local.area,
                           'reference_track_id':ridge['track_id']})
    return references


def detect_longitudinal_split(footprint,points,config=None,*,split_depth=0):
    tick=time.perf_counter();cfg={**DEFAULTS,**(config or {})}
    if set(cfg)-set(DEFAULTS):raise ValueError('Unknown longitudinal split settings')
    if not cfg['enabled']:return dict(candidates=[],reason='disabled',settings=cfg,timing={'total_seconds':0.})
    if split_depth>=1:return dict(candidates=[],reason='child_volume_splitting_disabled',settings=cfg,timing={'total_seconds':0.})
    poly=shape(footprint) if isinstance(footprint,dict) else footprint
    eligibility=footprint_gate(poly,cfg)
    if not eligibility['accepted']:return dict(candidates=[],reason='footprint_gate_rejected',eligibility=eligibility,settings=cfg,timing={'total_seconds':time.perf_counter()-tick})
    points=np.asarray(points,float);points=points[np.isfinite(points).all(axis=1)]
    points=points[shapely.intersects_xy(poly,points[:,0],points[:,1])];cells=_cells(points,cfg['cell_m'])
    wings,layout=_wing_boxes(poly,{**WINGS,'_outer_ends':False})
    # A wide, short pair can span almost the whole U and hide its real arms.
    # Only retry such a single-wing concave layout with elongated seed spans;
    # already established multi-wing layouts stay unchanged.
    if len(wings)<2 and 1-poly.area/poly.convex_hull.area>WINGS['min_concavity_fraction']:
        retry,retry_layout=_wing_boxes(poly,{**WINGS,'_outer_ends':False,
            'min_wing_aspect':cfg['fallback_min_wing_aspect']})
        if len(retry)>len(wings):
            wings,layout=retry,{**retry_layout,'profile_layout_fallback':'elongated_seed_spans'}
    profiles=[]
    for i,w in enumerate(wings):
        p=analyze_sections(poly,points,axis=w['u'],domain=w['inside'])
        p.update(wing_index=i,domain=mapping(w['inside']),area_m2=w['inside'].area)
        profiles.append(p)
    references=[r for profile in profiles for r in _ridge_references(profile)]
    supported=[r for r in references if r.get('ridge',{} ) and r['ridge'].get('supported')
        and r['ridge']['support_fraction']>=cfg['min_profile_fraction']
        and r['area_m2']>=poly.area*cfg['min_group_area_fraction']]
    counts=dict(transverse_sections_measured=sum(len(p.get('sections',[])) for p in profiles),
        longitudinal_bands_examined=0,longitudinal_bands_evaluated=0,
        longitudinal_bands_with_transition=0,supporting_bands=0,cut_positions_tested=0,
        snapped_edge_alternatives_tested=0,distinct_cut_candidates=0)
    base=dict(settings=cfg,profiles=profiles,references=references,candidates=[],layout=layout,eligibility=eligibility,counts=counts,
        interpretation='Geometric roof-height volumes, not legally separate buildings; profile transition need not be a vertical step.')
    if len(supported)<2:
        fallback=_long_building_fallback(poly,cells,cfg,base,tick)
        return fallback or dict(**base,reason='insufficient_supported_wings',timing={'total_seconds':time.perf_counter()-tick})
    # Cluster measured eave heights; wide and narrow wings at the same eave stay together.
    ordered=sorted(supported,key=lambda r:r['ridge']['eave_height_m']);groups=[]
    for r in ordered:
        if groups and r['ridge']['eave_height_m']-np.median([x['ridge']['eave_height_m'] for x in groups[-1]])<cfg['min_eave_difference_m']:
            groups[-1].append(r)
        else:groups.append([r])
    if len(groups)<2:
        fallback=_long_building_fallback(poly,cells,cfg,base,tick)
        return fallback or dict(**base,reason='one_supported_eave_level',timing={'total_seconds':time.perf_counter()-tick})
    low,high=groups[0],groups[-1]
    eh=float(np.median([r['ridge']['eave_height_m'] for r in high]));el=float(np.median([r['ridge']['eave_height_m'] for r in low]))
    dominant=max(high,key=lambda r:r['area_m2'])
    tangent=np.array(dominant['axis_xy']);normal=np.array([-tangent[1],tangent[0]])
    hc=np.array(shape(dominant['domain']).centroid.coords[0]);lc=np.mean([shape(r['domain']).centroid.coords[0] for r in low],axis=0)
    if (lc-hc)@normal<0:normal=-normal
    tangent=np.array([-normal[1],normal[0]])
    xy=cells[:,:2];z=cells[:,2];long=xy@normal;cross=xy@tangent
    # Union of low wing tents keeps its L/U connection in this cheap predictor.
    high_z=np.max([_reference(r,xy) for r in high],axis=0)
    low_z=np.maximum(el,np.max([_reference(r,xy) for r in low],axis=0))
    eh_err=_loss(high_z-z);el_err=_loss(low_z-z)
    reliable=np.minimum(abs(high_z-z),abs(low_z-z))<cfg['max_reference_error_m']
    rows=[]
    for center in np.arange(cross.min()+cfg['band_width_m']/2,cross.max(),cfg['band_width_m']):
        counts['longitudinal_bands_examined']+=1
        mask=(abs(cross-center)<=cfg['band_width_m']/2)&reliable
        if mask.sum()<20:continue
        bins=np.floor(long[mask]/cfg['profile_bin_m']).astype(int)
        data=[]
        for bucket in np.unique(bins):
            selected=np.flatnonzero(mask)[bins==bucket]
            data.append([float(np.median(long[selected])),float(np.median(z[selected])),
                float(np.median(eh_err[selected])),float(np.median(el_err[selected])),len(selected)])
        samples=np.array(data);n=len(samples)
        if n<2*cfg['min_side_bins']:continue
        counts['longitudinal_bands_evaluated']+=1
        best=None
        for j in range(cfg['min_side_bins'],n-cfg['min_side_bins']+1):
            # Large courtyard gaps give an interval, not a precise measured boundary.
            gap=samples[j,0]-samples[j-1,0]
            cost=float(np.mean(np.r_[samples[:j,2],samples[j:,3]]))
            if best is None or cost<best[0]:best=(cost,j,gap)
        cost,j,gap=best;unsplit=min(float(np.mean(samples[:,2])),float(np.mean(samples[:,3])))
        gain=unsplit-cost
        enough_high=np.mean(samples[:j,2]+.1<samples[:j,3])>=.5
        enough_low=np.mean(samples[j:,3]+.1<samples[j:,2])>=.5
        if gain<cfg['min_fit_improvement_m'] or not(enough_high and enough_low):continue
        position=float((samples[j,0]+samples[j-1,0])/2)
        rows.append(dict(cross_m=float(center),position_m=position,transition_interval_m=[float(samples[j-1,0]),float(samples[j,0])],
            gap_m=float(gap),gain_m=gain,high_bins=j,low_bins=n-j,samples_szhigherrlowerrcount=samples.tolist(),
            precise=bool(gap<2.0)))
    precise=[r for r in rows if r['precise']]
    counts['longitudinal_bands_with_transition']=len(rows)
    base.update(eave_groups=[dict(eave_height_m=el,wing_indices=[r['wing_index'] for r in low]),
        dict(eave_height_m=eh,wing_indices=[r['wing_index'] for r in high])],
        longitudinal_profiles=rows,normal_xy=normal.tolist(),tangent_xy=tangent.tolist())
    if len(precise)<cfg['min_bands']:return dict(**base,reason='insufficient_repeated_longitudinal_transitions',timing={'total_seconds':time.perf_counter()-tick})
    positions=np.array([r['position_m'] for r in precise]);middle=float(np.median(positions))
    coherent=[r for r in precise if abs(r['position_m']-middle)<=cfg['max_position_spread_m']]
    counts['supporting_bands']=len(coherent)
    if len(coherent)<cfg['min_bands']:return dict(**base,reason='inconsistent_longitudinal_transitions',timing={'total_seconds':time.perf_counter()-tick})
    # Search only the measured transition interval, not arbitrary subdivisions.
    lo=min(r['transition_interval_m'][0] for r in coherent)-.5;hi=max(r['transition_interval_m'][1] for r in coherent)+.5
    extent=max(poly.bounds[2]-poly.bounds[0],poly.bounds[3]-poly.bounds[1])*3+5
    proposals=[]
    for coordinate in np.arange(lo,hi+.001,.25):
        counts['cut_positions_tested']+=1
        center=normal*coordinate;line=LineString([center-extent*tangent,center+extent*tangent])
        parts=list(_polygons(split(poly,line)))
        if len(parts)!=2 or min(p.area for p in parts)<max(cfg['min_volume_area_m2'],poly.area*cfg['min_volume_fraction']):continue
        parts.sort(key=lambda p:np.array(p.centroid.coords[0])@normal)
        side=long<=coordinate
        score=float(np.mean(np.where(side,eh_err,el_err)))
        proposals.append(dict(score=score,cut_line_xy=list(map(list,line.coords)),coordinate_m=float(coordinate),
            footprints=[mapping(p) for p in parts],area_m2=[p.area for p in parts],
            supported_bands=len(coherent),transition_spread_m=float(np.ptp([r['position_m'] for r in coherent])),
            height_difference_m=eh-el,method='repeated_longitudinal_roof_system_transition'))
    proposals.sort(key=lambda p:p['score'])
    # Keep geometrically distinct cut options for the original roof generator.
    chosen=[]
    for p in proposals:
        if all(abs(p['coordinate_m']-q['coordinate_m'])>=.75 for q in chosen):chosen.append(p)
        if len(chosen)>=cfg['max_candidates']:break
    aligned=[]
    for proposal in chosen:
        proposal=snap_partition(poly,proposal,cells,eh_err,el_err,cfg)
        counts['snapped_edge_alternatives_tested']+=proposal['snapping']['tested_edges']
        # Several nearby scan positions may snap onto the very same wall.
        if any(sum(shape(p).symmetric_difference(shape(q)).area for p,q in zip(proposal['footprints'],other['footprints']))<1e-5 for other in aligned):continue
        aligned.append(proposal)
    counts['distinct_cut_candidates']=len(aligned)
    base['candidates']=aligned
    return dict(**base,reason='supported_height_group_transition' if aligned else 'no_valid_two_part_cut',timing={'total_seconds':time.perf_counter()-tick})
