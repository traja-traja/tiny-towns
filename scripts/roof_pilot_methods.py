"""Small deterministic roof-template experiment; independent of the renderer.

Coordinates are local metric XY and absolute Z in the same vertical datum as
``ground_z``.  This module does not classify a raw point cloud: callers must
provide roof candidates, separately for each building.  Shapely is used only
for polygon operations/triangulation; NumPy/SciPy perform the fits.

Selection score (metres) = winsorised RMSE + penalty_m * complexity_units.
The RMSE caps residual magnitudes at their 90th percentile.  Complexity units
are explicit modelling preferences, not a statistical likelihood.  Reported
quality is diagnostic and is NOT a calibrated probability of correctness.

All models are height fields with vertical walls.  Holes in the supplied
polygon remain holes; overhangs, arcades and multi-level passages are outside
the model's scope.  No data are downloaded and no files are written.
"""

from __future__ import annotations

import math
import time

import numpy as np
from scipy.optimize import least_squares
import shapely
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import split, triangulate


_COMPLEXITY = {"flat": 1.0, "shed": 3.0, "gabled": 5.5, "hipped": 6.0, "barrel": 6.5}
_SCHEMA = "roof-pilot-template/1"


def _polygon(footprint_xy, holes=None) -> Polygon:
    if isinstance(footprint_xy, Polygon):
        if holes is not None:
            raise ValueError("Do not supply holes twice")
        poly = footprint_xy
    elif isinstance(footprint_xy, dict):
        if footprint_xy.get("type") != "Polygon":
            raise ValueError("Only one Polygon per building is supported")
        rings = footprint_xy["coordinates"]
        poly = Polygon(rings[0], rings[1:])
    else:
        poly = Polygon(np.asarray(footprint_xy, dtype=float), holes)
    if poly.is_empty or not poly.is_valid or poly.area < 0.05:
        raise ValueError("Footprint must be a valid nonzero-area polygon")
    coords = np.concatenate([np.asarray(poly.exterior.coords)] +
                            [np.asarray(r.coords) for r in poly.interiors])
    if coords.shape[1] != 2 or not np.isfinite(coords).all():
        raise ValueError("Footprint coordinates must be finite XY pairs")
    return orient(poly, sign=1.0)


def _frame(xy, center, theta):
    d = np.asarray(xy, dtype=float) - center
    c, s = math.cos(theta), math.sin(theta)
    return np.column_stack((d[:, 0] * c + d[:, 1] * s,
                            -d[:, 0] * s + d[:, 1] * c))


def _angle_distance(a, b):
    return abs((a - b + math.pi / 2) % math.pi - math.pi / 2)


def _orientations(poly, max_orientations):
    rect = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)[:-1]
    ed = np.roll(rect, -1, axis=0) - rect
    main = ed[np.argmax(np.linalg.norm(ed, axis=1))]
    primary = math.atan2(main[1], main[0]) % math.pi
    result = [primary, (primary + math.pi / 2) % math.pi]
    xy = np.asarray(poly.exterior.coords)
    edges = np.diff(xy, axis=0)
    for i in np.argsort(-np.linalg.norm(edges, axis=1), kind="stable"):
        theta = math.atan2(edges[i, 1], edges[i, 0]) % math.pi
        if all(_angle_distance(theta, t) > math.radians(8) for t in result):
            result.append(theta)
        if len(result) >= max_orientations:
            break
    return result[:max_orientations]


def _extent(poly, center, theta):
    uv = _frame(np.asarray(poly.exterior.coords), center, theta)
    lo, hi = uv.min(axis=0), uv.max(axis=0)
    return lo, hi


