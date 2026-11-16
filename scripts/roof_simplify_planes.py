"""Bounded adjacent-plane simplification of an existing 2.5D roof mesh.

This is a geometric postprocess, not a new point-cloud reconstruction. The
vertical tolerance measures change from the supplied roof, not survey accuracy.
Holdout observations must never be passed to the merger or used to select merges.
"""
from __future__ import annotations

import copy
import math
import time

import numpy as np
import shapely
from shapely.geometry import Polygon, LineString, mapping
from shapely.ops import unary_union, triangulate
from shapely.strtree import STRtree


def _polygons(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [p for p in getattr(geometry, "geoms", []) if p.geom_type == "Polygon"]


def _line_segments(geometry):
    if geometry.geom_type in ("LineString", "LinearRing"):
        coords = list(geometry.coords)
        return [(np.asarray(a, float), np.asarray(b, float))
                for a, b in zip(coords, coords[1:]) if np.linalg.norm(np.subtract(a, b)) > 1e-8]
    result = []
    for part in getattr(geometry, "geoms", []):
        result.extend(_line_segments(part))
    return result


def _z(plane, xy):
    xy = np.asarray(xy, float)
    return xy[..., 0] * plane[0] + xy[..., 1] * plane[1] + plane[2]


def _normal(plane):
    n = np.asarray([-plane[0], -plane[1], 1.0])
    return n / np.linalg.norm(n)


def _fit(indices, triangles, areas):
    """Area integral least squares using exact degree-two triangle quadrature."""
    idx = np.asarray(sorted(indices), dtype=int)
    xyz = triangles[idx]
    # These three barycentric samples integrate all quadratic residual terms.
    bary = np.asarray([[2/3, 1/6, 1/6], [1/6, 2/3, 1/6], [1/6, 1/6, 2/3]])
    samples = np.einsum("ij,njk->nik", bary, xyz).reshape(-1, 3)
    weights = np.repeat(areas[idx] / 3, 3)
    centre = np.average(samples[:, :2], weights=weights, axis=0)
    design = np.column_stack((samples[:, :2] - centre, np.ones(len(samples))))
    coef, _, rank, _ = np.linalg.lstsq(design * np.sqrt(weights[:, None]),
                                      samples[:, 2] * np.sqrt(weights), rcond=None)
    if rank < 3:
        raise ValueError("Degenerate projected roof patch")
    plane = np.asarray([coef[0], coef[1], coef[2] - coef[:2] @ centre])
    err = _z(plane, xyz[:, :, :2]) - xyz[:, :, 2]
    qerr = _z(plane, samples[:, :2]) - samples[:, 2]
    return plane, float(np.max(np.abs(err))), float(np.dot(weights, qerr*qerr) / weights.sum())


def _triangles(poly):
    if hasattr(shapely, "constrained_delaunay_triangles"):
        triangles = list(shapely.constrained_delaunay_triangles(poly).geoms)
    else:
        triangles = [p for p in triangulate(poly) if poly.covers(p)]
    if abs(sum(p.area for p in triangles) - poly.area) > max(1e-7, poly.area * 1e-8):
        raise ValueError("Incomplete region triangulation")
    return triangles


def _mesh_regions(regions, domain, floor_z):
    """Closed height-field boundary; interior interfaces get only step walls.

    Polygon boundaries are noded in XY. At a crossing of two height functions,
    split a vertical interface to avoid a bow-tie quad. Individual regions are
    planar, and no common interior walls are extruded all the way to ground.
    """
    vertices, faces, semantics, lookup, face_region_ids = [], [], [], {}, []

    def vertex(xyz):
        key = tuple(round(float(v), 8) for v in xyz)
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append([float(v) for v in xyz])
        return lookup[key]

    def face(xyz, semantic, reverse=False, region_id=-1):
        ids = [vertex(p) for p in xyz]
        if len(set(ids)) < 3:
            return
        a, b, c = np.asarray([vertices[i] for i in ids])
        if np.linalg.norm(np.cross(b-a, c-a)) <= 1e-9:
            return
        faces.append(ids[::-1] if reverse else ids)
        semantics.append(semantic)
        face_region_ids.append(region_id)

    for region in regions:
        for p in _polygons(region["geometry"]):
            for tri in _triangles(p):
                xy = np.asarray(tri.exterior.coords)[:3]
                xyz = np.column_stack((xy, _z(region["plane"], xy)))
                reverse = np.cross(xyz[1]-xyz[0], xyz[2]-xyz[0])[2] < 0
                face(xyz, "roof", reverse, region["id"])

    for p in _polygons(domain):
        for tri in _triangles(p):
            xy = np.asarray(tri.exterior.coords)[:3]
            xyz = np.column_stack((xy, np.full(3, floor_z)))
            reverse = np.cross(xyz[1]-xyz[0], xyz[2]-xyz[0])[2] > 0
            face(xyz, "ground", reverse)

    boundaries = [r["geometry"].boundary for r in regions]
    network = unary_union(boundaries)
    tree = STRtree(boundaries)
    edge_lookup = set()
    structural_edges = []
    step_wall_count = 0
    max_interface_jump = 0.0
    for a, b in _line_segments(network):
        mid = shapely.Point((a+b)/2)
        touching = [int(i) for i in tree.query(mid.buffer(1e-7))
                    if boundaries[int(i)].distance(mid) < 1e-7]
        if not 1 <= len(touching) <= 2:
            raise ValueError(f"Non-partition boundary touches {len(touching)} roof regions")
        za = _z(regions[touching[0]]["plane"], [a, b])
        zb = (_z(regions[touching[1]]["plane"], [a, b]) if len(touching) == 2
              else np.full(2, floor_z))
        for heights in [za] + ([zb] if len(touching) == 2 else []):
            edge = [[*a, heights[0]], [*b, heights[1]]]
            key = tuple(sorted(tuple(round(float(v), 7) for v in p) for p in edge))
            if key not in edge_lookup:
                edge_lookup.add(key)
                structural_edges.append([[float(v) for v in p] for p in edge])
        if len(touching) == 2:
            max_interface_jump = max(max_interface_jump, float(np.max(np.abs(za-zb))))
        dif = za-zb
        split = [0.0, 1.0]
        if dif[0]*dif[1] < -1e-12:
            split.insert(1, float(dif[0] / (dif[0]-dif[1])))
        for lo, hi in zip(split, split[1:]):
            xy1, xy2 = a+(b-a)*lo, a+(b-a)*hi
            z1a, z2a = za[0]+(za[1]-za[0])*lo, za[0]+(za[1]-za[0])*hi
            z1b, z2b = zb[0]+(zb[1]-zb[0])*lo, zb[0]+(zb[1]-zb[0])*hi
            if max(abs(z1a-z1b), abs(z2a-z2b)) < 1e-8:
                continue
            # The normal of [a upper,b upper,b lower] points to the segment's left.
            a_higher = z1a+z2a >= z1b+z2b
            high_region = touching[0] if a_higher else touching[1] if len(touching)==2 else touching[0]
            direction = b-a
            left = np.asarray([-direction[1], direction[0]]) / np.linalg.norm(direction)
            inside_left = regions[high_region]["geometry"].covers(shapely.Point((xy1+xy2)/2 + left*1e-5))
            upper1, upper2 = max(z1a,z1b), max(z2a,z2b)
            lower1, lower2 = min(z1a,z1b), min(z2a,z2b)
            quad = [[*xy1,upper1],[*xy2,upper2],[*xy2,lower2],[*xy1,lower1]]
            face([quad[0],quad[1],quad[2]],"wall",inside_left)
            face([quad[0],quad[2],quad[3]],"wall",inside_left)
            if len(touching)==2:
                step_wall_count += 1
    return vertices, faces, semantics, structural_edges, step_wall_count, max_interface_jump, face_region_ids


def _partition(model):
    vertices = np.asarray(model.get("vertices", []), float)
    source_faces = [f for f,s in zip(model.get("faces",[]),model.get("face_semantics",[])) if s=="roof"]
    if not source_faces:
        raise ValueError("No roof geometry supplied")
    if any(len(f)!=3 for f in source_faces):
        raise ValueError("Expected a triangulated roof")
    triangles = vertices[np.asarray(source_faces,int)]
    polygons = [Polygon(t[:,:2]) for t in triangles]
    if any(not p.is_valid or p.area <= 1e-8 for p in polygons):
        raise ValueError("Invalid or vertical source roof triangle; do not silently discard it")
    areas = np.asarray([p.area for p in polygons])
    domain = unary_union(polygons)
    if sum(areas)-domain.area > max(1e-5,domain.area*1e-8):
        raise ValueError("Overlapping roof projection is not a single 2.5D partition")
    if not domain.is_valid:
        raise ValueError("Invalid source roof domain")
    source_planes = np.asarray([_fit({i},triangles,areas)[0] for i in range(len(triangles))])
    normals = np.asarray([_normal(p) for p in source_planes])
    tree = STRtree(polygons)
    adjacency = []
    for i,p in enumerate(polygons):
        for j0 in tree.query(p):
            j=int(j0)
            if j<=i:
                continue
            common=p.boundary.intersection(polygons[j].boundary)
            if common.length <= 1e-6:
                continue
            xy=np.asarray([q for a,b in _line_segments(common) for q in [a,b]])
            if not len(xy):
                continue
            baseline_gap=np.abs(_z(source_planes[i],xy)-_z(source_planes[j],xy))
            adjacency.append((i,j,xy,baseline_gap))
    return vertices, triangles, polygons, areas, domain, source_planes, normals, adjacency


def _coplanar_groups(triangles, areas, source_planes, normals, adjacency,
                     tolerance_m=.003, angle_deg=.25):
    groups={i:{i} for i in range(len(triangles))}
    planes={i:p for i,p in enumerate(source_planes)}
    labels={i:i for i in range(len(triangles))}
    cos_limit=math.cos(math.radians(angle_deg))
    for i,j,xy,gap in adjacency:
        a,b=labels[i],labels[j]
        if a==b or float(np.max(gap))>tolerance_m:
            continue
        indices=groups[a]|groups[b]
        plane,change,_=_fit(indices,triangles,areas)
        # Group-level check prevents transitive chaining across a curved roof.
        if change>tolerance_m or float(np.min(normals[list(indices)]@_normal(plane)))<cos_limit:
            continue
        groups[a]|=groups.pop(b);planes[a]=plane;planes.pop(b)
        for k in groups[a]:labels[k]=a
    return groups,planes,labels


def extract_roof_regions(model, *, tolerance_m=.003, angle_deg=.25):
    """Shared geometric plane-count metric for native, template and merged meshes.

    Adjacent triangles are grouped only when a joint plane fits every original
    vertex to 3 mm and every triangle normal to 0.25 degrees by default. Counts
    are connected nearly-coplanar regions, not native CityJSON surface records.
    Raises for overlapping roof projections instead of silently selecting a roof.
    """
    _,triangles,polygons,areas,domain,source_planes,normals,adjacency=_partition(model)
    groups,planes,labels=_coplanar_groups(triangles,areas,source_planes,normals,adjacency,tolerance_m,angle_deg)
    regions=[]
    for k,indices in sorted(groups.items()):
        union=unary_union([polygons[i] for i in sorted(indices)]).simplify(1e-8,preserve_topology=True)
        for p in _polygons(union):
            regions.append({"id":len(regions),"polygon":mapping(p),"plane":planes[k].tolist(),
                            "source_roof_triangles":sorted(indices)})
    return {"region_count":len(regions),"regions":regions,
            "tolerance_m":tolerance_m,"angle_deg":angle_deg,
            "metric":"connected near-coplanar roof regions, same geometric gate for all methods"}


def simplify_roof(model, train_relative, polygon, *, max_vertical_change_m=0.5,
                  max_normal_angle_deg=15.0, max_interface_jump_increase_m=None):
    """Merge adjoining, similarly oriented roof patches and rebuild geometry.

    ``train_relative`` is accepted for the shared experiment API but unused:
    this method approximates an existing reconstruction, without another fit
    to points. ``polygon`` is the input footprint in the model's local XY.
    """
    started = time.perf_counter()
    if not 0 < max_vertical_change_m <= 2:
        raise ValueError("Vertical tolerance must be in (0,2] metres")
    if not 0 < max_normal_angle_deg < 45:
        raise ValueError("Normal tolerance must be in (0,45) degrees")
    if max_interface_jump_increase_m is None:
        max_interface_jump_increase_m = max_vertical_change_m
    if not 0 <= max_interface_jump_increase_m <= max_vertical_change_m:
        raise ValueError("New interface-jump limit must be in [0,vertical tolerance]")
    vertices,triangles,polygons,areas,domain,source_planes,normals,adjacency=_partition(model)
    groups,planes,labels=_coplanar_groups(triangles,areas,source_planes,normals,adjacency)
    initial_count=len(groups)
    cos_limit=math.cos(math.radians(max_normal_angle_deg))
    merges=[]
    considered=0
    while True:
        pairs={tuple(sorted((labels[i],labels[j]))) for i,j,xy,gap in adjacency if labels[i]!=labels[j]}
        candidates=[]
        for a,b in sorted(pairs):
            considered+=1
            indices=groups[a]|groups[b]
            plane,change,mse=_fit(indices,triangles,areas)
            if change > max_vertical_change_m+1e-9:
                continue
            if float(np.min(normals[list(indices)]@_normal(plane))) < cos_limit:
                continue
            max_new_gap=0.0
            for i,j,xy,baseline_gap in adjacency:
                li,lj=labels[i],labels[j]
                in_i,in_j=li in (a,b),lj in (a,b)
                if in_i==in_j:
                    continue
                other=planes[lj if in_i else li]
                excess=np.abs(_z(plane,xy)-_z(other,xy))-baseline_gap
                max_new_gap=max(max_new_gap,float(np.max(excess)))
            if max_new_gap > max_interface_jump_increase_m+1e-8:
                continue
            candidates.append((mse,change,a,b,plane,max_new_gap))
        if not candidates:
            break
        _,change,a,b,plane,new_gap=min(candidates,key=lambda x:(x[0],x[1],x[2],x[3]))
        groups[a]|=groups.pop(b)
        planes[a]=plane;planes.pop(b)
        for i in groups[a]:labels[i]=a
        merges.append({"retained_region":a,"removed_region":b,"max_vertical_change_m":change,
                       "max_interface_jump_increase_m_at_merge":new_gap})

    regions=[]
    for k,indices in sorted(groups.items()):
        # Only remove mathematically collinear vertices; no footprint smoothing.
        geometry=unary_union([polygons[i] for i in sorted(indices)]).simplify(1e-8,preserve_topology=True)
        if not geometry.is_valid:
            raise ValueError("Merged roof region is invalid")
        for p in _polygons(geometry):
            regions.append({"id":len(regions),"geometry":p,"plane":planes[k],"source_roof_triangles":sorted(indices)})
    result_domain=unary_union([r["geometry"] for r in regions])
    changed_area=domain.symmetric_difference(result_domain).area
    if changed_area > max(1e-6,domain.area*1e-9):
        raise ValueError("Roof union changed its footprint or courtyard holes")
    ground_ids={i for f,s in zip(model.get('faces',[]),model.get('face_semantics',[])) if s=='ground' for i in f}
    floor_z=float(np.median(vertices[sorted(ground_ids),2])) if ground_ids else 0.0
    if any(float(np.min(_z(r['plane'],np.asarray(r['geometry'].exterior.coords)))) < floor_z-1e-6 for r in regions):
        raise ValueError("Merged roof intersects ground")
    v,f,s,edges,steps,max_jump,face_regions=_mesh_regions(regions,result_domain,floor_z)
    max_change=max(_fit(indices,triangles,areas)[1] for indices in groups.values())
    if max_change>max_vertical_change_m+1e-7:
        raise ValueError("Final vertical-change bound failed")
    max_new_jump=0.0
    for i,j,xy,gap in adjacency:
        if labels[i]!=labels[j]:
            excess=np.abs(_z(planes[labels[i]],xy)-_z(planes[labels[j]],xy))-gap
            max_new_jump=max(max_new_jump,float(np.max(excess)))
    if max_new_jump>max_interface_jump_increase_m+1e-7:
        raise ValueError("Final interface-jump bound failed")
    result={k:copy.deepcopy(model[k]) for k in ['id','coordinates','origin_epsg5514','ground_z'] if k in model}
    result.update({
        "schema":"roof-adjacent-planes/1","status":"ok","method":"adjacent_plane_merge",
        "shape":"piecewise_planar","lods":["experimental_2.5d"],
        "vertices":v,"faces":f,"face_semantics":s,"structural_edges":edges,
        "face_region_ids":face_regions,
        "roof_regions":[{"id":r['id'],"polygon":mapping(r['geometry']),"plane":r['plane'].tolist(),
                         "source_roof_triangles":r['source_roof_triangles']} for r in regions],
        "configuration":{"max_vertical_change_m":max_vertical_change_m,"max_normal_angle_deg":max_normal_angle_deg,
                         "max_interface_jump_increase_m":max_interface_jump_increase_m},
        "metrics":{"source_roof_region_count":initial_count,"actual_roof_region_count":len(regions),
                   "roof_triangle_count":s.count('roof'),"source_roof_triangle_count":len(triangles),
                   "render_triangle_count":len(f),"used_vertex_count":len(v),
                   "accepted_merge_count":len(merges),"considered_merge_count":considered,
                   "max_vertical_change_from_baseline_m":max_change,
                   "max_interface_jump_increase_m":max_new_jump,"max_interface_jump_m":max_jump,
                   "step_wall_segment_count":steps,"structural_edge_segment_count":len(edges),
                   "roof_domain_symmetric_difference_m2":changed_area,
                   "roof_footprint_coverage_fraction":float(result_domain.intersection(polygon).area/polygon.area),
                   "roof_area_outside_footprint_m2":float(result_domain.difference(polygon).area)},
        "timing":{"simplification_seconds":time.perf_counter()-started,"includes_point_loading":False},
        "merge_history":merges,
        "warnings":["Tolerance is vertical change from the input mesh, not accuracy against lidar or survey.",
                    "Refitting may introduce small step walls; their height increase is bounded and reported.",
                    "This is a 2.5D boundary mesh; manifoldness is not independently certified."],
        "fitting_inputs":"Existing roof triangles only; train_relative intentionally unused; no holdout access",
    })
    return result


def run_selected():
    """Measured, three-repeat postprocess of the frozen seven-footprint set."""
    import hashlib
    import json
    from pathlib import Path
    import statistics
    from datetime import datetime, timezone
    import roof_simplification_common as common
    import resource_guard as guard

    destination=common.DEST/'planes-results.json'
    if destination.exists():
        raise FileExistsError('Preserve the previous measurement: '+str(destination))
    guard.check_budget(reserve_bytes=10_000_000,force=True)
    provenance=common.snapshot([Path(__file__),common.ROOT/'scripts/roof_simplification_common.py',
                                common.ROOT/'scripts/roof_pilot_roofer.py'], 'planes')
    before=guard.sha256(Path(__file__))
    started=time.perf_counter()
    cases=common.load_cases()
    baseline={r['id']:r for r in common.baseline_rows() if r['variant']=='roofer_lod22_reference'}
    if set(baseline)!=set(cases):
        raise ValueError('The same seven .888 source models are required')
    variants=[('merge_8deg_025m',.25,8.0),('merge_15deg_050m',.5,15.0)]
    runs=[]
    for identifier,case in cases.items():
        source=baseline[identifier]['model']
        source_bytes=json.dumps(source,sort_keys=True,separators=(',',':')).encode('utf-8')
        for variant,tolerance,angle in variants:
            output=None;times=[];hashes=[];error=None
            for repeat in range(3):
                try:
                    result=simplify_roof(source,case['train_relative'],case['polygon'],
                                         max_vertical_change_m=tolerance,max_normal_angle_deg=angle,
                                         max_interface_jump_increase_m=tolerance)
                except (ValueError,shapely.errors.GEOSException) as exc:
                    error=type(exc).__name__+': '+str(exc)
                    break
                times.append(result['timing']['simplification_seconds'])
                geometry={k:result[k] for k in ['vertices','faces','face_semantics','roof_regions']}
                hashes.append(hashlib.sha256(json.dumps(geometry,sort_keys=True,separators=(',',':')).encode()).hexdigest())
                if output is None:output=result
            row={'id':identifier,'name':case['name'],'source':'dmpok','variant':variant,
                 'model':output,'status':'unsupported' if error else 'ok','error':error,
                 'configuration':{'max_vertical_change_m':tolerance,'max_normal_angle_deg':angle,
                                  'max_interface_jump_increase_m':tolerance},
                 'metrics':dict(output['metrics']) if output else {},
                 'timing':{'repeats_seconds':times,'median_seconds':statistics.median(times) if times else None,
                           'scope':'In-process geometric merge and remeshing; excludes input loading and holdout evaluation'},
                 'repeat_geometry_hashes':hashes,'repeat_geometry_identical':len(set(hashes))==1 if hashes else None,
                 'parent_variant':'roofer_lod22_reference','parent_model_sha256':hashlib.sha256(source_bytes).hexdigest(),
                 'parent_extrusion_mode':source.get('attributes',{}).get('rf_extrusion_mode'),
                 'parent_warnings':source.get('warnings',[]),'source_code':provenance}
            runs.append(row)
            print(case['name'],variant,'regions',row['metrics'].get('source_roof_region_count'),
                  '->',row['metrics'].get('actual_roof_region_count'),'error',error,flush=True)
    if before!=guard.sha256(Path(__file__)):
        raise RuntimeError('Source changed while the measured worker was running')
    report={'schema':'roof-simplification-planes/1','status':'complete','created_at':datetime.now(timezone.utc).isoformat(),
            'manifest_sha256':guard.sha256(common.MANIFEST),'source_code':provenance,'runs':runs,
            'elapsed_seconds':time.perf_counter()-started,'holdout_used_for_fitting':False,
            'notes':['Postprocess fitted to existing Roofer roof triangles, not to raw points.',
                     '0.25/0.5 m limits are maximum change from the .888 mesh, not a promise of lidar/survey accuracy.',
                     'The .888 reconstruction is a prerequisite and its previous runtime is not included.',
                     'A native fallback input remains a fallback-derived model even when postprocessing succeeds.',
                     'Native CityJSON surface counts and connected near-coplanar regions have different definitions.']}
    common.write(destination,report)
    print('Saved',destination,flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run-selected'])
    parser.parse_args()
    run_selected()
