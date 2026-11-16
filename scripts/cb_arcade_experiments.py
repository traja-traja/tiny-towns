"""Isolated, measured geometry experiment for three documented Krajinska arcades.

No city renderer edits, no downloads, no image synthesis. The street-side
ground-floor strip is removed from the body before supports are added.
All dimensions other than the recorded footprint and bay count are labelled.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

import numpy as np
import shapely
from shapely.geometry import Polygon, box, shape
from shapely.geometry.polygon import orient

import resource_guard as guard

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "cities/ceske-budejovice/experiments/arcades"
REVIEW = OUT / "source-review.json"
RESULTS = OUT / "results.json"
MESHES = OUT / "meshes"
NEUTRAL = [0.72, 0.72, 0.70]


def relative(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def write_json(path, document):
    payload = (json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    guard.check_budget(reserve_bytes=len(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return len(payload)


def polygon_parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        if geometry.area > 1e-8:
            yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from polygon_parts(part)


class Mesh:
    def __init__(self, frame, common_origin):
        self.frame = frame
        self.common_origin = np.asarray(common_origin)
        self.vertices, self.faces, self.groups = [], [], []
        self.vertex_index = {}
        self.skipped_degenerate_faces = 0
        self.reverses_orientation = np.linalg.det(np.column_stack([frame["u"], frame["v"]])) < 0

    def vertex(self, u, v, z):
        xy = self.frame["origin_absolute"] + u * self.frame["u"] + v * self.frame["v"] - self.common_origin
        value = tuple(round(float(q), 9) for q in (xy[0], xy[1], z))
        if value not in self.vertex_index:
            self.vertex_index[value] = len(self.vertices)
            self.vertices.append(list(value))
        return self.vertex_index[value]

    def face(self, a, b, c):
        if self.reverses_orientation:
            b, c = c, b
        va, vb, vc = np.asarray([self.vertices[i] for i in (a, b, c)])
        if len({a, b, c}) < 3 or np.linalg.norm(np.cross(vb - va, vc - va)) < 1e-12:
            self.skipped_degenerate_faces += 1
            return
        self.faces.append([a, b, c])

    def extrude(self, geometry, bottom, top, group):
        """Closed polygon components, including planar sloping bottoms."""
        start = len(self.faces)
        for poly in polygon_parts(geometry):
            poly = orient(poly, sign=1.0)
            triangles = list(shapely.constrained_delaunay_triangles(poly).geoms)
            if not math.isclose(sum(t.area for t in triangles), poly.area, rel_tol=1e-7, abs_tol=1e-7):
                raise ValueError("Cap triangulation does not cover its source polygon")
            for triangle in triangles:
                points = list(orient(triangle, sign=1.0).exterior.coords)[:3]
                hi = [self.vertex(u, v, top) for u, v in points]
                lo = [self.vertex(u, v, bottom(u, v)) for u, v in points]
                self.face(*hi)
                self.face(lo[2], lo[1], lo[0])
            for ring in [poly.exterior, *poly.interiors]:
                coords = list(ring.coords)
                for a, b in zip(coords, coords[1:]):
                    a0, b0 = self.vertex(*a, bottom(*a)), self.vertex(*b, bottom(*b))
                    a1, b1 = self.vertex(*a, top), self.vertex(*b, top)
                    self.face(a0, b0, b1)
                    self.face(a0, b1, a1)
        if len(self.faces) > start:
            self.groups.append({"name": group, "start_face": start,
                                "face_count": len(self.faces) - start, "color_rgb": NEUTRAL})

    def world_point(self, u, v, z):
        xy = self.frame["origin_absolute"] + u * self.frame["u"] + v * self.frame["v"] - self.common_origin
        return [float(xy[0]), float(xy[1]), float(z)]

    def volume(self):
        triangles = np.asarray(self.vertices)[np.asarray(self.faces)]
        return float(np.sum(np.einsum("ij,ij->i", triangles[:, 0],
                                    np.cross(triangles[:, 1], triangles[:, 2]))) / 6)


def prepare_building(candidate):
    footprint = shape(candidate["footprint_epsg5514"])
    a, b = np.asarray(candidate["front_edge_epsg5514"], dtype=float)
    width = float(np.linalg.norm(b - a))
    u = (b - a) / width
    v = np.asarray([u[1], -u[0]])
    centroid = np.asarray(footprint.centroid.coords[0])
    if np.dot(centroid - a, v) < 0:
        v = -v
    basis = np.column_stack([u, v])
    local = shapely.transform(footprint, lambda coords: (coords - a) @ basis)
    if not local.is_valid:
        raise ValueError("Invalid footprint in facade coordinates")
    return {"candidate": candidate, "footprint": local,
            "frame": {"origin_absolute": a, "u": u, "v": v, "width": width},
            "height": candidate["baseline_scene"]["body_height_m"]}


def bay_intervals(width, count, pier):
    span = (width - (count + 1) * pier) / count
    if span <= 0.5:
        raise ValueError("The assumed pier width leaves no usable opening")
    return [(pier + i * (pier + span), pier + i * (pier + span) + span) for i in range(count)]


def arc_profile(a, b, apex, rise_ratio, segments):
    span = b - a
    rise = span * rise_ratio
    radius = span * span / (8 * rise) + rise / 2
    mid = (a + b) / 2
    points = []
    for u in np.linspace(a, b, segments + 1):
        z = apex - radius + math.sqrt(max(0.0, radius * radius - (u - mid) ** 2))
        points.append((float(u), z))
    return points


def generate(building, common_origin, kind, depth, segments, parameters):
    p, frame, height = building["footprint"], building["frame"], building["height"]
    mesh = Mesh(frame, common_origin)
    if kind == "baseline":
        mesh.extrude(p, lambda u, v: 0.0, height, "full_body")
        return mesh
    soffit = parameters["soffit_height_m"]
    apex = parameters["opening_apex_height_m"]
    wall = parameters["front_wall_thickness_m"]
    pier = parameters["pier_width_m"]
    if not (height > soffit > apex > 1.6 and depth > wall + 0.5):
        raise ValueError("Inconsistent experimental dimensions")
    min_u, min_v, max_u, max_v = p.bounds
    strip = p.intersection(box(min_u - 1, min_v - 1, max_u + 1, depth))
    # Intersect both complementary half-planes directly. Subtracting the already
    # intersected strip can leave zero-width boundary spikes on nearly collinear
    # surveyed edges; extruding such a spike would introduce a false thin wall.
    rear = p.intersection(box(min_u - 1, depth, max_u + 1, max_v + 1))
    if not math.isclose(strip.area + rear.area, p.area, abs_tol=1e-7, rel_tol=1e-7):
        raise ValueError("Front-strip and rear-body partition changed footprint area")
    if not rear.is_empty and rear.bounds[1] < depth - 1e-8:
        raise ValueError("Rear body intrudes into the reserved arcade strip")
    front = strip.intersection(box(min_u - 1, min_v - 1, max_u + 1, wall))
    if strip.is_empty or front.is_empty:
        raise ValueError("Chosen street edge does not intersect the building")
    # The full original prism is never retained under the new openings.
    mesh.extrude(rear, lambda u, v: 0.0, height, "rear_body")
    mesh.extrude(strip, lambda u, v: soffit, height, "upper_body")
    count = building["candidate"]["bay_count"]
    bays = bay_intervals(frame["width"], count, pier)
    bounds = [(min_u - 1, bays[0][0])]
    bounds += [(bays[i - 1][1], bays[i][0]) for i in range(1, count)]
    bounds += [(bays[-1][1], max_u + 1)]
    for i, (a, b) in enumerate(bounds):
        support = front.intersection(box(a, min_v - 1, b, wall))
        mesh.extrude(support, lambda u, v: 0.0, soffit, f"pier_{i}")
    for i, (a, b) in enumerate(bays):
        if kind == "pillars_lintel":
            spandrel = front.intersection(box(a, min_v - 1, b, wall))
            mesh.extrude(spandrel, lambda u, v: apex, soffit, f"lintel_{i}")
        elif kind == "arch":
            ratio = parameters["arc_rise_to_width_ratio_by_cons_number"][building["candidate"]["conscription_number"]]
            profile = arc_profile(a, b, apex, ratio, segments)
            for j, ((u0, z0), (u1, z1)) in enumerate(zip(profile, profile[1:])):
                piece = front.intersection(box(u0, min_v - 1, u1, wall))
                slope = (z1 - z0) / (u1 - u0)
                mesh.extrude(piece, lambda u, v, q=z0, k=slope, x0=u0: q + k * (u - x0),
                             soffit, f"arch_{i}_segment_{j}")
        else:
            raise ValueError(kind)
    if mesh.skipped_degenerate_faces:
        raise ValueError(f"Unexpected degenerate faces: {mesh.skipped_degenerate_faces}")
    return mesh


def segment_hits(mesh, start, end, group=None):
    """Moller-Trumbore intersections with the exported triangle mesh itself."""
    faces = mesh.faces if group is None else mesh.faces[group["start_face"]:group["start_face"] + group["face_count"]]
    triangles = np.asarray(mesh.vertices, dtype=float)[np.asarray(faces, dtype=int)]
    origin = np.asarray(start, dtype=float)
    direction = np.asarray(end, dtype=float) - origin
    edge1, edge2 = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    h = np.cross(np.broadcast_to(direction, edge2.shape), edge2)
    determinant = np.einsum("ij,ij->i", edge1, h)
    mask = np.abs(determinant) > 1e-10
    if not np.any(mask):
        return []
    inv = np.zeros_like(determinant)
    inv[mask] = 1.0 / determinant[mask]
    s = origin - triangles[:, 0]
    u = inv * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, edge1)
    v = inv * np.einsum("j,ij->i", direction, q)
    t = inv * np.einsum("ij,ij->i", edge2, q)
    mask &= (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-8) & (t < 1 - 1e-8)
    return sorted(set(round(float(value), 8) for value in t[mask]))


def geometry_tests(mesh, building, kind, depth, parameters):
    frame, candidate = building["frame"], building["candidate"]
    pier, wall = parameters["pier_width_m"], parameters["front_wall_thickness_m"]
    actual_depth = depth if depth is not None else min(parameters["depth_m_scenarios"])
    bays = bay_intervals(frame["width"], candidate["bay_count"], pier)
    cases = []

    def check(label, start, end, expect_hit):
        hits = segment_hits(mesh, start, end)
        cases.append({"name": label, "segment": [start, end], "expected_hit": expect_hit,
                      "hit": bool(hits), "intersection_t": hits,
                      "passed": bool(hits) == expect_hit})

    for i, (a, b) in enumerate(bays):
        u = (a + b) / 2
        check(f"opening_{i}_eye_level", mesh.world_point(u, -0.6, 1.6),
              mesh.world_point(u, actual_depth - 0.2, 1.6), kind == "baseline")
        check(f"above_opening_{i}", mesh.world_point(u, -0.6, parameters["opening_apex_height_m"] + 0.15),
              mesh.world_point(u, wall + 0.2, parameters["opening_apex_height_m"] + 0.15), True)
    for i in range(len(bays) - 1):
        u = (bays[i][1] + bays[i + 1][0]) / 2
        check(f"pier_{i + 1}_eye_level", mesh.world_point(u, -0.6, 1.6),
              mesh.world_point(u, wall + 0.2, 1.6), True)
    corridor_v = (wall + actual_depth) / 2
    check("longitudinal_corridor", mesh.world_point(1.0, corridor_v, 1.6),
          mesh.world_point(frame["width"] - 1.0, corridor_v, 1.6), False)
    # The baseline longitudinal segment is inside a solid prism and may not cross
    # a face. Its empty-space check below distinguishes solid interior from void.
    test_points = [mesh.world_point((a + b) / 2, corridor_v, 1.6) for a, b in bays]
    for i, point in enumerate(test_points):
        # An off-axis ray avoids vertices/edges; odd intersection count means inside.
        far = np.asarray(point) + np.asarray([1000.123, 137.371, 29.517])
        # Classify against each closed component, then union them. Counting the
        # assembled mesh once would incorrectly count shared internal interfaces.
        inside_solid = any(len(segment_hits(mesh, point, far, group)) % 2 == 1 for group in mesh.groups)
        cases.append({"name": f"corridor_point_{i}_solid_occupancy", "point": point,
                      "expected_inside_solid": kind == "baseline", "inside_solid": inside_solid,
                      "passed": inside_solid == (kind == "baseline")})
    return {"all_passed": all(case["passed"] for case in cases), "cases": cases,
            "note": "Geometric mesh tests only; not a claim about present-day pedestrian access."}


def run_experiment():
    guard.check_budget(force=True)
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    parameters = review["experiment_design"]["parameters"]
    buildings = [prepare_building(candidate) for candidate in review["candidates"]]
    union = shapely.union_all([shape(b["candidate"]["footprint_epsg5514"]) for b in buildings])
    common_origin = np.asarray(union.centroid.coords[0])
    models, mesh_lookup, building_records = [], {}, []
    variants = [("baseline", "baseline", None, None)]
    for depth in parameters["depth_m_scenarios"]:
        suffix = f"d{round(depth * 10):02d}"
        variants.append(("pillars_lintel_" + suffix, "pillars_lintel", depth, None))
        for segments in parameters["arch_segments"]:
            variants.append((f"arch{segments}_" + suffix, "arch", depth, segments))
    started = time.perf_counter()
    for building in buildings:
        candidate, frame = building["candidate"], building["frame"]
        cp = candidate["conscription_number"]
        public_frame = {"origin_xy": (frame["origin_absolute"] - common_origin).tolist(),
                        "origin_epsg5514": frame["origin_absolute"].tolist(),
                        "u_xy": frame["u"].tolist(), "inward_v_xy": frame["v"].tolist(),
                        "width_m": frame["width"]}
        building_records.append({"building_id": candidate["building_id"], "name": candidate["name"],
                                 "bay_count": candidate["bay_count"], "facade_frame": public_frame,
                                 "body_height_m": building["height"],
                                 "body_height_basis": candidate["baseline_scene"]["source_note"],
                                 "photo_ids": candidate["photo_ids"]})
        baseline_volume = None
        for variant_id, kind, depth, segments in variants:
            times = []
            for repeat in range(parameters["generation_repetitions"]):
                start = time.perf_counter()
                mesh = generate(building, common_origin, kind, depth, segments, parameters)
                times.append(time.perf_counter() - start)
            volume = mesh.volume()
            if volume <= 0:
                raise ValueError("Mesh has non-positive oriented volume")
            if kind == "baseline":
                baseline_volume = volume
            elif not volume < baseline_volume:
                raise ValueError("Open variant did not actually remove volume")
            tests = geometry_tests(mesh, building, kind, depth, parameters)
            if not tests["all_passed"]:
                raise ValueError(json.dumps({"building": cp, "variant": variant_id,
                                             "failed_tests": [c for c in tests["cases"] if not c["passed"]]}))
            document = {"schema_version": 1, "building_id": candidate["building_id"], "name": candidate["name"],
                        "variant_id": variant_id, "coordinate_system": "local metres; EPSG:5514 horizontal offset; z up relative to floor",
                        "origin_epsg5514": [*common_origin.tolist(), 0.0], "facade_frame": public_frame,
                        "vertices": mesh.vertices, "faces": mesh.faces, "material_groups": mesh.groups,
                        "assembly": "Touching closed polygonal components; no opaque texture and no retained full front-strip prism.",
                        "assumptions": {"depth_m": depth, "dimensions": parameters,
                                        "height_basis": candidate["baseline_scene"]["source_note"]}}
            path = MESHES / f"krajinska_{cp}_{variant_id}.json"
            export_start = time.perf_counter()
            size = write_json(path, document)
            export_seconds = time.perf_counter() - export_start
            record = {"building_id": candidate["building_id"], "name": candidate["name"],
                      "variant_id": variant_id, "kind": kind, "depth_m": depth, "arch_segments": segments,
                      "mesh_path": relative(path), "vertices": len(mesh.vertices), "faces": len(mesh.faces),
                      "bytes": size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "volume_m3": volume, "removed_volume_m3": baseline_volume - volume,
                      "timing": {"generation_seconds_runs": times, "median_seconds": statistics.median(times),
                                 "min_seconds": min(times), "max_seconds": max(times), "export_seconds": export_seconds},
                      "tests": tests, "skipped_degenerate_faces": mesh.skipped_degenerate_faces,
                      "assumptions": {"depth_m": depth, "opening_apex_height_m": parameters["opening_apex_height_m"],
                                      "soffit_height_m": parameters["soffit_height_m"], "pier_width_m": parameters["pier_width_m"],
                                      "front_wall_thickness_m": parameters["front_wall_thickness_m"],
                                      "arc_rise_to_width_ratio": parameters["arc_rise_to_width_ratio_by_cons_number"][cp] if kind == "arch" else None}}
            models.append(record)
            mesh_lookup[(candidate["building_id"], variant_id)] = mesh
            print(json.dumps({"building": cp, "variant": variant_id, "vertices": len(mesh.vertices),
                              "faces": len(mesh.faces), "seconds": statistics.median(times),
                              "tests_passed": tests["all_passed"]}), flush=True)
    row_tests = []
    for variant_id, kind, depth, segments in variants:
        if kind == "baseline":
            continue
        corridor_v = (parameters["front_wall_thickness_m"] + depth) / 2
        for left, right in zip(buildings, buildings[1:]):
            lm = mesh_lookup[(left["candidate"]["building_id"], variant_id)]
            rm = mesh_lookup[(right["candidate"]["building_id"], variant_id)]
            start = lm.world_point(left["frame"]["width"] - 1, corridor_v, 1.6)
            end = rm.world_point(1, corridor_v, 1.6)
            hits = [hit for building in buildings for hit in
                    segment_hits(mesh_lookup[(building["candidate"]["building_id"], variant_id)], start, end)]
            row_tests.append({"variant_id": variant_id, "between_buildings": [left["candidate"]["building_id"], right["candidate"]["building_id"]],
                              "segment": [start, end], "passed": not hits, "hit_count": len(hits)})
    if not all(test["passed"] for test in row_tests):
        raise ValueError("Row corridor continuity test failed: " + json.dumps([t for t in row_tests if not t["passed"]]))
    result = {"schema_version": 1, "experiment": "arcades", "status": "geometry_completed",
              "source_review": relative(REVIEW), "source_review_sha256": hashlib.sha256(REVIEW.read_bytes()).hexdigest(),
              "generator": relative(Path(__file__)), "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "coordinate_system": "local metres; EPSG:5514 horizontal offset; z up relative to floor",
              "origin_epsg5514": [*common_origin.tolist(), 0.0],
              "buildings": building_records, "models": models, "row_connectivity_tests": row_tests,
              "parameters": parameters, "model_count": len(models),
              "generation_repetitions": parameters["generation_repetitions"],
              "all_geometry_tests_passed": all(m["tests"]["all_passed"] for m in models) and all(t["passed"] for t in row_tests),
              "total_json_mesh_bytes": sum(m["bytes"] for m in models),
              "experiment_seconds_excluding_process_start": time.perf_counter() - started,
              "environment": {"python": sys.version.split()[0], "numpy": np.__version__, "shapely": shapely.__version__,
                              "platform": platform.platform()},
              "performance_scope": "Median of three mesh generations. Export separately timed. No renderer FPS, network or whole-city reconstruction is measured.",
              "limitations": review["limitations"] + [
                  "Mesh comprises touching closed components; shared internal interfaces may remain. It is not asserted to be a single boolean-unioned CityGML solid.",
                  "The visible arch is parameterized; the hidden historical vault is represented by a flat soffit.",
                  "Geometric ray and occupancy tests show actual empty space; they do not verify historical or contemporary dimensions."]}
    write_json(RESULTS, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        result = run_experiment()
        print(json.dumps({"results": relative(RESULTS), "models": result["model_count"],
                          "all_passed": result["all_geometry_tests_passed"]}), flush=True)
        return
    log = MESHES / "generation.log"
    metrics = guard.run_guarded([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--run", "--worker"],
                                ROOT, log, min_available_gb=1.0, max_ram_gb=1.0)
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    result["status"] = "completed"
    result["resource_guard"] = metrics
    write_json(RESULTS, result)
    print(json.dumps({"results": relative(RESULTS), "models": result["model_count"],
                      "all_passed": result["all_geometry_tests_passed"],
                      "peak_commit_bytes": metrics["peak_job_commit_bytes"]}, indent=2))


if __name__ == "__main__":
    main()