def _prepare(footprint_xy, roof_xyz, ground_z, holes):
    poly = _polygon(footprint_xy, holes)
    ground = float(ground_z)
    if not np.isfinite(ground):
        raise ValueError("ground_z must be finite and use the point-cloud datum")
    points = np.asarray(roof_xyz, dtype=float)
    if points.size == 0:
        points = np.empty((0, 3), dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("roof_xyz must be an N by 3 array")
    finite = points[np.isfinite(points).all(axis=1)]
    # Include roof points exactly on the supplied boundary; no external buffer.
    keep = shapely.intersects_xy(poly, finite[:, 0], finite[:, 1])
    inside = finite[keep]
    center = np.asarray([poly.centroid.x, poly.centroid.y])
    return poly, inside, center, ground, {
        "input_point_count": int(len(points)),
        "finite_point_count": int(len(finite)),
        "inside_point_count": int(len(inside)),
        "footprint_area_m2": float(poly.area),
        "point_density_per_m2": float(len(inside) / poly.area),
        "interior_ring_count": len(poly.interiors),
    }


def _coverage(poly, points):
    minx, miny, maxx, maxy = poly.bounds
    cell = max(math.sqrt(poly.area / 100.0), 0.5,
               max(maxx - minx, maxy - miny) / 48.0)
    nx = max(1, int(math.ceil((maxx - minx) / cell)))
    ny = max(1, int(math.ceil((maxy - miny) / cell)))
    expected = set()
    for i in range(nx):
        for j in range(ny):
            q = box(minx + i * cell, miny + j * cell,
                    minx + (i + 1) * cell, miny + (j + 1) * cell)
            if poly.intersection(q).area > 1e-7:
                expected.add((i, j))
    occupied = set()
    for xy in points[:, :2]:
        i = min(nx - 1, max(0, int((xy[0] - minx) / cell)))
        j = min(ny - 1, max(0, int((xy[1] - miny) / cell)))
        occupied.add((i, j))
    return {
        "coverage_fraction": float(len(occupied & expected) / max(1, len(expected))),
        "coverage_cell_m": float(cell),
        "occupied_cells": len(occupied & expected),
        "footprint_cells": len(expected),
    }


def _predict(shape, params, xy):
    xy = np.asarray(xy, dtype=float)
    center = np.asarray(params["origin_xy"])
    uv = _frame(xy, center, params.get("ridge_angle_rad", 0.0))
    u, v = uv[:, 0], uv[:, 1]
    if shape == "flat":
        return np.full(len(xy), params["height_z"])
    if shape == "shed":
        return params["height_z"] + params["slope_x"] * u + params["slope_y"] * v
    if shape in ("gabled", "butterfly"):
        delta = v - params["ridge_offset_m"]
        fall = params["slope_left"] * np.maximum(-delta, 0) + params["slope_right"] * np.maximum(delta, 0)
        return params["ridge_z"] + (fall if shape == "butterfly" else -fall)
    if shape == "hipped":
        lo, hi = np.asarray(params["uv_min"]), np.asarray(params["uv_max"])
        side = params["slope_side"] * np.minimum(v - lo[1], hi[1] - v)
        end = params["slope_end"] * np.minimum(u - lo[0], hi[0] - u)
        return params["eave_z"] + np.minimum(side, end)
    if shape == "plane_envelope":
        planes = np.asarray(params["planes_uv"])
        return (uv @ planes[:, :2].T + planes[:, 2]).min(axis=1)
    if shape == "barrel":
        if "profile_v" in params:
            return np.interp(v, params["profile_v"], params["profile_z"])
        t = (v - params["center_v"]) / params["half_width_m"]
        return params["eave_z"] + params["rise_m"] * np.sqrt(np.maximum(0, 1 - t * t))
    raise ValueError("Unknown roof shape: " + shape)


def predict_roof_z(model, xy):
    """Evaluate a returned model at metric XY coordinates (including baseline)."""
    return _predict(model["shape"], model["params"], xy)


def _stats(residual, shape, penalty_m, tolerance_m):
    absolute = np.abs(residual)
    cap = float(np.percentile(absolute, 90))
    robust = float(np.sqrt(np.mean(np.minimum(absolute, cap) ** 2)))
    units = _COMPLEXITY[shape]
    return {
        "evaluation_set": "supplied_input_points_not_independent_holdout",
        "rmse_m": float(np.sqrt(np.mean(residual ** 2))),
        "mae_m": float(np.mean(absolute)),
        "median_abs_error_m": float(np.median(absolute)),
        "p90_abs_error_m": cap,
        "winsorised_rmse_m": robust,
        "inlier_fraction": float(np.mean(absolute <= tolerance_m)),
        "inlier_tolerance_m": float(tolerance_m),
        "complexity_units": units,
        "complexity_penalty_m": float(penalty_m * units),
        "selection_score_m": float(robust + penalty_m * units),
    }


def _candidate(shape, params, xyz, ground, penalty, tolerance, started):
    pred = _predict(shape, params, xyz[:, :2])
    return {"schema": _SCHEMA, "method": "parametric_template", "shape": shape,
            "params": params, "ground_z": ground,
            "metrics": _stats(pred - xyz[:, 2], shape, penalty, tolerance),
            "timing": {"fit_seconds": float(time.perf_counter() - started)},
            "warnings": []}


def _fit_templates(poly, sample, center, ground, orientations, penalty, tolerance,
                   allow_barrel):
    xyz, z = sample, sample[:, 2]
    origin = center.tolist()
    candidates = []
    started = time.perf_counter()
    h = float(np.median(z))
    candidates.append(_candidate("flat", {"origin_xy": origin, "height_z": h},
                                 xyz, ground, penalty, tolerance, started))
    started = time.perf_counter()
    d = sample[:, :2] - center
    design = np.column_stack((np.ones(len(d)), d))
    init = np.linalg.lstsq(design, z, rcond=None)[0]
    fit = least_squares(lambda x: design @ x - z, init, loss="soft_l1",
                        f_scale=tolerance / 2, max_nfev=70)
    params = {"origin_xy": origin, "height_z": float(fit.x[0]),
              "slope_x": float(fit.x[1]), "slope_y": float(fit.x[2])}
    candidates.append(_candidate("shed", params, xyz, ground, penalty, tolerance, started))
    height_hi = max(float(np.max(z) + 15), ground + 30)
    for theta in orientations:
        uv = _frame(sample[:, :2], center, theta)
        lo, hi = _extent(poly, center, theta)
        width = max(float(hi[1] - lo[1]), 0.2)
        midv = float((hi[1] + lo[1]) / 2)
        slope0 = min(2.0, max(0.05, float(np.ptp(z)) / (width / 2)))
        started = time.perf_counter()
        # Fit ridge angle as well as two independent slopes and ridge offset.
        def gable_residual(x):
            vv = _frame(sample[:, :2], center, x[4])[:, 1] - x[1]
            return x[0] - x[2] * np.maximum(-vv, 0) - x[3] * np.maximum(vv, 0) - z
        seed = [float(np.percentile(z, 95)), midv, slope0, slope0, theta]
        lower = [ground + 0.1, lo[1] + 0.05 * width, 0.0, 0.0, theta - math.pi / 12]
        upper = [height_hi, hi[1] - 0.05 * width, 3.0, 3.0, theta + math.pi / 12]
        seed = np.clip(seed, np.asarray(lower) + 1e-7, np.asarray(upper) - 1e-7)
        fit = least_squares(gable_residual, seed, bounds=(lower, upper),
                            loss="soft_l1", f_scale=tolerance / 2, max_nfev=90)
        p = fit.x
        params = {"origin_xy": origin, "ridge_z": float(p[0]),
                  "ridge_offset_m": float(p[1]), "slope_left": float(p[2]),
                  "slope_right": float(p[3]), "ridge_angle_rad": float(p[4]),
                  "ridge_azimuth_deg": float((90 - math.degrees(p[4])) % 180),
                  "pitch_left_deg": float(math.degrees(math.atan(p[2]))),
                  "pitch_right_deg": float(math.degrees(math.atan(p[3])))}
        candidates.append(_candidate("gabled", params, xyz, ground, penalty, tolerance, started))
        started = time.perf_counter()
        side_distance = np.minimum(uv[:, 1] - lo[1], hi[1] - uv[:, 1])
        end_distance = np.minimum(uv[:, 0] - lo[0], hi[0] - uv[:, 0])
        def hip_residual(x):
            return x[0] + np.minimum(x[1] * side_distance, x[2] * end_distance) - z
        hipseed = [max(ground + 0.2, float(np.percentile(z, 10))), slope0, slope0]
        fit = least_squares(hip_residual, hipseed,
                            bounds=([ground + 0.1, 0.0, 0.0], [height_hi, 3.0, 3.0]),
                            loss="soft_l1", f_scale=tolerance / 2, max_nfev=70)
        params = {"origin_xy": origin, "ridge_angle_rad": float(theta),
                  "ridge_azimuth_deg": float((90 - math.degrees(theta)) % 180),
                  "uv_min": lo.tolist(), "uv_max": hi.tolist(),
                  "eave_z": float(fit.x[0]), "slope_side": float(fit.x[1]),
                  "slope_end": float(fit.x[2])}
        candidates.append(_candidate("hipped", params, xyz, ground, penalty, tolerance, started))
        if allow_barrel:
            started = time.perf_counter()
            halfwidth = width / 2
            arch = np.sqrt(np.maximum(0, 1 - ((uv[:, 1] - midv) / halfwidth) ** 2))
            fit = least_squares(lambda x: x[0] + x[1] * arch - z,
                                [max(ground + 0.2, float(np.percentile(z, 10))),
                                 min(49.999, max(0.1, float(np.ptp(z))))],
                                bounds=([ground + 0.1, 0], [height_hi, 50]),
                                loss="soft_l1", f_scale=tolerance / 2, max_nfev=60)
            params = {"origin_xy": origin, "ridge_angle_rad": float(theta),
                      "ridge_azimuth_deg": float((90 - math.degrees(theta)) % 180),
                      "center_v": midv, "half_width_m": halfwidth,
                      "eave_z": float(fit.x[0]), "rise_m": float(fit.x[1]),
                      "cross_section": "elliptical", "mesh_strips": 12}
            candidates.append(_candidate("barrel", params, xyz, ground, penalty, tolerance, started))
    return candidates


def _roof_cuts(model):
    """Lines a*u+b*v=c in the model's local frame."""
    p, shape = model["params"], model["shape"]
    if shape in ("gabled", "butterfly"):
        return [(0.0, 1.0, p["ridge_offset_m"])]
    if shape == "plane_envelope":
        planes = p["planes_uv"]
    elif shape == "hipped":
        lo, hi = p["uv_min"], p["uv_max"]
        sv, su = p["slope_side"], p["slope_end"]
        planes = [(0, sv, -sv * lo[1]), (0, -sv, sv * hi[1]),
                  (su, 0, -su * lo[0]), (-su, 0, su * hi[0])]
    if shape in ("hipped", "plane_envelope"):
        cuts = []
        for i, (a, b, c) in enumerate(planes):
            for aa, bb, cc in planes[i + 1:]:
                if math.hypot(a - aa, b - bb) > 1e-9:
                    cuts.append((a - aa, b - bb, cc - c))
        return cuts
    if shape == "barrel":
        if "profile_v" in p:
            return [(0.0, 1.0, v) for v in p["profile_v"][1:-1]]
        return [(0.0, 1.0, float(v)) for v in np.linspace(
            p["center_v"] - p["half_width_m"],
            p["center_v"] + p["half_width_m"], p["mesh_strips"] + 1)[1:-1]]
    return []


def _triangles(poly):
    if hasattr(shapely, "constrained_delaunay_triangles"):
        return list(shapely.constrained_delaunay_triangles(poly).geoms)
    # Older Shapely: keep only completely covered triangles (never fill holes).
    triangles = [t for t in triangulate(poly) if poly.covers(t)]
    if abs(sum(t.area for t in triangles) - poly.area) > max(1e-7, poly.area * 1e-8):
        raise ValueError("Constrained polygon triangulation is unavailable")
    return triangles


def _mesh(poly, model):
    p = model["params"]
    center = np.asarray(p["origin_xy"])
    theta = p.get("ridge_angle_rad", 0.0)
    rot = np.array([[math.cos(theta), -math.sin(theta)],
                    [math.sin(theta), math.cos(theta)]])
    extent = max(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1]) * 6 + 10
    pieces = [poly]
    for a, b, c in _roof_cuts(model):
        norm = math.hypot(a, b)
        origin = np.asarray([a, b]) * (c / norm ** 2)
        along = np.asarray([-b, a]) / norm
        ends = np.asarray([origin - extent * along, origin + extent * along]) @ rot.T + center
        line = LineString(ends)
        nxt = []
        for part in pieces:
            nxt.extend(q for q in split(part, line).geoms
                       if isinstance(q, Polygon) and q.area > 1e-9)
        pieces = nxt
    vertices, faces, semantics, lookup = [], [], [], {}
    ground = model["ground_z"]
    def vertex(x, y, z):
        key = (round(float(x), 8), round(float(y), 8), round(float(z), 8))
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append(list(key))
        return lookup[key]
    def face(indices, kind):
        if len(set(indices)) == 3:
            faces.append(indices)
            semantics.append(kind)
    for part in pieces:
        part = orient(part, sign=1.0)
        for tri in _triangles(part):
            xy = np.asarray(orient(tri, sign=1.0).exterior.coords)[:3]
            zz = _predict(model["shape"], p, xy)
            top = [vertex(x, y, z) for (x, y), z in zip(xy, zz)]
            face(top, "roof")
            if ground is not None:
                base = [vertex(x, y, ground) for x, y in xy]
                face(base[::-1], "ground")
        if ground is None:
            continue
        for ring in [part.exterior, *part.interiors]:
            xy = np.asarray(ring.coords)
            for axy, bxy in zip(xy[:-1], xy[1:]):
                edge = LineString([axy, bxy])
                # Only the supplied footprint perimeter (including courtyards).
                if edge.difference(poly.boundary.buffer(1e-7)).length > 1e-7:
                    continue
                za, zb = _predict(model["shape"], p, np.array([axy, bxy]))
                a0, b0 = vertex(*axy, ground), vertex(*bxy, ground)
                a1, b1 = vertex(*axy, za), vertex(*bxy, zb)
                face([a0, b0, b1], "wall")
                face([a0, b1, a1], "wall")
    return {"vertices": vertices, "faces": faces, "face_semantics": semantics,
            "mesh_note": ("Piecewise-linear approximation of fitted barrel"
                          if model["shape"] == "barrel" else "planar roof faces and vertical walls")}


