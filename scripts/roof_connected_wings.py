"""MODULE connected_wings: bounded roof tents from opposing footprint walls.

Each wing has two primary eaves and finite end planes. Their upper envelope
creates valleys at real wing junctions; a global minimum over all courtyard
walls is deliberately not used. The unchanged footprint clips the result.
"""
import math
import time
import numpy as np
from roof_candidate_telemetry import record_attempt
import shapely
from scipy.optimize import least_squares
from shapely.geometry import Polygon, LineString, shape, mapping
from shapely.geometry.polygon import orient
from shapely.ops import unary_union, polygonize
from roof_v2_geometry import plane_regions
from roof_config import point_error

DEFAULTS = {'simplify_m':.65, 'min_wall_m':3., 'max_parallel_deviation_deg':16.,
    'min_width_m':3., 'max_width_m':30., 'min_length_m':3.,
    'max_wings':6, 'min_new_area_fraction':.035,
    'max_nfev':65, 'min_concavity_fraction':.04,
    'gable_variants':True, 'extend_junctions':True,
    'outer_end_variants':True,
    'merge_wall_segments':True,'wall_merge_distance_m':1.8,'wall_merge_angle_deg':7.,
    'min_wing_aspect':0.,'snap_frame_max_deviation_deg':8.,
    'convex_courtyard_reference':True,'separate_eave_variants':True,
    'eave_difference_threshold_m':1.,'min_wing_cells':20,'separate_eave_penalty_m':.04,
    'complexity_penalty_m':.065,
    'snap_frame_max_shift_m':.30,'supported_subset_variants':True,'extend_supported_wings':True,'anchor_actual_end_walls':True,
    'ridge_support_distance_m':.9,'ridge_support_height_m':.9,
    'min_ridge_support_cells':8,'min_ridge_support_fraction':.35,
    'paired_ridge_variants':True,'max_paired_layouts':8,
    'paired_local_widths':True,'paired_min_exclusive_fraction':.04,
    'paired_width_probe_count':5,'paired_width_support_fraction':.6,
    'paired_width_tolerance_m':1.8,'paired_width_tolerance_fraction':.15,
    'paired_prefer_symmetric':True,'paired_asymmetry_penalty_m':.15,'paired_slope_tolerance_deg':5.,'paired_slope_full_penalty_deg':25.,'paired_min_coverage_fraction':.85,
    'paired_ridge_offset_limit':.35,'paired_complexity_penalty_m':.075,
    'paired_min_support_fraction':.15,'paired_weak_support_penalty_m':.05,
    'paired_min_supported_span_m':2.,'paired_max_slope_deg':85.,'paired_min_roof_height_m':.5,
    'canonicalize_caps':True,'cap_merge_angle_deg':3.,'cap_merge_height_m':.25,
    'finite_joined_variants':True,'local_gable_inset_min_m':.8,'local_gable_inset_max_m':1.5,
    'local_gable_min_cells':6,'local_gable_min_bins':3,'local_gable_min_raise_m':.2,
    'local_gable_min_improvement_m':.1,'local_gable_support_error_m':.8,
    'local_gable_min_support_fraction':.5,'local_gable_max_ends':4}


def _polygons(g):
    if g.geom_type == 'Polygon' and g.area>1e-7:
        yield g
    elif hasattr(g,'geoms'):
        for q in g.geoms:
            yield from _polygons(q)


def _box(u,v,lo,hi,bottom,top):
    return Polygon([u*x+v*y for x,y in [(lo,bottom),(hi,bottom),(hi,top),(lo,top)]])


def _walls(poly,cfg):
    basic=poly.simplify(cfg['simplify_m'],preserve_topology=True)
    if cfg['convex_courtyard_reference'] and basic.interiors:
        # A stairwell protruding into a courtyard is a clipping detail, not
        # five independent primary eave lines.
        basic=Polygon(basic.exterior,[Polygon(r).convex_hull.exterior.coords for r in basic.interiors])
    basic=orient(basic,sign=1)
    walls=[]
    for ring in [basic.exterior,*basic.interiors]:
        q=np.asarray(ring.coords)
        for a,b in zip(q[:-1],q[1:]):
            d=b-a; length=float(np.linalg.norm(d))
            if length<cfg['min_wall_m']:continue
            u=d/length; normal=np.array([-u[1],u[0]])
            walls.append(dict(a=a,b=b,u=u,n=normal,length=length))
    if cfg['merge_wall_segments']:
        groups=[]
        for wall in sorted(walls,key=lambda w:-w['length']):
            matches=[g for g in groups if np.dot(wall['u'],g[0]['u'])>math.cos(math.radians(cfg['wall_merge_angle_deg']))
                and abs(((wall['a']+wall['b'])/2-(g[0]['a']+g[0]['b'])/2)@g[0]['n'])<cfg['wall_merge_distance_m']]
            if matches:matches[0].append(wall)
            else:groups.append([wall])
        walls=[]
        for group in groups:
            weights=np.array([w['length'] for w in group]);weights/=weights.sum()
            u=np.sum([weight*w['u'] for weight,w in zip(weights,group)],axis=0);u/=np.linalg.norm(u)
            n=np.array([-u[1],u[0]])
            q=np.array([p for w in group for p in (w['a'],w['b'])])
            offset=float(np.sum([weight*((w['a']+w['b'])/2@n) for weight,w in zip(weights,group)]))
            lo,hi=float((q@u).min()),float((q@u).max())
            walls.append(dict(a=u*lo+n*offset,b=u*hi+n*offset,u=u,n=n,length=hi-lo))
        # Preserve genuinely angled wings, but do not create a new direction
        # for every slight cadastral deviation in an otherwise right-angle block.
        theta=np.angle(sum(w['length']*np.exp(4j*math.atan2(w['u'][1],w['u'][0])) for w in walls))/4
        frame=np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
        deviation=max(math.degrees(math.acos(np.clip(np.max(np.abs(w['u']@frame)),0,1))) for w in walls)
        # An angular tolerance alone can move a long roof by over a metre.
        # Keep genuine acute/obtuse bends when that would exceed the metre
        # tolerance; short cadastral deviations can still share a frame.
        shifts=[]
        for w in walls:
            projection=w['u']@frame;axis=int(np.argmax(np.abs(projection)))
            u=frame[:,axis]*np.sign(projection[axis]);n=np.array([-u[1],u[0]])
            q=np.array([w['a'],w['b']]);shifts.append(float(np.ptp(q@n)/2))
        if deviation<=cfg['snap_frame_max_deviation_deg'] and max(shifts,default=0)<=cfg['snap_frame_max_shift_m']:
            for w in walls:
                projection=w['u']@frame;axis=int(np.argmax(np.abs(projection)))
                u=frame[:,axis]*np.sign(projection[axis]);n=np.array([-u[1],u[0]])
                q=np.array([w['a'],w['b']]);lo,hi=float((q@u).min()),float((q@u).max());offset=float(np.mean(q@n))
                w.update(a=u*lo+n*offset,b=u*hi+n*offset,u=u,n=n,length=hi-lo)
    return basic,walls


