"""Experimental modules: section-guided roofs and evidence-gated height volumes.
No address rules, remote inference or production pipeline changes.
"""
from __future__ import annotations
import os
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[_key]='1'
import copy, math, time
import numpy as np
import shapely
from shapely.geometry import Polygon, LineString, shape, mapping
from shapely.geometry.polygon import orient
from shapely.ops import split
from scipy.optimize import least_squares
from py_straight_skeleton import compute_skeleton
from roof_v2 import _cells, _lines, predict_regions, residual_stats
from roof_v2_geometry import build_mesh, plane_regions
from roof_connected_wings import _wing_boxes, DEFAULTS as WING_DEFAULTS
from roof_sections import analyze_sections

DEFAULTS = dict(cell_m=.65,max_cells=6000,sections_enabled=True,split_enabled=True,
    max_volumes=4,min_volume_area_m2=15.,min_volume_area_fraction=.045,
    max_cut_candidates=40,min_step_m=1.1,min_step_support=.60,min_step_stations=3,
    min_boundary_length_m=3.,station_spacing_m=2.,station_halfwidth_m=1.5,
    strip_depth_m=2.5,edge_exclusion_m=.25,max_plane_p80_m=.65,
    min_split_gain_m=.10,extra_volume_penalty_m=.09,plane_penalty_m=.006,
    scan_cuts=False,scan_step_m=1.,max_scan_per_axis=24,
    section_anchor_weight=.12,min_section_support=.45,box_quantile=.70)
VERSION='roof-volume-sections-0.1'


def _polygons(g):
    if g.geom_type=='Polygon' and g.area>1e-6:yield g
    elif hasattr(g,'geoms'):
        for p in g.geoms:yield from _polygons(p)


def _segments(g):
    if g.geom_type=='LineString':yield g
    elif hasattr(g,'geoms'):
        for p in g.geoms:yield from _segments(p)


def _axis(poly):
    q=np.array(poly.minimum_rotated_rectangle.exterior.coords)[:4]
    d=np.roll(q,-1,axis=0)-q
    u=d[np.argmax(np.linalg.norm(d,axis=1))];return u/np.linalg.norm(u)


def _error(residual):
    a=np.minimum(np.abs(residual[np.isfinite(residual)]),1.5)
    return float(.6*np.mean(a)+.4*np.quantile(a,.8)) if len(a) else 100.


def _plane(points):
    # Robust IRLS local plane: distinguishes a slope from a vertical jump.
    center=np.mean(points[:,:2],axis=0); A=np.c_[points[:,:2]-center,np.ones(len(points))]
    z=points[:,2];p=np.linalg.lstsq(A,z,rcond=None)[0]
    for _ in range(4):
        w=np.sqrt(np.minimum(1.,.30/np.maximum(abs(A@p-z),1e-9)))
        p=np.linalg.lstsq(A*w[:,None],z*w,rcond=None)[0]
    error=float(np.quantile(abs(A@p-z),.8));p[2]-=center@p[:2]
    return p,error


def _skeleton_unit(poly):
    p=orient(poly.simplify(1e-7,preserve_topology=True),sign=1.)
    sk=compute_skeleton(list(p.exterior.coords)[:-1],[list(r.coords)[:-1] for r in p.interiors])
    regions=[]
    for face in sk.get_faces():
        nodes=[sk.nodes[i] for i in face]
        xy=np.array([[n.position.x,n.position.y] for n in nodes]);z=np.array([n.time for n in nodes])
        A=np.c_[xy,np.ones(len(xy))];plane=np.linalg.lstsq(A,z,rcond=None)[0]
        polygon=Polygon(xy)
        # Library rounds event geometry at approximately 1e-5 m. Allow 0.1 mm,
        # still far below input accuracy, before rejecting a nonplanar face.
        if np.max(abs(A@plane-z))>1e-4:raise ValueError('Nonplanar skeleton face')
        # Faces around a courtyard may have a zero-width bridge traversed twice.
        # GEOS converts that weakly-simple contour to area polygons, preserving holes.
        repaired=shapely.make_valid(polygon) if not polygon.is_valid else polygon
        pieces=list(_polygons(repaired))
        if not pieces:raise ValueError('Empty skeleton face')
        for piece in pieces:regions.append(dict(polygon=mapping(piece),plane=plane.tolist()))
    return regions