def fit_roof_models(footprint_xy, roof_xyz, ground_z, *, holes=None,
                    allow_barrel=False, max_fit_points=3500, max_orientations=4,
                    penalty_m=0.04, tolerance_m=0.5, include_candidate_meshes=False):
    """Fit a bounded family of simple roofs; return best model and alternatives.

    Accepts an Nx2 exterior ring, a GeoJSON Polygon, or a Shapely Polygon.
    ``holes`` are optional interior Nx2 rings when the first form is used.
    ``ridge_azimuth_deg`` is an unoriented axis clockwise from +Y, modulo 180.
    Fits are deterministic, use at most ``max_fit_points`` points, and score
    against ALL finite in-footprint input points.  No ground-height estimation
    is performed here.  Errors in a footprint/datum are reported, not repaired.
    """
    started = time.perf_counter()
    if max_fit_points < 12 or not 1 <= max_orientations <= 8:
        raise ValueError("Use max_fit_points >= 12 and 1..8 orientations")
    if tolerance_m <= 0 or penalty_m < 0:
        raise ValueError("Positive tolerance and nonnegative penalty are required")
    try:
        poly, xyz, center, ground, info = _prepare(footprint_xy, roof_xyz, ground_z, holes)
    except (ValueError, TypeError, IndexError, shapely.errors.GEOSException) as exc:
        return {"schema": _SCHEMA, "status": "invalid_input", "reason": str(exc),
                "best": None, "candidates": [],
                "timing": {"total_seconds": time.perf_counter() - started}}
    info.update(_coverage(poly, xyz))
    if len(xyz) < 12 or np.linalg.matrix_rank(xyz[:, :2] - xyz[:, :2].mean(axis=0)) < 2:
        return {"schema": _SCHEMA, "status": "insufficient_data",
                "reason": "At least 12 roof points spanning both XY dimensions are required",
                "input": info, "best": None, "candidates": [],
                "timing": {"total_seconds": time.perf_counter() - started}}
    if float(np.median(xyz[:, 2])) <= ground + 0.1:
        return {"schema": _SCHEMA, "status": "invalid_heights",
                "reason": "Roof median is not above ground_z; check class/datum",
                "input": info, "best": None, "candidates": [],
                "timing": {"total_seconds": time.perf_counter() - started}}
    # Canonical ordering also makes subsampling independent of LAS chunk order.
    order = np.lexsort((xyz[:, 2], xyz[:, 1], xyz[:, 0]))
    sample = xyz[order]
    if len(sample) > max_fit_points:
        indices = np.sort(np.random.default_rng(0).choice(len(sample), max_fit_points, replace=False))
        sample = sample[indices]
    info["fit_point_count"] = len(sample)
    orientations = _orientations(poly, max_orientations)
    raw = _fit_templates(poly, sample, center, ground, orientations,
                         penalty_m, tolerance_m, allow_barrel)
    bounds_xy = np.concatenate([np.asarray(poly.exterior.coords)] +
                               [np.asarray(r.coords) for r in poly.interiors])
    candidates = []
    for model in raw:
        if np.min(predict_roof_z(model, bounds_xy)) <= ground + 0.05:
            continue  # Do not manufacture roofs intersecting the supplied ground.
        model["metrics"] = _stats(predict_roof_z(model, xyz[:, :2]) - xyz[:, 2],
                                  model["shape"], penalty_m, tolerance_m)
        model["metrics"].update(info)
        candidates.append(model)
    # Return one strongest candidate per family, keeping alternatives reviewable.
    by_shape = {}
    for candidate in candidates:
        shape = candidate["shape"]
        if shape not in by_shape or candidate["metrics"]["selection_score_m"] < by_shape[shape]["metrics"]["selection_score_m"]:
            by_shape[shape] = candidate
    candidates = sorted(by_shape.values(), key=lambda m: (m["metrics"]["selection_score_m"], m["shape"]))
    if not candidates:
        return {"schema": _SCHEMA, "status": "no_valid_model", "input": info,
                "best": None, "candidates": [],
                "timing": {"total_seconds": time.perf_counter() - started}}
    best = candidates[0]
    gap = (candidates[1]["metrics"]["selection_score_m"] - best["metrics"]["selection_score_m"]
           if len(candidates) > 1 else None)
    best["metrics"]["runner_up_score_gap_m"] = gap
    for model in candidates:
        m = model["metrics"]
        if m["coverage_fraction"] < 0.5:
            model["warnings"].append("low_spatial_coverage")
        if m["inlier_fraction"] < 0.75:
            model["warnings"].append("poor_template_fit")
        if len(xyz) < 50:
            model["warnings"].append("few_roof_points")
        model["quality"] = {"heuristic": True,
                            "label": "review" if model["warnings"] else "supported",
                            "not_a_probability": True}
    if gap is not None and gap < 0.06:
        best["warnings"].append("ambiguous_roof_family")
        best["quality"]["label"] = "review"
    for model in candidates if include_candidate_meshes else [best]:
        mesh_started = time.perf_counter()
        try:
            model.update(_mesh(poly, model))
        except (ValueError, shapely.errors.GEOSException) as exc:
            model.update({"vertices": [], "faces": [], "face_semantics": []})
            model["warnings"].append("mesh_failed: " + str(exc))
            model["quality"]["label"] = "review"
        model["timing"]["mesh_seconds"] = time.perf_counter() - mesh_started
    return {"schema": _SCHEMA, "status": "ok", "input": info, "best": best,
            "candidates": candidates,
            "selection_rule": "winsorised_rmse_m + penalty_m * complexity_units",
            "penalty_m": float(penalty_m), "tested_orientations": len(orientations),
            "timing": {"total_seconds": time.perf_counter() - started}}


