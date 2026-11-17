"""Construct bounded, watertight 2.5D roofs from explicit planar regions.

All coordinates are local metric coordinates.  A plane [a,b,c] denotes
z=a*x+b*y+c.  This module never infers a roof type or invents missing regions.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math

import numpy as np
import shapely
from shapely.geometry import Polygon, shape, mapping
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

XY_GRID = 1e-7
Z_WELD = 1e-6


def _polygons(geom):
    if geom.is_empty:
        return
    if geom.geom_type == 'Polygon':
        yield geom
    elif geom.geom_type in ('MultiPolygon', 'GeometryCollection'):
        for g in geom.geoms:
            yield from _polygons(g)


def _geometry(value):
    return shape(value) if isinstance(value, dict) else value


def _check_footprint(value):
    p = _geometry(value)
    if p.geom_type != 'Polygon' or p.is_empty or not p.is_valid or p.area <= 1e-8:
        raise ValueError('footprint must be a valid nonempty Polygon, with optional holes')
    if not np.isfinite(shapely.get_coordinates(p)).all():
        raise ValueError('footprint has nonfinite coordinates')
    p = shapely.set_precision(p, XY_GRID)
    if p.is_empty or p.geom_type != 'Polygon':
        raise ValueError('footprint collapses at numerical precision')
    return orient(p, sign=1)


def _plane(value):
    a = np.asarray(value, dtype=float)
    if a.shape != (3,) or not np.isfinite(a).all():
        raise ValueError('plane must contain three finite coefficients [a,b,c]')
    return a


def _xy(point):
    return tuple(float(round(float(q) / XY_GRID) * XY_GRID) for q in point[:2])


def _z(plane, point):
    return float(plane[0] * point[0] + plane[1] * point[1] + plane[2])


def _halfplane(bounds, a, b, c):
    """A bounded polygon containing exactly the part a*x+b*y+c <= 0."""
    xmin, ymin, xmax, ymax = bounds
    pad = max(xmax-xmin, ymax-ymin, 1.0) + 1.0
    ring = [(xmin-pad,ymin-pad), (xmax+pad,ymin-pad),
            (xmax+pad,ymax+pad), (xmin-pad,ymax+pad)]
    clipped = []
    for first, second in zip(ring, ring[1:]+ring[:1]):
        f = a*first[0] + b*first[1] + c
        s = a*second[0] + b*second[1] + c
        if f <= 0:
            clipped.append(first)
        if (f < 0 < s) or (s < 0 < f):
            t = f / (f-s)
            clipped.append((first[0]+t*(second[0]-first[0]),
                            first[1]+t*(second[1]-first[1])))
    return Polygon(clipped) if len(clipped) >= 3 else Polygon()


def plane_regions(poly, planes, mode='min'):
    """Clip a lower/upper envelope of planes to a footprint, preserving holes.

    Coincident planes are assigned to the first plane, avoiding duplicate
    surfaces.  Returned regions contain GeoJSON polygons, plane and plane_index.
    """
    poly = _check_footprint(poly)
    if mode not in ('min', 'max'):
        raise ValueError('mode must be min or max')
    planes = [_plane(p) for p in planes]
    if not planes:
        raise ValueError('at least one plane is required')
    output = []
    sign = 1.0 if mode == 'min' else -1.0
    for i, pi in enumerate(planes):
        region = poly
        for j, pj in enumerate(planes):
            if i == j:
                continue
            a, b, c = sign*(pi-pj)
            if math.hypot(a, b) < 1e-12:
                if c > 1e-10 or (abs(c) <= 1e-10 and j < i):
                    region = Polygon()
                    break
                continue
            region = region.intersection(_halfplane(poly.bounds, a, b, c))
            if region.is_empty:
                break
        if region.is_empty:
            continue
        region = shapely.set_precision(region, XY_GRID)
        for part in sorted(_polygons(region), key=lambda p: (-p.area, p.bounds)):
            if part.area > XY_GRID**2:
                output.append({'polygon': mapping(orient(part, sign=1)),
                               'plane': pi.tolist(), 'plane_index': i})
    return output


def normalize_regions(footprint, regions):
    """Validate a complete nonoverlapping partition; numerical noise is snapped.

    Significant overlap, uncovered area and outside area are errors.  Invalid
    polygons are rejected rather than silently repaired into another topology.
    """
    footprint = _check_footprint(footprint)
    tolerance = max(1e-7, footprint.area*1e-8)
    output = []
    for index, record in enumerate(regions):
        geom = _geometry(record['polygon'])
        if not geom.is_valid:
            raise ValueError(f'region {index} is invalid')
        if not np.isfinite(shapely.get_coordinates(geom)).all():
            raise ValueError(f'region {index} has nonfinite coordinates')
        plane = _plane(record['plane'])
        geom = shapely.set_precision(geom, XY_GRID)
        outside = geom.difference(footprint).area
        if outside > tolerance:
            raise ValueError(f'region {index} lies outside footprint ({outside:.8g} m2)')
        for part in _polygons(geom.intersection(footprint)):
            if part.area > XY_GRID**2:
                output.append({**record, 'polygon': mapping(orient(part, sign=1)),
                               'plane': plane.tolist()})
    if not output:
        raise ValueError('no nonempty roof regions')
    geoms = [shapely.set_precision(shape(r['polygon']), XY_GRID) for r in output]
    union = unary_union(geoms)
    overlap = sum(g.area for g in geoms) - union.area
    missing = footprint.difference(union).area
    if overlap > tolerance:
        raise ValueError(f'roof regions overlap ({overlap:.8g} m2)')
    if missing > tolerance:
        raise ValueError(f'roof regions do not cover footprint ({missing:.8g} m2)')
    return output


def _edges(poly):
    for ring in (poly.exterior, *poly.interiors):
        points = [_xy(p) for p in ring.coords]
        for a, b in zip(points, points[1:]):
            if a != b:
                yield a, b


def _edge_key(a, b):
    return tuple(sorted((a, b)))


def _ring_with_splits(ring, splits):
    coords = [_xy(p) for p in ring.coords]
    result = []
    for a,b in zip(coords, coords[1:]):
        result.append(a)
        candidates = splits.get(_edge_key(a,b), [])
        if candidates:
            dx,dy = b[0]-a[0],b[1]-a[1]
            result.extend(sorted(candidates, key=lambda p: (p[0]-a[0])*dx+(p[1]-a[1])*dy))
    return result


def _triangles(poly):
    # GEOS constrained triangulation retains boundary constraints and holes.
    collection = shapely.constrained_delaunay_triangles(poly)
    for triangle in collection.geoms:
        pts = [_xy(p) for p in list(triangle.exterior.coords)[:3]]
        signed = ((pts[1][0]-pts[0][0])*(pts[2][1]-pts[0][1])
                  -(pts[1][1]-pts[0][1])*(pts[2][0]-pts[0][0]))
        if abs(signed) <= 1e-14:
            continue
        if signed < 0:
            pts[1],pts[2] = pts[2],pts[1]
        yield pts


def _weld_mesh_vertices(vertices, face_groups):
    """Collapse submicrometre round-off vertices shared by roof junctions.

    Grid rounding alone may place the same analytic intersection in adjacent
    cells. Welding happens before topology checks and removes only triangles
    collapsed by that numerical merge, never architectural-scale gaps.
    """
    xy_tolerance = 3*XY_GRID
    z_tolerance = 2*Z_WELD
    buckets = defaultdict(list)
    remap = {}
    welded = []
    for old_index in sorted(range(len(vertices)), key=lambda i:tuple(vertices[i])):
        point = vertices[old_index]
        key = (math.floor(point[0]/xy_tolerance), math.floor(point[1]/xy_tolerance),
               math.floor(point[2]/z_tolerance))
        nearby = []
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1):
                    for index in buckets.get((key[0]+dx,key[1]+dy,key[2]+dz),()):
                        q = welded[index]
                        if (math.hypot(point[0]-q[0],point[1]-q[1]) <= xy_tolerance
                                and abs(point[2]-q[2]) <= z_tolerance):
                            nearby.append(index)
        if nearby:
            remap[old_index] = min(nearby)
        else:
            remap[old_index] = len(welded)
            buckets[key].append(len(welded))
            welded.append(point)
    cleaned = []
    removed = 0
    for faces in face_groups:
        result, seen = [],set()
        for face in faces:
            f = [remap[i] for i in face]
            key = tuple(sorted(f))
            if len(set(f)) < 3 or key in seen:
                removed += 1
                continue
            seen.add(key)
            result.append(f)
        cleaned.append(result)
    return welded, cleaned, {'numerical_vertex_weld_count':len(vertices)-len(welded),
                             'numerical_collapsed_face_count':removed,
                             'vertex_xy_weld_tolerance_m':xy_tolerance}


def build_mesh(footprint, regions, base_z=0.0):
    """Extrude planar roof cells to a base and close exterior, holes and steps.

    Input region boundaries are globally noded before triangulation.  Vertical
    edges are split at every incident roof height so stepped junctions do not
    introduce T-junctions.  The returned diagnostics report topology; callers
    must not publish a mesh with diagnostics.valid == False.
    """
    footprint = _check_footprint(footprint)
    if not math.isfinite(base_z):
        raise ValueError('base_z must be finite')
    records = normalize_regions(footprint, regions)
    geoms = [shapely.set_precision(shape(r['polygon']), XY_GRID) for r in records]
    planes = [_plane(r['plane']) for r in records]
    partition = shapely.union_all([footprint.boundary]+[g.boundary for g in geoms], grid_size=XY_GRID)
    cells = []
    numerical_repair_cells = 0
    numerical_repair_area = 0.0
    numerical_boundary_gap_cells = 0
    numerical_boundary_gap_area = 0.0
    boundary_roundoff_band = footprint.boundary.buffer(3*XY_GRID)
    area_tolerance = max(1e-7, footprint.area*1e-8)
    for cell in polygonize(partition):
        point = cell.representative_point()
        if not footprint.covers(point):
            continue
        owners = [i for i,g in enumerate(geoms) if g.covers(point)]
        if len(owners) != 1:
            # Independently clipped plane envelopes may leave microscopic
            # overlap/gap slivers after grid snapping at triple junctions.
            # Input coverage was already checked; assign only tolerance-sized
            # ambiguity, never a substantial missing architectural region.
            areas = [cell.intersection(g).area for g in geoms]
            # A grid-snapped facade edge may differ from its independently
            # clipped roof boundary by a fraction of a micrometre. A long,
            # empty boundary sliver can span several roof planes: assigning
            # it ONE plane extrapolates that slope across the other slope
            # and creates a tall vertical fin, despite a watertight mesh.
            # Omit only empty, tolerance-sized slivers wholly in the boundary
            # roundoff band. The adjacent roof cells then close their own
            # facade, shifting the mesh perimeter by at most 3*XY_GRID.
            # Owned regions and internal gaps/real height steps are retained.
            if (not owners and cell.area <= area_tolerance
                    and max(areas) <= XY_GRID**2
                    and cell.difference(boundary_roundoff_band).area <= XY_GRID**2):
                numerical_boundary_gap_cells += 1
                numerical_boundary_gap_area += cell.area
                continue
            best = int(np.argmax(areas))
            ambiguous_area = cell.area if len(owners) > 1 else cell.area-max(areas)
            if ambiguous_area > area_tolerance:
                raise ValueError(f'partition cell has {len(owners)} owning regions')
            if max(areas) <= XY_GRID**2:
                best = min(range(len(geoms)), key=lambda i:(geoms[i].distance(point), i))
            owners = [best]
            numerical_repair_cells += 1
            numerical_repair_area += max(0., ambiguous_area)
        cells.append((orient(cell, sign=1), owners[0]))
    if not cells:
        raise ValueError('empty roof partition')

    # If two neighbouring height functions cross along a discontinuity, insert
    # the crossing into BOTH boundaries before either roof is triangulated.
    edge_owners = defaultdict(list)
    for ci,(cell,ri) in enumerate(cells):
        for a,b in _edges(cell):
            edge_owners[_edge_key(a,b)].append((ci,ri,a,b))
    splits = defaultdict(list)
    for key, owners in edge_owners.items():
        if len(owners) > 2:
            raise ValueError('more than two cells share a planar boundary')
        if len(owners) == 2:
            p,q = planes[owners[0][1]],planes[owners[1][1]]
            a,b = key
            da,db = _z(p,a)-_z(q,a),_z(p,b)-_z(q,b)
            if da*db < 0 and min(abs(da),abs(db)) > Z_WELD:
                t = da/(da-db)
                splits[key].append(_xy((a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1]))))
    if splits:
        cells = [(orient(Polygon(_ring_with_splits(c.exterior,splits),
                                  [_ring_with_splits(r,splits) for r in c.interiors]),sign=1),ri)
                 for c,ri in cells]

    levels = defaultdict(list)
    for cell,ri in cells:
        for ring in (cell.exterior,*cell.interiors):
            for raw in ring.coords:
                xy = _xy(raw)
                height = _z(planes[ri],xy)
                if height <= base_z + 1e-5:
                    raise ValueError('roof reaches or lies below the supplied base')
                levels[xy].extend([float(base_z),height])
    for xy, values in levels.items():
        groups = []
        for v in sorted(values):
            if groups and v-groups[-1][-1] <= Z_WELD:
                groups[-1].append(v)
            else:
                groups.append([v])
        levels[xy] = [float(np.mean(group)) for group in groups]

    vertices, roof_faces, wall_faces, ground_faces = [],[],[],[]
    vertex_index = {}
    def canonical_z(xy,z):
        near = [v for v in levels.get(xy,[]) if abs(v-z) <= 2*Z_WELD]
        return min(near,key=lambda q:abs(q-z)) if near else float(z)

    def vertex(xy,z):
        xy = _xy(xy)
        z = canonical_z(xy,z)
        key = (*xy,round(z,9))
        if key not in vertex_index:
            vertex_index[key] = len(vertices)
            vertices.append([*xy,float(z)])
        return vertex_index[key]

    edge_owners = defaultdict(list)
    for ci,(cell,ri) in enumerate(cells):
        for tri in _triangles(cell):
            roof_faces.append([vertex(p,_z(planes[ri],p)) for p in tri])
            ground_faces.append([vertex(p,base_z) for p in reversed(tri)])
        for a,b in _edges(cell):
            edge_owners[_edge_key(a,b)].append((ci,ri,a,b))

    def wall(a,b,lower,upper):
        # Traverse material with the interior on the left; t,z CCW yields the
        # outward (right-hand) horizontal normal in local XYZ.
        za0,za1 = canonical_z(a,lower[0]),canonical_z(b,lower[1])
        zb0,zb1 = canonical_z(a,upper[0]),canonical_z(b,upper[1])
        if max(zb0-za0,zb1-za1) <= Z_WELD:
            return
        length = math.hypot(b[0]-a[0],b[1]-a[1])
        coords = [(0.,za0),(length,za1)]
        coords += [(length,z) for z in levels[b] if za1+Z_WELD < z < zb1-Z_WELD]
        coords.append((length,zb1))
        coords.append((0.,zb0))
        coords += [(0.,z) for z in reversed(levels[a]) if za0+Z_WELD < z < zb0-Z_WELD]
        clean=[]
        for p in coords:
            if not clean or math.dist(p,clean[-1]) > 1e-9:
                clean.append(p)
        if len(clean)>1 and math.dist(clean[0],clean[-1]) <= 1e-9:
            clean.pop()
        panel = Polygon(clean)
        if panel.area <= 1e-12:
            return
        if not panel.is_valid:
            raise ValueError('invalid vertical wall panel')
        for tri in _triangles(panel):
            ids=[]
            for t,z in tri:
                xy = a if abs(t)<=2*XY_GRID else b if abs(t-length)<=2*XY_GRID else (
                    a[0]+(b[0]-a[0])*t/length,a[1]+(b[1]-a[1])*t/length)
                ids.append(vertex(xy,z))
            if len(set(ids))==3:
                wall_faces.append(ids)

    step_edges=0
    for key, owners in edge_owners.items():
        ci,ri,a,b = owners[0]
        za,zb = _z(planes[ri],a),_z(planes[ri],b)
        if len(owners)==1:
            wall(a,b,(base_z,base_z),(za,zb))
        else:
            cj,rj,_,_ = owners[1]
            qa,qb = _z(planes[rj],a),_z(planes[rj],b)
            if max(abs(za-qa),abs(zb-qb)) <= Z_WELD:
                continue
            step_edges+=1
            if (za+zb) >= (qa+qb):
                wall(a,b,(qa,qb),(za,zb))
            else:
                wall(b,a,(zb,za),(qb,qa))

    vertices, groups, weld_diagnostics = _weld_mesh_vertices(
        vertices, [roof_faces, wall_faces, ground_faces])
    roof_faces, wall_faces, ground_faces = groups
    faces = roof_faces+wall_faces+ground_faces
    edge_counts = Counter()
    directed = Counter()
    for face in faces:
        for a,b in zip(face,face[1:]+face[:1]):
            edge_counts[tuple(sorted((a,b)))] += 1
            directed[(a,b)] += 1
    open_edges = sum(n==1 for n in edge_counts.values())
    nonmanifold = sum(n>2 for n in edge_counts.values())
    orientation_errors = sum(n==2 and directed[(a,b)]!=1 for (a,b),n in edge_counts.items())
    va = np.asarray(vertices,dtype=float)
    fa = np.asarray(faces,dtype=int)
    signed_volume = float(np.einsum('ij,ij->i',va[fa[:,0]],np.cross(va[fa[:,1]],va[fa[:,2]])).sum()/6)
    roof_triangles = va[np.asarray(roof_faces, dtype=int), :2]
    ab = roof_triangles[:,1] - roof_triangles[:,0]
    ac = roof_triangles[:,2] - roof_triangles[:,0]
    roof_area = np.abs(ab[:,0]*ac[:,1]-ab[:,1]*ac[:,0]).sum()/2
    union = unary_union(geoms)
    diagnostics = {
        **weld_diagnostics,
        'valid': open_edges==0 and nonmanifold==0 and orientation_errors==0 and signed_volume>0,
        'watertight':open_edges==0 and nonmanifold==0,
        'open_edge_count':open_edges,'nonmanifold_edge_count':nonmanifold,
        'inconsistent_orientation_edge_count':orientation_errors,
        'coverage_fraction':float(union.intersection(footprint).area/footprint.area),
        'missing_area_m2':float(footprint.difference(union).area),
        'outside_area_m2':float(union.difference(footprint).area),
        'overlap_area_m2':float(max(0,sum(g.area for g in geoms)-union.area)),
        'projected_roof_triangle_area_m2':float(roof_area),
        'footprint_area_m2':float(footprint.area),
        'signed_volume_m3':signed_volume,'partition_cell_count':len(cells),
        'height_step_edge_count':step_edges,
        'numerical_partition_repair_cells':numerical_repair_cells,
        'numerical_partition_repair_area_m2':float(numerical_repair_area),
        'numerical_boundary_gap_cells':numerical_boundary_gap_cells,
        'numerical_boundary_gap_area_m2':float(numerical_boundary_gap_area),
        'numerical_boundary_gap_max_shift_m':3*XY_GRID,
        'xy_precision_m':XY_GRID,'z_weld_tolerance_m':Z_WELD,
    }
    return {'vertices':vertices,'roof_faces':roof_faces,'wall_faces':wall_faces,
            'ground_faces':ground_faces,'diagnostics':diagnostics}
