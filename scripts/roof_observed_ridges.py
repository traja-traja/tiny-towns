"""MODULE observed_ridges: independent, bounded point-profile diagnostics.

No model ridge seeds, no raw maxima, no address rules. Wall directions seed
cross sections; location/height/extent need two measured descending flanks
in repeated sections. Training points only. This does NOT move model geometry.
"""
from __future__ import annotations
import copy,math,time
import numpy as np
import shapely
from shapely.geometry import shape,LineString
from roof_v2 import _cells

VERSION='point-profile-ridges-1'
DEFAULTS=dict(cell_m=.5,edge_exclusion_m=.65,min_wall_m=2.,max_axes=6,
    axis_merge_degrees=10.,slice_step_m=1.2,slice_width_m=1.6,profile_bin_m=.5,
    flank_window_m=4.5,min_flank_span_m=1.5,min_flank_bins=3,
    min_slope=.14,max_slope=2.5,max_profile_error_m=.28,
    min_prominence_m=.45,track_gap_slices=2,track_offset_m=1.2,
    track_height_step_m=.7,min_length_m=3.6,min_sections=4,
    max_height_span_m=.65,max_ridge_grade=.07,max_line_error_m=.4,
    max_direction_adjust_degrees=15.,max_lines=8)


def _axes(poly,cfg):
    entries=[]
    for ring in [poly.exterior,*poly.interiors]:
        q=np.asarray(ring.coords)
        for a,b in zip(q[:-1],q[1:]):
            d=b-a;length=float(np.linalg.norm(d))
            if length>=cfg['min_wall_m']:entries.append((math.atan2(d[1],d[0])%math.pi,length))
    entries.sort(key=lambda x:-x[1]);groups=[]
    for angle,length in entries:
        near=next((g for g in groups if abs(math.atan2(math.sin(2*(angle-g[0])),math.cos(2*(angle-g[0]))))/2<math.radians(cfg['axis_merge_degrees'])),None)
        if near is None:groups.append([angle,length])
        else:
            vector=near[1]*np.exp(2j*near[0])+length*np.exp(2j*angle)
            near[:]=[float(np.angle(vector)/2)%math.pi,near[1]+length]
    return [g[0] for g in sorted(groups,key=lambda g:-g[1])[:int(cfg['max_axes'])]]


def _profile_peaks(v,z,cfg):
    bins=np.floor(v/cfg['profile_bin_m']).astype(int)
    keys=np.unique(bins)
    y=np.array([np.median(v[bins==k]) for k in keys]);h=np.array([np.median(z[bins==k]) for k in keys])
    if len(y)<2*cfg['min_flank_bins']+1:return []
    peaks=[]
    for center in y[1:-1]:
        mask=abs(y-center)<=cfg['flank_window_m'];yy=y[mask];zz=h[mask]
        left=yy<center-.15;right=yy>center+.15
        if left.sum()<cfg['min_flank_bins'] or right.sum()<cfg['min_flank_bins']:continue
        if center-min(yy)<cfg['min_flank_span_m'] or max(yy)-center<cfg['min_flank_span_m']:continue
        best=None
        for c in (center-.20,center,center+.20):
            A=np.c_[np.ones(len(yy)),-np.maximum(c-yy,0),-np.maximum(yy-c,0)]
            coef=np.linalg.lstsq(A,zz,rcond=None)[0]
            for _ in range(2):
                err=A@coef-zz;weight=np.minimum(1.,.22/np.maximum(abs(err),1e-6))
                coef=np.linalg.lstsq(A*np.sqrt(weight[:,None]),zz*np.sqrt(weight),rcond=None)[0]
            error=float(np.quantile(abs(A@coef-zz),.7))
            if min(coef[1:])<cfg['min_slope'] or max(coef[1:])>cfg['max_slope']:continue
            if min(coef[1]*(c-min(yy)),coef[2]*(max(yy)-c))<cfg['min_prominence_m']:continue
            if error>cfg['max_profile_error_m']:continue
            item=dict(across=float(c),height=float(coef[0]),error=error,left_slope=float(coef[1]),right_slope=float(coef[2]),bins=len(yy))
            if best is None or error<best['error']:best=item
        if best is not None:peaks.append(best)
    keep=[]
    for peak in sorted(peaks,key=lambda p:p['error']):
        if all(abs(peak['across']-k['across'])>=cfg['min_flank_span_m']*1.5 for k in keep):keep.append(peak)
    return keep


