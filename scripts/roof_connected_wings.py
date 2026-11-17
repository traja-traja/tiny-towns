"""MODULE connected_wings: bounded roof tents from opposing footprint walls.

Each wing has two primary eaves and finite end planes. Their upper envelope
creates valleys at real wing junctions; a global minimum over all courtyard
walls is deliberately not used. The unchanged footprint clips the result.
"""
import math
import time
import numpy as np
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
    'complexity_penalty_m':.065}


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
        if deviation<=cfg['snap_frame_max_deviation_deg']:
            for w in walls:
                projection=w['u']@frame;axis=int(np.argmax(np.abs(projection)))
                u=frame[:,axis]*np.sign(projection[axis]);n=np.array([-u[1],u[0]])
                q=np.array([w['a'],w['b']]);lo,hi=float((q@u).min()),float((q@u).max());offset=float(np.mean(q@n))
                w.update(a=u*lo+n*offset,b=u*hi+n*offset,u=u,n=n,length=hi-lo)
    return basic,walls


def _wing_boxes(poly,cfg):
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
    if hip_ends[0]:planes.append(np.r_[u,-wing['lo']])
    if hip_ends[1]:planes.append(np.r_[-u,wing['hi']])
    return np.asarray(planes)


def _envelope(poly,wings):
    # Start with the horizontal eave as a safe finite extension for tiny
    # footprint details not represented by any primary wing.
    poly=shapely.set_precision(poly,1e-7)
    sources=[];lines=[poly.boundary]
    for group,planes in enumerate([np.array([[0.,0.,0.]])]+wings):
        for r in plane_regions(poly,planes):
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
        a=np.array([point.x,point.y,1.]);winning=np.array([0.,0.,0.]);height=0.
        for planes in wings:
            values=planes@a;index=int(np.argmin(values))
            if values[index]>height:height=float(values[index]);winning=planes[index]
        key=tuple(winning)
        groups.setdefault(key,[]).append(cell)
    regions=[{'polygon':mapping(p),'plane':list(key)} for key,ps in groups.items()
             for p in _polygons(unary_union(ps))]
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
    if not poly.interiors and 1-poly.area/poly.convex_hull.area<cfg['min_concavity_fraction']:return []
    boxes,layout=_wing_boxes(poly,cfg)
    if len(boxes)<2:return []
    xy=np.asarray(cells[:,:2]); z=np.asarray(cells[:,2]); A=np.c_[xy,np.ones(len(xy))]
    variants=[('hipped',[(True,True)]*len(boxes))]
    if cfg['gable_variants']:
        # Only globally exposed ends may omit their cap: there is no domain
        # beyond such an end where an infinite gable could take over a wing.
        gables=[]
        coords=shapely.get_coordinates(poly)
        for w in boxes:
            bounds=coords@w['u']; pad=.7
            gables.append((not(w['physical_ends'][0] and w['lo']<=bounds.min()+pad),
                           not(w['physical_ends'][1] and w['hi']>=bounds.max()-pad)))
        if any(not a or not b for a,b in gables):variants.append(('exposed_gables',gables))
    proposals=[]
    # Evidence is local to each finite supporting rectangle. Missing returns
    # never justify an independently fitted height.
    masks=[shapely.intersects_xy(w['polygon'],xy[:,0],xy[:,1]) for w in boxes]
    counts=[int(m.sum()) for m in masks]
    for label,ends in variants:
        unit_wings=[_wing_planes(w,h) for w,h in zip(boxes,ends)]
        unit_predictions=np.array([np.min(A@p.T,axis=1) for p in unit_wings])
        support=np.maximum(0,np.max(unit_predictions,axis=0))
        useful=support>.25
        if useful.sum()<20:continue
        z10,z90=np.quantile(z,[.1,.9]); q90=np.quantile(support[useful],.9)
        initial=[max(.6,z10-.3),float(np.clip((z90-z10)/max(q90,.5),.15,2.))]
        common=least_squares(lambda p:p[0]+p[1]*support-z,initial,
            bounds=([.5,.12],[max(1.,float(z90)),2.5]),loss='soft_l1',f_scale=.35,
            max_nfev=cfg['max_nfev'],ftol=2e-4,xtol=2e-4,gtol=2e-4)
        fits=[('common_eave',np.repeat(common.x[0],len(boxes)),float(common.x[1]),common.x)]
        local=[]
        for i,m in enumerate(masks):
            if counts[i]<cfg['min_wing_cells']:local.append(None);continue
            f=least_squares(lambda p:p[0]+p[1]*unit_predictions[i,m]-z[m],common.x,
                bounds=([.5,.12],[max(1.,float(z90)),2.5]),loss='soft_l1',f_scale=.35,max_nfev=40)
            local.append(f.x)
        supported=[i for i,p in enumerate(local) if p is not None]
        if cfg['separate_eave_variants'] and len(supported)>1 and np.ptp([local[i][0] for i in supported])>=cfg['eave_difference_threshold_m']:
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
            fits.append(('measured_eave_groups',independent.x[:-1][owners],float(independent.x[-1]),independent.x))
        for eave_mode,eaves,pitch,parameters in fits:
            proposal=_fitted_proposal(poly,cells,settings,cfg,boxes,layout,unit_wings,ends,label,eave_mode,eaves,pitch,parameters,counts,tick)
            proposals.append(proposal)
    return proposals


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
    return result


