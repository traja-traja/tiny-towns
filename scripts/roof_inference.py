"""Infer a roof from classified points in a metric footprint, independently of the renderer."""
from __future__ import annotations

import math
import time

import numpy as np
from scipy.optimize import least_squares
import shapely
from shapely.geometry import LineString, Point

import roof_pilot_methods as templates
from roof_simplify_templates import _huber_twice, _main_axes, _proposals


TOLERANCE = 0.50
COMPLEXITY_PENALTY = {
    "flat": 0.0, "shed": 0.06, "gabled": 0.10, "hipped": 0.15,
    "pyramidal": 0.13, "barrel": 0.15, "butterfly": 0.12,
}


def _cells(points, origin, width):
    keys = np.floor((points[:, :2] - origin) / width).astype(int)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    return np.array([np.median(group, axis=0) for group in
                     np.split(points[order], np.flatnonzero(np.diff(inverse[order])) + 1)])


def _stats(errors):
    absolute = np.abs(errors)
    p50, p75, p90, p95, p99 = np.percentile(absolute, [50, 75, 90, 95, 99])
    return {
        "count": len(errors), "median_signed_m": float(np.median(errors)),
        "median_abs_m": float(p50), "p75_abs_m": float(p75), "p90_abs_m": float(p90),
        "p95_abs_m": float(p95), "p99_abs_m": float(p99),
        "rmse_m": float(np.sqrt(np.mean(errors ** 2))),
        "p90_winsorized_rmse_m": float(np.sqrt(np.mean(np.minimum(absolute, p90) ** 2))),
        "within_0_5m_fraction": float(np.mean(absolute <= TOLERANCE)),
        "above_model_1m_count": int(np.count_nonzero(errors > 1)),
        "below_model_1m_count": int(np.count_nonzero(errors < -1)),
    }


def _ridge_evidence(uv, z, lo, hi, *, valley=False):
    """Find useful ridge seeds in cross sections even when a few points are very high."""
    positions = []
    along = (uv[:, 0] - lo[0]) / (hi[0] - lo[0])
    for i in range(6):
        inside = (along >= i / 6) & (along < (i + 1) / 6)
        if inside.sum() < 8:
            continue
        cutoff = np.quantile(z[inside], 0.20 if valley else 0.80)
        peak = inside & ((z <= cutoff) if valley else (z >= cutoff))
        positions.append([float(np.median(uv[peak, 0])),
                          float(np.median(uv[peak, 1])),
                          float(np.median(z[peak]))])
    return positions


def _candidate(kind, origin, angle=0.0, *, params, ridge_uv=None, eaves=(), shape=None):
    return {
        "type": kind, "shape": shape or kind,
        "params": {"origin_xy": origin.tolist(), "ridge_angle_rad": angle, **params},
        "ridge_uv": ridge_uv, "eave_segments_uv": eaves,
    }