def _wing_boxes(poly,cfg,all_candidates=False):
    basic,walls=_walls(poly,cfg)
    vertices=shapely.get_coordinates(basic)
    allowed=poly.buffer(.55,join_style='mitre')
    candidates=[]
    angular=math.cos(math.radians(cfg['max_parallel_deviation_deg']))
    for i,first in enumerate(walls):
        for j,second in enumerate(walls[i+1:],i+1):
            if np.dot(first['n'],second['n'])>-angular:continue
            u=first['u']-second['u'];u/=np.linalg.norm(u)
            v=np.array([-u[1],u[0]])
            bottom=float(np.mean([first['a']@v,first['b']@v]))
            top=float(np.mean([second['a']@v,second['b']@v]))
            width=top-bottom
            if not cfg['min_width_m']<=width<=cfg['max_width_m']:continue
            t1=sorted([first['a']@u,first['b']@u]);t2=sorted([second['a']@u,second['b']@u])
            lo=max(t1[0],t2[0]);hi=min(t1[1],t2[1])
            if hi-lo<cfg['min_length_m']:continue
            # Split at projected vertices before testing visibility. Thus two
            # opposite exterior walls cannot bridge a courtyard or a U notch.
            cuts=sorted(set([lo,hi,*[float(t) for t in vertices@u if lo+1e-6<t<hi-1e-6]]))
            intervals=[]
            for a,b in zip(cuts[:-1],cuts[1:]):
                t=(a+b)/2
                connector=LineString([u*t+v*(bottom+.08),u*t+v*(top-.08)])
                if allowed.intersection(connector).length<connector.length-.15:continue
                if intervals and abs(intervals[-1][1]-a)<1e-5:intervals[-1][1]=b
                else:intervals.append([a,b])
            for start,end in intervals:
                if end-start<cfg['min_length_m']:continue
                if (end-start)/width<cfg['min_wing_aspect']:continue
                physical=[]
                for value,sign in ((start,-1),(end,1)):
                    # An actual end wall occupies most of the transverse end.
                    probe=LineString([u*(value+sign*.4)+v*(bottom+.2),u*(value+sign*.4)+v*(top-.2)])
                    physical.append(poly.intersection(probe).length<.35*probe.length)
                left,right=start,end
                if cfg['extend_junctions'] and cfg.get('_outer_ends',False):
                    # Follow this finite transverse band through the connected
                    # footprint, up to its real exterior ends. Half-width caps
                    # inside a junction create artificial mini-hips in corners.
                    all_u=vertices@u;pad=max(poly.bounds[2]-poly.bounds[0],poly.bounds[3]-poly.bounds[1])+1
                    strip=_box(u,v,float(all_u.min()-pad),float(all_u.max()+pad),bottom,top).intersection(poly)
                    seed=_box(u,v,start,end,bottom,top)
                    pieces=list(_polygons(strip))
                    if pieces:
                        component=max(pieces,key=lambda p:p.intersection(seed).area)
                        ext=shapely.get_coordinates(component)@u
                        left=min(left,float(ext.min()));right=max(right,float(ext.max()))
                elif cfg['extend_junctions']:
                    left=start if physical[0] else start-width*.5
                    right=end if physical[1] else end+width*.5
                rect=_box(u,v,left,right,bottom,top)
                inside=rect.intersection(poly)
                # Reject virtual strips mainly outside the actual building.
                if inside.area<.65*rect.area:continue
                candidates.append({'u':u,'v':v,'lo':left,'hi':right,'bottom':bottom,'top':top,
                    'width':width,'length':right-left,'polygon':rect,'inside':inside,
                    'physical_ends':physical,'wall_ids':[i,j],
                    'area':float(inside.area),'source_span_m':[float(start),float(end)]})
    if all_candidates:
        return candidates, {'simple_footprint':mapping(basic),'wall_count':len(walls),
            'concavity_fraction':float(1-poly.area/poly.convex_hull.area)}
    # Greedy cover favours long supported wings; duplicative alternative pairs
    # cannot add extra ridge lines over the same volume.
    selected=[];covered=Polygon()
    while candidates and len(selected)<cfg['max_wings']:
        ranked=[]
        for c in candidates:
            new=c['inside'].difference(covered).area
            quality=min(1.,c['length']/c['width'])
            ranked.append((new*quality,new,c))
        _,new,chosen=max(ranked,key=lambda t:t[0])
        if new<max(8.,poly.area*cfg['min_new_area_fraction']):break
        selected.append(chosen);covered=covered.union(chosen['inside']);candidates=[c for c in candidates if c is not chosen]
    return selected, {'simple_footprint':mapping(basic),'wall_count':len(walls),
                     'wing_count':len(selected),'covered_fraction':float(covered.area/poly.area),
                     'concavity_fraction':float(1-poly.area/poly.convex_hull.area)}


def _wing_planes(wing,hip_ends):
    u,v=wing['u'],wing['v']
    planes=[np.r_[v,-wing['bottom']],np.r_[-v,wing['top']]]
    caps=wing.get('end_planes',[None,None])
    if hip_ends[0]:planes.append(caps[0] if caps[0] is not None else np.r_[u,-wing['lo']])
    if hip_ends[1]:planes.append(caps[1] if caps[1] is not None else np.r_[-u,wing['hi']])
    return np.asarray(planes)


def _anchor_wing_ends(poly,boxes,cfg):
    """Actual oblique end walls cap each finite tent independently.

    At a bend an end wall may be another wing's outside eave. It then remains
    a cap even in a gable alternative, preventing the roof from crossing it.
    No global minimum across all walls of a concave footprint is used.
    """
    if not cfg['anchor_actual_end_walls']:
        return [dict(w,end_planes=[None,None],junction_ends=[False,False]) for w in boxes]
    outline=orient(poly.simplify(cfg['simplify_m'],preserve_topology=True),sign=1)
    walls=[]
    for ring in [outline.exterior,*outline.interiors]:
        q=np.asarray(ring.coords)
        for a,b in zip(q[:-1],q[1:]):
            d=b-a;length=float(np.linalg.norm(d))
            if length<cfg['min_wall_m']:continue
            t=d/length;n=np.array([-t[1],t[0]])
            walls.append((a,b,t,n))
    result=[]
    for index,original in enumerate(boxes):
        w=dict(original);planes=[];junctions=[]
        for end,(value,sign) in enumerate(((w['lo'],1),(w['hi'],-1))):
            choices=[];mid=(w['bottom']+w['top'])/2
            for a,b,t,n in walls:
                if sign*(n@w['u'])<.8:continue
                ranges=sorted([a@w['v'],b@w['v']])
                overlap=min(ranges[1],w['top'])-max(ranges[0],w['bottom'])
                if overlap<.35*w['width']:continue
                at_mid=float((n@a-mid*(n@w['v']))/(n@w['u']))
                distance=abs(at_mid-value)
                if distance>.5*w['width']+.5:continue
                line=LineString([a,b])
                joint=any(j!=index and abs(t@other['u'])>math.cos(math.radians(cfg['max_parallel_deviation_deg']))
                    and line.intersection(other['inside'].buffer(.15)).length>max(1.,other['width']*.25)
                    for j,other in enumerate(boxes))
                choices.append((distance,np.r_[n,-n@a],joint))
            if choices:
                _,plane,joint=min(choices,key=lambda x:x[0]);planes.append(plane);junctions.append(joint)
            else:planes.append(None);junctions.append(False)
        w.update(end_planes=planes,junction_ends=junctions);result.append(w)
    return result