def _section_records(poly,cells,cfg):
    if not cfg['sections_enabled']:return []
    domains=[]
    try:
        wings,_=_wing_boxes(poly,{**WING_DEFAULTS,'_outer_ends':False})
        domains=[(w['u'],w['inside']) for w in wings]
    except (ValueError,shapely.errors.GEOSException):pass
    if not domains:
        u=_axis(poly);domains=[(u,poly),(np.array([-u[1],u[0]]),poly)]
    records=[]
    for u,domain in domains[:6]:
        try:
            r=analyze_sections(poly,cells,axis=u,domain=domain)
            r['domain']=mapping(domain);records.append(r)
        except (ValueError,TypeError,np.linalg.LinAlgError) as e:
            records.append({'error':str(e),'axis_xy':u.tolist(),'domain':mapping(domain)})
    return records


def _skeleton_fit(poly,cells,cfg,unit=None,profiles=None):
    unit=unit or _skeleton_unit(poly)
    distance=predict_regions(unit,cells[:,:2]);ok=np.isfinite(distance)
    if ok.sum()<15:raise ValueError('Insufficient skeleton cells')
    d=distance[ok];z=cells[ok,2]
    lower=.3;upper=max(1.,float(np.quantile(z,.95)))
    initial=[float(np.clip(np.quantile(z,.1)-.2,lower+.01,upper-.01)),.7]
    anchors=[];eave_anchor_count=0
    for record in profiles or []:
        ridge=record.get('ridge') or {}
        if not ridge.get('supported') or ridge.get('support_fraction',0)<cfg['min_section_support']:continue
        xyz=np.asarray(ridge.get('ridge_measurements_xyz',[]),float)
        if len(xyz):
            dt=predict_regions(unit,xyz[:,:2]);mask=np.isfinite(dt)&(dt>.4)
            anchors.extend(zip(dt[mask],xyz[mask,2]))
        for section in record.get('sections',[]):
            profile=section.get('fit',{})
            if profile.get('kind')!='pitched':continue
            for side,index in (('left',0),('right',1)):
                point=shapely.Point(section['line_xy'][index])
                extrapolation=section.get('eave_extrapolation_'+side+'_m')
                if point.distance(poly.boundary)>.25 or extrapolation is None or extrapolation>1.5:continue
                anchors.append((0.,float(profile['eave_'+side+'_m'])));eave_anchor_count+=1
    def residual(p):
        raw=p[0]+p[1]*d-z
        if anchors:
            a=np.asarray(anchors);weight=math.sqrt(len(raw)*cfg['section_anchor_weight']/len(a))
            raw=np.r_[raw,weight*(p[0]+p[1]*a[:,0]-a[:,1])]
        return raw
    fit=least_squares(residual,initial,bounds=([lower,.12],[upper,2.5]),
        loss='soft_l1',f_scale=.35,max_nfev=45)
    eave,pitch=map(float,fit.x)
    regions=[dict(polygon=r['polygon'],plane=(np.array(r['plane'])*pitch+[0,0,eave]).tolist()) for r in unit]
    return regions,dict(roof_type='hipped',eave_height_m=eave,pitch_tangent=pitch,
        pitch_degrees=math.degrees(math.atan(pitch)),common_eave=True,section_anchor_count=len(anchors),section_eave_anchor_count=eave_anchor_count)