def _tracks(records,cfg):
    tracks=[]
    for section in records:
        used=set()
        for p in sorted(section,key=lambda p:p['error']):
            options=[]
            for i,track in enumerate(tracks):
                last=track[-1];gap=p['along']-last['along']
                if i in used or gap<=0 or gap>cfg['slice_step_m']*(cfg['track_gap_slices']+.01):continue
                if abs(p['across']-last['across'])>cfg['track_offset_m']:continue
                if abs(p['height']-last['height'])>cfg['track_height_step_m']:continue
                options.append((abs(p['across']-last['across'])+abs(p['height']-last['height']),i))
            if options:
                _,index=min(options);tracks[index].append(p);used.add(index)
            else:tracks.append([p]);used.add(len(tracks)-1)
    return tracks


def _segments(track,axis,origin,cfg):
    # Maximal supported near-horizontal spans. Never extend to the footprint
    # boundary or across missing sections just because the model does so.
    found=[];n=len(track)
    if n<cfg['min_sections']:return found
    t=np.array([p['along'] for p in track]);v=np.array([p['across'] for p in track]);z=np.array([p['height'] for p in track])
    for a in range(n-int(cfg['min_sections'])+1):
        for b in range(n,a+int(cfg['min_sections'])-1,-1):
            if any(a>=x[0] and b<=x[1] for x in found):break
            tt=t[a:b];vv=v[a:b];zz=z[a:b]
            if tt[-1]-tt[0]<cfg['min_length_m']:continue
            A=np.c_[tt-tt.mean(),np.ones(len(tt))]
            lateral=np.linalg.lstsq(A,vv,rcond=None)[0];vertical=np.linalg.lstsq(A,zz,rcond=None)[0]
            span=float(np.quantile(zz,.9)-np.quantile(zz,.1));error=float(np.quantile(abs(A@lateral-vv),.8))
            if span>cfg['max_height_span_m'] or abs(vertical[0])>cfg['max_ridge_grade'] or error>cfg['max_line_error_m']:continue
            if abs(math.degrees(math.atan(lateral[0])))>cfg['max_direction_adjust_degrees']:continue
            found.append((a,b,lateral,span,error));break
    u=np.array([math.cos(axis),math.sin(axis)]);w=np.array([-u[1],u[0]])
    result=[]
    for a,b,lateral,span,error in found:
        tt=t[a:b];height=float(np.median(z[a:b]));ends=np.array([tt[0],tt[-1]])
        across=(ends-tt.mean())*lateral[0]+lateral[1]
        xy=origin+ends[:,None]*u+across[:,None]*w
        length=float(np.linalg.norm(xy[1]-xy[0]));sections=b-a
        confidence='supported' if sections>=6 and span<=.45 and error<=.25 else 'tentative'
        result.append(dict(points=np.c_[xy,np.full(2,height)].tolist(),source='point_profiles',role='secondary',
            confidence=confidence,length_m=length,height_m=height,section_count=sections,
            height_p10_p90_span_m=span,lateral_p80_error_m=error,
            profile_median_error_m=float(np.median([p['error'] for p in track[a:b]])),
            observed_height_range_m=[float(min(z[a:b])),float(max(z[a:b]))],
            extent_policy='First to last supported section; not extended to wall',
            support_sections=[dict(point=(origin+p['along']*u+p['across']*w).tolist()+[p['height']],
                error_m=p['error'],left_slope=p['left_slope'],right_slope=p['right_slope']) for p in track[a:b]]))
    return result