def _envelope(poly,wings,clamp_base=True,domains=None):
    # Start with the horizontal eave as a safe finite extension for tiny
    # footprint details not represented by any primary wing.
    poly=shapely.set_precision(poly,1e-7)
    sources=[];lines=[poly.boundary]
    sources_with_domains=([(np.array([[0.,0.,0.]]),poly)] if clamp_base else [])+[(planes,poly if domains is None else poly.intersection(domains[i])) for i,planes in enumerate(wings)]
    for group,(planes,domain) in enumerate(sources_with_domains):
        if domain.is_empty:continue
        domain_parts=list(_polygons(domain))
        for r in [r for part in domain_parts for r in plane_regions(part,planes)]:
            g=shape(r['polygon']);p=np.asarray(r['plane'])
            sources.append((g,p,group));lines.append(g.boundary)
    span=max(poly.bounds[2]-poly.bounds[0],poly.bounds[3]-poly.bounds[1])*4
    for i,(a,p,group) in enumerate(sources):
        for b,q,other in sources[i+1:]:
            if group==other or not a.intersects(b):continue
            overlap=a.intersection(b)
            if overlap.area<1e-7:continue
            delta=p-q;norm=float(np.linalg.norm(delta[:2]))
            if norm<1e-9:continue
            center=-delta[2]*delta[:2]/(norm*norm);tangent=np.array([-delta[1],delta[0]])/norm
            cut=LineString([center-span*tangent,center+span*tangent]).intersection(overlap)
            if not cut.is_empty:lines.append(cut)
    groups={}
    # One jointly noded partition avoids repeatedly rounded, almost coincident
    # intersections at multi-wing joints.
    for cell in polygonize(shapely.union_all(lines,grid_size=1e-7)):
        point=cell.representative_point()
        if not poly.covers(point):continue
        a=np.array([point.x,point.y,1.]);winning=np.array([0.,0.,0.]);height=0. if clamp_base else -math.inf
        for wi,planes in enumerate(wings):
            if domains is not None and not domains[wi].covers(point):continue
            values=planes@a;index=int(np.argmin(values))
            if values[index]>height:height=float(values[index]);winning=planes[index]
        key=tuple(winning)
        groups.setdefault(key,[]).append(cell)
    regions=[{'polygon':mapping(p),'plane':list(key)} for key,ps in groups.items()
             for p in _polygons(unary_union(ps))]
    if not clamp_base:return regions
    # Enforce the horizontal base explicitly after noding. An envelope cell
    # touching a zero contour at an almost-collinear multi-junction must not
    # extrapolate its slope even a few centimetres below the common base.
    clipped=[]
    for r in regions:
        clipped.extend(plane_regions(shape(r['polygon']),[r['plane'],[0.,0.,0.]],mode='max'))
    groups={}
    for r in clipped:groups.setdefault(tuple(r['plane']),[]).append(shape(r['polygon']))
    return [{'polygon':mapping(p.simplify(1e-6,preserve_topology=True)),'plane':list(key)} for key,ps in groups.items()
            for p in _polygons(unary_union(ps))]


def _connected_wing_layout(poly,cells,settings,outer_ends=False):
    """Return competing common-pitch roof systems, no address-based rules."""
    cfg={**DEFAULTS,**settings.get('connected_wings',{})}
    cfg['_outer_ends']=outer_ends
    if not settings.get('modules',{}).get('connected_wings',True):return []
    tick=time.perf_counter()
    poly=shape(poly) if isinstance(poly,dict) else poly
    if not poly.interiors and 1-poly.area/poly.convex_hull.area<cfg['min_concavity_fraction']:
        record_attempt('connected_wings',status='skipped',count=0,stage='eligibility',reason='insufficient_concavity',overhead_seconds=time.perf_counter()-tick)
        return []
    boxes,layout=_wing_boxes(poly,cfg)
    if len(boxes)<2:
        record_attempt('connected_wings',status='skipped',count=0,stage='eligibility',reason='fewer_than_two_wings',overhead_seconds=time.perf_counter()-tick)
        return []
    boxes=_anchor_wing_ends(poly,boxes,cfg)
    xy=np.asarray(cells[:,:2]); z=np.asarray(cells[:,2]); A=np.c_[xy,np.ones(len(xy))]
    variants=[('hipped',[(True,True)]*len(boxes))]
    if cfg['gable_variants']:
        # Only globally exposed ends may omit their cap: there is no domain
        # beyond such an end where an infinite gable could take over a wing.
        gables=[]
        coords=shapely.get_coordinates(poly)
        for w in boxes:
            bounds=coords@w['u']; pad=.7
            gables.append((w['junction_ends'][0] or not(w['physical_ends'][0] and w['lo']<=bounds.min()+pad),
                           w['junction_ends'][1] or not(w['physical_ends'][1] and w['hi']>=bounds.max()-pad)))
        if any(not a or not b for a,b in gables):variants.append(('exposed_gables',gables))
    proposals=[]
    # Evidence is local to each finite supporting rectangle. Missing returns
    # never justify an independently fitted height.
    masks=[shapely.intersects_xy(w['polygon'],xy[:,0],xy[:,1]) for w in boxes]
    counts=[int(m.sum()) for m in masks]
    record_attempt('connected_wings',label='layout',count=0,stage='preprocessing',overhead_seconds=time.perf_counter()-tick)
    for label,ends in variants:
        variant_tick=time.perf_counter()
        unit_wings=[_wing_planes(w,h) for w,h in zip(boxes,ends)]
        unit_predictions=np.array([np.min(A@p.T,axis=1) for p in unit_wings])
        support=np.maximum(0,np.max(unit_predictions,axis=0))
        useful=support>.25
        if useful.sum()<20:
            record_attempt('connected_wings',label,status='rejected',reason='insufficient_supported_cells',fitting_seconds=time.perf_counter()-variant_tick)
            continue
        z10,z90=np.quantile(z,[.1,.9]); q90=np.quantile(support[useful],.9)
        initial=[max(.6,z10-.3),float(np.clip((z90-z10)/max(q90,.5),.15,2.))]
        common=least_squares(lambda p:p[0]+p[1]*support-z,initial,
            bounds=([.5,.12],[max(1.,float(z90)),2.5]),loss='soft_l1',f_scale=.35,
            max_nfev=cfg['max_nfev'],ftol=2e-4,xtol=2e-4,gtol=2e-4)
        fits=[('common_eave',np.repeat(common.x[0],len(boxes)),float(common.x[1]),common.x,time.perf_counter()-variant_tick)]
        local_tick=time.perf_counter()
        local=[]
        for i,m in enumerate(masks):
            if counts[i]<cfg['min_wing_cells']:local.append(None);continue
            f=least_squares(lambda p:p[0]+p[1]*unit_predictions[i,m]-z[m],common.x,
                bounds=([.5,.12],[max(1.,float(z90)),2.5]),loss='soft_l1',f_scale=.35,max_nfev=40)
            local.append(f.x)
        supported=[i for i,p in enumerate(local) if p is not None]
        record_attempt('connected_wings',label+' local eave probes',count=0,stage='local_probes',fitting_seconds=time.perf_counter()-local_tick)
        if cfg['separate_eave_variants'] and len(supported)>1 and np.ptp([local[i][0] for i in supported])>=cfg['eave_difference_threshold_m']:
            independent_tick=time.perf_counter()
            main=max(supported,key=lambda i:counts[i])
            # Share groups of eaves already within the measurement tolerance.
            groups=[];owners=[]
            for i in range(len(boxes)):
                ref=i if i in supported else min(supported,key=lambda j:boxes[i]['polygon'].distance(boxes[j]['polygon']))
                height=local[ref][0]
                existing=[j for j,g in enumerate(groups) if abs(g-height)<cfg['eave_difference_threshold_m']]
                if existing:owners.append(existing[0])
                else:owners.append(len(groups));groups.append(float(height))
            owners=np.array(owners,int)
            def separate_prediction(p):
                eaves=p[:-1][owners];pitch=p[-1]
                return np.maximum(np.min(eaves),np.max(eaves[:,None]+pitch*unit_predictions,axis=0))
            initial=np.r_[groups,local[main][1]]
            independent=least_squares(lambda p:separate_prediction(p)-z,initial,
                bounds=([.5]*len(groups)+[.12],[max(1.,float(z90))]*len(groups)+[2.5]),
                loss='soft_l1',f_scale=.35,max_nfev=cfg['max_nfev'],ftol=2e-4,xtol=2e-4,gtol=2e-4)
            fits.append(('measured_eave_groups',independent.x[:-1][owners],float(independent.x[-1]),independent.x,time.perf_counter()-independent_tick))
        for eave_mode,eaves,pitch,parameters,fit_elapsed in fits:
            geo_tick=time.perf_counter()
            proposal=_fitted_proposal(poly,cells,settings,cfg,boxes,layout,unit_wings,ends,label,eave_mode,eaves,pitch,parameters,counts,tick)
            geo_elapsed=time.perf_counter()-geo_tick
            proposal.update(fitting_seconds=fit_elapsed,geometry_seconds=geo_elapsed,candidate_label=label+' / '+eave_mode)
            record_attempt('connected_wings',proposal['candidate_label'],fitting_seconds=fit_elapsed,geometry_seconds=geo_elapsed,outer_ends=outer_ends)
            proposals.append(proposal)
            if cfg['supported_subset_variants'] and eave_mode=='common_eave':
                subset=_supported_subset(poly,cells,settings,cfg,boxes,layout,unit_wings,ends,label,proposal,counts,tick)
                if subset is not None:
                    proposals.append(subset)
                    record_attempt('connected_wings',subset['candidate_label'],fitting_seconds=subset['fitting_seconds'],geometry_seconds=subset['geometry_seconds'],outer_ends=outer_ends)
    return proposals