def _pitched(poly, points, origin, z_ref, angle, spread, evidence):
    uv = templates._frame(points[:, :2], origin, angle)
    lo, hi = templates._extent(poly, origin, angle)
    length, width = hi - lo
    h_low = float(np.percentile(points[:, 2], 10) - z_ref)
    peak = float(np.percentile(points[:, 2], 95) - z_ref)
    z = points[:, 2] - z_ref
    offset = np.median(np.asarray(evidence)[:, 1]) if evidence else (lo[1] + hi[1]) / 2
    v_seed = float(np.clip((offset - lo[1]) / width, .17, .83))
    height_bounds = (h_low - max(spread, 5), peak + max(spread, 3))
    min_rise, max_rise = .15, min(60, 3 * max(length, width), max(4, 3 * spread))
    rise_seed = min(max_rise * .8, max(.35, peak - h_low))

    def fit(fun, seed, lower, upper):
        seed = np.clip(seed, np.asarray(lower) + 1e-6, np.asarray(upper) - 1e-6)
        return least_squares(fun, seed, bounds=(lower, upper), loss="soft_l1",
                             f_scale=.25, max_nfev=55).x

    def bounds_at(theta):
        return templates._extent(poly, origin, theta)

    def gable_residual(x, sign):
        ridge_relative_z, rise_left, across, theta = x[:4]
        rise_right = x[4] if len(x) == 5 else rise_left
        v = templates._frame(points[:, :2], origin, theta)[:, 1]
        low, high = bounds_at(theta)
        t = (v - low[1]) / (high[1] - low[1])
        drop = rise_left * np.maximum(1 - t / across, 0) + rise_right * np.maximum((t - across) / (1 - across), 0)
        return ridge_relative_z - sign * drop - z

    # Keep the ridge and each eave level. Test unequal eave heights as a more
    # complex variant, starting from the fit with one shared height.
    seed = [peak, rise_seed, v_seed, angle]
    lower = [height_bounds[0], min_rise, .12, angle - math.radians(15)]
    upper = [height_bounds[1], max_rise, .88, angle + math.radians(15)]
    for kind, sign in (("gabled", 1), ("butterfly", -1)):
        if kind == "butterfly":
            valleys = _ridge_evidence(uv, z, lo, hi, valley=True)
            center_v = float(np.median(np.asarray(valleys)[:, 1])) if valleys else (lo[1] + hi[1]) / 2
            seed = [h_low, rise_seed, (center_v - lo[1]) / width, angle]
        shared = fit(lambda x: gable_residual(x, sign), seed, lower, upper)
        unequal = fit(lambda x: gable_residual(x, sign), [*shared, shared[1]],
                      [*lower, min_rise], [*upper, max_rise])
        for x in (shared, unequal):
            ridge_z, rise_left, across, theta = x[:4]
            ridge_z += z_ref
            rise_right = x[4] if len(x) == 5 else rise_left
            low, high = bounds_at(theta)
            ridge_v = low[1] + across * (high[1] - low[1])
            yield _candidate(kind, origin, theta, params={
                "ridge_z": ridge_z, "ridge_offset_m": ridge_v,
                "slope_left": rise_left / (ridge_v - low[1]),
                "slope_right": rise_right / (high[1] - ridge_v),
                "eave_z": ridge_z - sign * min(rise_left, rise_right), "separate_eave_levels": len(x) == 5},
                ridge_uv=[[low[0], ridge_v, ridge_z], [high[0], ridge_v, ridge_z]],
                eaves=((low[0], low[1], high[0], low[1]), (low[0], high[1], high[0], high[1])))

    def hip_parameters(x, pyramidal):
        eave_z, rise_m, center_u, v_ratio = x[:4]
        half = 0 if pyramidal else x[4] * min(center_u, 1 - center_u)
        left, right = lo[0] + length * np.array([center_u - half, center_u + half])
        center_v = lo[1] + width * v_ratio
        return eave_z, rise_m, left, right, center_v

    def hip_planes(x, pyramidal):
        eave_z, rise_m, left, right, center_v = hip_parameters(x, pyramidal)
        su0, su1 = rise_m / (left - lo[0]), rise_m / (hi[0] - right)
        sv0, sv1 = rise_m / (center_v - lo[1]), rise_m / (hi[1] - center_v)
        return np.array([[0, sv0, eave_z - sv0 * lo[1]], [0, -sv1, eave_z + sv1 * hi[1]],
                         [su0, 0, eave_z - su0 * lo[0]], [-su1, 0, eave_z + su1 * hi[0]]])

    def hip_residual(x, pyramidal):
        planes = hip_planes(x, pyramidal)
        return (uv @ planes[:, :2].T + planes[:, 2]).min(axis=1) - z

    for kind in ("hipped", "pyramidal"):
        pyramidal = kind == "pyramidal"
        seed = [h_low, rise_seed, .5, v_seed]
        lower = [height_bounds[0], min_rise, .15, .12]
        upper = [height_bounds[1], max_rise, .85, .88]
        if not pyramidal:
            seed.append(.55)
            lower.append(.15)
            upper.append(.92)
        x = fit(lambda x: hip_residual(x, pyramidal), seed, lower, upper)
        eave_z, rise_m, left, right, center_v = hip_parameters(x, pyramidal)
        planes = hip_planes(x, pyramidal)
        planes[:, 2] += z_ref
        yield _candidate(kind, origin, angle, shape="plane_envelope", params={
            "planes_uv": planes.tolist(), "eave_z": eave_z + z_ref,
            "ridge_z": eave_z + rise_m + z_ref, "rise_m": rise_m},
            ridge_uv=[[left, center_v, eave_z + rise_m + z_ref],
                      [right, center_v, eave_z + rise_m + z_ref]],
            eaves=((lo[0], lo[1], hi[0], lo[1]), (hi[0], lo[1], hi[0], hi[1]),
                   (hi[0], hi[1], lo[0], hi[1]), (lo[0], hi[1], lo[0], lo[1])))

    # Evaluate the same linear strips that will be triangulated.
    profile_v = np.linspace(lo[1], hi[1], 25)
    arch = np.sqrt(np.maximum(0, 1 - np.linspace(-1, 1, 25) ** 2))
    observed_arch = np.interp(uv[:, 1], profile_v, arch)
    eave, rise = fit(lambda x: x[0] + x[1] * observed_arch - z, [h_low, rise_seed],
                     [height_bounds[0], min_rise], [height_bounds[1], max_rise])
    mid_v = (lo[1] + hi[1]) / 2
    yield _candidate("barrel", origin, angle, params={
        "profile_v": profile_v.tolist(), "profile_z": (z_ref + eave + rise * arch).tolist(),
        "eave_z": z_ref + eave, "ridge_z": z_ref + eave + rise, "rise_m": rise},
        ridge_uv=[[lo[0], mid_v, z_ref + eave + rise], [hi[0], mid_v, z_ref + eave + rise]],
        eaves=((lo[0], lo[1], hi[0], lo[1]), (lo[0], hi[1], hi[0], hi[1])))