def detect_volume_ridges(footprint,points,settings=None,volume_id=1):
    tick=time.perf_counter();cfg={**DEFAULTS,**(settings or {})}
    poly=shape(footprint) if isinstance(footprint,dict) else footprint
    pts=np.asarray(points,float);pts=pts[np.isfinite(pts).all(axis=1)]
    pts=pts[shapely.intersects_xy(poly,pts[:,0],pts[:,1])]
    if len(pts)<12:
        return dict(volume_id=volume_id,status='not_detected',reason='insufficient_training_points',lines=[],input_points=len(pts),seconds=time.perf_counter()-tick)
    cells=_cells(pts,cfg['cell_m']);inside=shapely.distance(shapely.points(cells[:,:2]),poly.boundary)>=cfg['edge_exclusion_m'] if len(cells) else np.zeros(0,bool)
    cells=cells[inside];origin=np.asarray(poly.centroid.coords[0]);axes=_axes(poly,cfg)
    lines=[];profile_count=0;peak_count=0
    for axis in axes:
        u=np.array([math.cos(axis),math.sin(axis)]);v=np.array([-u[1],u[0]])
        uv=(cells[:,:2]-origin)@np.column_stack([u,v])
        records=[]
        if len(cells)<12:continue
        for t in np.arange(min(uv[:,0])+.3,max(uv[:,0]),cfg['slice_step_m']):
            mask=abs(uv[:,0]-t)<=cfg['slice_width_m']/2
            peaks=_profile_peaks(uv[mask,1],cells[mask,2],cfg) if mask.sum()>=8 else []
            for p in peaks:p['along']=float(t)
            records.append(peaks);profile_count+=1;peak_count+=len(peaks)
        for track in _tracks(records,cfg):lines.extend(_segments(track,axis,origin,cfg))
    kept=[]
    # Prefer measured length/support, then remove overlapping copies from nearby
    # seeded axes. Separate parallel ridges more than 1.2 m remain distinct.
    for line in sorted(lines,key=lambda x:(-x['length_m'],x['profile_median_error_m'])):
        geom=LineString(np.asarray(line['points'])[:,:2]);duplicate=False
        for other in kept:
            othergeom=LineString(np.asarray(other['points'])[:,:2])
            if abs(line['height_m']-other['height_m'])<cfg['max_height_span_m'] and geom.intersection(othergeom.buffer(1.2)).length>=.7*geom.length:
                duplicate=True;break
        if not duplicate:kept.append(line)
        if len(kept)>=cfg['max_lines']:break
    if kept:
        high=max(x['height_m'] for x in kept)
        main=max((x for x in kept if x['height_m']>=high-.5),key=lambda x:x['length_m'])
        main['role']='main';status='detected' if main['confidence']=='supported' else 'uncertain'
    else:status='not_detected'
    return dict(volume_id=volume_id,status=status,reason='repeated_two_sided_point_profiles' if kept else 'no_continuous_two_sided_near_horizontal_peak',
        lines=kept,profile_count=profile_count,profile_peak_count=peak_count,axis_count=len(axes),
        input_points=len(pts),interior_cells=len(cells),excluded_boundary_cells=int((~inside).sum()),
        edge_exclusion_m=cfg['edge_exclusion_m'],seconds=time.perf_counter()-tick)


def compare_with_model(observed,model):
    from roof_v2 import predict_regions
    candidates=[np.asarray(line,float) for line in model.get('ridge_lines',[]) if len(line)>=2]
    for volume in observed['volumes']:
        for line in volume['lines']:
            q=np.asarray(line['points']);samples=q[0]+np.linspace(0,1,9)[:,None]*(q[-1]-q[0])
            predicted=predict_regions(model.get('regions',[]),samples[:,:2]);finite=np.isfinite(predicted)
            delta=float(np.median(samples[finite,2]-predicted[finite])) if finite.any() else None
            direction=q[-1,:2]-q[0,:2];direction/=np.linalg.norm(direction)
            distances=[]
            for candidate in candidates:
                other=candidate[-1,:2]-candidate[0,:2];length=np.linalg.norm(other)
                if length<1e-8 or abs(direction@(other/length))<math.cos(math.radians(20)):continue
                geom=LineString(candidate[:,:2])
                distances.append(float(np.median(shapely.distance(shapely.points(samples[:,:2]),geom))))
            line['model_comparison']=dict(observed_minus_model_roof_m=delta,
                nearest_parallel_model_ridge_distance_m=min(distances) if distances else None,
                note='Independent profile estimate vs model geometry; neither is ground truth.')
    return observed


def attach_observed_ridges(result,footprint,points,settings=None):
    tick=time.perf_counter();meta=result['model'].get('metadata',{})
    bodies=meta.get('bodies') or [dict(footprint=meta.get('main_footprint',meta.get('effective_footprint',footprint)))]
    volumes=[detect_volume_ridges(body['footprint'],points,settings,volume_id=i+1) for i,body in enumerate(bodies)]
    diagnostic=dict(version=VERSION,method='Independent two-sided transverse profiles of training cells',
        model_geometry_used=False,selection_uses_holdout=False,settings={**DEFAULTS,**(settings or {})},
        volumes=volumes,seconds=time.perf_counter()-tick,
        note='Diagnostic estimate only. Boundary cells excluded; no guarantee all neighboring-house contamination is removed.')
    compare_with_model(diagnostic,result['model'])
    result.setdefault('diagnostics',{})['observed_ridges']=diagnostic
    result.setdefault('timing',{})['observed_ridges_seconds']=diagnostic['seconds']
    return result
