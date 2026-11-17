"""MODULE skeleton caps: remove end planes and continue surviving neighbors.

Works with polygonal, not just triangular, end faces. Only accept a patch if
it agrees with the old roof along ALL joins and cannot lower the removed roof.
Neighboring removed faces are reconstructed together. No point diagnostics or
observed-ridge lines participate in construction/selection.
"""
from __future__ import annotations
import numpy as np
import shapely
from shapely.geometry import LineString,shape,mapping
from shapely.ops import unary_union
from roof_v2_geometry import plane_regions


def _parts(g):
    if g.geom_type=='Polygon' and not g.is_empty:yield g
    elif hasattr(g,'geoms'):
        for p in g.geoms:yield from _parts(p)


def _height(planes,xy):
    return np.min(np.c_[xy,np.ones(len(xy))]@np.asarray(planes).T,axis=1)


def continuation_patch(faces,removed,tolerance=1e-5):
    selected=[f for f in faces if f['index'] in removed]
    domain=unary_union([f['polygon'] for f in selected])
    neighbors=[f for f in faces if f['index'] not in removed and
        domain.boundary.intersection(f['polygon'].boundary).length>.005]
    if len(neighbors)<2:raise ValueError('side_plane_count')
    planes=[f['plane'] for f in neighbors]
    # Each surviving face is itself in the lower envelope; affine endpoint
    # checks on every common segment ensure exact joins along the full segment.
    for neighbor in neighbors:
        join=domain.boundary.intersection(neighbor['polygon'].boundary)
        q=shapely.get_coordinates(join)
        if len(q) and np.max(abs(_height(planes,q)-np.c_[q,np.ones(len(q))]@neighbor['plane']))>tolerance:
            raise ValueError('neighbor_continuation_breaks_join')
    for old in selected:
        q=shapely.get_coordinates(old['polygon'])
        if np.min(_height(planes,q)-np.c_[q,np.ones(len(q))]@old['plane']) < -tolerance:
            raise ValueError('continuation_lowers_original_roof')
    patch=[]
    for piece in _parts(domain):patch.extend(plane_regions(piece,[p.tolist() for p in planes],mode='min'))
    return dict(patch=patch,polygon=domain,side_face_indices=[f['index'] for f in neighbors],planes=planes)


def edge_peak_profile(edge_xy,patch,cfg):
    a,b=np.asarray(edge_xy);q=a+np.linspace(0,1,21)[:,None]*(b-a)
    z=_height(patch['planes'],q);peak=int(np.argmax(z));lift=float(max(z)-max(z[0],z[-1]))
    if peak<3 or peak>17 or lift<cfg['min_unit_lift_m']:raise ValueError('no_interior_gable_peak')
    return dict(unit_edge_peak_m=float(z[peak]),peak_fraction=peak/20,
        unit_prominence_m=lift,edge_profile_unit_height=z.tolist())


def terminal_caps(reference,faces,cfg):
    caps=[];audit=[]
    for face in faces:
        boundary=shapely.line_merge(face['polygon'].boundary.intersection(reference.boundary))
        lines=[l for l in shapely.get_parts(boundary) if l.geom_type=='LineString']
        if not lines:continue
        edge=max(lines,key=lambda l:l.length);q=np.asarray(edge.coords);a,b=q[0],q[-1]
        length=float(np.linalg.norm(b-a));entry=dict(id='edge_'+str(face['index']+1),face_index=face['index'],
            edge_xy=[a.tolist(),b.tolist()],edge_length_m=length,
            face_vertex_count=len(face['polygon'].simplify(1e-7).exterior.coords)-1,eligible=False)
        audit.append(entry)
        if length<cfg['min_end_edge_m']:entry['reason']='edge_too_short';continue
        if face['polygon'].area<cfg['min_cap_area_m2']:entry['reason']='cap_too_small';continue
        try:
            patch=continuation_patch(faces,{face['index']})
            evidence=edge_peak_profile(entry['edge_xy'],patch,cfg)
        except ValueError as error:entry['reason']=str(error);continue
        entry.update(eligible=True,reason='eligible',continuation_neighbor_count=len(patch['side_face_indices']))
        caps.append(dict(face_index=face['index'],edge_xy=entry['edge_xy'],edge_length_m=length,
            cap_area_m2=face['polygon'].area,side_face_indices=patch['side_face_indices'],
            unit_midpoint_lift_m=evidence['unit_edge_peak_m'],end_profile=evidence,
            patch=patch['patch'],polygon=face['polygon'],audit_id=entry['id']))
    caps.sort(key=lambda c:(-c['edge_length_m'],-c['cap_area_m2'],c['face_index']))
    for cap in caps[int(cfg['max_gable_candidates']):]:
        next(e for e in audit if e['id']==cap['audit_id']).update(eligible=False,reason='candidate_budget')
    caps=caps[:int(cfg['max_gable_candidates'])]
    for i,cap in enumerate(caps):
        cap['id']='end_'+str(i+1);next(e for e in audit if e['id']==cap['audit_id'])['candidate_id']=cap['id']
    return caps,audit


def clipped_regions(faces,caps,selected,original,cfg=None):
    removed={caps[i]['face_index'] for i in selected};remaining=set(removed);components=[]
    lookup={f['index']:f for f in faces}
    while remaining:
        group={remaining.pop()};changed=True
        while changed:
            changed=False
            for i in list(remaining):
                if any(lookup[i]['polygon'].boundary.intersection(lookup[j]['polygon'].boundary).length>.005 for j in group):
                    group.add(i);remaining.remove(i);changed=True
        components.append(group)
    patches=[]
    for component in components:
        made=continuation_patch(faces,component)
        if cfg:
            for cap in caps:
                if cap['face_index'] in component:edge_peak_profile(cap['edge_xy'],made,cfg)
        patches.extend(made['patch'])
    pieces=patches+[dict(polygon=mapping(f['polygon']),plane=f['plane'].tolist()) for f in faces if f['index'] not in removed]
    regions=[]
    for piece in pieces:
        for poly in _parts(shape(piece['polygon']).intersection(original)):
            if poly.area>1e-8:regions.append(dict(polygon=mapping(poly),plane=list(piece['plane'])))
    return regions
