"""Bounded, training-only decomposition into a few simple roof templates.

This experiment does not modify the map renderer. Coordinates are local XY and
height above the shared ground. It never reads a holdout field from the case.
The resulting parts are separate closed volumes; internal walls are retained,
so the output is not claimed to be a Boolean-unioned/manifold building solid.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import math
import time

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon, mapping
from shapely.ops import split, unary_union

import roof_pilot_methods as templates


SETTINGS = {
    "max_parts": 4,
    "max_candidate_cuts_per_stage": 6,
    "max_selection_points": 6000,
    "max_fit_points_per_part": 1500,
    "max_orientations": 2,
    "template_penalty_m": 0.04,
    "additional_part_penalty_m": 0.20,
    "minimum_objective_improvement_m": 0.02,
    "huber_delta_m": 0.50,
    "minimum_part_area_m2": 25.0,
    "minimum_part_area_fraction": 0.03,
    "minimum_part_points": 40,
    "allow_barrel": True,
}


def _huber_twice(error, delta):
    absolute = np.abs(error)
    return np.where(absolute <= delta, error * error,
                    2.0 * delta * absolute - delta * delta)


def _train_sample(polygon, points, maximum):
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("train_relative must be an N by 3 array")
    points = points[np.isfinite(points).all(axis=1)]
    points = points[shapely.intersects_xy(polygon, points[:, 0], points[:, 1])]
    order = np.lexsort((points[:, 2], points[:, 1], points[:, 0]))
    points = points[order]
    if len(points) > maximum:
        selected = np.sort(np.random.default_rng(41).choice(len(points), maximum, replace=False))
        points = points[selected]
    return points


def _main_axes(polygon):
    ring = np.asarray(polygon.minimum_rotated_rectangle.exterior.coords)[:-1]
    edges = np.roll(ring, -1, axis=0) - ring
    axis = edges[np.argmax(np.linalg.norm(edges, axis=1))]
    axis = axis / np.linalg.norm(axis)
    if axis[0] < 0 or (abs(axis[0]) < 1e-9 and axis[1] < 0):
        axis = -axis
    return [axis, np.array([-axis[1], axis[0]])]


def _fit_region(polygon, points, indices, settings):
    result = templates.fit_roof_models(
        polygon, points[indices], 0.0,
        allow_barrel=settings["allow_barrel"],
        max_fit_points=settings["max_fit_points_per_part"],
        max_orientations=settings["max_orientations"],
        penalty_m=settings["template_penalty_m"],
        tolerance_m=settings["huber_delta_m"],
    )
    model = result.get("best")
    if not model or not model.get("faces"):
        return None
    residual = templates.predict_roof_z(model, points[indices, :2]) - points[indices, 2]
    return {"polygon": polygon, "indices": indices, "model": model,
            "residual": residual,
            "loss_sum": float(_huber_twice(residual, settings["huber_delta_m"]).sum()),
            "fitting": {"seconds": result["timing"]["total_seconds"],
                        "points": len(indices),
                        "shape": model["shape"],
                        "fit_points": model.get("metrics", {}).get("fit_point_count")}}


def _objective(parts, total_points, settings):
    return (math.sqrt(sum(part["loss_sum"] for part in parts) / total_points)
            + settings["additional_part_penalty_m"] * (len(parts) - 1))


def _proposals(parts, points, axes, root_area, settings):
    """Rank geometrical cuts using only current training residuals.

    Candidate positions are footprint vertices and sample quantiles. Ranking
    estimates the reduction after removing the residual median on each side;
    full template refits subsequently decide whether a split is worthwhile.
    """
    candidates = []
    minimum_area = max(settings["minimum_part_area_m2"],
                       root_area * settings["minimum_part_area_fraction"])
    for leaf_index, leaf in enumerate(parts):
        polygon, indices = leaf["polygon"], leaf["indices"]
        ring = np.asarray(polygon.exterior.coords)[:-1]
        for axis_index, axis in enumerate(axes):
            projected = points[indices, :2] @ axis
            extent = ring @ axis
            lo, hi = float(extent.min()), float(extent.max())
            positions = list(extent) + list(np.quantile(projected, [.15, .25, .35, .5, .65, .75, .85]))
            # Canonical centimetre rounding deduplicates almost identical cuts.
            positions = sorted({round(float(c), 2) for c in positions if lo + 1.0 < c < hi - 1.0})
            for position in positions:
                side = projected <= position
                counts = [int(side.sum()), int((~side).sum())]
                if min(counts) < settings["minimum_part_points"]:
                    continue
                along = np.array([-axis[1], axis[0]])
                reach = max(np.linalg.norm(ring, axis=1).max() * 4, 100.0)
                origin = axis * position
                boundary = LineString([origin - along * reach, origin + along * reach])
                pieces = [p for p in split(polygon, boundary).geoms
                          if isinstance(p, Polygon) and p.area > 1e-7]
                # Do not silently collapse disconnected pieces into one roof.
                if len(pieces) != 2 or min(p.area for p in pieces) < minimum_area:
                    continue
                pieces.sort(key=lambda p: float(np.array(p.centroid.coords[0]) @ axis))
                adjusted = leaf["residual"].copy()
                adjusted[side] -= np.median(adjusted[side])
                adjusted[~side] -= np.median(adjusted[~side])
                gain = leaf["loss_sum"] - float(_huber_twice(adjusted, settings["huber_delta_m"]).sum())
                candidates.append({"leaf": leaf_index, "axis": axis_index,
                                   "position_m": position, "rank_gain": gain,
                                   "pieces": pieces, "sides": [indices[side], indices[~side]]})
    candidates.sort(key=lambda c: (-c["rank_gain"], c["leaf"], c["axis"], c["position_m"]))
    return candidates[:settings["max_candidate_cuts_per_stage"]]


def _seams(parts):
    result = []
    for i, left in enumerate(parts):
        for j, right in enumerate(parts[i + 1:], i + 1):
            line = left["polygon"].boundary.intersection(right["polygon"].boundary)
            if line.length < 1e-6:
                continue
            lines = list(line.geoms) if hasattr(line, "geoms") else [line]
            for edge in lines:
                if edge.geom_type != "LineString" or edge.length < 1e-6:
                    continue
                xy = np.array([edge.interpolate(t, normalized=True).coords[0]
                               for t in np.linspace(0, 1, 25)])
                jump = (templates.predict_roof_z(left["model"], xy)
                        - templates.predict_roof_z(right["model"], xy))
                result.append({"left_part": i, "right_part": j,
                               "length_m": float(edge.length),
                               "maximum_height_jump_m": float(np.max(np.abs(jump))),
                               "median_height_jump_m": float(np.median(np.abs(jump))),
                               "note": "Internal division may be a real height step or a fitting seam; requires review."})
    return result


def _combine(parts, polygon, identifier, method):
    vertices, faces, semantics = [], [], []
    for part in parts:
        offset = len(vertices)
        model = part["model"]
        vertices.extend(deepcopy(model["vertices"]))
        faces.extend([[index + offset for index in face] for face in model["faces"]])
        semantics.extend(model["face_semantics"])
    union = unary_union([p["polygon"] for p in parts])
    missing = polygon.difference(union).area
    outside = union.difference(polygon).area
    overlap = sum(p["polygon"].area for p in parts) - union.area
    if max(missing, outside, overlap) > max(1e-6, polygon.area * 1e-9):
        raise ValueError("Partition failed footprint/hole coverage validation")
    return {"schema": "roof-simplified-template-parts/1", "id": identifier,
            "method": method, "status": "ok", "shape": "compound_templates",
            "vertices": vertices, "faces": faces, "face_semantics": semantics,
            "ground_z": 0.0,
            "parts": [{"footprint_local": mapping(p["polygon"]),
                       "shape": p["model"]["shape"], "params": deepcopy(p["model"]["params"]),
                       "fitting": p["fitting"]} for p in parts],
            "template_part_count": len(parts),
            "partition_coverage": {"missing_area_m2": float(missing),
                                   "outside_area_m2": float(outside),
                                   "overlap_area_m2": float(overlap)},
            "internal_seams": _seams(parts),
            "warnings": ["training_selected_partition_requires_visual_review",
                         "separate_extruded_parts_with_internal_walls_not_boolean_union"],
            "mesh_note": "A collection of simple roof volumes clipped to the exact footprint, including courtyard holes."}


def fit_simple_candidates(case, *, max_parts=4, max_candidate_cuts=6):
    """Return whole and bounded compound candidates without reading holdout.

    case requires polygon (Shapely local XY), train_relative (local XYZ,
    height above ground), and optionally id/name. There is no holdout argument.
    """
    started = time.perf_counter()
    if not 1 <= max_parts <= 4 or not 1 <= max_candidate_cuts <= 6:
        raise ValueError("This experiment permits 1..4 parts and 1..6 cuts per stage")
    settings = dict(SETTINGS, max_parts=max_parts, max_candidate_cuts_per_stage=max_candidate_cuts)
    polygon = case["polygon"]
    if not isinstance(polygon, Polygon) or not polygon.is_valid or polygon.area <= 0:
        raise ValueError("A valid Polygon with preserved courtyard holes is required")
    points = _train_sample(polygon, case["train_relative"], settings["max_selection_points"])
    identifier = case.get("id", "anonymous")
    if len(points) < settings["minimum_part_points"]:
        return {"status": "insufficient_data", "id": identifier, "candidates": [],
                "reason": "Too few finite training points inside footprint", "settings": settings}
    first = _fit_region(polygon, points, np.arange(len(points)), settings)
    if first is None:
        return {"status": "no_valid_template", "id": identifier, "candidates": [], "settings": settings}
    whole = deepcopy(first["model"])
    whole.update({"id": identifier, "method": "template_whole_bounded",
                  "status": "ok", "template_part_count": 1})
    parts, history = [first], []
    axes = _main_axes(polygon)
    fitted_regions = 1
    while len(parts) < max_parts:
        objective_before = _objective(parts, len(points), settings)
        proposals = _proposals(parts, points, axes, polygon.area, settings)
        best, evaluated = None, []
        for candidate in proposals:
            children = [_fit_region(p, points, indices, settings)
                        for p, indices in zip(candidate["pieces"], candidate["sides"])]
            fitted_regions += 2
            record = {k: candidate[k] for k in ["leaf", "axis", "position_m", "rank_gain"]}
            if any(c is None for c in children):
                record["status"] = "no_valid_child_template"
                evaluated.append(record)
                continue
            revised = parts[:candidate["leaf"]] + children + parts[candidate["leaf"] + 1:]
            score = _objective(revised, len(points), settings)
            record.update({"status": "evaluated", "objective_m": score,
                           "child_shapes": [c["model"]["shape"] for c in children]})
            evaluated.append(record)
            if best is None or score < best[0]:
                best = (score, revised, record)
        accepted = best is not None and objective_before - best[0] >= settings["minimum_objective_improvement_m"]
        history.append({"parts_before": len(parts), "objective_before_m": objective_before,
                        "evaluated_cuts": evaluated, "accepted": accepted,
                        "selected": best[2] if accepted else None})
        if not accepted:
            break
        parts = best[1]
    compound = _combine(parts, polygon, identifier, "template_parts4_train")
    compound["selection"] = {"set": "bounded_training_subset_only", "points": len(points),
                             "objective_m": _objective(parts, len(points), settings),
                             "rule": "sqrt(mean(twice_Huber_loss_delta_0.5m)) + 0.20m * (part_count - 1)",
                             "holdout_used": False}
    total = time.perf_counter() - started
    return {"schema": "roof-simplification-template-comparison/1", "id": identifier,
            "status": "ok", "settings": settings,
            "candidates": [whole, compound], "partition_log": history,
            "timing": {"total_seconds": total, "fitted_region_count": fitted_regions,
                       "whole_fit_seconds": first["fitting"]["seconds"],
                       "scope": "training subset, proposal search, all accepted/rejected child fits and mesh construction"},
            "notes": ["All partition and roof-family decisions use training points only.",
                      "Huber delta 0.5m is a robust-loss parameter, not a guaranteed output accuracy.",
                      "The partition is a bounded experimental heuristic, not a validated universal roof classifier.",
                      "Barrel candidates use the existing 12-strip mesh approximation; evaluate the displayed mesh separately."]}


def run_frozen_cases():
    """One measured comparison; root owns the external process/resource guard."""
    import roof_simplification_common as common
    import resource_guard as guard
    root = Path(__file__).resolve().parents[1]
    before = guard.check_budget(force=True)
    provenance = common.snapshot([
        Path(__file__), root/'scripts/roof_pilot_methods.py',
        root/'scripts/roof_simplification_common.py', root/'scripts/roof_pilot_roofer.py',
        root/'scripts/resource_guard.py'], 'templates')
    start = time.perf_counter()
    cases = common.load_cases()
    results = {'schema': 'roof-simplification-templates/1',
               'created_at': datetime.now(timezone.utc).isoformat(),
               'source': 'dmpok', 'settings': SETTINGS, 'code_provenance': provenance,
               'input_manifest_sha256': guard.sha256(common.MANIFEST),
               'runs': [], 'partition_logs': {}, 'process_scope': 'one comparison, no repeated real fits',
               'resource_before': before}
    for identifier, case in cases.items():
        guard.check_budget()
        print('Fitting simple/compound templates:', case['name'], flush=True)
        comparison = fit_simple_candidates(case)
        results['partition_logs'][identifier] = {
            'status': comparison['status'], 'partition_log': comparison.get('partition_log', []),
            'timing': comparison.get('timing'), 'settings': comparison['settings']}
        for model in comparison.get('candidates', []):
            variant = model['method']
            evaluation = common.evaluate_model(model, case)
            evaluation['template_part_count'] = model.get('template_part_count', 1)
            rows = model.get('parts') or [{'shape': model['shape']}]
            counts = {}
            for part in rows:
                counts[part['shape']] = counts.get(part['shape'], 0) + 1
            evaluation['template_family_counts'] = counts
            evaluation['internal_seam_max_jump_m'] = max(
                (s['maximum_height_jump_m'] for s in model.get('internal_seams', [])), default=0.0)
            timing = {'seconds': (comparison['timing']['whole_fit_seconds']
                                   if variant == 'template_whole_bounded'
                                   else comparison['timing']['total_seconds']),
                      'repetitions': 1,
                      'scope': ('whole-template solver including mesh; excludes global input loading'
                                if variant == 'template_whole_bounded'
                                else comparison['timing']['scope']),
                      'timings_overlap': 'Compound search includes its initial whole fit; do not add the two rows.'}
            results['runs'].append({'id': identifier, 'name': case['name'], 'variant': variant,
                                    'source': 'dmpok', 'model': model, 'metrics': evaluation,
                                    'timing': timing,
                                    'review': {'status': 'review',
                                               'note': 'Training-only experimental decomposition; inspect shape and internal height seams before use.'}})
        common.write(common.DEST/'templates-results.json', results)
    results['elapsed_seconds'] = time.perf_counter()-start
    results['resource_after'] = guard.check_budget(force=True)
    results['status'] = 'complete'
    common.write(common.DEST/'templates-results.json', results)
    print('Saved:', common.DEST/'templates-results.json', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Fit only the frozen selected footprint cases')
    arguments = parser.parse_args()
    if arguments.execute:
        run_frozen_cases()
    else:
        parser.print_help()