def _gable(poly,cells,cfg):
    # Simple rectangular bodies only; L/U/ring roofs retain skeleton topology.
    if poly.interiors or poly.area/poly.convex_hull.area<.90:return None
    q=np.array(poly.exterior.coords);best=None
    main=_axis(poly)
    for u in (main,np.array([-main[1],main[0]])):
        v=np.array([-u[1],u[0]]);lo,hi=float((q@v).min()),float((q@v).max())
        if hi-lo<2:continue
        x=cells[:,:2]@v;z=cells[:,2];width=hi-lo
        # Four parameters permit asymmetric slopes but keep horizontal crest.
        def pred(p):
            r,h,sl,sr=p
            return h-sl*np.maximum(r-x,0)-sr*np.maximum(x-r,0)
        initial=[(lo+hi)/2,float(np.quantile(z,.9)),.65,.65]
        fit=least_squares(lambda p:pred(p)-z,initial,
            bounds=([lo+.2*width,.5,.12,.12],[hi-.2*width,max(float(z.max())+1,1.),2.5,2.5]),
            loss='soft_l1',f_scale=.35,max_nfev=40)
        r,h,sl,sr=fit.x
        planes=[np.r_[sl*v,h-sl*r],np.r_[-sr*v,h+sr*r]]
        regions=plane_regions(poly,planes)
        if min(float(np.min(np.c_[shapely.get_coordinates(shape(t['polygon'])),np.ones(len(shapely.get_coordinates(shape(t['polygon']))))]@np.asarray(t['plane']))) for t in regions)<=.3:continue
        err=_error(pred(fit.x)-z)+.025
        if best is None or err<best[0]:best=(err,regions,dict(roof_type='gabled',ridge_height_m=float(h),
            ridge_axis_xy=u.tolist(),ridge_offset_m=float(r),eave_left_m=float(h-sl*(r-lo)),eave_right_m=float(h-sr*(hi-r))))
    return best


def _body_roof(poly,cells,cfg):
    candidates=[]
    flat=float(np.median(cells[:,2]));regions=[dict(polygon=mapping(poly),plane=[0.,0.,max(.5,flat)])]
    candidates.append((_error(cells[:,2]-flat),regions,dict(roof_type='flat',eave_height_m=flat)))
    p,err=_plane(cells)
    if np.linalg.norm(p[:2])<math.tan(math.radians(15)) and np.min(np.c_[np.array(poly.exterior.coords),np.ones(len(poly.exterior.coords))]@p)>.3:
        candidates.append((_error(np.c_[cells[:,:2],np.ones(len(cells))]@p-cells[:,2])+.025,
            [dict(polygon=mapping(poly),plane=p.tolist())],dict(roof_type='skillion')))
    g=_gable(poly,cells,cfg)
    if g:candidates.append(g)
    try:
        regions,meta=_skeleton_fit(poly,cells,cfg)
        candidates.append((_error(predict_regions(regions,cells[:,:2])-cells[:,2])+.04,regions,meta))
    except (ValueError,RuntimeError,AssertionError,ZeroDivisionError):pass
    score,regions,meta=min(candidates,key=lambda c:c[0])
    meta.update(local_score=score,candidate_types=[c[2]['roof_type'] for c in candidates])
    return regions,meta


def _cut_lines(poly,profiles,cfg):
    simple=poly.simplify(.5,preserve_topology=True);coords=shapely.get_coordinates(simple)
    u=_axis(poly);axes=[u,np.array([-u[1],u[0]])]
    q=np.asarray(simple.exterior.coords)
    long_edges=sorted((b-a for a,b in zip(q[:-1],q[1:])),key=lambda d:-np.linalg.norm(d))
    for d in long_edges[:4]:
        n=d/np.linalg.norm(d)
        if all(abs(n@a)<.995 for a in axes):axes.append(n)
    span=max(poly.bounds[2]-poly.bounds[0],poly.bounds[3]-poly.bounds[1])*3+10
    cuts=[];keys=set()
    for n in axes[:4]:
        t=np.array([-n[1],n[0]]);proj=coords@n;lo,hi=proj.min(),proj.max()
        for value in sorted(set(np.round(proj,2))):
            if value-lo<2.5 or hi-value<2.5:continue
            key=(round(math.atan2(n[1],n[0])%math.pi,2),round(float(value),1))
            if key in keys:continue
            keys.add(key);center=n*value
            cuts.append((LineString([center-span*t,center+span*t]),'footprint_vertex'))
    if cfg['scan_cuts']:
        scans=[]
        for n in axes[:2]:
            tangent=np.array([-n[1],n[0]]);proj=coords@n;lo,hi=float(proj.min()),float(proj.max())
            count=min(cfg['max_scan_per_axis'],max(0,int((hi-lo-5)/cfg['scan_step_m'])))
            scans.append([(LineString([n*value-span*tangent,n*value+span*tangent]),'sparse_profile_scan') for value in np.linspace(lo+2.5,hi-2.5,count)])
        # Interleave both directions so the fixed computation budget is balanced.
        for i in range(max([len(x) for x in scans],default=0)):
            for items in scans:
                if i<len(items):cuts.append(items[i])
    for r in profiles:
        for change in r.get('longitudinal_changes',[]):
            line=change.get('cut_line_xy')
            if line and len(line)>=2:
                a,b=np.array(line[0]),np.array(line[-1]);t=b-a;t/=np.linalg.norm(t)
                center=(a+b)/2;cuts.insert(0,(LineString([center-span*t,center+span*t]),'profile_change'))
    return cuts[:cfg['max_cut_candidates']+(2*cfg['max_scan_per_axis'] if cfg['scan_cuts'] else 0)]