def _supported_subset(poly,cells,settings,cfg,boxes,layout,unit_wings,ends,label,proposal,counts,tick):
    """MODULE wing evidence: offer a smaller system, retain the full candidate.

    A footprint wall pair may span two real roof wings and invent a high third
    ridge. Refit a subset supported by actual ridge-height cells. Missing cells
    are uncertainty, not proof of an absent roof; the full layout still competes.
    """
    keep=[r['wing_index'] for r in proposal['branch_support']
        if r['supported_cells']>=cfg['min_ridge_support_cells']
        and r['supported_cells']/max(1,r['nearby_cells'])>=cfg['min_ridge_support_fraction']]
    if not 2<=len(keep)<len(boxes):return None
    subset_tick=time.perf_counter()
    selected=[dict(boxes[i]) for i in keep];selected_ends=[ends[i] for i in keep]
    if cfg['extend_supported_wings']:
        # Extend already supported axes; do not repeat greedy selection after
        # extension, when a wide false cross-junction band could win on area.
        vertices=shapely.get_coordinates(poly)
        for j,w in enumerate(selected):
            values=vertices@w['u'];pad=float(np.ptp(values)+1)
            strip=_box(w['u'],w['v'],float(values.min()-pad),float(values.max()+pad),w['bottom'],w['top']).intersection(poly)
            components=list(_polygons(strip))
            if not components:continue
            component=max(components,key=lambda p:p.intersection(w['inside']).area)
            extent=shapely.get_coordinates(component)@w['u']
            lo,hi=float(extent.min()),float(extent.max())
            rectangle=_box(w['u'],w['v'],lo,hi,w['bottom'],w['top'])
            w.update(lo=lo,hi=hi,length=hi-lo,polygon=rectangle,inside=rectangle.intersection(poly))
            if label=='exposed_gables':
                selected_ends[j]=(not(lo<=values.min()+.7),not(hi>=values.max()-.7))
    selected=_anchor_wing_ends(poly,selected,cfg)
    selected_ends=[tuple(hip or joint for hip,joint in zip(h,w['junction_ends'])) for w,h in zip(selected,selected_ends)]
    units=[_wing_planes(w,h) for w,h in zip(selected,selected_ends)]
    A=np.c_[cells[:,:2],np.ones(len(cells))];z=cells[:,2]
    support=np.maximum(0,np.max([np.min(A@p.T,axis=1) for p in units],axis=0))
    fit=least_squares(lambda p:p[0]+p[1]*support-z,proposal['parameters'],
        bounds=([.5,.12],[max(1.,float(np.quantile(z,.9))),2.5]),loss='soft_l1',f_scale=.35,
        max_nfev=cfg['max_nfev'],ftol=2e-4,xtol=2e-4,gtol=2e-4)
    covered=shapely.union_all([w['inside'] for w in selected])
    subset_layout={**layout,'wing_count':len(keep),'covered_fraction':float(covered.area/poly.area),
        'supported_subset':True,'original_wing_count':len(boxes),'kept_wing_indices':keep,
        'supported_axes_extended':cfg['extend_supported_wings'],
        'omitted_wing_indices':[i for i in range(len(boxes)) if i not in keep],
        'original_branch_support':proposal['branch_support'],
        'omission_policy':'Alternative hypothesis only; missing ridge points do not prove absence.'}
    fit_elapsed=time.perf_counter()-subset_tick;geo_tick=time.perf_counter()
    result=_fitted_proposal(poly,cells,settings,cfg,selected,subset_layout,units,selected_ends,
        label+'_supported_subset','common_eave',np.repeat(fit.x[0],len(keep)),float(fit.x[1]),fit.x,[counts[i] for i in keep],tick)
    result.update(fitting_seconds=fit_elapsed,geometry_seconds=time.perf_counter()-geo_tick,candidate_label=label+'_supported_subset')
    return result


def connected_wing_proposals(poly,cells,settings):
    """Compete bounded half-junction and full exterior-end roof systems.

    The exterior-end alternative is beneficial for continuous courtyard wings;
    point fitting can reject it where a slanted footprint would overextend a
    primary roof. This is a general competition, never an address switch.
    """
    result=_connected_wing_layout(poly,cells,settings,outer_ends=False)
    cfg={**DEFAULTS,**settings.get('connected_wings',{})}
    if cfg['outer_end_variants'] and cfg['extend_junctions']:
        result+=_connected_wing_layout(poly,cells,settings,outer_ends=True)
    if cfg['paired_ridge_variants']:
        result+=_paired_ridge_proposals(poly,cells,settings,cfg)
    if cfg['finite_joined_variants']:
        result+=_finite_joined_proposals(poly,cells,settings,cfg)
    return result



def _canonicalize_caps(poly,wings,boxes,cfg):
    """Merge almost coplanar end caps into existing primary roof planes.

    Only cap coefficients change; primary eave planes and wing directions
    stay intact. The maximum vertical change is bounded over the entire
    footprint, before the shared envelope and its point score are computed.
    """
    result=[np.array(wing,dtype=float,copy=True) for wing in wings]
    metadata={'enabled':bool(cfg['canonicalize_caps']),'merged_cap_count':0,
              'maximum_plane_change_m':0.,'merges':[]}
    if not cfg['canonicalize_caps']:return result,metadata
    xy=shapely.get_coordinates(poly);A=np.c_[xy,np.ones(len(xy))]
    anchors=[]
    for wi,planes in enumerate(wings):
        for pi,plane in enumerate(planes[:2]):
            anchors.append((float(boxes[wi]['length']),wi,pi,np.asarray(plane)))
    angular=math.cos(math.radians(cfg['cap_merge_angle_deg']))
    for wi,planes in enumerate(result):
        for pi,plane in enumerate(planes[2:],2):
            norm=float(np.linalg.norm(plane[:2]))
            if norm<1e-8:continue
            choices=[]
            for length,ai,ap,anchor in anchors:
                denominator=norm*float(np.linalg.norm(anchor[:2]))
                if denominator<1e-10 or float(plane[:2]@anchor[:2])/denominator<angular:continue
                change=float(np.max(np.abs(A@(anchor-plane))))
                if change>cfg['cap_merge_height_m']:continue
                choices.append((-length,change,ai,ap,anchor))
            if not choices:continue
            _,change,ai,ap,anchor=min(choices,key=lambda row:row[:4])
            if np.array_equal(plane,anchor):continue
            planes[pi]=anchor
            metadata['merged_cap_count']+=1
            metadata['maximum_plane_change_m']=max(metadata['maximum_plane_change_m'],change)
            metadata['merges'].append({'wing_index':wi,'cap_index':pi,'anchor_wing':ai,
                'anchor_plane':ap,'maximum_height_change_m':change})
    return result,metadata

