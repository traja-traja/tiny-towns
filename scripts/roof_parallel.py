"""MODULE parallel_gables: 2–4 parallel horizontal ridges and their valleys.

Fit a small piecewise-linear transverse height profile to the existing cells.
Each segment becomes one planar roof face, clipped to the original footprint.
No address rules. Ridge spacing and heights are fitted; ridges stay aligned
with the main wall directions. The candidate competes with all existing types.
"""
import numpy as np
import shapely
from shapely.geometry import Polygon, mapping
from scipy.optimize import least_squares
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
from roof_config import point_error


def _parts(geometry):
    if geometry.geom_type=='Polygon' and not geometry.is_empty:
        yield geometry
    elif hasattr(geometry,'geoms'):
        for part in geometry.geoms:
            yield from _parts(part)


def _predict(v, knots, heights):
    index = np.clip(np.searchsorted(knots,v,side='right')-1,0,len(knots)-2)
    fraction = (v-knots[index])/(knots[index+1]-knots[index])
    return heights[index]+fraction*(heights[index+1]-heights[index])


def parallel_proposal(poly, matrix, extent, cells, count, settings):
    cfg, scoring = settings['parallel_gables'],settings['scoring']
    u0,u1,v0,v1 = map(float,extent[:4]); span = v1-v0
    if span < count*cfg['min_bay_width_m']:
        return None
    uv = cells[:,:2]@matrix; v,z = uv[:,1],cells[:,2]
    bins = np.arange(v0,v1+cfg['profile_bin_m'],cfg['profile_bin_m'])
    centers = (bins[:-1]+bins[1:])/2
    medians = np.array([np.median(z[(v>=a)&(v<b)]) if np.any((v>=a)&(v<b)) else np.nan
                        for a,b in zip(bins[:-1],bins[1:])])
    valid = np.isfinite(medians)
    if valid.sum()<5:
        return None
    smooth = gaussian_filter1d(np.interp(centers,centers[valid],medians[valid]),1.)
    peaks, info = find_peaks(smooth,prominence=cfg['min_prominence_m'],
        distance=max(1,int(cfg['min_bay_width_m']/cfg['profile_bin_m'])))
    gap = cfg['min_segment_width_m']; segments = 2*count
    if span <= segments*gap:
        return None
    knots = np.linspace(v0,v1,segments+1)
    if len(peaks)>=count:
        picked = np.sort(peaks[np.argsort(info['prominences'])[-count:]])
        proposed = [v0]
        for index, peak in enumerate(picked):
            proposed.append(float(centers[peak]))
            if index<count-1:
                valley = peak+int(np.argmin(smooth[peak:picked[index+1]+1]))
                proposed.append(float(centers[valley]))
        proposed.append(v1)
        if np.min(np.diff(proposed))>gap:
            knots = np.array(proposed)
    residual_widths = np.maximum(np.diff(knots)-gap,1e-4)
    widths = np.clip(np.log(residual_widths[:-1]/residual_widths[-1]),-3.,3.)
    q10,q90 = np.quantile(z,[.1,.9])
    eave = max(.6,float(q10)-.5)
    max_rise = max(5.,float(np.ptp(z))+5.)
    rises = np.clip(np.interp(knots[1::2],centers,smooth)-eave,cfg['min_rise_m'],max_rise-.01)
    initial = np.r_[widths,eave,rises,np.full(count-1,.8)]
    lower = np.r_[np.full(segments-1,-3.),.5,np.full(count,cfg['min_rise_m']),np.full(count-1,.1)]
    upper = np.r_[np.full(segments-1,3.),max(1.,float(q90)),np.full(count,max_rise),np.ones(count-1)]
    initial = np.clip(initial,lower+1e-7,upper-1e-7)

    def decode(parameters):
        weights = np.exp(np.r_[parameters[:segments-1],0.])
        lengths = gap+(span-segments*gap)*weights/weights.sum()
        positions = np.r_[v0,v0+np.cumsum(lengths)]
        E = parameters[segments-1]
        rise = parameters[segments:segments+count]
        depth = parameters[segments+count:]
        heights = np.full(segments+1,E)
        heights[1::2] = E+rise
        heights[2:-1:2] = E+np.minimum(rise[:-1],rise[1:])*(1-depth)
        return positions,heights

    fit = least_squares(lambda p:_predict(v,*decode(p))-z,initial,bounds=(lower,upper),
        loss='soft_l1',f_scale=.25,max_nfev=cfg['max_fit_evaluations'],
        ftol=2e-4,xtol=2e-4,gtol=2e-4)
    knots,heights = decode(fit.x)
    residual = abs(_predict(v,knots,heights)-z)
    support = []
    for index in range(count):
        peak = 2*index+1
        prominence = float(heights[peak]-max(heights[peak-1],heights[peak+1]))
        nearby = abs(v-knots[peak])<cfg['support_distance_m']
        supported = int(np.sum(nearby & (residual<cfg['support_error_m'])))
        support.append({'nearby_cells':int(nearby.sum()),'supported_cells':supported,'prominence_m':prominence})
        if prominence<cfg['min_prominence_m'] or supported<cfg['min_support_cells']:
            return None
    uv_poly = shapely.get_coordinates(poly)@matrix
    low_u,high_u = float(uv_poly[:,0].min())-1,float(uv_poly[:,0].max())+1
    low_v,high_v = float(uv_poly[:,1].min())-1,float(uv_poly[:,1].max())+1
    regions = []
    for index in range(segments):
        lo = min(low_v,knots[0]) if index==0 else knots[index]
        hi = max(high_v,knots[-1]) if index==segments-1 else knots[index+1]
        strip = Polygon(np.array([[low_u,lo],[high_u,lo],[high_u,hi],[low_u,hi]])@matrix.T)
        slope = (heights[index+1]-heights[index])/(knots[index+1]-knots[index])
        normal = matrix@np.array([0.,slope])
        plane = [*map(float,normal),float(heights[index]-slope*knots[index])]
        regions.extend({'polygon':mapping(piece),'plane':plane} for piece in _parts(poly.intersection(strip)) if piece.area>1e-8)
    def line(offset):
        return (np.array([[low_u,offset],[high_u,offset]])@matrix.T).tolist()
    error = point_error(residual,scoring)
    penalty = scoring['complexity_m']['parallel_gables']+cfg['extra_ridge_penalty_m']*(count-1)
    return {'kind':'parallel_gables','hips':(), 'score':error+penalty,'data_error_m':error,
        'complexity_penalty_m':penalty,'support_penalty_m':0.,'parameters':fit.x,
        'strip_regions':regions,'ridge_xy':[line(t) for t in knots[1::2]],
        'ridge_heights_m':heights[1::2].tolist(), 'valley_xy':[line(t) for t in knots[2:-1:2]],
        'valley_heights_m':heights[2:-1:2].tolist(), 'cross_section_uvz':np.c_[knots,heights].tolist(),
        'eave_height_m':float(heights[0]),'ridge_height_m':float(max(heights)),
        'matrix':matrix,'extent':extent,'branch_support':support,'ridge_count':count}