def _evaluate(model, poly, points, ground_z):
    xy, z = points[:, :2], points[:, 2]
    expected = templates.predict_roof_z(model, xy)
    errors = z - expected
    kind, params = model["type"], model["params"]
    metrics = _stats(errors)
    rejected = []
    boundary = np.concatenate([np.asarray(r.coords) for r in [poly.exterior, *poly.interiors]])
    perimeter_z = templates.predict_roof_z(model, boundary)
    if ground_z is not None and min(perimeter_z) <= ground_z + .1:
        rejected.append("surface_intersects_ground")
    support = None
    uv = templates._frame(xy, np.asarray(params["origin_xy"]), params["ridge_angle_rad"])
    inliers = np.abs(errors) <= TOLERANCE
    if kind == "flat" and float(np.ptp(np.percentile(z, [10, 90]))) > 2 * TOLERANCE:
        rejected.append("height_spread_too_large_for_flat")
    if kind == "shed" and np.ptp(perimeter_z) < .45:
        rejected.append("shed_rise_too_small")
    if kind in ("gabled", "barrel", "hipped", "pyramidal", "butterfly"):
        ridge = np.asarray(model["ridge_uv"])
        rise = abs(params["ridge_z"] - params["eave_z"])
        if rise < .45:
            rejected.append("ridge_rise_too_small")
        if kind in ("hipped", "pyramidal"):
            planes = np.asarray(params["planes_uv"])
            panel = (uv @ planes[:, :2].T + planes[:, 2]).argmin(axis=1)
            panels = 4
        else:
            panel = (uv[:, 1] > ridge[0, 1]).astype(int)
            panels = 2
        support = np.bincount(panel[inliers], minlength=panels).tolist()
        if min(support) < max(3, math.ceil(.04 * len(z))):
            rejected.append("insufficient_support_on_a_roof_face")
    extra_penalty = .05 if params.get("separate_eave_levels") else 0
    score = (metrics["p90_winsorized_rmse_m"] + .25 * (1 - metrics["within_0_5m_fraction"])
             + COMPLEXITY_PENALTY[kind] + extra_penalty)
    return {"type": kind, "score_m": score, "residuals": metrics, "rejected": rejected,
            "azimuth_deg": float((90 - math.degrees(params["ridge_angle_rad"])) % 180)
            if model["ridge_uv"] is not None else None, "face_inlier_cells": support,
            "separate_eave_levels": params.get("separate_eave_levels")}