def _fitted_proposal(poly,cells,settings,cfg,boxes,layout,unit_wings,ends,label,eave_mode,eaves,pitch,parameters,counts,tick):
        xy=np.asarray(cells[:,:2]);z=np.asarray(cells[:,2]);A=np.c_[xy,np.ones(len(xy))]
        base=float(np.min(eaves));eave=float(eaves[np.argmax(counts)])
        wings=[pitch*p+np.array([0.,0.,height-base]) for p,height in zip(unit_wings,eaves)]
        original_wings=[w.copy() for w in wings]
        wings,cap_simplification=_canonicalize_caps(poly,wings,boxes,cfg)
        domains=[w['inside'] for w in boxes] if cfg.get('_finite_domains',False) else None
        support=_wing_prediction(A,wings,domains)
        useful=support>.25
        pred=base+support
        residual=np.abs(pred-z);error=point_error(residual,settings['scoring'])
        normalized=_envelope(poly,wings,domains=domains)
        regions=[{'polygon':r['polygon'],'plane':[r['plane'][0],r['plane'][1],base+r['plane'][2]]} for r in normalized]
        ridges=[];ridge_heights=[];support_meta=[]
        for index,(w,h,wing_eave) in enumerate(zip(boxes,ends,eaves)):
            mid=(w['bottom']+w['top'])/2
            start=w['lo']+(w['width']/2 if h[0] else 0)
            end=w['hi']-(w['width']/2 if h[1] else 0)
            if end-start<=.1:continue
            segment=LineString([w['u']*start+w['v']*mid,w['u']*end+w['v']*mid])
            height=float(wing_eave)+pitch*w['width']/2
            distance=shapely.distance(shapely.points(xy),segment)
            near=distance<cfg['ridge_support_distance_m']
            supported=near&(np.abs(z-height)<cfg['ridge_support_height_m'])
            support_meta.append({'wing_index':index,'nearby_cells':int(near.sum()),'supported_cells':int(supported.sum()),
                'width_m':w['width'],'length_m':w['length'],'ridge_height_m':height})
            ridges.append(np.asarray(segment.coords).tolist());ridge_heights.append(height)
        penalty=cfg['complexity_penalty_m']+.008*max(0,len(boxes)-2)+(cfg['separate_eave_penalty_m']*(len(np.unique(eaves))-1) if eave_mode!='common_eave' else 0.)
        frame=np.column_stack((boxes[0]['u'],boxes[0]['v']))
        coords=shapely.get_coordinates(poly)@frame
        metadata={**layout,'cap_simplification':cap_simplification,'variant':label,'pitch_tangent':pitch,'pitch_degrees':math.degrees(math.atan(pitch)),
                  'common_eave':eave_mode=='common_eave','common_pitch':True,'eave_mode':eave_mode,'wing_eaves_m':eaves.tolist(),'wing_cell_counts':counts,'unsupported_wings':[i for i,n in enumerate(counts) if n<cfg['min_wing_cells']],'wing_widths_m':[float(w['width']) for w in boxes],
                  'wing_frames_xy':[np.column_stack((w['u'],w['v'])).tolist() for w in boxes],
                  'wing_domains_xy':[mapping(w['inside']) for w in boxes],
                  'covered_point_fraction':float(useful.mean()),'candidate_seconds':time.perf_counter()-tick,
                  'construction':'upper envelope of finite convex wing roofs; original footprint clipping',
                  'settings':cfg}
        heights=[float(np.r_[q,1]@r['plane']) for r in regions for q in shapely.get_coordinates(shape(r['polygon']))]
        return {'kind':'connected_wings','hips':(), 'score':float(error+penalty),
            'data_error_m':float(error),'complexity_penalty_m':float(penalty),'support_penalty_m':0.,
            'parameters':parameters,'strip_regions':regions,'ridge_xy':ridges,'ridge_heights_m':ridge_heights,
            'eave_height_m':eave,'ridge_height_m':max(heights),'matrix':frame,
            'extent':[float(coords[:,0].min()),float(coords[:,0].max()),float(coords[:,1].min()),float(coords[:,1].max())],
            'branch_support':support_meta,'connected_wings':metadata,'supporting_envelope':'opposing primary wall pairs',
            '_cap_original_wings':original_wings if cap_simplification['merged_cap_count'] else None,
            '_cap_base_height_m':base,'_cap_scoring':settings['scoring'],'_cap_domains':domains}


def _paired_symmetry_penalty(units, rise, cfg):
    """Tolerate small pitch differences; penalize strong asymmetry smoothly."""
    differences=[abs(math.degrees(math.atan(float(np.linalg.norm(wing[0][:2])*rise)))-
                     math.degrees(math.atan(float(np.linalg.norm(wing[1][:2])*rise)))) for wing in units]
    excess=max(differences,default=0.)-cfg['paired_slope_tolerance_deg']
    span=cfg['paired_slope_full_penalty_deg']-cfg['paired_slope_tolerance_deg']
    weight=float(np.clip(excess/span,0.,1.)) if cfg['paired_prefer_symmetric'] else 0.
    return weight*cfg['paired_asymmetry_penalty_m']


def _paired_layout_evidence(poly, wings, cfg):
    """MODULE local widths: require two distinct arms before fitting their roof.

    Broad overlapping strips can each cover an entire L. Coverage alone then
    rewards the wrong opposite wall. Check each arm outside the junction, with
    a few 2D sections through its own exclusive footprint. Small facade steps
    may differ from the virtual eave line within the configured tolerance.
    """
    if not cfg['paired_local_widths']:
        return {'accepted':True,'enabled':False,'wings':[]}
    evidence=[]
    for i,wing in enumerate(wings):
        exclusive=wing['inside'].difference(wings[1-i]['inside'])
        fraction=float(exclusive.area/poly.area)
        row={'wing_index':i,'width_m':float(wing['width']),
             'exclusive_area_fraction':fraction,'probes':[]}
        evidence.append(row)
        if fraction < cfg['paired_min_exclusive_fraction']:
            return {'accepted':False,'enabled':True,'reason':'redundant_wing_width','wings':evidence}
        coords=shapely.get_coordinates(exclusive)
        along=coords@wing['u'];lo,hi=float(along.min()),float(along.max())
        mid=(wing['bottom']+wing['top'])/2
        span=max(poly.bounds[2]-poly.bounds[0],poly.bounds[3]-poly.bounds[1])*2+1
        tolerance=max(cfg['paired_width_tolerance_m'],cfg['paired_width_tolerance_fraction']*wing['width'])
        for t in np.linspace(lo+.1*(hi-lo),hi-.1*(hi-lo),int(cfg['paired_width_probe_count'])):
            center=wing['u']*t+wing['v']*mid
            if not exclusive.covers(shapely.Point(center)):
                continue
            cut=LineString([center-wing['v']*span,center+wing['v']*span])
            pieces=[q for q in _line_parts(poly.intersection(cut)) if q.distance(shapely.Point(center))<1e-6]
            if not pieces:continue
            section=max(pieces,key=lambda q:q.length);transverse=np.asarray(section.coords)@wing['v']
            low,high=float(transverse.min()),float(transverse.max())
            supported=max(abs(low-wing['bottom']),abs(high-wing['top']))<=tolerance
            row['probes'].append({'along_m':float(t),'measured_width_m':high-low,'supported':bool(supported)})
        probes=row['probes'];support=sum(r['supported'] for r in probes)/max(1,len(probes))
        row['width_support_fraction']=float(support)
        if len(probes)<2 or support<cfg['paired_width_support_fraction']:
            return {'accepted':False,'enabled':True,'reason':'unsupported_local_wing_width','wings':evidence}
    return {'accepted':True,'enabled':True,'wings':evidence}