def boundary_step(poly,cells,line,cfg):
    # MODULE boundary evidence: compare extrapolated local planes at one XY,
    # not raw heights on two different positions of a continuous sloped roof.
    a,b=np.asarray(line.coords[0]),np.asarray(line.coords[-1]);t=b-a;t/=np.linalg.norm(t);n=np.array([-t[1],t[0]])
    stations=[];total=0
    for segment in _segments(line.intersection(poly)):
        if segment.length<cfg['min_boundary_length_m']:continue
        count=max(3,min(18,int(segment.length/cfg['station_spacing_m'])))
        for f in np.linspace(.1,.9,count):
            pt=np.array(segment.interpolate(float(f),normalized=True).coords[0])
            # Exterior wall portions are not a join between two volumes.
            if not all(poly.covers(shapely.Point(pt+sign*n*.35)) for sign in (-1,1)):continue
            total+=1;delta=cells[:,:2]-pt
            across=delta@n;along=delta@t
            local=(abs(along)<cfg['station_halfwidth_m'])&(abs(across)<cfg['strip_depth_m'])
            left=cells[local&(across<-cfg['edge_exclusion_m'])];right=cells[local&(across>cfg['edge_exclusion_m'])]
            if min(len(left),len(right))<6:continue
            # Need geometric support in both horizontal directions for extrapolation.
            if any(np.linalg.eigvalsh(np.cov(c[:,:2].T)).min()<.025 for c in (left,right)):continue
            p,pe=_plane(left);q,qe=_plane(right)
            if max(pe,qe)>cfg['max_plane_p80_m']:continue
            height=float(np.r_[pt,1.]@(p-q))
            stations.append(dict(xy=pt.tolist(),height_step_m=height,left_p80_m=pe,right_p80_m=qe))
    if not stations:return dict(accepted=False,reason='insufficient_boundary_support',stations=[],total_stations=total)
    steps=np.array([s['height_step_m'] for s in stations]);median=float(np.median(steps))
    agreeing=(np.sign(steps)==np.sign(median))&(abs(steps)>=cfg['min_step_m'])
    support=float(agreeing.sum()/max(total,1))
    accepted=abs(median)>=cfg['min_step_m'] and agreeing.sum()>=cfg['min_step_stations'] and support>=cfg['min_step_support']
    return dict(accepted=bool(accepted),reason='supported_vertical_step' if accepted else 'continuous_or_inconclusive',
        height_step_m=median,support_fraction=support,total_stations=total,supported_stations=int(agreeing.sum()),stations=stations)


def _partition(poly,cells,profiles,cfg):
    parts=[poly];accepted=[];checks=[]
    if not cfg['split_enabled']:return parts,accepted,checks
    cuts=_cut_lines(poly,profiles,cfg)
    minarea=max(cfg['min_volume_area_m2'],poly.area*cfg['min_volume_area_fraction'])
    for _ in range(cfg['max_volumes']-1):
        choices=[]
        for index,body in enumerate(parts):
            bodycells=cells[shapely.intersects_xy(body,cells[:,0],cells[:,1])]
            for line,source in cuts:
                pieces=list(_polygons(split(body,line)))
                if len(pieces)!=2 or min(p.area for p in pieces)<minarea:continue
                if any(p.area/p.length<.75 for p in pieces):continue
                record=boundary_step(body,bodycells,line,cfg)
                record.update(source=source,cut_line_xy=list(map(list,line.coords)),body_index=index)
                checks.append(record)
                if record['accepted']:
                    quality=abs(record['height_step_m'])*record['support_fraction']
                    choices.append((quality,index,pieces,record))
        if not choices:break
        _,index,pieces,record=max(choices,key=lambda c:c[0])
        accepted.append(record);parts=parts[:index]+pieces+parts[index+1:]
    return parts,accepted,checks


