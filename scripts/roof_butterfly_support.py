"""MODULE butterfly_support: measured local slopes, independent of model error.

A stepped collection of flat patches can resemble a V in global percentiles.
Require a majority of locally planar samples on EACH side to actually slope in
the candidate direction. A third end plane is excluded by active-plane ownership.
All normals are XY gradients dz/dx, dz/dy in the input coordinate frame.
"""
import time
import numpy as np
from scipy.spatial import cKDTree


DEFAULTS = dict(local_radius_m=1.5, local_max_p80_error_m=.25,
    local_min_neighbors=6, local_min_cells=8,
    min_directional_fraction=.60, min_directional_slope=.05)


def build_local_support(cells,cfg=None):
    """Fit robust local 2D planes once, then reuse them for every candidate."""
    tick=time.perf_counter();settings={**DEFAULTS,**(cfg or {})}
    cells=np.asarray(cells,float)
    if cells.ndim!=2 or cells.shape[1]!=3:
        raise ValueError('Local support expects an Nx3 array of median cells')
    count=len(cells);normals=np.full((count,2),np.nan);errors=np.full(count,np.nan)
    neighbors=np.zeros(count,dtype=int);finite=np.isfinite(cells).all(axis=1)
    indices=np.flatnonzero(finite)
    if len(indices):
        tree=cKDTree(cells[indices,:2])
        for index,local_ids in zip(indices,tree.query_ball_point(cells[indices,:2],settings['local_radius_m'])):
            ids=indices[local_ids];neighbors[index]=len(ids)
            if len(ids)<settings['local_min_neighbors']:
                continue
            sample=cells[ids];a=np.c_[sample[:,:2]-cells[index,:2],np.ones(len(sample))]
            # Reject effectively one-dimensional neighbourhoods at thin borders.
            if np.linalg.cond(a)>15.:
                continue
            beta=np.linalg.lstsq(a,sample[:,2],rcond=None)[0]
            for _ in range(3):
                residual=a@beta-sample[:,2]
                weight=np.sqrt(np.minimum(1.,.15/np.maximum(abs(residual),1e-9)))
                beta=np.linalg.lstsq(a*weight[:,None],sample[:,2]*weight,rcond=None)[0]
            normals[index]=beta[:2]
            errors[index]=float(np.quantile(abs(a@beta-sample[:,2]),.8))
    valid=finite&np.isfinite(normals).all(axis=1)&np.isfinite(errors)&(errors<=settings['local_max_p80_error_m'])
    return dict(normals=normals,valid=valid,p80_error_m=errors,neighbor_counts=neighbors,
        total_seconds=time.perf_counter()-tick,
        policy='Robust local planes; no filtering by the candidate roof residual.')


def evaluate_side_support(cells,planes,local_support,cfg=None):
    """Check the first two planes, using argmax ownership over ALL roof planes.

The optional third plane caps one end of the trough. Its cells cannot count
against either side. Returned records are JSON-ready; the reusable local arrays
belong only to build_local_support and should not be serialized into each model.
"""
    settings={**DEFAULTS,**(cfg or {})};cells=np.asarray(cells,float);planes=np.asarray(planes,float)
    if planes.ndim!=2 or planes.shape[1]!=3 or len(planes)<2:
        raise ValueError('Expected at least two plane coefficients [a,b,c]')
    normals=np.asarray(local_support['normals'],float);valid=np.asarray(local_support['valid'],bool)
    if normals.shape!=(len(cells),2) or valid.shape!=(len(cells),):
        raise ValueError('Local support and candidate cells do not match')
    values=np.c_[cells[:,:2],np.ones(len(cells))]@planes.T
    owners=np.argmax(values,axis=1)
    records=[]
    for index,label in enumerate(('left','right')):
        owned=(owners==index)&np.isfinite(cells).all(axis=1)
        planar=owned&valid
        gradient=planes[index,:2];length=float(np.linalg.norm(gradient))
        direction=gradient/length if length>1e-12 else np.zeros(2)
        measured=normals@direction
        directional=planar&(measured>=settings['min_directional_slope'])
        denominator=int(planar.sum());numerator=int(directional.sum())
        fraction=numerator/denominator if denominator else 0.
        reasons=[]
        if denominator<settings['local_min_cells']:
            reasons.append('insufficient_local_planar_cells')
        if fraction<settings['min_directional_fraction']:
            reasons.append('no_majority_of_measured_inward_slopes')
        if length<settings['min_directional_slope']:
            reasons.append('candidate_side_is_too_flat')
        records.append(dict(side=label,plane_index=index,accepted=not reasons,reasons=reasons,
            assigned_cells=int(owned.sum()),local_planar_cells=denominator,
            directional_cells=numerator,directional_fraction=float(fraction),
            median_uphill_slope=float(np.median(measured[planar])) if denominator else None,
            candidate_slope=float(length),min_directional_fraction=settings['min_directional_fraction'],
            min_directional_slope=settings['min_directional_slope'],
            ownership_policy='Upper envelope of all planes; cap-plane cells excluded; no roof-residual preselection.'))
    return records
