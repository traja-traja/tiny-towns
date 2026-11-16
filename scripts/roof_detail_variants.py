"""Bounded follow-up variants for at most 20 selected Ceske Budejovice buildings.

This is separate from the Velesin pilot.  Importing/listing profiles never runs
Roofer.  Real runs require baseline_preview_complete=True and one frozen train
cloud shared with the reference.  No downloads and no whole-city execution.

LoD1.3 deliberately represents height volumes; LoD2.2 includes roof slopes.
Lower complexity-factor trades data fit for a simpler roof partition.  Native
CityJSON surfaces/solids and display triangles are reported separately.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from scipy.optimize import least_squares

try:
    from . import resource_guard
    from .roof_pilot_roofer import (
        ROOT, ROOFER_EXE, _safe, _features, _surface_records,
        parse_cityjsonseq, predict_roofer_z,
    )
    from .roof_pilot_methods import fit_roof_models, predict_roof_z
except ImportError:
    import resource_guard
    from roof_pilot_roofer import (
        ROOT, ROOFER_EXE, _safe, _features, _surface_records,
        parse_cityjsonseq, predict_roofer_z,
    )
    from roof_pilot_methods import fit_roof_models, predict_roof_z


VARIANTS = {
    "roofer_lod22_reference": {
        "lod": "2.2", "complexity_factor": 0.888,
        "role": "reference_reuse_if_same_train_hash", "priority": "primary",
    },
    "roofer_lod22_regular": {
        "lod": "2.2", "complexity_factor": 0.60,
        "role": "stronger_simplicity_preference", "priority": "primary",
    },
    "roofer_lod13_volumes": {
        "lod": "1.3", "complexity_factor": 0.888, "lod13_step_height_m": 3.0,
        "role": "simple_height_volumes", "priority": "primary",
    },
    "roofer_lod22_minimal": {
        "lod": "2.2", "complexity_factor": 0.35,
        "role": "aggressive_simplification_sensitivity", "priority": "optional_max_5_buildings",
    },
    "roofer_lod13_coarse": {
        "lod": "1.3", "complexity_factor": 0.888, "lod13_step_height_m": 5.0,
        "role": "height_merge_sensitivity", "priority": "optional_max_5_buildings",
    },
    "roofer_tower_allow_insufficient": {
        "lod": "2.2", "complexity_factor": 0.888, "clear_insufficient": False,
        "role": "diagnostic_extrapolation_over_insufficient_coverage",
        "priority": "diagnostic_single_tower",
    },
}


def variant_command(variant_id, train_path, footprints_path, output_path):
    """Argument array, using options verified against installed Roofer --help-all."""
    cfg = VARIANTS[variant_id]
    command = [str(ROOFER_EXE), "-j", "1", "--srs", "EPSG:5514",
               "--id-attribute", "id", "--h-terrain-attribute", "ground_z",
               "--h-terrain-strategy", "user", "--bld-class", "6", "--grnd-class", "2",
               "--no-lod12", "--no-clip-terrain", "--ceil-point-density", "20",
               "--complexity-factor", str(cfg["complexity_factor"]),
               "--lod11-fallback-time", "10000", "--lod11-fallback-planes", "120"]
    if cfg["lod"] == "1.3":
        command += ["--lod13", "--no-lod22", "--lod13-step-height", str(cfg["lod13_step_height_m"])]
    else:
        command += ["--lod22", "--no-lod13"]
    if cfg.get("clear_insufficient") is False:
        command += ["--no-clear-insufficient"]
    return command + [str(train_path), str(footprints_path), str(output_path)]


def _local_roof_area(model):
    vertices = np.asarray(model.get("vertices", []))
    polygons = []
    for face, semantic in zip(model.get("faces", []), model.get("face_semantics", [])):
        if semantic != "roof":
            continue
        polygon = Polygon(vertices[face, :2])
        if polygon.is_valid and polygon.area > 1e-9:
            polygons.append(polygon)
    return unary_union(polygons) if polygons else Polygon()


def _height_regions(model, tolerance_m=0.01):
    """Connected horizontal top regions; not a count of watertight solids."""
    if model.get("lods") != ["1.3"]:
        return None
    vertices = np.asarray(model.get("vertices", []))
    levels = []
    for face, semantic in zip(model.get("faces", []), model.get("face_semantics", [])):
        if semantic != "roof":
            continue
        xyz = vertices[face]
        if np.ptp(xyz[:, 2]) > tolerance_m:
            continue
        polygon = Polygon(xyz[:, :2])
        if polygon.is_empty or not polygon.is_valid or polygon.area < 1e-9:
            continue
        height = float(np.mean(xyz[:, 2]))
        for level in levels:
            if abs(level[0] - height) <= tolerance_m:
                level[1].append(polygon)
                break
        else:
            levels.append([height, [polygon]])
    count = 0
    for _, polygons in levels:
        union = unary_union(polygons)
        count += 1 if union.geom_type == "Polygon" else len(union.geoms)
    return count


def _native_stats(paths, requested_lod):
    stats = {}
    for path in paths:
        with Path(path).open(encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("type") != "CityJSONFeature":
                    continue
                identifier = str(item["id"])
                objects = item.get("CityObjects", {})
                geometries = [g for o in objects.values() for g in o.get("geometry", [])]
                geometries = [g for g in geometries if str(g.get("lod")) == requested_lod]
                surfaces = Counter()
                solids = 0
                for geometry in geometries:
                    surfaces.update(semantic or "unknown" for _, semantic in _surface_records(geometry))
                    if geometry.get("type") == "Solid":
                        solids += 1
                    elif geometry.get("type") in ("MultiSolid", "CompositeSolid"):
                        solids += len(geometry.get("boundaries", []))
                stats[identifier] = {
                    "native_vertex_count": len(item.get("vertices", [])),
                    "native_surface_count": sum(surfaces.values()),
                    "native_roof_surface_count": surfaces.get("RoofSurface", 0),
                    "native_semantic_surface_counts": dict(surfaces),
                    "cityjson_solid_count": solids,
                    "building_part_count": sum(o.get("type") == "BuildingPart" for o in objects.values()),
                    "volume_count_note": "CityJSON solids and connected horizontal roof regions are different quantities",
                }
    return stats


def _adapt_requested_lod(model, cfg, variant_id):
    # The shared parser prefers LoD2.2.  A deliberate LoD1.3 run is not a failed
    # LoD2.2 reconstruction; preserve genuinely different fallback warnings.
    if cfg["lod"] == "1.3" and model.get("lods") == ["1.3"]:
        model["warnings"] = [w for w in model.get("warnings", [])
                             if w != "lod22_unavailable_using_explicit_lower_lod"]
        model["requested_lod_match"] = True
    else:
        model["requested_lod_match"] = cfg["lod"] in model.get("lods", [])
    model["method"] = variant_id
    model["requested_lod"] = cfg["lod"]
    model["configuration"] = dict(cfg)
    model["metrics"]["roof_height_region_count"] = _height_regions(model)
    model["metrics"]["render_triangle_count"] = len(model.get("faces", []))
    model["metrics"]["used_vertex_count"] = len(set(i for face in model.get("faces", []) for i in face))
    model["metrics"]["roofer_reported_rmse_requested_lod_m"] = model.get("attributes", {}).get(
        "rf_rmse_lod" + cfg["lod"].replace(".", ""))
    return model


def evaluate_holdout(model, holdout_local_xyz):
    """External holdout: local XY and Z ABOVE the shared input ground elevation."""
    xyz = np.asarray(holdout_local_xyz, dtype=float)
    if xyz.size == 0:
        xyz = np.empty((0, 3))
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("Holdout must contain local XY and relative Z in three columns")
    if not np.isfinite(xyz).all():
        raise ValueError("Holdout contains non-finite coordinates")
    prediction = predict_roofer_z(model, xyz[:, :2])
    supported = np.isfinite(prediction)
    errors = prediction[supported] - xyz[supported, 2]
    return {
        "evaluation_set": "external_common_holdout",
        "holdout_points": len(xyz), "predicted_points": int(supported.sum()),
        "coverage_fraction": float(supported.mean()) if len(xyz) else None,
        "holdout_rmse_m": float(np.sqrt(np.mean(errors ** 2))) if len(errors) else None,
        "holdout_mae_m": float(np.mean(np.abs(errors))) if len(errors) else None,
        "holdout_p95_abs_m": float(np.percentile(np.abs(errors), 95)) if len(errors) else None,
        "holdout_bias_m": float(np.mean(errors)) if len(errors) else None,
        "error_scope": "only predicted holdout points; compare coverage alongside errors",
    }


def run_roofer_variant(source_name, features_epsg5514, train_laz_path, out_dir,
                       variant_id, *, baseline_preview_complete=False,
                       synthetic=False, holdout_by_id=None):
    """Run one selected profile after the basic preview, never a parameter sweep."""
    if not baseline_preview_complete and not synthetic:
        raise RuntimeError("Complete/review the basic Ceske Budejovice preview before real detail runs")
    cfg = dict(VARIANTS[variant_id])
    features = _features(features_epsg5514)
    count_limit = 3 if synthetic else (5 if cfg["priority"].startswith("optional") else 20)
    if cfg["priority"] == "diagnostic_single_tower":
        count_limit = 1
        if set(features) != {"8b11dd1d-1fd4-40f2-bae9-56da48a0a78a"}:
            raise ValueError("Insufficient-coverage diagnostic is restricted to the selected Black Tower")
    if not 1 <= len(features) <= count_limit:
        raise ValueError(f"This profile permits 1..{count_limit} selected footprints")
    pointcloud = Path(train_laz_path).resolve()
    if not pointcloud.is_file() or pointcloud.suffix.lower() not in (".las", ".laz"):
        raise ValueError("Supply one existing, frozen training LAS/LAZ")
    out_dir = Path(out_dir).resolve()
    if not out_dir.is_relative_to(ROOT) or out_dir == ROOT:
        raise ValueError("Output must be a dedicated subdirectory of the budgeted project")
    resource_guard.check_budget(reserve_bytes=20_000_000, force=True)
    started = time.perf_counter()
    version = subprocess.run([str(ROOFER_EXE), "--version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=10, check=True).stdout.strip()
    if not version.startswith("roofer 1.0.0"):
        raise RuntimeError("These profiles were verified for Roofer 1.0.0; found " + version)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = out_dir / (variant_id + "-" + stamp)
    run_dir.mkdir(parents=True)
    output_dir = run_dir / "cityjson"
    collection = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:5514"}},
                  "features": list(features.values())}
    data = json.dumps(_safe(collection), ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    footprint_path = run_dir / "footprints-epsg5514.geojson"
    footprint_path.write_bytes(data)
    train_hash = resource_guard.sha256(pointcloud)
    command = variant_command(variant_id, pointcloud, footprint_path, output_dir)
    cli_metrics = resource_guard.run_guarded(
        command, cwd=ROOT, log_path=run_dir / "roofer.log", min_available_gb=1.0,
        max_ram_gb=2.0, wait_memory_seconds=60, reserve_bytes=20_000_000,
    )
    paths = sorted(set(output_dir.rglob("*.jsonl")) | set(output_dir.rglob("*.cityjsonseq")))
    if not paths:
        raise RuntimeError("No CityJSONSeq output; inspect " + str(run_dir / "roofer.log"))
    models = {}
    for path in paths:
        parsed = parse_cityjsonseq(path, list(features.values()))
        if set(models) & set(parsed):
            raise ValueError("Duplicate output building IDs")
        models.update(parsed)
    native = _native_stats(paths, cfg["lod"])
    buildings = {}
    for identifier, feature in features.items():
        model = models.get(identifier)
        if model is None:
            buildings[identifier] = {"model": None, "error": "missing_output", "elapsed_seconds": None}
            continue
        _adapt_requested_lod(model, cfg, variant_id)
        model["metrics"].update(native.get(identifier, {}))
        props = feature["properties"]
        footprint = affinity.translate(shape(feature["geometry"]), -props["centre_x"], -props["centre_y"])
        roof_area = _local_roof_area(model)
        model["metrics"]["roof_footprint_coverage_fraction"] = float(roof_area.intersection(footprint).area / footprint.area)
        model["metrics"]["roof_area_outside_footprint_m2"] = float(roof_area.difference(footprint).area)
        model["metrics"]["model_json_bytes"] = len(json.dumps(_safe(model), separators=(",", ":")).encode("utf-8"))
        entry = {"model": model if model["status"] == "ok" else None,
                 "elapsed_seconds": model["timing"]["reconstruction_seconds"],
                 "timing_scope": "Roofer reported reconstruction milliseconds / 1000; excludes CLI I/O",
                 "attributes": model.get("attributes", {}), "geometry_metrics": model["metrics"]}
        if model["status"] != "ok":
            entry["error"] = model["status"]
        if holdout_by_id is not None and identifier in holdout_by_id:
            entry["holdout"] = evaluate_holdout(model, holdout_by_id[identifier])
        buildings[identifier] = entry
    result = _safe({
        "schema": "roof-detail-variant/1", "status": "ok", "source": source_name,
        "variant": variant_id, "configuration": cfg, "roofer_version": version,
        "synthetic": bool(synthetic), "baseline_preview_complete": bool(baseline_preview_complete),
        "inputs": {"train_path": str(pointcloud), "train_sha256": train_hash,
                   "footprints_sha256": hashlib.sha256(data).hexdigest(), "feature_count": len(features),
                   "holdout_used_for_fitting": False},
        "buildings": buildings, "models": models, "metrics": cli_metrics,
        "output_bytes": {"native_cityjsonseq": sum(path.stat().st_size for path in paths)},
        "timing": {"adapter_total_seconds": time.perf_counter() - started,
                   "cli_elapsed_includes_startup_crop_io_and_output": True},
        "files": {"run_dir": str(run_dir), "footprints": str(footprint_path),
                  "cityjsonseq": [str(path) for path in paths], "log": str(run_dir / "roofer.log")},
    })
    (run_dir / "variant-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def fit_partwise_templates(footprint_local, train_local_xyz_absolute_z, ground_z,
                           parts, *, allow_barrel=False, max_parts=8):
    """Fit existing templates to explicitly supplied nonoverlapping local parts.

    Parts are GeoJSON Features with a Polygon geometry and properties.id/source.
    They must cover the footprint, including its holes, and must be frozen before
    holdout evaluation.  This function does NOT discover/claim architectural
    parts automatically.  The combined mesh is a collection of part solids,
    not their Boolean union; shared internal walls remain in the preview mesh.
    """
    started = time.perf_counter()
    footprint = footprint_local if isinstance(footprint_local, Polygon) else shape(footprint_local)
    if not footprint.is_valid or footprint.area <= 0:
        raise ValueError("Valid local Polygon required")
    if not 1 <= len(parts) <= min(8, max_parts):
        raise ValueError("Use 1..8 explicit building parts")
    polygons = [shape(part["geometry"]) for part in parts]
    if any(p.geom_type != "Polygon" or not p.is_valid or p.area <= 0 for p in polygons):
        raise ValueError("Parts must be valid nonempty Polygons")
    union = unary_union(polygons)
    tolerance = max(0.01, footprint.area * 1e-5)
    if union.symmetric_difference(footprint).area > tolerance:
        raise ValueError("Part union must preserve the footprint and its holes")
    if sum(p.area for p in polygons) - union.area > tolerance:
        raise ValueError("Part interiors must not overlap")
    train = np.asarray(train_local_xyz_absolute_z, dtype=float)
    if train.ndim != 2 or train.shape[1] != 3 or not np.isfinite(train).all():
        raise ValueError("Training points must be finite local XY, absolute Z")
    vertices, faces, semantics, fitted_parts, warnings = [], [], [], [], []
    for index, (part, polygon) in enumerate(zip(parts, polygons)):
        points = train[shapely.intersects_xy(polygon, train[:, 0], train[:, 1])]
        result = fit_roof_models(polygon, points, ground_z, allow_barrel=allow_barrel,
                                 max_fit_points=3500, max_orientations=4)
        fitted = result.get("best")
        record = {"id": str(part.get("properties", {}).get("id", index)),
                  "source": part.get("properties", {}).get("source"),
                  "geometry": mapping(polygon), "template": fitted,
                  "status": result["status"], "training_point_count": len(points)}
        fitted_parts.append(record)
        if not fitted or not fitted.get("vertices"):
            warnings.append("part_not_reconstructed:" + record["id"])
            continue
        offset = len(vertices)
        new_vertices = np.asarray(fitted["vertices"], dtype=float)
        new_vertices[:, 2] -= ground_z
        vertices.extend(new_vertices.tolist())
        faces.extend([[i + offset for i in face] for face in fitted["faces"]])
        semantics.extend(fitted["face_semantics"])
    return _safe({"schema": "roof-detail-parts/1", "method": "explicit_parts_templates",
                  "shape": "composite", "ground_z": float(ground_z), "vertices": vertices,
                  "faces": faces, "face_semantics": semantics, "parts": fitted_parts,
                  "status": "partial" if warnings else "ok", "warnings": warnings,
                  "coordinates": "local XY; mesh Z relative to ground_z; template parameters retain absolute Z",
                  "metrics": {"requested_part_count": len(parts),
                              "reconstructed_part_count": sum(bool(p["template"]) for p in fitted_parts),
                              "render_triangle_count": len(faces), "used_vertex_count": len(vertices)},
                  "mesh_is_boolean_union": False, "holdout_used_for_fitting": False,
                  "timing": {"model_and_mesh_seconds": time.perf_counter() - started}})


def predict_partwise_z(model, local_xy):
    xy = np.asarray(local_xy, dtype=float)
    if xy.size == 0:
        return np.empty(0)
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError("Prediction coordinates must be Nx2 local XY")
    result = np.full(len(xy), np.nan)
    for part in model["parts"]:
        if part["template"] is None:
            continue
        polygon = shape(part["geometry"])
        inside = shapely.intersects_xy(polygon, xy[:, 0], xy[:, 1])
        result[inside] = np.fmax(result[inside], predict_roof_z(part["template"], xy[inside]) - model["ground_z"])
    return result


def predict_hypar_z(model, local_xy):
    """Continuous fitted surface, relative to the shared building ground."""
    xy = np.asarray(local_xy, dtype=float).reshape((-1, 2))
    params = model["params"]
    uv = (xy - np.asarray(params["origin_xy"])) / np.asarray(params["scale_xy"])
    u, v = uv[:, 0], uv[:, 1]
    design = np.column_stack((np.ones(len(xy)), u, v, u * u, u * v, v * v))
    result = design @ np.asarray(params["coefficients"])
    inside = shapely.intersects_xy(shape(model["part_geometry"]), xy[:, 0], xy[:, 1])
    return np.where(inside, result, np.nan)


def fit_hypar_part(part_local, train_local_xyz_absolute_z, ground_z, *,
                   part_evidence, max_fit_points=3500, mesh_spacing_m=2.0,
                   max_roof_triangles=600):
    """Robust quadratic saddle over ONE explicitly evidenced roof part.

    Does not discover the swimming hall boundary, invent a low wing, or fit the
    whole complex. A near-flat/convex/concave quadratic is rejected as non-saddle.
    Roof mesh alone is returned; no claim of a complete solid or repaired site.
    """
    started = time.perf_counter()
    polygon = part_local if isinstance(part_local, Polygon) else shape(part_local)
    if polygon.geom_type != "Polygon" or not polygon.is_valid or polygon.area <= 0:
        raise ValueError("One valid, explicitly delimited roof-part Polygon is required")
    if not part_evidence or not part_evidence.get("source"):
        raise ValueError("Record evidence for this part boundary before fitting")
    if max_fit_points < 24 or mesh_spacing_m <= 0 or max_roof_triangles < 20:
        raise ValueError("Invalid bounded-fit or mesh limits")
    xyz = np.asarray(train_local_xyz_absolute_z, dtype=float).reshape((-1, 3))
    if not np.isfinite(xyz).all() or not np.isfinite(ground_z):
        raise ValueError("Training coordinates and ground must be finite")
    xyz = xyz[shapely.intersects_xy(polygon, xyz[:, 0], xyz[:, 1])]
    if len(xyz) < 24 or np.linalg.matrix_rank(xyz[:, :2] - xyz[:, :2].mean(axis=0)) < 2:
        return {"status": "insufficient_data", "model": None}
    if len(xyz) > max_fit_points:
        xyz = xyz[np.random.default_rng(20261115).choice(len(xyz), max_fit_points, replace=False)]
    origin = np.array([polygon.centroid.x, polygon.centroid.y])
    bounds = np.asarray(polygon.bounds)
    scale = np.maximum(bounds[2:] - bounds[:2], 1.0)
    uv = (xyz[:, :2] - origin) / scale
    u, v = uv[:, 0], uv[:, 1]
    design = np.column_stack((np.ones(len(xyz)), u, v, u * u, u * v, v * v))
    if np.linalg.matrix_rank(design) < 6:
        return {"status": "insufficient_quadratic_support", "model": None}
    target = xyz[:, 2] - ground_z
    initial = np.linalg.lstsq(design, target, rcond=None)[0]
    fit = least_squares(lambda beta: design @ beta - target, initial,
                        jac=lambda beta: design.copy(), loss="soft_l1", f_scale=0.25,
                        max_nfev=60)
    beta = fit.x
    hessian = np.array([[2 * beta[3] / scale[0] ** 2, beta[4] / np.prod(scale)],
                        [beta[4] / np.prod(scale), 2 * beta[5] / scale[1] ** 2]])
    eigenvalues = np.linalg.eigvalsh(hessian)
    # At least 2 cm of curvature over the shorter half-span in both directions.
    curvature_floor = 0.04 / (min(scale) / 2) ** 2
    if not fit.success or not eigenvalues[0] < -curvature_floor < 0 < curvature_floor < eigenvalues[1]:
        return _safe({"status": "quadratic_not_supported_as_saddle", "model": None,
                      "curvature_eigenvalues_per_m": eigenvalues,
                      "curvature_floor_per_m": curvature_floor})
    model = {"schema": "roof-detail-hypar/1", "method": "hypar_explicit_part",
             "status": "ok", "shape": "quadratic_saddle", "ground_z": float(ground_z),
             "part_geometry": mapping(polygon), "part_evidence": part_evidence,
             "params": {"origin_xy": origin.tolist(), "scale_xy": scale.tolist(),
                        "coefficients": beta.tolist(), "coefficient_order": ["1", "u", "v", "u2", "uv", "v2"]},
             "evaluation_scope": "explicit_roof_part_only", "complete_building": False,
             "coordinates": "same local XY as whole-building baseline; Z relative to ground_z",
             "holdout_used_for_fitting": False}
    spacing = float(mesh_spacing_m)
    triangles = []
    for attempt in range(20):
        triangles = []
        for x in np.arange(bounds[0], bounds[2], spacing):
            for y in np.arange(bounds[1], bounds[3], spacing):
                clipped = polygon.intersection(shapely.box(x, y, x + spacing, y + spacing))
                pieces = [clipped] if clipped.geom_type == "Polygon" else list(getattr(clipped, "geoms", []))
                for piece in pieces:
                    if piece.geom_type == "Polygon" and piece.area > 1e-9:
                        triangles.extend(shapely.constrained_delaunay_triangles(piece).geoms)
        if len(triangles) <= max_roof_triangles:
            break
        spacing *= 1.3
    if len(triangles) > max_roof_triangles:
        return {"status": "footprint_exceeds_mesh_budget", "model": None}
    vertices, faces, lookup = [], [], {}
    for triangle in triangles:
        ring = list(triangle.exterior.coords)[:3]
        indices = []
        for x, y in ring:
            key = (round(x, 8), round(y, 8))
            if key not in lookup:
                lookup[key] = len(vertices)
                z = predict_hypar_z(model, [[x, y]])[0]
                # Boolean intersections can displace boundary round-off by ulps.
                if not np.isfinite(z):
                    uu, vv = (np.array([x, y]) - origin) / scale
                    z = np.dot([1, uu, vv, uu * uu, uu * vv, vv * vv], beta)
                vertices.append([x, y, float(z)])
            indices.append(lookup[key])
        faces.append(indices)
    error = design @ beta - target
    model.update(vertices=vertices, faces=faces, face_semantics=["roof"] * len(faces),
                 metrics={"parameter_count": 6, "fit_point_count": len(xyz),
                          "train_rmse_m": float(np.sqrt(np.mean(error ** 2))),
                          "train_mae_m": float(np.mean(np.abs(error))),
                          "curvature_eigenvalues_per_m": eigenvalues.tolist(),
                          "render_triangle_count": len(faces), "used_vertex_count": len(vertices),
                          "mesh_spacing_m": spacing, "part_area_m2": polygon.area},
                 timing={"model_and_mesh_seconds": time.perf_counter() - started})
    return _safe({"status": "ok", "model": model})


def run_detail_comparison(source_name, features_epsg5514, train_laz_path, out_dir,
                          result_path, holdout_by_id, *, names_by_id=None,
                          baseline_preview_complete=False, repeats=3,
                          max_wall_seconds=900):
    """Measured three-profile comparison; serial runs with a bounded repeat plan.

    The wall budget stops NEW repeat batches; a running guarded batch finishes.
    Each profile gets its first run regardless of this repeat budget. Identical holdout arrays are
    used for all profiles and never passed into reconstruction.  This is a
    single-host repeatability check, not independent hardware benchmarking.
    """
    if not baseline_preview_complete:
        raise RuntimeError("Complete the basic preview before real detail runs")
    if not 1 <= repeats <= 3 or not 0 < max_wall_seconds <= 3600:
        raise ValueError("Use 1..3 repetitions and a repeat budget greater than 0 and at most 3600 seconds")
    features = _features(features_epsg5514)
    if not 1 <= len(features) <= 20:
        raise ValueError("Select at most 20 detailed buildings")
    missing = set(features) - set(holdout_by_id)
    if missing:
        raise ValueError("Every building needs the frozen holdout, including an empty array if unavailable")
    result_path = Path(result_path).resolve()
    if not result_path.is_relative_to(ROOT) or result_path == ROOT:
        raise ValueError("Results must stay in the project")
    names_by_id = names_by_id or {}
    variants = ["roofer_lod22_reference", "roofer_lod22_regular", "roofer_lod13_volumes"]
    started, batches, warnings = time.perf_counter(), {key: [] for key in variants}, []
    frozen_input_hashes = None
    stop = False
    for repeat in range(repeats):
        for variant in variants:
            remaining = max_wall_seconds - (time.perf_counter() - started)
            previous = batches[variant][-1]["timing"]["adapter_total_seconds"] if batches[variant] else 0
            if repeat > 0 and (remaining <= 0 or (previous and remaining < previous * 1.25)):
                warnings.append("new_batch_budget_reached")
                stop = True
                break
            batch = run_roofer_variant(source_name, list(features.values()), train_laz_path,
                                       out_dir, variant, baseline_preview_complete=True,
                                       holdout_by_id=holdout_by_id)
            input_hashes = (batch["inputs"]["train_sha256"], batch["inputs"]["footprints_sha256"])
            if frozen_input_hashes is None:
                frozen_input_hashes = input_hashes
            elif input_hashes != frozen_input_hashes:
                raise RuntimeError("Training cloud or footprints changed during the comparison")
            batch["repeat_index"] = repeat
            batches[variant].append(batch)
        if stop:
            break
    rows = []
    for identifier in features:
        xyz = np.asarray(holdout_by_id[identifier], dtype=float).reshape((-1, 3))
        predictions = {}
        for variant in variants:
            if batches[variant]:
                model = batches[variant][0]["buildings"][identifier].get("model")
                if model:
                    predictions[variant] = predict_roofer_z(model, xyz[:, :2])
        common = np.ones(len(xyz), dtype=bool)
        for variant in variants:
            common &= np.isfinite(predictions[variant]) if variant in predictions else False
        for variant in variants:
            if not batches[variant]:
                rows.append({"id": identifier, "name": names_by_id.get(identifier, identifier),
                             "source": source_name, "variant": variant, "model": None,
                             "error": "not_run_within_new_batch_time_budget", "metrics": {},
                             "configuration": VARIANTS[variant],
                             "timing": {"completed_repeats": 0, "median_internal_seconds": None,
                                        "repetitions_internal_seconds": []},
                             "repeats": [], "human_review": {"status": "unavailable"}})
                continue
            first = batches[variant][0]
            entry = first["buildings"][identifier]
            model = entry.get("model")
            observations = []
            for batch in batches[variant]:
                item = batch["buildings"][identifier]
                item_model = item.get("model")
                mesh = {key: item_model.get(key) for key in ("vertices", "faces", "face_semantics")} if item_model else None
                observations.append({
                    "repeat_index": batch["repeat_index"],
                    "reconstruction_seconds": item.get("elapsed_seconds"),
                    "cli_batch_seconds": batch["metrics"]["elapsed_seconds"],
                    "cpu_batch_seconds": batch["metrics"].get("cpu_seconds"),
                    "cpu_batch_user_seconds": batch["metrics"].get("cpu_user_seconds"),
                    "cpu_batch_kernel_seconds": batch["metrics"].get("cpu_kernel_seconds"),
                    "cpu_metric": batch["metrics"].get("cpu_metric"),
                    "process_count": batch["metrics"].get("process_count"),
                    "peak_job_commit_bytes": batch["metrics"]["peak_job_commit_bytes"],
                    "native_batch_output_bytes": batch["output_bytes"]["native_cityjsonseq"],
                    "model_sha256": hashlib.sha256(json.dumps(mesh, sort_keys=True).encode()).hexdigest(),
                    "holdout": item.get("holdout"),
                    "run_dir": batch["files"]["run_dir"],
                })
            times = [r["reconstruction_seconds"] for r in observations if r["reconstruction_seconds"] is not None]
            metrics = dict(entry.get("geometry_metrics", {}))
            metrics.update(entry.get("holdout", {}))
            metrics["common_support_points"] = int(common.sum())
            metrics["common_support_fraction"] = float(common.mean()) if len(common) else None
            if common.any() and variant in predictions:
                error = predictions[variant][common] - xyz[common, 2]
                metrics["common_support_rmse_m"] = float(np.sqrt(np.mean(error ** 2)))
                metrics["common_support_mae_m"] = float(np.mean(np.abs(error)))
            else:
                metrics["common_support_rmse_m"] = metrics["common_support_mae_m"] = None
            rows.append({
                "id": identifier, "name": names_by_id.get(identifier, identifier),
                "source": source_name, "variant": variant, "model": model,
                "configuration": VARIANTS[variant], "error": entry.get("error"),
                "metrics": metrics,
                "timing": {"reconstruction_seconds_median": float(np.median(times)) if times else None,
                           "median_internal_seconds": float(np.median(times)) if times else None,
                           "repetitions_internal_seconds": times,
                           "reconstruction_seconds_min": min(times) if times else None,
                           "reconstruction_seconds_max": max(times) if times else None,
                           "completed_repeats": len(observations),
                           "reported_reconstruction_time_unit": "rf_t_run milliseconds divided by 1000",
                           "cli_batch_timing_scope": "whole selected set including startup, crop, I/O and output",
                           "independent_hardware_trials": False},
                "repeat_geometry_identical": len({r["model_sha256"] for r in observations}) == 1,
                "repeats": observations, "human_review": {"status": "pending"},
            })
    holdout_hash = hashlib.sha256()
    for identifier in sorted(features):
        holdout_hash.update(identifier.encode())
        holdout_hash.update(np.asarray(holdout_by_id[identifier], dtype="<f8").reshape((-1, 3)).tobytes())
    any_batch = next((items[0] for items in batches.values() if items), None)
    result = _safe({
        "schema": "roof-detail-comparison/1", "city": "ceske-budejovice", "source": source_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if all(batches.values()) else "partial",
        "repetition_plan_completed": all(len(x) == repeats for x in batches.values()),
        "requested_repeats": repeats, "new_batch_budget_seconds": max_wall_seconds,
        "first_run_of_every_profile_required": True,
        "actual_elapsed_seconds": time.perf_counter() - started,
        "inputs": any_batch["inputs"] if any_batch else {},
        "holdout_sha256": holdout_hash.hexdigest(), "runs": rows, "warnings": warnings,
        "notes": ["Height errors use held-out points from the same source, not independent surveyed truth.",
                  "Common-support errors use only points covered by all three profiles; coverage remains separately visible.",
                  "Selected difficult buildings do not represent city-wide speed or accuracy.",
                  "Peak committed memory is not physical resident RAM; CLI times are whole-batch times.",
                  "All three first runs are required. The time budget only limits additional repetitions; an already running guarded batch is allowed to finish.",
                  "Recognition, silhouette and source photographs need a separate human review."],
    })
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def run_cb_details(source="dmpok", *, baseline_preview_complete=False, max_wall_seconds=900):
    """Use frozen CB benchmark files; never regenerate the split or training LAZ."""
    if not baseline_preview_complete:
        raise RuntimeError("Complete the basic preview and benchmark first")
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import cb_roof_pilot

    shared = cb_roof_pilot.configure()
    sample_path = shared.SAMPLE
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    selected = {f["id"]: f for f in sample["features"] if f["properties"].get("detailed_candidate")}
    if not 1 <= len(selected) <= 20:
        raise ValueError("Expected a frozen selection of at most 20 detailed candidates")
    source_dir = shared.WORK / source
    train_path = source_dir / "train.laz"
    split = json.loads((source_dir / "split.json").read_text(encoding="utf-8"))
    if resource_guard.sha256(train_path) != split["input_cloud_sha256"]:
        raise ValueError("Frozen benchmark training cloud no longer matches split.json")
    references = sorted((source_dir / "roofer").glob("run-*/adapter-result.json"))
    if not references:
        raise ValueError("Finish the real baseline Roofer benchmark before detail comparison")
    reference = json.loads(references[-1].read_text(encoding="utf-8"))
    source_features = _features(json.loads(Path(reference["files"]["footprints"]).read_text(encoding="utf-8")))
    if set(selected) - set(source_features):
        raise ValueError("A detailed candidate lacks the shared ground/centroid baseline input")
    features = [source_features[identifier] for identifier in selected]
    xyz, cls, held = shared.load_source(source)
    holdout, pool_data = {}, None
    for feature, polygon in shared.samples():
        identifier = feature["id"]
        if identifier not in selected:
            continue
        data = shared.building_data(polygon, xyz, cls, held)
        props = source_features[identifier]["properties"]
        if not np.allclose([*data["centre"], data["ground_z"]],
                           [props["centre_x"], props["centre_y"], props["ground_z"]], atol=1e-7, rtol=0):
            raise ValueError("Ground or centroid differs from baseline for " + identifier)
        holdout[identifier] = data["test"].copy()
        holdout[identifier][:, 2] -= props["ground_z"]
        if identifier == "48f63de9-e9ea-4307-81c5-8c1553976441":
            pool_data = data
    del xyz, cls, held
    destination = ROOT / "cities/ceske-budejovice/experiments/roofs/results.json"
    result = run_detail_comparison(source, features, train_path,
                                   ROOT / ".work/cb-roof-details" / source, destination,
                                   holdout, names_by_id={k: f["properties"]["name"] for k, f in selected.items()},
                                   baseline_preview_complete=True, max_wall_seconds=max_wall_seconds)
    result["inputs"]["selection_sha256"] = resource_guard.sha256(sample_path)
    result["inputs"]["split_path"] = str(source_dir / "split.json")
    result["inputs"]["baseline_adapter_path"] = str(references[-1])
    result["hypar_status"] = "awaiting_explicit_roi_train_review"
    # Retain only the small pool crop for a separately reviewed conditional fit;
    # this does not select/fill a main-hall boundary or look at holdout errors.
    if pool_data is not None:
        pool_file = ROOT / ".work/cb-roof-details" / source / "pool-frozen-points.npz"
        np.savez_compressed(pool_file, train=pool_data["train"], test=pool_data["test"],
                            ground_z=pool_data["ground_z"], centre=pool_data["centre"])
        result["inputs"]["pool_crop"] = str(pool_file)
    destination.write_text(json.dumps(_safe(result), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def pool_hypar_roi(results):
    """Conservative exterior lobe, not a claim about the hall/wing joint."""
    expected = "aa3ca9cd50f0f639421545c9f1fee11391757c00ecafe7c5137adbf1b4082d21"
    if results["inputs"].get("selection_sha256") != expected:
        raise ValueError("Re-review footprint vertex indices after any selection change")
    reference = json.loads(Path(results["inputs"]["baseline_adapter_path"]).read_text(encoding="utf-8"))
    features = _features(json.loads(Path(reference["files"]["footprints"]).read_text(encoding="utf-8")))
    feature = features["48f63de9-e9ea-4307-81c5-8c1553976441"]
    props = feature["properties"]
    whole = affinity.translate(shape(feature["geometry"]), -props["centre_x"], -props["centre_y"])
    coordinates = list(whole.exterior.coords)
    if len(coordinates) != 75:
        raise ValueError("Re-review changed pool footprint topology")
    lobe = Polygon(coordinates[29:61])
    if not lobe.is_valid or lobe.difference(whole).area > 1e-6:
        raise ValueError("The proposed lobe is not inside the frozen footprint")
    roi = lobe.buffer(-1.0)
    if roi.geom_type != "Polygon" or roi.area <= 0:
        raise ValueError("The conservative one-metre inset is not one roof region")
    return roi, whole


def run_pool_hypar(*, train_review_note):
    """Optional fit AFTER visual inspection of the training-only pool crop."""
    if not train_review_note or len(train_review_note) < 20:
        raise ValueError("Record the training-only continuity check before fitting the ROI")
    path = ROOT / "cities/ceske-budejovice/experiments/roofs/results.json"
    results = json.loads(path.read_text(encoding="utf-8"))
    roi, whole = pool_hypar_roi(results)
    with np.load(results["inputs"]["pool_crop"]) as saved:
        train, test = saved["train"], saved["test"]
        ground, centre = float(saved["ground_z"]), saved["centre"]
    inside = shapely.intersects_xy(roi, test[:, 0], test[:, 1])
    holdout = test[inside].copy()
    holdout[:, 2] -= ground
    evidence = {
        "source": "frozen sample footprint + NPÚ hall description + Czeva 2017 reference photo",
        "source_url": "https://www.npu.cz/cs/novinky/29872-ceske-budejovice-maji-novou-kulturni-pamatku-plavecky-stadion",
        "photo_url": "https://commons.wikimedia.org/wiki/File:%C4%8CBu,_sports_hall_(02).jpg",
        "footprint_sha256": results["inputs"]["selection_sha256"],
        "exterior_vertices_inclusive": [29, 60], "inward_buffer_m": 1.0,
        "boundary_status": "closing chord is an analytical crop, not a confirmed architectural joint",
        "training_only_review": train_review_note,
        "holdout_used_for_roi_selection": False,
    }
    repetitions, model, status = [], None, None
    for repeat in range(3):
        wall_start, cpu_start = time.perf_counter(), time.process_time()
        fit = fit_hypar_part(roi, train, ground, part_evidence=evidence,
                            mesh_spacing_m=4.0, max_roof_triangles=160)
        repetitions.append({"repeat_index": repeat, "fit_and_mesh_seconds": time.perf_counter() - wall_start,
                            "fit_and_mesh_cpu_seconds": time.process_time() - cpu_start,
                            "status": fit["status"]})
        status = fit["status"]
        if model is None and fit.get("model"):
            model = fit["model"]
        if status != "ok":
            break
    identifier = "48f63de9-e9ea-4307-81c5-8c1553976441"
    base_rows = [r for r in results["runs"] if r["id"] == identifier and r["variant"] in VARIANTS]
    metrics = {"evaluation_scope": "explicit_roof_part_only", "part_area_m2": roi.area,
               "whole_footprint_area_m2": whole.area, "whole_footprint_fraction": roi.area / whole.area,
               "whole_building_holdout_fraction": float(inside.mean()) if len(test) else None,
               "holdout_points_in_part": len(holdout)}
    if model:
        metrics.update(model["metrics"])
        metrics.update(evaluate_holdout(model, holdout))
        analytic = predict_hypar_z(model, holdout[:, :2])
        metrics["continuous_surface_holdout_rmse_m"] = float(np.sqrt(np.mean((analytic - holdout[:, 2]) ** 2))) if len(holdout) else None
        metrics["model_json_bytes"] = len(json.dumps(model, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        for row in base_rows:
            row["pool_explicit_part_holdout"] = evaluate_holdout(row["model"], holdout) if row.get("model") else None
    row = {"id": identifier, "name": base_rows[0]["name"] if base_rows else "Plavecký stadion",
           "source": results["source"], "variant": "hypar_explicit_part", "model": model,
           "evaluation_scope": "explicit_roof_part_only", "complete_building": False,
           "status": status, "error": None if model else status, "metrics": metrics,
           "timing": {"median_internal_seconds": float(np.median([r["fit_and_mesh_seconds"] for r in repetitions])),
                      "repetitions_internal_seconds": [r["fit_and_mesh_seconds"] for r in repetitions],
                      "fit_and_mesh_cpu_seconds": [r["fit_and_mesh_cpu_seconds"] for r in repetitions],
                      "completed_repeats": len(repetitions),
                      "scope": "Python robust fit and roof tessellation only; excludes load and holdout evaluation",
                      "independent_hardware_trials": False},
           "repeats": repetitions, "part_evidence": evidence,
           "note": "Pouze konzervativní výřez vystupující oválné haly; uzavírací spojnice není stavební spára. Bez nízkého křídla, fasád a bez tvrzení o kompletní opravě areálu.",
           "human_review": {"status": "pending_model_photo_comparison"}}
    results["runs"] = [r for r in results["runs"] if r["variant"] != "hypar_explicit_part"] + [row]
    results["hypar_status"] = status
    path.write_text(json.dumps(_safe(results), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    part_path = path.with_name("pool-hypar-part.geojson")
    part_path.write_text(json.dumps({"type": "Feature", "properties": evidence,
                                     "geometry": mapping(roi), "coordinate_convention": "local XY in metres",
                                     "centre_epsg5514": centre.tolist()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return row


def run_tower_diagnostic():
    """One explicitly authorized no-clear-insufficient trial, unchanged inputs.

    Invoke this CLI under resource_guard with a 60-second parent timeout.  It is
    appended separately and never replaces the three unsuccessful tower rows.
    """
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import cb_roof_pilot
    shared = cb_roof_pilot.configure()
    path = ROOT / "cities/ceske-budejovice/experiments/roofs/results.json"
    results = json.loads(path.read_text(encoding="utf-8"))
    identifier = "8b11dd1d-1fd4-40f2-bae9-56da48a0a78a"
    if any(row["variant"] == "roofer_tower_allow_insufficient" for row in results["runs"]):
        raise ValueError("The single tower diagnostic has already been recorded")
    if resource_guard.sha256(results["inputs"]["train_path"]) != results["inputs"]["train_sha256"]:
        raise ValueError("Training LAZ changed")
    reference = json.loads(Path(results["inputs"]["baseline_adapter_path"]).read_text(encoding="utf-8"))
    features = _features(json.loads(Path(reference["files"]["footprints"]).read_text(encoding="utf-8")))
    feature = features[identifier]
    xyz, cls, held = shared.load_source(results["source"])
    original, polygon = next((f, p) for f, p in shared.samples() if f["id"] == identifier)
    data = shared.building_data(polygon, xyz, cls, held)
    holdout = data["test"].copy()
    holdout[:, 2] -= feature["properties"]["ground_z"]
    del xyz, cls, held
    batch = run_roofer_variant(results["source"], [feature], results["inputs"]["train_path"],
                               ROOT / ".work/cb-roof-details/tower-diagnostic",
                               "roofer_tower_allow_insufficient", baseline_preview_complete=True,
                               holdout_by_id={identifier: holdout})
    item = batch["buildings"][identifier]
    model = item.get("model")
    if model:
        model["warnings"].append("diagnostic_extrapolation_over_insufficient_input_coverage")
    metrics = dict(item.get("geometry_metrics", {}))
    metrics.update(item.get("holdout", {}))
    metrics["input_coverage_was_rejected_by_default_roofer"] = True
    row = {"id": identifier, "name": original["properties"]["name"], "source": results["source"],
           "variant": "roofer_tower_allow_insufficient", "model": model, "error": item.get("error"),
           "metrics": metrics, "configuration": VARIANTS["roofer_tower_allow_insufficient"],
           "timing": {"median_internal_seconds": item.get("elapsed_seconds"),
                      "repetitions_internal_seconds": [item.get("elapsed_seconds")],
                      "completed_repeats": 1, "independent_hardware_trials": False},
           "repeats": [{"repeat_index": 0, "reconstruction_seconds": item.get("elapsed_seconds"),
                        "cli_batch_seconds": batch["metrics"]["elapsed_seconds"],
                        "cpu_batch_seconds": batch["metrics"].get("cpu_seconds"),
                        "peak_job_commit_bytes": batch["metrics"]["peak_job_commit_bytes"],
                        "native_batch_output_bytes": batch["output_bytes"]["native_cityjsonseq"],
                        "run_dir": batch["files"]["run_dir"]}],
           "diagnostic_only": True, "production_map_changed": False,
           "note": "Jediný diagnostický pokus --no-clear-insufficient: povolená extrapolace přes vstupní pokrytí, které výchozí Roofer odmítl. Původní tři neúspěchy se zachovávají; není to ověřená oprava věže.",
           "human_review": {"status": "pending_model_photo_comparison"}}
    results["runs"].append(row)
    results["tower_diagnostic_status"] = "model_created" if model else item.get("error", "no_model")
    path.write_text(json.dumps(_safe(results), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    compare = sub.add_parser("compare-cb")
    compare.add_argument("--source", choices=["dmp1g", "dmpok"], default="dmpok")
    compare.add_argument("--baseline-preview-complete", action="store_true")
    compare.add_argument("--max-wall-seconds", type=float, default=900,
                         help="Budget for starting additional repeats; all three first profiles always run (0 < seconds <= 3600)")
    hypar = sub.add_parser("hypar-cb")
    hypar.add_argument("--train-review-note", required=True)
    sub.add_parser("tower-diagnostic")
    run = sub.add_parser("run")
    run.add_argument("--variant", choices=VARIANTS, required=True)
    run.add_argument("--source", required=True)
    run.add_argument("--footprints", required=True)
    run.add_argument("--train", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--baseline-preview-complete", action="store_true")
    args = parser.parse_args()
    if args.action == "list":
        print(json.dumps(VARIANTS, indent=2))
        return
    if args.action == "compare-cb":
        result = run_cb_details(args.source, baseline_preview_complete=args.baseline_preview_complete,
                                max_wall_seconds=args.max_wall_seconds)
        print(json.dumps({"status": result["status"], "rows": len(result["runs"]),
                          "elapsed_seconds": result["actual_elapsed_seconds"],
                          "inputs": result["inputs"]}, indent=2))
        return
    if args.action == "hypar-cb":
        result = run_pool_hypar(train_review_note=args.train_review_note)
        print(json.dumps({"status": result["status"], "metrics": result["metrics"], "timing": result["timing"]}, indent=2))
        return
    if args.action == "tower-diagnostic":
        result = run_tower_diagnostic()
        print(json.dumps({"variant": result["variant"], "error": result["error"],
                          "metrics": result["metrics"], "timing": result["timing"]}, indent=2))
        return
    features = json.loads(Path(args.footprints).read_text(encoding="utf-8"))
    result = run_roofer_variant(args.source, features, args.train, args.out, args.variant,
                               baseline_preview_complete=args.baseline_preview_complete)
    print(json.dumps({"variant": result["variant"], "metrics": result["metrics"],
                      "files": result["files"], "output_bytes": result["output_bytes"]}, indent=2))


if __name__ == "__main__":
    main()