def _finish(poly,regions,metadata,seconds,diagnostics=None):
    tick=time.perf_counter();mesh=build_mesh(poly,regions)
    if not mesh['diagnostics']['valid']:raise ValueError('Mesh validation failed')
    z=np.asarray(mesh['vertices'])[:,2];top=float(z.max())
    floor=min(float(np.min(np.c_[shapely.get_coordinates(shape(r['polygon'])),np.ones(len(shapely.get_coordinates(shape(r['polygon']))))]@np.asarray(r['plane']))) for r in regions)
    metadata={**metadata,'ridge_height_m':top,'eave_height_m':floor,'roof_height_m':top-floor,
        'nominal_roof_plane_count':len(regions),'footprint_modified':False}
    model=dict(type='compound' if len(regions)>1 else 'flat',regions=regions,mesh=mesh,metadata=metadata,height_range_m=[floor,top])
    model['ridge_lines'],model['eave_lines'],model['roof_boundary_lines']=_lines(model,poly)
    return dict(algorithm=VERSION,model=model,candidates=[],diagnostics=diagnostics or {},
        timing=dict(total_seconds=seconds+time.perf_counter()-tick,geometry_seconds=time.perf_counter()-tick))


def _volume_variant(poly,cells,parts,accepted,cfg,partition_seconds):
    tick=time.perf_counter();records=[];regions=[];boxes=[]
    for index,body in enumerate(parts):
        selected=cells[shapely.intersects_xy(body,cells[:,0],cells[:,1])]
        if len(selected)<15:raise ValueError('Too few cells in body')
        fitted,meta=_body_roof(body,selected,cfg)
        height=float(np.quantile(selected[:,2],cfg['box_quantile']))
        boxes.append(dict(polygon=mapping(body),plane=[0.,0.,max(.5,height)]))
        for r in fitted:r['volume_index']=index
        regions.extend(fitted)
        records.append(dict(index=index,footprint=mapping(body),area_m2=body.area,cells=len(selected),
            box_height_m=height,box_quantile=cfg['box_quantile'],height_p90_m=float(np.quantile(selected[:,2],.9)),**meta))
    result=_finish(poly,regions,dict(ridge_kind='height_volumes',volume_count=len(parts),bodies=records,split_evidence=accepted),time.perf_counter()-tick+partition_seconds)
    return result,boxes,records