def _critical_edges(poly, model):
    p = model["params"]
    theta = p["ridge_angle_rad"]
    transform = np.array([[math.cos(theta), math.sin(theta)], [-math.sin(theta), math.cos(theta)]])

    def xy(uv):
        return np.asarray(uv) @ transform + p["origin_xy"]

    def clipped(a, b, domain):
        if np.allclose(a, b, rtol=0, atol=1e-7):
            return []
        result = domain.intersection(LineString([a, b]))
        return [segment for segment in getattr(result, "geoms", [result])
                if segment.geom_type == "LineString" and segment.length > 1e-7]

    ridge, apex = [], None
    if model["ridge_uv"] is not None:
        a, b = np.asarray(model["ridge_uv"])
        aa, bb = xy([a[:2], b[:2]])
        if model["type"] == "pyramidal" and poly.covers(Point(aa)):
            apex = [*aa.tolist(), float(a[2])]
        ridge = [[[x, y, float(a[2])] for x, y in line.coords]
                 for line in clipped(aa, bb, poly)]
    # The horizontal design eaves are clipped to the real wall outline. Irregular
    # footprints may cut across a roof face and yield sloping perimeter segments.
    eaves = []
    for u0, v0, u1, v1 in model["eave_segments_uv"]:
        aa, bb = xy([[u0, v0], [u1, v1]])
        for line in clipped(aa, bb, poly.boundary.buffer(.03)):
            if line.length >= .25:
                z = templates.predict_roof_z(model, [line.interpolate(.5, normalized=True).coords[0]])[0]
                eaves.append([[x, y, float(z)] for x, y in line.coords])
    return ridge, apex, eaves


def _compound_type(parts, models):
    types = [model["type"] for model in models]
    params = [model["diagnostics"]["levelled_parameters"] for model in models]
    if types == ["flat", "flat"] and abs(params[0]["height_z"] - params[1]["height_z"]) >= .45:
        return "multi_flat"
    if types != ["shed", "shed"]:
        return "compound"
    slopes = np.asarray([[p["slope_x"], p["slope_y"]] for p in params])
    magnitudes = np.linalg.norm(slopes, axis=1)
    if min(magnitudes) < .12:
        return "compound"
    direction = slopes[0] / magnitudes[0]
    if np.dot(direction, slopes[1] / magnitudes[1]) < .94:
        return "compound"
    seam = parts[0].boundary.intersection(parts[1].boundary)
    if seam.length < 2:
        return "compound"
    points = np.array([seam.interpolate(float(t), normalized=True).coords[0]
                       for t in np.linspace(.1, .9, 7)])
    if np.ptp(points @ direction) > .30 * seam.length:
        return "compound"
    z = [templates.predict_roof_z({"shape": "shed", "params": p}, points) for p in params]
    centroids = np.array([part.centroid.coords[0] for part in parts])
    first = np.argmin(centroids @ direction)
    return "sawtooth" if np.quantile(z[first] - z[1 - first], .20) > .60 else "compound"


def _compound(poly, points, sample, ground_z, winner, single):
    """Try a small set of straight footprint splits when one roof fits poorly."""
    training_error = sample[:, 2] - templates.predict_roof_z(winner, sample[:, :2])
    leaf = {"polygon": poly, "indices": np.arange(len(sample)), "residual": training_error,
            "loss_sum": float(_huber_twice(training_error, TOLERANCE).sum())}
    cuts = _proposals([leaf], sample, _main_axes(poly), poly.area, {
        "minimum_part_area_m2": 20, "minimum_part_area_fraction": .09,
        "minimum_part_points": 20, "max_candidate_cuts_per_stage": 6,
        "huber_delta_m": TOLERANCE})
    single_stats = single["diagnostics"]["residuals"]
    attempts = []
    best = None
    for cut in cuts:
        pieces = cut["pieces"]
        first = shapely.intersects_xy(pieces[0], points[:, 0], points[:, 1])
        masks = (first, ~first)
        models = [_infer_roof(part, points[mask], ground_z, allow_compound=False)
                  for part, mask in zip(pieces, masks)]
        if any(not model["roof_faces"] for model in models):
            continue
        errors = []
        for model, mask in zip(models, masks):
            params = model["diagnostics"]["levelled_parameters"]
            shape = "plane_envelope" if "planes_uv" in params else model["type"]
            actual = points[mask]
            errors.append(actual[:, 2] - templates.predict_roof_z(
                {"shape": shape, "params": params}, actual[:, :2]))
        stats = _stats(np.concatenate(errors))
        improvement = single_stats["p90_winsorized_rmse_m"] - stats["p90_winsorized_rmse_m"]
        inlier_gain = stats["within_0_5m_fraction"] - single_stats["within_0_5m_fraction"]
        kind = _compound_type(pieces, models)
        attempt = {"type": kind, "part_types": [model["type"] for model in models], "residuals": stats,
                   "rmse_gain_m": improvement, "inlier_gain": inlier_gain,
                   "eligible": improvement >= .22 and inlier_gain >= .08}
        attempts.append(attempt)
        if attempt["eligible"] and (best is None or improvement > best[0]):
            best = improvement, models, stats, kind
    if not best:
        single["diagnostics"]["compound_trials"] = attempts
        return single
    _, models, stats, kind = best
    combined = {key: [] for key in ("vertices", "roof_faces", "wall_faces", "ground_faces",
                                   "ridge", "valley", "eaves", "parts")}
    for part in models:
        offset = len(combined["vertices"])
        combined["vertices"].extend(part["vertices"])
        for key in ("roof_faces", "wall_faces", "ground_faces"):
            combined[key].extend([[index + offset for index in face] for face in part[key]])
        for key in ("ridge", "valley", "eaves"):
            combined[key].extend(part[key])
        combined["parts"].append({"type": part["type"], "status": part["status"],
                                  "diagnostics": part["diagnostics"], "apex": part["apex"]})
    diagnostics = single["diagnostics"].copy()
    diagnostics.update(selected_type=kind, residuals=stats, compound_trials=attempts,
                       single_roof={"type": single["type"], "residuals": single_stats},
                       reasons=["compound_split_requires_review"])
    return {**combined, "type": kind, "apex": None, "status": "review",
            "diagnostics": diagnostics}