def baseline_roof_model(footprint_xy, roof_xyz, ground_z, *, holes=None,
                        roof_shape=None, source_height=None, source_levels=None,
                        tolerance_m=0.5):
    """Approximate percentile/long-axis/40-degree baseline, NOT renderer replay.

    Uses p50/p90, a 0.4m flatness threshold and otherwise a symmetric 40-degree
    gable along the long rotated bounding-box edge (roof rise capped at 7m).
    A source hipped/half_hipped tag enables a nominal hip.  Source height
    (metres above ground) or levels provide a fallback only without roof points.
    It deliberately omits renderer land-use rules, footprint decomposition,
    manual overrides and neighbourhood heuristics.  It must be labelled as an
    approximation in comparisons; it is not the current renderer's exact mesh.
    """
    started = time.perf_counter()
    try:
        poly, xyz, center, ground, info = _prepare(footprint_xy, roof_xyz, ground_z, holes)
    except (ValueError, TypeError, IndexError, shapely.errors.GEOSException) as exc:
        return {"status": "invalid_input", "reason": str(exc), "vertices": [], "faces": []}
    if len(xyz):
        p50, p90 = map(float, np.percentile(xyz[:, 2], [50, 90]))
        total = max(p90, p50 + 1.0)
    else:
        usable_height = (source_height is not None and np.isfinite(source_height)
                         and float(source_height) > 0)
        usable_levels = (source_levels is not None and np.isfinite(source_levels)
                         and float(source_levels) > 0)
        if not usable_height and not usable_levels:
            return {"status": "insufficient_data", "vertices": [], "faces": [], "input": info}
        total = ground + (float(source_height) if usable_height else float(source_levels) * 2.9 + 0.4)
        p50 = p90 = None
    theta = _orientations(poly, 2)[0]
    lo, hi = _extent(poly, center, theta)
    flat = roof_shape == "flat" or (roof_shape is None and (p50 is None or p90 - p50 < 0.4))
    shape = "flat" if flat else ("hipped" if roof_shape in ("hipped", "half_hipped") else "gabled")
    params = {"origin_xy": center.tolist(), "height_z": max(ground + 0.2, p50 if p50 is not None else total)}
    if shape != "flat":
        halfwidth = max(float(hi[1] - lo[1]) / 2, 0.1)
        rise = min(halfwidth * math.tan(math.radians(40)), 7.0)
        ridge = max(total, ground + rise + 2.2)
        params = {"origin_xy": center.tolist(), "ridge_angle_rad": float(theta),
                  "ridge_azimuth_deg": float((90 - math.degrees(theta)) % 180),
                  "ridge_z": ridge, "ridge_offset_m": float((lo[1] + hi[1]) / 2),
                  "slope_left": rise / halfwidth, "slope_right": rise / halfwidth}
        if shape == "hipped":
            params = {"origin_xy": center.tolist(), "ridge_angle_rad": float(theta),
                      "ridge_azimuth_deg": float((90 - math.degrees(theta)) % 180),
                      "uv_min": lo.tolist(), "uv_max": hi.tolist(),
                      "eave_z": ridge - rise, "slope_side": rise / halfwidth,
                      "slope_end": rise / halfwidth}
    if len(xyz):
        model = _candidate(shape, params, xyz, ground, 0.0, tolerance_m, started)
    else:
        model = {"schema": _SCHEMA, "shape": shape, "params": params, "ground_z": ground,
                 "metrics": {"evaluation_set": "no_roof_points"},
                 "timing": {"fit_seconds": time.perf_counter() - started},
                 "warnings": ["source_attributes_only", "no_point_validation"]}
    model.update({"status": "ok", "method": "baseline_approximation",
                  "exact_renderer_replay": False,
                  "description": "Percentiles + long-axis + nominal 40-degree roof; excludes renderer rules/overrides",
                  "input": info, "source_roof_shape": str(roof_shape) if roof_shape is not None else None,
                  "source_height": float(source_height) if source_height is not None and np.isfinite(source_height) else None,
                  "source_levels": float(source_levels) if source_levels is not None and np.isfinite(source_levels) else None})
    model["metrics"].update({"p50_z": p50, "p90_z": p90})
    model.update(_mesh(poly, model))
    model["timing"]["total_seconds"] = time.perf_counter() - started
    return model