def run_variants(footprint,train,config=None,*,baseline=None):
    started=time.perf_counter();cfg={**DEFAULTS,**(config or {})}
    if set(cfg)-set(DEFAULTS):raise ValueError('Unknown volume experiment configuration')
    poly=shape(footprint) if isinstance(footprint,dict) else footprint
    points=np.asarray(train,float);points=points[np.isfinite(points).all(axis=1)]
    points=points[shapely.intersects_xy(poly,points[:,0],points[:,1])]
    cells=_cells(points,cfg['cell_m']);cells=cells[::max(1,int(np.ceil(len(cells)/cfg['max_cells'])))]
    if len(cells)<20:raise ValueError('Insufficient measurement cells')
    tick=time.perf_counter();profiles=_section_records(poly,cells,cfg);profile_seconds=time.perf_counter()-tick
    variants={};errors={};unit=None
    for key,guided in [('skeleton_shared',False),('skeleton_sections',True)]:
        tick=time.perf_counter()
        try:
            if unit is None:unit=_skeleton_unit(poly)
            regions,meta=_skeleton_fit(poly,cells,cfg,unit,profiles if guided else None)
            meta.update(ridge_kind='straight_skeleton',volume_count=1,section_guided=guided)
            variants[key]=_finish(poly,regions,meta,time.perf_counter()-tick)
        except Exception as e:errors[key]=dict(type=type(e).__name__,message=str(e))
    partitions={};box_regions=None;body_records=[]
    for key,scan in [('split_volumes',False),('split_scan',True)]:
        local_cfg={**cfg,'scan_cuts':scan,'station_spacing_m':1. if scan else cfg['station_spacing_m']}
        tick=time.perf_counter();parts,accepted,checks=_partition(poly,cells,profiles,local_cfg)
        seconds=time.perf_counter()-tick
        partitions[key]=dict(parts=parts,accepted=accepted,checks=checks,seconds=seconds)
        try:
            result,boxes,records=_volume_variant(poly,cells,parts,accepted,local_cfg,seconds)
            variants[key]=result
            if box_regions is None or len(parts)>len(box_regions):box_regions,body_records=boxes,records
        except Exception as e:errors[key]=dict(type=type(e).__name__,message=str(e))
    if box_regions:
        variants['lod_boxes']=_finish(poly,box_regions,dict(ridge_kind='height_blocks',volume_count=len(box_regions),
            bodies=body_records,box_quantile=cfg['box_quantile'],representation='LoD1.3-inspired diagnostic; not a certified LoD implementation'),0.)
    partition_seconds=sum(p['seconds'] for p in partitions.values())
    scores={};score_results={**variants}
    if baseline:score_results['baseline']=baseline
    for key,r in score_results.items():
        if key=='lod_boxes':continue
        predicted=predict_regions(r['model']['regions'],cells[:,:2]);valid=np.isfinite(predicted)
        base=_error(predicted[valid]-cells[valid,2])
        planes=len(r['model']['regions']);volumes=r['model']['metadata'].get('volume_count',1)
        score=base+cfg['plane_penalty_m']*planes+cfg['extra_volume_penalty_m']*(volumes-1)+(1-float(valid.mean()))*2
        scores[key]=dict(score=score,data_error_m=base,coverage_fraction=float(valid.mean()),plane_count=planes,volume_count=volumes)
    joint=[k for k in scores if k not in partitions]
    joint_best=min(joint,key=lambda k:scores[k]['score']) if joint else None
    allowed={}
    for key,p in partitions.items():
        ok=len(p['parts'])>1 and bool(p['accepted']) and key in scores
        if ok and joint_best:ok=scores[key]['score']+cfg['min_split_gain_m']<scores[joint_best]['score']
        allowed[key]=bool(ok)
    eligible=[k for k in scores if k not in partitions or len(partitions[k]['parts'])==1 or allowed[k]]
    winner=min(eligible,key=lambda k:scores[k]['score']) if eligible else 'baseline'
    selected=partitions.get(winner)
    max_parts=max((len(p['parts']) for p in partitions.values()),default=1)
    decision=dict(selected_variant=winner,split_proposed=max_parts>1,split_accepted=bool(allowed.get(winner,False)),
        proposed_volume_count=max_parts,selected_volume_count=scores.get(winner,{}).get('volume_count',1),
        reason='supported_step_and_fit_gain' if allowed.get(winner) else 'keep_continuous_roof_or_insufficient_split_gain',
        scores=scores,split_checks=[dict(variant=k,**check) for k,p in partitions.items() for check in p['checks']],
        accepted_boundaries=selected['accepted'] if selected else [],
        partition_variants={k:dict(proposed_volume_count=len(p['parts']),passes_gain_gate=allowed[k],boundaries=p['accepted'],seconds=p['seconds']) for k,p in partitions.items()},
        warning='Morphological roof volumes, not cadastral or legal building identities. Selection uses training data only.')
    for key,r in variants.items():
        r['configuration']=cfg;r['diagnostics'].update(decision=decision,profiles=profiles)
        r['model']['metadata'].update(experiment=True,automatic_selection=(winner==key))
    return dict(variants=variants,decision=decision,profiles=profiles,errors=errors,
        timing=dict(total_seconds=time.perf_counter()-started,section_seconds=profile_seconds,partition_seconds=partition_seconds),configuration=cfg)