def _paired_ridge_proposals(poly,cells,settings,cfg):
    """MODULE paired ridges: point-fitted bent roof using actual wall directions.

    A greedy footprint cover can miss a second roof axis on an almost solid
    footprint. Retain bounded alternative wall-pair layouts, fit a shared level
    ridge and eave, and join the two tents through their own eave planes. The
    axes may be acute or obtuse; no perpendicular L template is restored.
    """
    tick=time.perf_counter()
    poly=shape(poly) if isinstance(poly,dict) else poly
    if not settings.get('modules',{}).get('connected_wings',True) or poly.interiors:
        return []
    if 1-poly.area/poly.convex_hull.area<cfg['min_concavity_fraction']:
        return []
    boxes,layout=_wing_boxes(poly,{**cfg,'_outer_ends':True},all_candidates=True)
    unique={}
    for w in boxes:
        key=tuple(np.round(np.r_[w['u'],w['bottom'],w['top']],4))
        unique.setdefault(key,w)
    boxes=list(unique.values());pairs=[]
    for i,a in enumerate(boxes):
        for b in boxes[i+1:]:
            if abs(a['u']@b['u'])>math.cos(math.radians(25.)):continue
            coverage=a['inside'].union(b['inside']).area/poly.area
            if coverage<cfg['paired_min_coverage_fraction']:continue
            if a['inside'].intersection(b['inside']).area<4.:continue
            evidence=_paired_layout_evidence(poly,[a,b],cfg)
            if not evidence['accepted']:
                record_attempt('connected_wings','paired ridge layout',status='rejected',count=0,
                    stage='preprocessing',reason=evidence['reason'])
                continue
            pairs.append((coverage,[a,b],evidence))
    pairs.sort(key=lambda row:-row[0]);pairs=pairs[:int(cfg['max_paired_layouts'])]
    record_attempt('connected_wings',label='paired ridge layouts',count=0,stage='preprocessing',
        overhead_seconds=time.perf_counter()-tick)
    xy=np.asarray(cells[:,:2]);z=np.asarray(cells[:,2]);A=np.c_[xy,np.ones(len(xy))]
    z10,z90=np.quantile(z,[.1,.9]);fitted=[]
    offset=float(cfg['paired_ridge_offset_limit'])
    low=[.5-offset,.5-offset,.5,.4]
    high=[.5+offset,.5+offset,max(1.,z90),max(4.,np.ptp(z)+4)]
    coords=shapely.get_coordinates(poly)
    for layout_index,(coverage,ws,width_evidence) in enumerate(pairs):
        normals=np.array([w['v'] for w in ws])
        def geometry(p,cap_sides,with_lines=False):
            halves=[];ridge_offsets=[]
            for fraction,w in zip(p[:2],ws):
                mid=w['bottom']+fraction*w['width'];ridge_offsets.append(mid)
                halves.append([np.r_[w['v'], -w['bottom']]/(mid-w['bottom']),
                               np.r_[-w['v'],w['top']]/(w['top']-mid)])
            wings=[np.array([*halves[0],halves[1][cap_sides[0]]]),
                   np.array([*halves[1],halves[0][cap_sides[1]]])]
            joint=np.linalg.solve(normals,ridge_offsets)
            ridges=[]
            if not with_lines:return wings,joint,ridges
            for i,w in enumerate(ws):
                cap=halves[1-i][cap_sides[i]]
                sign=1 if cap[:2]@w['u']>0 else -1
                direction=w['u']*sign;along=coords@direction
                length=max(.0,float(along.max()-joint@direction))
                ray=LineString([joint,joint+direction*max(length,.001)])
                pieces=list(_line_parts(ray.intersection(poly)))
                segment=max(pieces,key=lambda line:line.length) if pieces else ray
                ridges.append(np.asarray(segment.coords))
            return wings,joint,ridges
        for side_a in (0,1):
            for side_b in (0,1):
                variant_tick=time.perf_counter();sides=(side_a,side_b)
                def prediction(p):
                    wings,_,_=geometry(p,sides)
                    unit=np.max([np.min(A@q.T,axis=1) for q in wings],axis=0)
                    return p[2]+p[3]*unit
                for fit_mode in (('symmetric','free') if cfg['paired_prefer_symmetric'] else ('free',)):
                    variant_tick=time.perf_counter()
                    initial=[.5,.5,max(.6,z10-.8),max(.6,z90-z10+1.)]
                    if fit_mode=='symmetric':
                        fit=least_squares(lambda p:prediction(np.r_[.5,.5,p])-z,
                            np.clip(initial[2:],low[2:],high[2:]),bounds=(low[2:],high[2:]),
                            loss='soft_l1',f_scale=.25,max_nfev=cfg['max_nfev'],ftol=2e-4,xtol=2e-4,gtol=2e-4)
                        fit.x=np.r_[.5,.5,fit.x]
                    else:
                        fit=least_squares(lambda p:prediction(p)-z,np.clip(initial,low,high),bounds=(low,high),
                            loss='soft_l1',f_scale=.25,max_nfev=cfg['max_nfev'],ftol=2e-4,xtol=2e-4,gtol=2e-4)
                    units,joint,ridges=geometry(fit.x,sides,with_lines=True)
                    height=float(fit.x[2]+fit.x[3]);support=[]
                    for i,line in enumerate(ridges):
                        segment=LineString(line);distance=shapely.distance(shapely.points(xy),segment)
                        near=distance<cfg['ridge_support_distance_m']
                        good=near&(np.abs(z-height)<cfg['ridge_support_height_m'])
                        along=xy[good]@ws[i]['u']
                        span=float(np.ptp(np.quantile(along,[.1,.9]))) if len(along)>1 else 0.
                        support.append({'wing_index':i,'nearby_cells':int(near.sum()),'supported_cells':int(good.sum()),
                            'width_m':ws[i]['width'],'length_m':float(segment.length),'ridge_height_m':height,
                            'supported_span_m':span})
                    valid=poly.buffer(.3).covers(shapely.Point(joint)) and all(
                        r['length_m']>=cfg['min_length_m'] and r['supported_span_m']>=cfg['paired_min_supported_span_m']
                        and r['supported_cells']>=cfg['min_ridge_support_cells']
                        and r['supported_cells']/max(1,r['nearby_cells'])>=cfg['paired_min_support_fraction'] for r in support)
                    max_slope=max(math.degrees(math.atan(float(np.linalg.norm(q[:2])*fit.x[3]))) for wing in units for q in wing[:2])
                    valid=valid and max_slope<=cfg['paired_max_slope_deg']
                    label=f'paired_ridge_{layout_index}_{side_a}{side_b}'+('_symmetric' if fit_mode=='symmetric' else '')
                    elapsed=time.perf_counter()-variant_tick
                    record_attempt('connected_wings',label,status='considered' if valid else 'rejected',
                        reason=None if valid else 'unsupported_joint_or_branch',fitting_seconds=elapsed)
                    if not valid:continue
                    error=float(point_error(abs(prediction(fit.x)-z),settings['scoring']))
                    weak=sum(r['supported_cells']/max(1,r['nearby_cells'])<cfg['min_ridge_support_fraction'] for r in support)
                    symmetry_penalty=_paired_symmetry_penalty(units,float(fit.x[3]),cfg)
                    penalty=weak*cfg['paired_weak_support_penalty_m']
                    fitted.append((error+cfg['paired_complexity_penalty_m']+penalty+symmetry_penalty,error,ws,coverage,fit.x,units,ridges,support,label,elapsed,width_evidence,fit_mode,symmetry_penalty))
    # Construct only the best bounded hypotheses. All evaluated fits are logged.
    proposals=[]
    for score,error,ws,coverage,p,units,ridges,support,label,elapsed,width_evidence,fit_mode,symmetry_penalty in sorted(fitted,key=lambda x:x[0])[:3]:
        geo_tick=time.perf_counter();base=float(p[2]);rise=float(p[3]);wings=[rise*q for q in units]
        regions=[{'polygon':r['polygon'],'plane':[r['plane'][0],r['plane'][1],base+r['plane'][2]]}
                 for r in _envelope(poly,wings,clamp_base=False)]
        min_height=min(float(np.r_[q,1]@r['plane']) for r in regions for q in shapely.get_coordinates(shape(r['polygon'])))
        if min_height<cfg['paired_min_roof_height_m']:
            record_attempt('connected_wings',label,status='rejected',count=0,stage='geometry',
                reason='roof_below_minimum_height',geometry_seconds=time.perf_counter()-geo_tick)
            continue
        frame=np.column_stack((ws[0]['u'],ws[0]['v']));uv=coords@frame
        eaves=np.repeat(base,2);counts=[int(shapely.intersects_xy(w['inside'],xy[:,0],xy[:,1]).sum()) for w in ws]
        metadata={**layout,'wing_count':2,'covered_fraction':float(coverage),'variant':label,
            'common_eave':True,'common_pitch':False,'common_ridge':True,'ridge_offsets_fitted':fit_mode=='free',
            'opposing_slopes_symmetric':bool(np.max(np.abs(p[:2]-.5))<1e-6),
            'local_width_evidence':width_evidence,'symmetry_preference_penalty_m':float(symmetry_penalty),
            'eave_mode':'common_eave','wing_eaves_m':eaves.tolist(),'wing_cell_counts':counts,
            'wing_widths_m':[float(w['width']) for w in ws],
            'wing_frames_xy':[np.column_stack((w['u'],w['v'])).tolist() for w in ws],
            'wing_domains_xy':[mapping(w['inside']) for w in ws],
            'ridge_fractions':p[:2].tolist(),'ridge_height_m':base+rise,
            'weakly_supported_wings':[r['wing_index'] for r in support if r['supported_cells']/max(1,r['nearby_cells'])<cfg['min_ridge_support_fraction']],
            'slope_degrees_by_wing':[[math.degrees(math.atan(float(np.linalg.norm(q[:2])*rise))) for q in wing[:2]] for wing in units],
            'construction':'independent wall-pair directions; common level ridge/eave; continuous joined roof planes',
            'settings':cfg}
        geometry_elapsed=time.perf_counter()-geo_tick
        record_attempt('connected_wings',label,count=0,stage='geometry',geometry_seconds=geometry_elapsed)
        proposals.append({'kind':'connected_wings','hips':(),'score':float(score),'data_error_m':error,
            'complexity_penalty_m':cfg['paired_complexity_penalty_m']+symmetry_penalty,'support_penalty_m':float(score-error-cfg['paired_complexity_penalty_m']-symmetry_penalty),
            'parameters':p,'strip_regions':regions,'ridge_xy':[r.tolist() for r in ridges],
            'ridge_heights_m':[base+rise]*2,'eave_height_m':base,'ridge_height_m':base+rise,
            'matrix':frame,'extent':[float(uv[:,0].min()),float(uv[:,0].max()),float(uv[:,1].min()),float(uv[:,1].max())],
            'branch_support':support,'connected_wings':metadata,'supporting_envelope':'actual nonparallel wall pairs',
            'candidate_label':label,'fitting_seconds':elapsed,'geometry_seconds':geometry_elapsed})
    return proposals


