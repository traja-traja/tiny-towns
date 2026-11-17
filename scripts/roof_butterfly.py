"""MODULE butterfly: evidence-backed inward roof with one closing end plane.

Dominant wall lines anchor horizontal high edges. The three-plane upper
 envelope forms two inward slopes and a triangular end, without address rules.
"""
import numpy as np
from scipy.optimize import least_squares
from roof_config import point_error
from roof_butterfly_support import build_local_support,evaluate_side_support


def _wall(poly,matrix,extent,axis,side,cfg):
    coords=np.asarray(poly.exterior.coords)[:-1];edges=np.roll(coords,-1,axis=0)-coords
    expected=extent[axis*2+side];normal=matrix[:,axis]*(1 if side==0 else -1)
    along=matrix[:,1-axis];choices=[]
    for a,edge in zip(coords,edges):
        length=np.linalg.norm(edge)
        if length<cfg['min_wall_m'] or abs(edge@along)/length<np.cos(np.deg2rad(cfg['wall_angle_deg'])):continue
        offset=abs(float((a+edge/2)@matrix[:,axis])-expected)
        if offset>cfg['wall_offset_m']:continue
        n=np.array([-edge[1],edge[0]])/length
        if n@normal<0:n=-n
        choices.append((offset-.01*length,n,float(n@a),[a.tolist(),(a+edge).tolist()]))
    if choices:
        _,n,c,line=min(choices,key=lambda item:item[0])
        return dict(normal=n,offset=c,line=line,source='actual_dominant_wall')
    point=matrix[:,axis]*expected
    return dict(normal=normal,offset=float(normal@point),line=None,source='reference_frame')


def butterfly_proposal(poly,matrix,extent,cells,settings,cap_end=0,local_support=None):
    cfg=settings['butterfly'];scoring=settings['scoring']
    u0,u1,v0,v1=extent[:4];width=v1-v0
    if width<cfg['min_width_m'] or len(cells)<2*cfg['min_side_cells']:return None
    uv=cells[:,:2]@matrix;z=cells[:,2];v=uv[:,1];A=np.c_[cells[:,:2],np.ones(len(cells))]
    z10,z90=np.quantile(z,[.1,.9]);margin=cfg['min_side_fraction']
    capped=cfg['end_cap_required'];walls=[_wall(poly,matrix,extent,1,s,cfg) for s in (0,1)]
    if capped:walls.append(_wall(poly,matrix,extent,0,cap_end,cfg))
    low=[margin,.5,cfg['min_rise_m']]
    high=[1-margin,max(1.,float(z90)),max(3.,float(np.ptp(z))+3)]
    def geometry(p):
        valley=v0+p[0]*width;anchor=matrix@np.array([(u0+u1)/2,valley]);high_z=p[1]+p[2]
        distances=[float(anchor@w['normal']-w['offset']) for w in walls[:2]]
        if min(distances)<=.05:raise ValueError('Valley reference is outside the opposing main walls')
        slopes=[p[2]/d for d in distances]
        if capped:slopes.append(float(np.mean(slopes)))
        planes=[[*(-s*w['normal']).tolist(),float(high_z+s*w['offset'])] for s,w in zip(slopes,walls)]
        return planes,slopes,anchor
    def prediction(p):return np.max(A@np.asarray(geometry(p)[0]).T,axis=1)
    fitted=[]
    for fraction in (.3,.5,.7):
        initial=np.clip([fraction,max(.6,float(z10)),max(cfg['min_rise_m']*1.5,float(z90-z10))],np.asarray(low)+1e-6,np.asarray(high)-1e-6)
        try:
            fit=least_squares(lambda p:prediction(p)-z,initial,bounds=(low,high),loss='soft_l1',f_scale=.25,
                max_nfev=cfg['max_nfev'],ftol=2e-4,xtol=2e-4,gtol=2e-4)
            fitted.append((point_error(abs(prediction(fit.x)-z),scoring),fit.x))
        except ValueError:continue
    if not fitted:return None
    data_error,p=min(fitted,key=lambda item:item[0]);planes,slopes,anchor=geometry(p)
    pred=prediction(p);active=np.argmax(A@np.asarray(planes).T,axis=1);residual=abs(pred-z)
    rejection=[];support=[];valley=v0+p[0]*width
    for i,(label,distance,span) in enumerate((('left',valley-v,valley-v0),('right',v-valley,v1-valley))):
        side=active==i;count=int(side.sum());supported=side&(residual<=cfg['support_error_m'])
        near=side&(distance>=0)&(distance<=.30*span);outer=side&(distance>=.65*span)&(distance<=1.1*span)
        rise=float(np.median(z[outer])-np.median(z[near])) if near.sum()>=3 and outer.sum()>=3 else None
        support.append(dict(side=label,cells=count,supported_cells=int(supported.sum()),observed_rise_m=rise))
        if count<cfg['min_side_cells'] or supported.sum()<cfg['min_side_cells'] or supported.sum()<cfg['min_support_fraction']*count:rejection.append(label+'_insufficient_plane_support')
        if rise is None or rise<cfg['min_observed_rise_m']:rejection.append(label+'_no_observed_rise_away_from_valley')
    if max(np.degrees(np.arctan(np.asarray(slopes))))>cfg['max_slope_deg']:rejection.append('butterfly_slope_too_steep')
    directional=[]
    if cfg['local_direction_check']:
        if local_support is None:local_support=build_local_support(cells,cfg)
        directional=evaluate_side_support(cells,planes,local_support,cfg)
        for i,item in enumerate(directional):
            if not item['accepted']:rejection.append(('left' if i==0 else 'right')+'_local_slope_direction_not_supported')
    if capped:
        cap_fraction=float(np.mean(active==2))
        if cap_fraction<cfg['min_cap_fraction'] or cap_fraction>cfg['max_cap_fraction']:rejection.append('end_cap_has_insufficient_or_excessive_area_support')
    else:cap_fraction=0.
    penalty=scoring['complexity_m']['butterfly']+(cfg['end_cap_penalty_m'] if capped else 0.)
    return dict(kind='butterfly',hips=(),parameters=p,matrix=matrix,extent=extent,upper_planes=planes,ridge_xy=[],
        eave_height_m=float(p[1]),ridge_height_m=float(p[1]+p[2]),valley_height_m=float(p[1]),
        high_edge_height_m=float(p[1]+p[2]),valley_depth_m=float(p[2]),
        score=float(data_error+penalty),data_error_m=float(data_error),complexity_penalty_m=penalty,support_penalty_m=0.,
        plane_count=len(planes),branch_support=support,evidence_rejections=rejection,
        butterfly=dict(end_cap=capped,cap_end=cap_end if capped else None,cap_fraction=cap_fraction,
            slopes_deg=np.degrees(np.arctan(np.asarray(slopes))).tolist(),
            wall_anchors=[dict(line=w['line'],source=w['source']) for w in walls],
            side_direction_support=directional,valley_reference_xy=anchor.tolist(),
            horizontal_edge_policy='Each plane anchored to one horizontal dominant facade edge; nonparallel walls may yield a gently sloping valley.'),
        drainage_policy='Inward side planes and one closing triangular end plane; dominant facade edges share one horizontal height.')
