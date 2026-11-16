"""Guarded adapter for the actual Roofer 1.0.0 executable.

Input features and LAS/LAZ use EPSG:5514, metres and a shared vertical datum.
Returned models use local XY relative to each feature's centre_x/centre_y,
and Z relative to its ground_z.  Roof-type labels are Roofer's broad labels
(e.g. ``slanted``), not inferred gable/hip classifications.

CityJSON transform and semantic surfaces are honoured.  Holdout prediction
uses only explicitly labelled RoofSurface triangles and leaves gaps as NaN.
CLI elapsed time includes I/O, cropping and output; per-building reconstruction
time, when reported by Roofer, is kept separately with its original attribute.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import time
import uuid

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.ops import triangulate

try:
    from . import resource_guard
except ImportError:  # Running this file directly from PowerShell.
    import resource_guard


ROOT = Path(__file__).resolve().parents[1]
ROOFER_EXE = ROOT / ".work/roof-pilot/tools/roofer/bin/roofer.exe"
_SEMANTIC_NAMES = {"RoofSurface": "roof", "WallSurface": "wall", "GroundSurface": "ground"}


def _safe(value):
    """Convert external attributes to strict JSON values, including nonfinite floats."""
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _features(features):
    values = features["features"] if isinstance(features, dict) else features
    checked = {}
    for feature in values:
        props = feature["properties"]
        identifier = str(props["id"])
        if identifier in checked:
            raise ValueError("Duplicate footprint ID: " + identifier)
        for key in ("ground_z", "centre_x", "centre_y"):
            if not math.isfinite(float(props[key])):
                raise ValueError("Non-finite " + key + " for " + identifier)
        if feature["geometry"]["type"] not in ("Polygon", "MultiPolygon"):
            raise ValueError("Footprints must be Polygon/MultiPolygon geometries")
        checked[identifier] = feature
    return checked


def _surface_records(geometry):
    """Yield polygon rings + their semantic type for valid CityJSON nesting."""
    boundaries = geometry.get("boundaries", [])
    sem = geometry.get("semantics", {})
    values, descriptions = sem.get("values", []), sem.get("surfaces", [])
    kind = geometry.get("type")
    def semantic(path):
        try:
            index = values
            for i in path:
                index = index[i]
            if index is None or isinstance(index, bool) or not isinstance(index, int):
                return None
            if not 0 <= index < len(descriptions):
                return None
            return descriptions[index].get("type")
        except (IndexError, TypeError):
            return None
    if kind in ("MultiSurface", "CompositeSurface"):
        for i, rings in enumerate(boundaries):
            yield rings, semantic([i])
    elif kind == "Solid":
        for i, shell in enumerate(boundaries):
            for j, rings in enumerate(shell):
                yield rings, semantic([i, j])
    elif kind in ("MultiSolid", "CompositeSolid"):
        for i, solid in enumerate(boundaries):
            for j, shell in enumerate(solid):
                for k, rings in enumerate(shell):
                    yield rings, semantic([i, j, k])


def _triangulate_surface(rings, vertices):
    """Triangulate one planar polygon in its best 2D projection, preserving holes."""
    if not rings:
        raise ValueError("Empty face")
    cleaned = []
    for ring in rings:
        if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(vertices) for i in ring):
            raise ValueError("Face references an invalid vertex")
        ring = list(ring)
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring.pop()
        if len(set(ring)) < 3:
            raise ValueError("Face has fewer than three distinct vertices")
        cleaned.append(ring)
    exterior = np.asarray([vertices[i] for i in cleaned[0]])
    normal = np.sum(np.cross(exterior, np.roll(exterior, -1, axis=0)), axis=0)
    if np.linalg.norm(normal) < 1e-10:
        raise ValueError("Degenerate face")
    drop_axis = int(np.argmax(np.abs(normal)))
    axes = [i for i in range(3) if i != drop_axis]
    all_indices = sorted(set(i for ring in cleaned for i in ring))
    projected = [[np.asarray(vertices[i])[axes] for i in ring] for ring in cleaned]
    poly = Polygon(projected[0], projected[1:])
    if not poly.is_valid or poly.area < 1e-10:
        raise ValueError("Invalid projected face")
    if hasattr(shapely, "constrained_delaunay_triangles"):
        triangles = list(shapely.constrained_delaunay_triangles(poly).geoms)
    else:
        triangles = [q for q in triangulate(poly) if poly.covers(q)]
    if abs(sum(q.area for q in triangles) - poly.area) > max(1e-7, poly.area * 1e-7):
        raise ValueError("Incomplete face triangulation")
    lookup = {tuple(round(float(vertices[i][a]), 9) for a in axes): i for i in all_indices}
    result = []
    for triangle in triangles:
        ids = []
        for xy in list(triangle.exterior.coords)[:3]:
            key = tuple(round(float(v), 9) for v in xy)
            if key not in lookup:
                raise ValueError("Triangulation inserted an unsupported vertex")
            ids.append(lookup[key])
        coords = np.asarray([vertices[i] for i in ids])
        tri_normal = np.cross(coords[1] - coords[0], coords[2] - coords[0])
        if np.dot(tri_normal, normal) < 0:
            ids.reverse()
        result.append(ids)
    return result


def _object_group(objects, identifier):
    if identifier not in objects:
        roots = [key for key, obj in objects.items() if obj.get("type") == "Building"]
        if len(roots) == 1:
            identifier = roots[0]
        else:
            return list(objects.values())
    selected, pending = [], [identifier]
    seen = set()
    while pending:
        key = pending.pop(0)
        if key in seen or key not in objects:
            continue
        seen.add(key)
        obj = objects[key]
        selected.append(obj)
        pending.extend(obj.get("children", []))
    # Some writers give only a child's parent link, rather than root.children.
    for key, obj in objects.items():
        if key not in seen and any(p in seen for p in obj.get("parents", [])):
            selected.append(obj)
    return selected


def _parse_feature(feature, header, identifier, input_feature):
    props = input_feature["properties"]
    origin = np.asarray([props["centre_x"], props["centre_y"], props["ground_z"]], dtype=float)
    transform = feature.get("transform", header.get("transform", {}))
    scale = np.asarray(transform.get("scale", [1, 1, 1]), dtype=float)
    translate = np.asarray(transform.get("translate", [0, 0, 0]), dtype=float)
    raw_vertices = np.asarray(feature.get("vertices", []), dtype=float)
    if raw_vertices.size == 0:
        raw_vertices = np.empty((0, 3))
    if raw_vertices.ndim != 2 or raw_vertices.shape[1] != 3:
        raise ValueError("Invalid CityJSON vertices")
    vertices = raw_vertices * scale + translate - origin
    if not np.isfinite(vertices).all():
        raise ValueError("Non-finite transformed vertices")
    vertices = vertices.tolist()
    objects = _object_group(feature.get("CityObjects", {}), identifier)
    attributes = {}
    for obj in objects:
        for key, value in obj.get("attributes", {}).items():
            attributes.setdefault(key, value)
    geometries = [g for obj in objects for g in obj.get("geometry", [])]
    lod22 = [g for g in geometries if str(g.get("lod")) == "2.2"]
    selected = lod22
    warnings = []
    if not selected and geometries:
        # Keep an explicitly identified fallback reviewable, never relabel it LoD2.2.
        fallback = [g for g in geometries if str(g.get("lod")) in ("1", "1.0", "1.1", "1.2", "1.3")]
        if fallback:
            highest = max(float(g["lod"]) for g in fallback)
            selected = [g for g in fallback if float(g["lod"]) == highest]
            warnings.append("lod22_unavailable_using_explicit_lower_lod")
    faces, semantics, semantic_types = [], [], []
    invalid_faces = 0
    for geometry in selected:
        for rings, surface_type in _surface_records(geometry):
            try:
                triangles = _triangulate_surface(rings, vertices)
            except (ValueError, TypeError, IndexError, shapely.errors.GEOSException):
                invalid_faces += 1
                continue
            faces.extend(triangles)
            semantics.extend([_SEMANTIC_NAMES.get(surface_type, "unknown")] * len(triangles))
            semantic_types.extend([surface_type] * len(triangles))
    if invalid_faces:
        warnings.append("invalid_faces_skipped")
    if "roof" not in semantics:
        warnings.append("no_semantic_roof_surface")
    extrusion_mode = attributes.get("rf_extrusion_mode", attributes.get("extrusion_mode"))
    if extrusion_mode and extrusion_mode != "standard":
        warnings.append("roofer_extrusion_mode:" + str(extrusion_mode))
    time_key = next((key for key in ("rf_reconstruction_time", "reconstruction_time", "rf_t_run")
                     if isinstance(attributes.get(key), (float, int)) and not isinstance(attributes[key], bool)), None)
    # --attributes for the installed Roofer 1.0.0 documents milliseconds.
    time_value = float(attributes[time_key]) if time_key is not None else None
    if time_value is not None and not math.isfinite(time_value):
        time_value = None
    shape = attributes.get("rf_roof_type", attributes.get("roof_type"))
    return _safe({
        "schema": "roof-pilot-roofer/1", "id": identifier, "method": "roofer_1.0.0",
        "status": ("ok" if "roof" in semantics else "no_roof_geometry") if faces else "no_geometry", "shape": shape,
        "shape_taxonomy": "roofer_broad_roof_type_not_gable_hip_classifier",
        "vertices": vertices, "faces": faces, "face_semantics": semantics,
        "semantic_types": semantic_types,
        "coordinates": "XY relative to centre_x/centre_y; Z relative to input ground_z; metres",
        "origin_epsg5514": origin.tolist(), "ground_z": float(origin[2]),
        "lods": sorted(set(str(g.get("lod")) for g in selected)),
        "attributes": attributes, "warnings": warnings,
        "metrics": {"roof_triangle_count": semantics.count("roof"),
                    "invalid_faces_skipped": invalid_faces,
                    "roofer_reported_rmse_lod22_m": attributes.get("rf_rmse_lod22"),
                    "roofer_reported_nodata_fraction": attributes.get("rf_nodata_frac"),
                    "roofer_extrusion_mode": extrusion_mode},
        "timing": {"reconstruction_time_attribute": time_key,
                   "reconstruction_time_raw_ms": time_value,
                   "reconstruction_seconds": time_value / 1000 if time_value is not None else None,
                   "includes_cli_io": False},
    })


def parse_cityjsonseq(path, footprints_features_epsg5514):
    """Read a Roofer CityJSONSeq file, including header transforms and children."""
    lookup = _features(footprints_features_epsg5514)
    header, models = {}, {}
    with Path(path).open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("type") == "CityJSON" and not item.get("CityObjects"):
                header = item
                continue
            identifier = str(item.get("id", ""))
            if identifier not in lookup:
                matches = [key for key in item.get("CityObjects", {}) if key in lookup]
                if len(matches) != 1:
                    raise ValueError(f"Cannot associate CityJSON line {line_number} with exactly one footprint")
                identifier = matches[0]
            if identifier in models:
                raise ValueError("Duplicate building output: " + identifier)
            models[identifier] = _parse_feature(item, header, identifier, lookup[identifier])
    return models


def predict_roofer_z(parsed_model, local_xy):
    """Roof height above input ground_z; NaN outside labelled roof geometry.

    Only RoofSurface triangles participate.  Where multiple roofs overlap in
    XY, the upper envelope is returned.  Invalid/vertical triangles are skipped.
    NaNs deliberately signal missing coverage; filter them before JSON output.
    """
    xy = np.asarray(local_xy, dtype=float)
    if xy.size == 0:
        return np.empty(0, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError("local_xy must be an N by 2 array")
    result = np.full(len(xy), np.nan)
    vertices = np.asarray(parsed_model.get("vertices", []), dtype=float)
    if vertices.size == 0:
        return result
    for face, semantic in zip(parsed_model.get("faces", []), parsed_model.get("face_semantics", [])):
        if semantic != "roof" or len(face) != 3:
            continue
        triangle = vertices[face]
        a, b, c = triangle[:, :2]
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if not math.isfinite(denominator) or abs(denominator) < 1e-10:
            continue
        lo, hi = triangle[:, :2].min(axis=0) - 1e-8, triangle[:, :2].max(axis=0) + 1e-8
        indices = np.flatnonzero(np.all((xy >= lo) & (xy <= hi), axis=1))
        if not len(indices):
            continue
        q = xy[indices]
        w0 = ((b[1] - c[1]) * (q[:, 0] - c[0]) + (c[0] - b[0]) * (q[:, 1] - c[1])) / denominator
        w1 = ((c[1] - a[1]) * (q[:, 0] - c[0]) + (a[0] - c[0]) * (q[:, 1] - c[1])) / denominator
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-8) & (w1 >= -1e-8) & (w2 >= -1e-8)
        indices = indices[inside]
        heights = w0[inside] * triangle[0, 2] + w1[inside] * triangle[1, 2] + w2[inside] * triangle[2, 2]
        result[indices] = np.fmax(result[indices], heights)
    return result


def run_roofer(source_name, footprints_features_epsg5514, train_laz_path, out_dir):
    """Run real Roofer once, single worker, 2GB job limit, then parse its output."""
    features = _features(footprints_features_epsg5514)
    if not features:
        raise ValueError("At least one footprint is required")
    pointcloud = Path(train_laz_path).resolve()
    if not pointcloud.is_file() or pointcloud.suffix.lower() not in (".las", ".laz"):
        raise ValueError("An existing LAS/LAZ training point cloud is required")
    if not ROOFER_EXE.is_file():
        raise FileNotFoundError(ROOFER_EXE)
    out_dir = Path(out_dir).resolve()
    if not out_dir.is_relative_to(ROOT):
        raise ValueError("Roofer pilot outputs must stay inside the budgeted project")
    resource_guard.check_budget(reserve_bytes=10_000_000, force=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = out_dir / ("run-" + stamp)
    run_dir.mkdir(parents=True)
    output = run_dir / "output"
    footprint_path = run_dir / "footprints-epsg5514.geojson"
    collection = {"type": "FeatureCollection", "name": "roof_pilot",
                  "crs": {"type": "name", "properties": {"name": "EPSG:5514"}},
                  "features": list(features.values())}
    footprint_path.write_text(json.dumps(_safe(collection), ensure_ascii=False, allow_nan=False), encoding="utf-8")
    command = [str(ROOFER_EXE), "-j", "1", "--srs", "EPSG:5514",
               "--id-attribute", "id", "--h-terrain-attribute", "ground_z",
               "--h-terrain-strategy", "user", "--bld-class", "6", "--grnd-class", "2",
               "--lod22", "--no-lod12", "--no-lod13", "--no-clip-terrain",
               "--lod11-fallback-time", "10000", "--lod11-fallback-planes", "120",
               str(pointcloud), str(footprint_path), str(output)]
    started = time.perf_counter()
    cli_metrics = resource_guard.run_guarded(
        command, cwd=ROOT, log_path=run_dir / "roofer.log",
        min_available_gb=1.0, max_ram_gb=2.0, wait_memory_seconds=60,
        reserve_bytes=10_000_000,
    )
    # Roofer currently writes .city.jsonl; accept alternate sequence suffixes.
    paths = sorted(set(output.rglob("*.jsonl")) | set(output.rglob("*.cityjsonseq")))
    if not paths:
        raise RuntimeError("Roofer produced no CityJSONSeq files; inspect " + str(run_dir / "roofer.log"))
    models = {}
    for path in paths:
        parsed = parse_cityjsonseq(path, list(features.values()))
        overlap = set(models) & set(parsed)
        if overlap:
            raise ValueError("Duplicate Roofer building files: " + ", ".join(sorted(overlap)))
        models.update(parsed)
    for identifier in features:
        if identifier not in models:
            models[identifier] = {"id": identifier, "method": "roofer_1.0.0",
                                  "status": "missing_output", "shape": None,
                                  "vertices": [], "faces": [], "face_semantics": [],
                                  "warnings": ["building_missing_from_roofer_output"]}
    buildings = {}
    for identifier, model in models.items():
        item = {"model": model if model.get("status") == "ok" else None,
                "elapsed_seconds": model.get("timing", {}).get("reconstruction_seconds"),
                "timing_scope": "Roofer per-building reconstruction attribute, milliseconds converted to seconds; excludes CLI I/O",
                "attributes": model.get("attributes", {})}
        if model.get("status") != "ok":
            item["error"] = model.get("status", "no_geometry")
        buildings[identifier] = item
    result = _safe({"status": "ok", "source": source_name, "models": models,
                    "buildings": buildings, "metrics": cli_metrics,
                    "cli_metrics": cli_metrics,
                    "timing": {"adapter_total_seconds": time.perf_counter() - started,
                               "cli_elapsed_includes_io_crop_and_output": True},
                    "configuration": {"executable": str(ROOFER_EXE), "expected_version": "1.0.0",
                                      "workers": 1, "max_job_ram_gb": 2, "min_available_ram_gb": 1,
                                      "complexity_factor": "roofer_default_0.888",
                                      "density_ceiling": "roofer_default_20_points_per_m2",
                                      "ground_strategy": "user", "terrain_clipping": False,
                                      "expensive_stage_fallback_ms": 10000, "fallback_plane_limit": 120},
                    "files": {"run_dir": str(run_dir), "footprints": str(footprint_path),
                              "cityjsonseq": [str(p) for p in paths], "log": str(run_dir / "roofer.log")}})
    (run_dir / "adapter-result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return result


def _smoke(out_dir):
    """Small real-executable diagnostic, intentionally synthetic and bounded."""
    import laspy
    from pyproj import CRS
    resource_guard.check_budget(reserve_bytes=10_000_000, force=True)
    out_dir = Path(out_dir).resolve()
    if not out_dir.is_relative_to(ROOT):
        raise ValueError("Synthetic diagnostic must stay inside project")
    out_dir.mkdir(parents=True, exist_ok=True)
    identifier = "synthetic-gable-" + uuid.uuid4().hex[:8]
    cx, cy, ground = -758000.0, -1186000.0, 500.0
    xx, yy = np.meshgrid(np.arange(-9.85, 10, 0.3), np.arange(-3.85, 4, 0.3))
    roof_xy = np.column_stack((xx.ravel(), yy.ravel()))
    roof_z = ground + 8 + 0.7 * (4 - np.abs(roof_xy[:, 1]))
    roof_z += np.random.default_rng(3).normal(0, 0.015, len(roof_z))
    xx, yy = np.meshgrid(np.arange(-13, 14, 0.6), np.arange(-7, 8, 0.6))
    ground_xy = np.column_stack((xx.ravel(), yy.ravel()))
    ground_xy = ground_xy[(np.abs(ground_xy[:, 0]) > 10) | (np.abs(ground_xy[:, 1]) > 4)]
    xy = np.vstack((roof_xy, ground_xy)) + [cx, cy]
    zz = np.concatenate((roof_z, np.full(len(ground_xy), ground)))
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = [0.001, 0.001, 0.001]
    header.offsets = [cx, cy, ground]
    header.add_crs(CRS.from_epsg(5514))
    las = laspy.LasData(header)
    las.x, las.y, las.z = xy[:, 0], xy[:, 1], zz
    las.classification = np.concatenate((np.full(len(roof_xy), 6), np.full(len(ground_xy), 2))).astype(np.uint8)
    point_path = out_dir / (identifier + ".las")
    las.write(point_path)
    ring = [[cx - 10, cy - 4], [cx + 10, cy - 4], [cx + 10, cy + 4], [cx - 10, cy + 4], [cx - 10, cy - 4]]
    feature = {"type": "Feature", "properties": {"id": identifier, "ground_z": ground, "centre_x": cx, "centre_y": cy},
               "geometry": {"type": "Polygon", "coordinates": [ring]}}
    result = run_roofer("synthetic_smoke", [feature], point_path, out_dir)
    model = result["models"][identifier]
    prediction = predict_roofer_z(model, roof_xy)
    good = np.isfinite(prediction)
    result["synthetic_validation"] = {"roof_points": len(roof_xy), "coverage": float(np.mean(good)),
                                      "rmse_to_analytic_roof_m": float(np.sqrt(np.mean((prediction[good] - (8 + 0.7 * (4 - np.abs(roof_xy[good, 1])))) ** 2))) if good.any() else None,
                                      "model_shape": model.get("shape"), "model_status": model.get("status")}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", required=True)
    parser.add_argument("--out", default=str(ROOT / ".work/roof-pilot/roofer-adapter-smoke"))
    args = parser.parse_args()
    result = _smoke(args.out)
    print(json.dumps({"validation": result["synthetic_validation"], "cli_metrics": result["cli_metrics"],
                      "files": result["files"]}, indent=2, allow_nan=False))