def _line_parts(geometry):
    if geometry.geom_type=='LineString' and geometry.length>1e-5:
        yield geometry
    elif hasattr(geometry,'geoms'):
        for child in geometry.geoms:yield from _line_parts(child)


def cap_rollback_candidates(poly,cells,proposal,max_alternatives=3):
    """Selected-only recovery when coincident merged caps defeat mesh noding.

    No fitting is repeated. Each alternative rebuilds the same continuous
    envelope used for its numerical score. Try removing individual merges,
    last first, then the unchanged original. This generator does no work for
    alternatives the caller does not consume.
    """
    originals=proposal.get('_cap_original_wings')
    if originals is None:return
    base=float(proposal['_cap_base_height_m'])
    previous=proposal['connected_wings'].get('cap_simplification',{})
    merges=previous.get('merges',[])
    if not merges:return
    all_indices=set(range(len(merges)))
    omissions=[{i} for i in reversed(range(len(merges)))][:max(0,int(max_alternatives))]
    if all_indices not in omissions:omissions.append(all_indices)
    xy=np.asarray(cells[:,:2]);z=np.asarray(cells[:,2]);A=np.c_[xy,np.ones(len(xy))]
    failures=[]
    for omitted in omissions:
        tick=time.perf_counter();wings=[np.array(w,dtype=float,copy=True) for w in originals]
        retained=[]
        for index,merge in enumerate(merges):
            if index in omitted:continue
            wings[merge['wing_index']][merge['cap_index']]=originals[merge['anchor_wing']][merge['anchor_plane']]
            retained.append(merge)
        pred=base+_wing_prediction(A,wings,proposal.get('_cap_domains'))
        data_error=float(point_error(np.abs(pred-z),proposal['_cap_scoring']))
        try:
            regions=[{'polygon':r['polygon'],'plane':[r['plane'][0],r['plane'][1],base+r['plane'][2]]}
                     for r in _envelope(poly,wings,domains=proposal.get('_cap_domains'))]
        except (ValueError,shapely.errors.GEOSException) as error:
            failures.append({'omitted_merge_indices':sorted(omitted),'error':str(error)})
            continue
        metadata={**previous,'merged_cap_count':len(retained),'merges':retained,
            'maximum_plane_change_m':max((m['maximum_height_change_m'] for m in retained),default=0.),
            'rollback_reason':'closed_mesh_validation_failed',
            'rolled_back_merge_indices':sorted(omitted),
            'attempted_merge_count':len(merges),'original_geometry_restored':not retained,
            'rollback_construction_errors':list(failures)}
        result={**proposal,'strip_regions':regions,'_regions':regions,
            'plane_count':len({tuple(round(v,8) for v in r['plane']) for r in regions}),
            'data_error_m':data_error,
            'score':float(data_error+proposal.get('complexity_penalty_m',0.)+proposal.get('support_penalty_m',0.)),
            'connected_wings':{**proposal['connected_wings'],'cap_simplification':metadata},
            'candidate_label':proposal.get('candidate_label','connected_wings')+' / cap rollback '+','.join(map(str,sorted(omitted))),
            '_cap_original_wings':None,'geometry_seconds':time.perf_counter()-tick}
        yield result


def _wing_prediction(A,wings,domains=None):
    values=np.array([np.min(A@wing.T,axis=1) for wing in wings])
    if domains is not None:
        for i,domain in enumerate(domains):
            mask=shapely.intersects_xy(domain,A[:,0],A[:,1])
            values[i,~mask]=-np.inf
    return np.maximum(0,np.max(values,axis=0))