def _fitted_proposal(poly,cells,settings,cfg,boxes,layout,unit_wings,ends,label,eave_mode,eaves,pitch,parameters,counts,tick):
        xy=np.asarray(cells[:,:2]);z=np.asarray(cells[:,2]);A=np.c_[xy,np.ones(len(xy))]
        base=float(np.min(eaves));eave=float(eaves[np.argmax(counts)])
        wings=[pitch*p+np.array([0.,0.,height-base]) for p,height in zip(unit_wings,eaves)]
        support=np.maximum(0,np.max([np.min(A@p.T,axis=1) for p in wings],axis=0))
        useful=support>.25
        pred=base+support
        residual=np.abs(pred-z);error=point_error(residual,settings['scoring'])
        normalized=_envelope(poly,wings)
        regions=[{'polygon':r['polygon'],'plane':[r['plane'][0],r['plane'][1],base+r['plane'][2]]} for r in normalized]
        ridges=[];ridge_heights=[];support_meta=[]
        for w,h,wing_eave in zip(boxes,ends,eaves):
            mid=(w['bottom']+w['top'])/2
            start=w['lo']+(w['width']/2 if h[0] else 0)
            end=w['hi']-(w['width']/2 if h[1] else 0)
            if end-start<=.1:continue
            segment=LineString([w['u']*start+w['v']*mid,w['u']*end+w['v']*mid])
            height=float(wing_eave)+pitch*w['width']/2
            distance=shapely.distance(shapely.points(xy),segment)
            near=distance<.9
            supported=near&(np.abs(z-height)<.9)
            support_meta.append({'nearby_cells':int(near.sum()),'supported_cells':int(supported.sum()),
                'width_m':w['width'],'length_m':w['length'],'ridge_height_m':height})
            ridges.append(np.asarray(segment.coords).tolist());ridge_heights.append(height)
        penalty=cfg['complexity_penalty_m']+.008*max(0,len(boxes)-2)+(cfg['separate_eave_penalty_m']*(len(np.unique(eaves))-1) if eave_mode!='common_eave' else 0.)
        frame=np.column_stack((boxes[0]['u'],boxes[0]['v']))
        coords=shapely.get_coordinates(poly)@frame
        metadata={**layout,'variant':label,'pitch_tangent':pitch,'pitch_degrees':math.degrees(math.atan(pitch)),
                  'common_eave':eave_mode=='common_eave','common_pitch':True,'eave_mode':eave_mode,'wing_eaves_m':eaves.tolist(),'wing_cell_counts':counts,'unsupported_wings':[i for i,n in enumerate(counts) if n<cfg['min_wing_cells']],'wing_widths_m':[float(w['width']) for w in boxes],
                  'wing_frames_xy':[np.column_stack((w['u'],w['v'])).tolist() for w in boxes],
                  'covered_point_fraction':float(useful.mean()),'candidate_seconds':time.perf_counter()-tick,
                  'construction':'upper envelope of finite convex wing roofs; original footprint clipping',
                  'settings':cfg}
        heights=[float(np.r_[q,1]@r['plane']) for r in regions for q in shapely.get_coordinates(shape(r['polygon']))]
        return {'kind':'connected_wings','hips':(), 'score':float(error+penalty),
            'data_error_m':float(error),'complexity_penalty_m':float(penalty),'support_penalty_m':0.,
            'parameters':parameters,'strip_regions':regions,'ridge_xy':ridges,'ridge_heights_m':ridge_heights,
            'eave_height_m':eave,'ridge_height_m':max(heights),'matrix':frame,
            'extent':[float(coords[:,0].min()),float(coords[:,0].max()),float(coords[:,1].min()),float(coords[:,1].max())],
            'branch_support':support_meta,'connected_wings':metadata,'supporting_envelope':'opposing primary wall pairs'}