def infer_roof(polygon, xyz, ground_z=None):
    """Return one classified building mesh in input XY and absolute Z (EPSG:5514/Bpv for ČB)."""
    return _infer_roof(polygon, xyz, ground_z, allow_compound=True)


def _infer_roof(polygon, xyz, ground_z, *, allow_compound):
    started = time.perf_counter()
    poly = templates._polygon(polygon)
    points = np.asarray(xyz, dtype=float)
    if points.size == 0:
        points = np.empty((0, 3))
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("xyz must be an N by 3 array")
    if ground_z is not None:
        ground_z = float(ground_z)
        if not np.isfinite(ground_z):
            raise ValueError("ground_z must be finite")
    points = points[np.isfinite(points).all(axis=1)]
    points = points[shapely.intersects_xy(poly, points[:, 0], points[:, 1])]
    result = {"type": None, "vertices": [], "roof_faces": [], "wall_faces": [],
              "ground_faces": [], "ridge": [], "valley": [], "apex": None, "eaves": []}
    diagnostics = {"input_point_count": len(points), "ground_z": ground_z,
                   "area_m2": float(poly.area), "reasons": []}
    result["diagnostics"] = diagnostics
    if len(points) < 12:
        diagnostics["reasons"].append("fewer_than_12_roof_points")
        return {**result, "status": "insufficient_data"}
    origin = np.array(poly.centroid.coords[0])
    z_ref = float(np.median(points[:, 2]))
    coverage = templates._coverage(poly, points)
    width = max(.65, math.sqrt(poly.area / 700))
    sample = _cells(points, np.asarray(poly.bounds[:2]), width)
    sample = sample[shapely.intersects_xy(poly, sample[:, 0], sample[:, 1])]
    diagnostics.update(coverage, fit_cell_m=width, fit_cell_count=len(sample))
    if len(sample) < 10 or np.linalg.matrix_rank(sample[:, :2] - sample[:, :2].mean(axis=0)) < 2:
        diagnostics["reasons"].append("insufficient_spatial_support")
        return {**result, "status": "insufficient_data"}

    z = sample[:, 2] - z_ref
    p10, p90 = np.percentile(z, [10, 90])
    spread = float(p90 - p10)
    diagnostics["height_p90_minus_p10_m"] = spread
    design = np.column_stack([np.ones(len(z)), sample[:, :2] - origin])
    plane = least_squares(lambda x: design @ x - z, np.linalg.lstsq(design, z, rcond=None)[0],
                          loss="soft_l1", f_scale=.25, max_nfev=30).x
    models = [_candidate("flat", origin, params={"height_z": float(np.median(z) + z_ref)}),
              _candidate("shed", origin, params={"height_z": plane[0] + z_ref,
                                                 "slope_x": plane[1], "slope_y": plane[2]})]
    if spread < .40:
        diagnostics["prefilter"] = {"pitched": "height_spread_below_0_40m"}
    else:
        sections = []
        for angle in templates._orientations(poly, 4):
            lo, hi = templates._extent(poly, origin, angle)
            evidence = _ridge_evidence(templates._frame(sample[:, :2], origin, angle),
                                       sample[:, 2], lo, hi)
            sections.append({"angle_deg_from_east": math.degrees(angle), "peaks_uvz": evidence})
            models.extend(_pitched(poly, sample, origin, z_ref, angle, spread, evidence))
        diagnostics["cross_section_peaks"] = sections

    scored = [(model, _evaluate(model, poly, sample, ground_z)) for model in models]
    scored.sort(key=lambda pair: (bool(pair[1]["rejected"]), pair[1]["score_m"], pair[0]["type"]))
    diagnostics["candidates"] = [metrics for _, metrics in scored]
    eligible = [pair for pair in scored if not pair[1]["rejected"]]
    if not eligible:
        diagnostics["reasons"].append("all_candidates_rejected")
        return {**result, "status": "unresolved"}

    within_tolerance = [pair for pair in eligible if pair[1]["residuals"]["within_0_5m_fraction"] >= .90
                        and pair[1]["residuals"]["median_abs_m"] <= .25]
    winner, metrics = (min(within_tolerance, key=lambda pair: (
        COMPLEXITY_PENALTY[pair[0]["type"]] + .05 * bool(pair[0]["params"].get("separate_eave_levels")),
        pair[1]["score_m"])) if within_tolerance else eligible[0])
    alternative = next((other for model, other in eligible if model["type"] != winner["type"]), None)
    gap = None if alternative is None else abs(alternative["score_m"] - metrics["score_m"])
    diagnostics.update(selected_type=winner["type"], selection_score_m=metrics["score_m"],
                       runner_up=alternative and alternative["type"], runner_up_gap_m=gap,
                       selection_rule="simplest_within_tolerance" if within_tolerance else "minimum_penalised_error",
                       levelled_parameters=winner["params"])
    reasons = diagnostics["reasons"]
    if gap is not None and gap < .06:
        reasons.append("small_gap_between_roof_types")
    azimuth = metrics["azimuth_deg"]
    if azimuth is not None:
        competing = next((m for model, m in eligible if model["type"] == winner["type"]
                          and abs((m["azimuth_deg"] - azimuth + 90) % 180 - 90) > 20), None)
        if competing and abs(competing["score_m"] - metrics["score_m"]) < .06:
            reasons.append("ambiguous_ridge_orientation")
    if coverage["coverage_fraction"] < .60:
        reasons.append("low_spatial_coverage")
    if len(sample) < 35:
        reasons.append("few_fit_cells")
    if metrics["residuals"]["within_0_5m_fraction"] < .72:
        reasons.append("low_surface_inlier_fraction")
    if ground_z is None:
        reasons.append("no_ground_points_for_walls")

    try:
        mesh = templates._mesh(poly, {**winner, "ground_z": ground_z})
    except (ValueError, shapely.errors.GEOSException) as exc:
        reasons.append(f"mesh_failed: {exc}")
        return {**result, "status": "unresolved"}
    ridge, apex, eaves = _critical_edges(poly, winner)
    if winner["type"] == "pyramidal" and apex is None:
        reasons.append("apex_outside_footprint")
    if winner["type"] in ("gabled", "hipped", "barrel") and not ridge:
        reasons.append("ridge_outside_footprint")
    if winner["type"] == "butterfly" and not ridge:
        reasons.append("valley_outside_footprint")
    check_started = time.perf_counter()
    residual = points[:, 2] - templates.predict_roof_z(winner, points[:, :2])
    residual_stats = _stats(residual)
    diagnostics.update(residuals=residual_stats, residual_check_seconds=time.perf_counter() - check_started)
    if residual_stats["p90_abs_m"] > 2.5:
        reasons.append("large_tail_residuals")
    result.update(type=winner["type"], vertices=mesh["vertices"], ridge=ridge, apex=apex, eaves=eaves,
                  status="review" if reasons else "supported")
    if winner["type"] == "butterfly":
        result["valley"], result["ridge"] = ridge, []
    for face, semantic in zip(mesh["faces"], mesh["face_semantics"]):
        result[f"{semantic}_faces"].append(face)
    if (allow_compound and len(sample) >= 65 and poly.area >= 60
            and metrics["residuals"]["within_0_5m_fraction"] < .72
            and coverage["coverage_fraction"] >= .55):
        result = _compound(poly, points, sample, ground_z, winner, result)
    result["diagnostics"]["total_seconds"] = time.perf_counter() - started
    return result