def _local_gable_evidence(poly,cells,boxes,units,eave,pitch,cfg):
    """Measured local end tests; never sample the uncertain immediate edge."""
    xy=np.asarray(cells[:,:2]);z=np.asarray(cells[:,2]);A=np.c_[xy,np.ones(len(xy))]
    domains=[w['inside'] for w in boxes]
    before=eave+pitch*_wing_prediction(A,units,domains)
    boundary_distance=shapely.distance(shapely.points(xy),poly.boundary)
    evidence=[]
    for wi,w in enumerate(boxes):
        for end,cap in enumerate(w.get('end_planes',[None,None])):
            record={'wing_index':wi,'end_index':end,'supported':False,'edge_xy':None}
            if cap is None:
                record['reason']='no_actual_terminal_wall';evidence.append(record);continue
            cap=np.asarray(cap);norm=float(np.linalg.norm(cap[:2]));normal=cap[:2]/norm
            denom=float(normal@w['u'])
            if abs(denom)<.2:
                record['reason']='not_a_terminal_edge';evidence.append(record);continue
            edge=[]
            for vcoord in (w['bottom'],w['top']):
                ucoord=(-cap[2]/norm-vcoord*(normal@w['v']))/denom
                edge.append((w['u']*ucoord+w['v']*vcoord).tolist())
            record['edge_xy']=edge
            along=(xy@w['v']-w['bottom'])/w['width']
            inward=(xy@cap[:2]+cap[2])/norm
            mask=(inward>=cfg['local_gable_inset_min_m'])&(inward<=cfg['local_gable_inset_max_m'])
            mask&=(boundary_distance>=cfg['local_gable_inset_min_m'])&(boundary_distance<=cfg['local_gable_inset_max_m'])
            mask&=(along>=.15)&(along<=.85)&shapely.intersects_xy(w['inside'],xy[:,0],xy[:,1])
            count=int(mask.sum());bins=len(np.unique(np.clip((along[mask]*5).astype(int),0,4)))
            record.update(cells=count,width_bins=bins,inset_m=[cfg['local_gable_inset_min_m'],cfg['local_gable_inset_max_m']])
            if count<cfg['local_gable_min_cells'] or bins<cfg['local_gable_min_bins']:
                record['reason']='insufficient_inset_support';evidence.append(record);continue
            alternative=[p.copy() for p in units]
            # Baseline units contain both hips, in stable end order.
            alternative[wi]=np.delete(alternative[wi],2+end,axis=0)
            after=eave+pitch*_wing_prediction(A,alternative,domains)
            old_error=np.minimum(abs(before[mask]-z[mask]),1.5)
            new_error=np.minimum(abs(after[mask]-z[mask]),1.5)
            gain=float(np.mean(old_error-new_error))
            observed_raise=float(np.median(z[mask]-before[mask]))
            fraction=float(np.mean(abs(after[mask]-z[mask])<=cfg['local_gable_support_error_m']))
            lift=float(np.median(after[mask]-before[mask]))
            accepted=gain>=cfg['local_gable_min_improvement_m'] and observed_raise>=cfg['local_gable_min_raise_m']
            accepted=accepted and fraction>=cfg['local_gable_min_support_fraction'] and lift>=cfg['local_gable_min_raise_m']
            record.update(supported=bool(accepted),reason='supported_inset_gable' if accepted else 'hip_not_disproved',
                error_improvement_m=gain,median_observed_raise_m=observed_raise,
                supported_fraction=fraction,median_candidate_raise_m=lift)
            evidence.append(record)
    return evidence


def _finite_joined_proposals(poly,cells,settings,cfg):
    """Full connected wing spans, local gables and bounded spatial influence.

    Roof planes extend through each real connected wing to its outside ends.
    Their upper envelope joins overlaps. A removed terminal hip cannot leak
    across a courtyard and cover a different wing, because each tent has a
    finite footprint domain. Candidates with internal height steps must be
    rejected by the final mesh selection; they are not connected roof systems.
    """
    if not settings.get('modules',{}).get('connected_wings',True):return []
    poly=shape(poly) if isinstance(poly,dict) else poly
    if not poly.interiors and 1-poly.area/poly.convex_hull.area<cfg['min_concavity_fraction']:return []
    tick=time.perf_counter();cfg={**cfg,'_outer_ends':True,'_finite_domains':True}
    boxes,layout=_wing_boxes(poly,cfg)
    if len(boxes)<2:return []
    if layout['covered_fraction']<.8:return []
    boxes=_anchor_wing_ends(poly,boxes,cfg)
    xy=np.asarray(cells[:,:2]);z=np.asarray(cells[:,2]);A=np.c_[xy,np.ones(len(xy))]
    domains=[w['inside'] for w in boxes]
    counts=[int(shapely.intersects_xy(d,xy[:,0],xy[:,1]).sum()) for d in domains]
    ends=[(True,True)]*len(boxes);units=[_wing_planes(w,h) for w,h in zip(boxes,ends)]
    z10,z90=np.quantile(z,[.1,.9])
    def fit_units(candidate_units):
        support=_wing_prediction(A,candidate_units,domains);useful=support>.25
        if int(useful.sum())<20:return None
        initial=[max(.6,z10-.3),float(np.clip((z90-z10)/max(float(np.quantile(support[useful],.9)),.5),.15,2.))]
        return least_squares(lambda p:p[0]+p[1]*support-z,initial,
            bounds=([.5,.12],[max(1.,float(z90)),2.5]),loss='soft_l1',f_scale=.35,
            max_nfev=cfg['max_nfev'],ftol=2e-4,xtol=2e-4,gtol=2e-4)
    record_attempt('connected_wings','finite wing layout',count=0,stage='preprocessing',overhead_seconds=time.perf_counter()-tick)
    fit_tick=time.perf_counter();fit=fit_units(units)
    if fit is None:return []
    fit_seconds=time.perf_counter()-fit_tick
    evidence_tick=time.perf_counter();evidence=_local_gable_evidence(poly,cells,boxes,units,float(fit.x[0]),float(fit.x[1]),cfg)
    record_attempt('connected_wings','local gable evidence',count=0,stage='local_probes',fitting_seconds=time.perf_counter()-evidence_tick)
    variants=[('finite_joined_hipped',ends,units,fit,fit_seconds,[])]
    accepted=sorted([e for e in evidence if e['supported']],key=lambda e:-e['error_improvement_m'])[:int(cfg['local_gable_max_ends'])]
    if accepted:
        gable_ends=[list(v) for v in ends]
        for e in accepted:gable_ends[e['wing_index']][e['end_index']]=False
        gable_ends=[tuple(v) for v in gable_ends]
        candidate_units=[_wing_planes(w,h) for w,h in zip(boxes,gable_ends)]
        fit_tick=time.perf_counter();gable_fit=fit_units(candidate_units)
        if gable_fit is not None:
            variants.append(('finite_joined_supported_gables',gable_ends,candidate_units,gable_fit,time.perf_counter()-fit_tick,accepted))
    proposals=[]
    for label,ends,units,fit,elapsed,accepted_ends in variants:
        geo_tick=time.perf_counter()
        proposal=_fitted_proposal(poly,cells,settings,cfg,boxes,layout,units,ends,label,'common_eave',
            np.repeat(fit.x[0],len(boxes)),float(fit.x[1]),fit.x,counts,tick)
        proposal['connected_wings'].update(finite_domains=True,requires_continuous_roof=True,
            local_end_evidence=evidence,accepted_gable_edges=accepted_ends,
            construction='upper envelope over full connected wing domains; local measured terminal gables')
        proposal.update(requires_continuous_roof=True,candidate_label=label+' / common_eave',
            fitting_seconds=elapsed,geometry_seconds=time.perf_counter()-geo_tick)
        record_attempt('connected_wings',proposal['candidate_label'],fitting_seconds=elapsed,geometry_seconds=proposal['geometry_seconds'])
        proposals.append(proposal)
    return proposals

