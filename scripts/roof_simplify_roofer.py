"""Small, reproducible Roofer LoD2.2 simplification experiment.

Reads an existing frozen training LAZ and at most eight selected footprints.
The three profiles isolate graph-cut complexity from plane-growing tolerance.
No downloads, edits to previous results, or promotion to the city renderer.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

import numpy as np
from shapely import affinity
from shapely.geometry import shape

try:
    from . import resource_guard
    from .roof_detail_variants import _local_roof_area, _native_stats, evaluate_holdout
    from .roof_pilot_roofer import ROOT, ROOFER_EXE, _features, _safe, parse_cityjsonseq, predict_roofer_z
except ImportError:
    import resource_guard
    from roof_detail_variants import _local_roof_area, _native_stats, evaluate_holdout
    from roof_pilot_roofer import ROOT, ROOFER_EXE, _features, _safe, parse_cityjsonseq, predict_roofer_z


PROFILES = {
    "roofer_c035": {
        "lod": "2.2", "complexity_factor": 0.35, "plane_detect_epsilon_m": 0.3,
        "label": "Roofer c=0,35", "purpose": "stronger graph-cut simplicity preference",
    },
    "roofer_c015": {
        "lod": "2.2", "complexity_factor": 0.15, "plane_detect_epsilon_m": 0.3,
        "label": "Roofer c=0,15", "purpose": "aggressive graph-cut simplicity sensitivity",
    },
    "roofer_c035_eps050": {
        "lod": "2.2", "complexity_factor": 0.35, "plane_detect_epsilon_m": 0.5,
        "label": "Roofer c=0,35 + roviny 0,5 m", "purpose": "coarser plane detection at fixed complexity",
    },
}

SOURCE_FILES = (
    "scripts/roof_simplify_roofer.py", "scripts/roof_detail_variants.py",
    "scripts/roof_pilot_roofer.py", "scripts/roof_pilot_methods.py", "scripts/resource_guard.py",
)


def native_variant_command(profile_id, train_path, footprints_path, output_path):
    cfg = PROFILES[profile_id]
    return [
        str(ROOFER_EXE), "-j", "1", "--srs", "EPSG:5514",
        "--id-attribute", "id", "--h-terrain-attribute", "ground_z",
        "--h-terrain-strategy", "user", "--bld-class", "6", "--grnd-class", "2",
        "--no-lod12", "--no-lod13", "--lod22", "--no-clip-terrain",
        "--ceil-point-density", "20", "--complexity-factor", str(cfg["complexity_factor"]),
        "--plane-detect-epsilon", str(cfg["plane_detect_epsilon_m"]),
        "--plane-detect-k", "15", "--plane-detect-min-points", "15",
        "--lod11-fallback-time", "10000", "--lod11-fallback-planes", "120",
        str(train_path), str(footprints_path), str(output_path),
    ]


def snapshot_sources(destination):
    """Archive exact adapter/helper bytes before launching native reconstruction."""
    destination = Path(destination)
    records = []
    for relative in SOURCE_FILES:
        source = ROOT / relative
        data = source.read_bytes()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        records.append({"path": relative, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(), "snapshot_path": str(target)})
    return records


def native_model_status(model):
    """Roofer can label an automatic LoD1.1 extrusion as geometry LoD2.2."""
    if model is None:
        return "missing_output"
    status = model.get("status")
    if status != "ok":
        return status
    mode = model.get("attributes", {}).get("rf_extrusion_mode")
    if mode is None:
        mode = model.get("metrics", {}).get("roofer_extrusion_mode")
    if mode == "lod11_fallback" or "2.2" not in model.get("lods", []):
        return "lod11_fallback"
    return "ok"


def run_native_variant(features_epsg5514, train_path, output_root, profile_id,
                       *, holdout_by_id=None, expected_train_sha256=None):
    """Run one new profile; all model coordinates match the previous comparison.

    Feature properties: id, centre_x/centre_y (EPSG:5514), ground_z (Bpv).
    Holdout arrays: local XY and Z ABOVE ground_z; never passed to Roofer.
    Result retains fallback/missing statuses rather than treating them as LoD2.2.
    """
    cfg = dict(PROFILES[profile_id])
    features = _features(features_epsg5514)
    if not 1 <= len(features) <= 8:
        raise ValueError("This experiment permits one to eight frozen footprints")
    train_path = Path(train_path).resolve()
    if not train_path.is_file() or train_path.suffix.lower() not in (".las", ".laz"):
        raise ValueError("An existing frozen training LAS/LAZ is required")
    output_root = Path(output_root).resolve()
    if not output_root.is_relative_to(ROOT) or output_root == ROOT:
        raise ValueError("Use a dedicated output subdirectory of the budgeted project")
    resource_guard.check_budget(reserve_bytes=20_000_000, force=True)
    start = time.perf_counter()
    train_hash = resource_guard.sha256(train_path)
    if expected_train_sha256 and train_hash != expected_train_sha256:
        raise ValueError("Training LAZ differs from frozen input hash")
    version = subprocess.run([str(ROOFER_EXE), "--version"], capture_output=True,
                             text=True, encoding="utf-8", check=True, timeout=10).stdout.strip()
    if not version.startswith("roofer 1.0.0"):
        raise ValueError("The profiles were validated against Roofer1.0.0; found " + version)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = output_root / (profile_id + "-" + stamp)
    run_dir.mkdir(parents=True)
    sources = snapshot_sources(run_dir / "implementation")
    collection = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:5514"}},
                  "features": list(features.values())}
    data = json.dumps(_safe(collection), sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    footprint_path = run_dir / "footprints-epsg5514.geojson"
    footprint_path.write_bytes(data)
    output_path = run_dir / "cityjson"
    command = native_variant_command(profile_id, train_path, footprint_path, output_path)
    launch = {"created_at": datetime.now(timezone.utc).isoformat(), "profile": cfg,
              "command": command, "roofer_version": version,
              "roofer_sha256": resource_guard.sha256(ROOFER_EXE), "sources": sources,
              "train_sha256": train_hash, "footprints_sha256": hashlib.sha256(data).hexdigest(),
              "holdout_used_for_fitting": False}
    (run_dir / "launch-manifest.json").write_text(json.dumps(launch, indent=2), encoding="utf-8")
    process_metrics = resource_guard.run_guarded(
        command, cwd=ROOT, log_path=run_dir / "roofer.log", max_ram_gb=2.0,
        min_available_gb=1.0, wait_memory_seconds=60, reserve_bytes=20_000_000,
    )
    paths = sorted(set(output_path.rglob("*.jsonl")) | set(output_path.rglob("*.cityjsonseq")))
    if not paths:
        raise RuntimeError("Roofer produced no CityJSONSeq; inspect " + str(run_dir / "roofer.log"))
    models = {}
    for path in paths:
        found = parse_cityjsonseq(path, list(features.values()))
        if set(found) & set(models):
            raise ValueError("Duplicate building ID in native outputs")
        models.update(found)
    native = _native_stats(paths, "2.2")
    buildings = {}
    for identifier, feature in features.items():
        model = models.get(identifier)
        if model is None:
            buildings[identifier] = {"model": None, "error": "missing_output", "metrics": {}, "timing": {}}
            continue
        model["method"] = profile_id
        model["configuration"] = cfg
        model["requested_lod"] = "2.2"
        model["requested_lod_match"] = "2.2" in model.get("lods", [])
        metrics = dict(model.get("metrics", {}))
        metrics.update(native.get(identifier, {}))
        props = feature["properties"]
        footprint = affinity.translate(shape(feature["geometry"]), -props["centre_x"], -props["centre_y"])
        roof_area = _local_roof_area(model)
        metrics.update({
            "roof_footprint_coverage_fraction": float(roof_area.intersection(footprint).area / footprint.area),
            "roof_area_outside_footprint_m2": float(roof_area.difference(footprint).area),
            "render_triangle_count": len(model.get("faces", [])),
            "used_vertex_count": len({i for face in model.get("faces", []) for i in face}),
            "model_json_bytes": len(json.dumps(_safe(model), separators=(",", ":")).encode("utf-8")),
            "requested_lod_match": model["requested_lod_match"],
            "native_lod11_fallback": native_model_status(model) == "lod11_fallback",
        })
        if holdout_by_id is not None and identifier in holdout_by_id:
            holdout = np.asarray(holdout_by_id[identifier], dtype=float).reshape((-1, 3))
            metrics.update(evaluate_holdout(model, holdout))
            pred = predict_roofer_z(model, holdout[:, :2])
            ok = np.isfinite(pred)
            error = pred[ok] - holdout[ok, 2]
            metrics["holdout_within_05m_fraction_of_predicted"] = float(np.mean(np.abs(error) <= 0.5)) if len(error) else None
            metrics["holdout_within_05m_fraction_of_all"] = float(np.sum(np.abs(error) <= 0.5) / len(holdout)) if len(holdout) else None
        model["metrics"].update(metrics)
        status = model.get("status")
        buildings[identifier] = {
            "model": model if status == "ok" else None,
            "error": None if status == "ok" else status,
            "status": native_model_status(model),
            "metrics": metrics, "attributes": model.get("attributes", {}),
            "timing": {"internal_seconds": model.get("timing", {}).get("reconstruction_seconds"),
                       "scope": "Roofer per-building rf_t_run /1000, excludes CLI I/O"},
        }
    result = _safe({
        "schema": "roof-simplify-native/1", "profile_id": profile_id, "configuration": cfg,
        "status": "complete", "created_at": datetime.now(timezone.utc).isoformat(),
        "roofer_version": version, "inputs": launch, "buildings": buildings,
        "process_metrics": process_metrics,
        "timing": {"adapter_total_seconds": time.perf_counter() - start},
        "files": {"run_dir": str(run_dir), "footprints": str(footprint_path),
                  "cityjsonseq": [str(p) for p in paths], "launch_manifest": str(run_dir / "launch-manifest.json")},
        "native_bytes": sum(p.stat().st_size for p in paths),
        "production_map_changed": False,
        "notes": ["Plane epsilon is an inlier tolerance, not a bound on final surface deviation.",
                  "Lower complexity can remove meaningful ridges: inspect silhouette and coverage.",
                  "Holdout belongs to the same point source, not independent surveyed truth."],
    })
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def geometry_sha256(model):
    if model is None:
        return None
    geometry = {key: model.get(key) for key in ("vertices", "faces", "face_semantics", "lods")}
    return hashlib.sha256(json.dumps(_safe(geometry), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalise_summary_statuses(result_path, archive_root):
    """Correct derived labels only; preserve original native outputs and timings.

    The initial measured adapter preserved rf_extrusion_mode but inferred status
    from the LoD tag alone. Archive its summary and this correction before write.
    """
    result_path, archive_root = Path(result_path), Path(archive_root)
    original = result_path.read_bytes()
    result = json.loads(original)
    if result.get("status_normalisation"):
        raise ValueError("Summary already normalised")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    archive = archive_root / stamp
    archive.mkdir(parents=True)
    original_path = archive / "native-results-before-status-normalisation.json"
    original_path.write_bytes(original)
    source_records = snapshot_sources(archive / "implementation")
    corrected = []
    for row in result["runs"]:
        model = row.get("model")
        status = native_model_status(model)
        if model is None:
            status = row.get("status") or row.get("error") or status
        if row.get("status") != status:
            corrected.append({"id": row["id"], "variant": row["variant"],
                              "previous_status": row.get("status"), "status": status})
        row["status"] = status
        fallback = status == "lod11_fallback"
        row["metrics"]["native_lod11_fallback"] = fallback
        if model is not None:
            model["metrics"]["native_lod11_fallback"] = fallback
        for observation in row["repeats"]:
            raw_path = Path(observation["run_dir"]) / "result.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))["buildings"][row["id"]]
            observation["status"] = native_model_status(raw.get("model"))
            observation["native_lod11_fallback"] = observation["status"] == "lod11_fallback"
    result["status_normalisation"] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reason": "Native rf_extrusion_mode is authoritative: fallback may retain geometry lod=2.2",
        "original_summary_sha256": hashlib.sha256(original).hexdigest(),
        "original_summary_path": str(original_path.resolve()),
        "source_snapshots": source_records,
        "corrected_rows": corrected,
        "raw_native_files_modified": False,
        "geometry_and_measured_times_modified": False,
    }
    result["notes"].append("Geometry hashes include vertex/face ordering: a different hash alone does not prove a changed silhouette.")
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result["status_normalisation"]


def run_selected_comparison(manifest_path, result_path, output_root, *, repeats=3, start_budget_seconds=600):
    """Fixed profiles and first-mesh presentation; no holdout-driven selection."""
    if not 1 <= repeats <= 3 or not 0 < start_budget_seconds <= 1200:
        raise ValueError("Use1..3 repeats and a positive start budget at most1200s")
    start = time.perf_counter()
    manifest_path, result_path = Path(manifest_path), Path(result_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "roof-simplification-inputs/1" or manifest.get("source") != "dmpok":
        raise ValueError("Expected frozen roof simplification DMPOK inputs")
    buildings = manifest["buildings"]
    if len(buildings) != 7 or len({b["id"] for b in buildings}) != 7:
        raise ValueError("Expected exactly seven frozen footprints for six objects")
    for relative, expected in manifest["input_sha256"].items():
        if resource_guard.sha256(ROOT / relative) != expected:
            raise ValueError("Frozen input changed: " + relative)
    holdout = {}
    for building in buildings:
        points_path = ROOT / building["points_path"]
        if resource_guard.sha256(points_path) != building["points_sha256"]:
            raise ValueError("Frozen crop changed: " + building["id"])
        with np.load(points_path) as points:
            holdout[building["id"]] = points["test_relative"].copy()
    train_path = Path(manifest["train_laz"])
    expected_train = manifest["input_sha256"][train_path.relative_to(ROOT).as_posix()]
    features = [b["feature"] for b in buildings]
    batches = {profile: [] for profile in PROFILES}
    for repeat in range(repeats):
        for profile in PROFILES:
            if repeat > 0 and time.perf_counter() - start >= start_budget_seconds:
                continue
            print(f"Native Roofer {profile}, repeat {repeat+1}/{repeats}", flush=True)
            result = run_native_variant(features, train_path, output_root, profile,
                                        holdout_by_id=holdout, expected_train_sha256=expected_train)
            batches[profile].append(result)
            progress = {p: [b["files"]["run_dir"] for b in v] for p, v in batches.items()}
            Path(output_root).joinpath("native-progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    rows = []
    for building in buildings:
        identifier = building["id"]
        for profile, observations in batches.items():
            if not observations:
                continue
            first = observations[0]["buildings"][identifier]
            histories, times = [], []
            for index, batch in enumerate(observations):
                observed = batch["buildings"][identifier]
                internal = observed["timing"].get("internal_seconds")
                if internal is not None:
                    times.append(internal)
                histories.append({
                    "repeat_index": index, "status": observed.get("status"), "error": observed.get("error"),
                    "geometry_sha256": geometry_sha256(observed.get("model")),
                    "internal_seconds": internal, "holdout_rmse_m": observed["metrics"].get("holdout_rmse_m"),
                    "native_roof_surfaces": observed["metrics"].get("native_semantic_surface_counts", {}).get("RoofSurface"),
                    "run_dir": batch["files"]["run_dir"],
                })
            rows.append({
                "id": identifier, "pilot_id": building["pilot_id"], "name": building["name"],
                "group_id": building["group_id"], "source": "dmpok", "variant": profile,
                "configuration": PROFILES[profile], "model": first.get("model"),
                "status": first.get("status"), "error": first.get("error"), "metrics": first["metrics"],
                "timing": {"internal_seconds_median": float(np.median(times)) if times else None,
                           "median_internal_seconds": float(np.median(times)) if times else None,
                           "repetitions_internal_seconds": times, "completed_repeats": len(histories),
                           "scope": "native per-building rf_t_run; CLI batches separately recorded"},
                "repeats": histories,
                "repeat_geometry_identical": len({h["geometry_sha256"] for h in histories}) == 1,
                "displayed_geometry_repeat_index": 0, "human_review": {"status": "pending"},
            })
    batch_records = []
    for profile, observations in batches.items():
        for index, batch in enumerate(observations):
            batch_records.append({"variant": profile, "repeat_index": index,
                                  "process_metrics": batch["process_metrics"], "files": batch["files"],
                                  "native_bytes": batch["native_bytes"], "adapter_timing": batch["timing"]})
    result = _safe({
        "schema": "roof-simplify-native-comparison/1", "status": "complete", "source": "dmpok",
        "created_at": datetime.now(timezone.utc).isoformat(), "requested_repeats": repeats,
        "start_budget_seconds": start_budget_seconds, "first_run_of_every_profile_required": True,
        "repetition_plan_completed": all(len(v) == repeats for v in batches.values()),
        "manifest_path": str(manifest_path.resolve()), "manifest_sha256": resource_guard.sha256(manifest_path),
        "profiles": PROFILES, "runs": rows, "batches": batch_records,
        "elapsed_seconds": time.perf_counter() - start,
        "production_map_changed": False, "holdout_used_for_fitting_or_profile_selection": False,
        "notes": ["First actual geometry is displayed; all repeats remain stored, not the best-scoring repeat.",
                  "Repeated geometry can differ; median internal time is not the time of one selected geometry.",
                  "External holdout is from the same source; compare coverage and silhouette separately.",
                  "A plane-detection threshold of0.5m does not guarantee a final0.5m maximum model error."],
    })
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--profile", choices=PROFILES)
    parser.add_argument("--footprints")
    parser.add_argument("--train")
    parser.add_argument("--out")
    parser.add_argument("--expected-train-sha256")
    parser.add_argument("--run-selected", action="store_true")
    parser.add_argument("--normalise-statuses", action="store_true")
    parser.add_argument("--manifest", default="cities/ceske-budejovice/experiments/roof-simplification/manifest.json")
    parser.add_argument("--result", default="cities/ceske-budejovice/experiments/roof-simplification/native-results.json")
    parser.add_argument("--start-budget-seconds", type=float, default=600)
    args = parser.parse_args()
    if args.list:
        print(json.dumps(PROFILES, ensure_ascii=False, indent=2))
        return
    if args.normalise_statuses:
        correction = normalise_summary_statuses(args.result,
            ROOT / ".work/cb-roof-simplification/native/status-normalisation")
        print(json.dumps({"corrected_rows": len(correction["corrected_rows"]),
                          "original_summary_path": correction["original_summary_path"]}, indent=2))
        return
    if args.run_selected:
        result = run_selected_comparison(args.manifest, args.result,
            args.out or ROOT / ".work/cb-roof-simplification/native", start_budget_seconds=args.start_budget_seconds)
        print(json.dumps({"status": result["status"], "rows": len(result["runs"]),
                          "batches": len(result["batches"]), "elapsed_seconds": result["elapsed_seconds"],
                          "repetition_plan_completed": result["repetition_plan_completed"]}, indent=2))
        return
    if not all([args.profile, args.footprints, args.train, args.out]):
        parser.error("Supply --profile, --footprints, --train and --out")
    result = run_native_variant(json.loads(Path(args.footprints).read_text(encoding="utf-8")),
                                args.train, args.out, args.profile,
                                expected_train_sha256=args.expected_train_sha256)
    print(json.dumps({"profile": result["profile_id"], "files": result["files"],
                      "process_metrics": result["process_metrics"]}, indent=2))


if __name__ == "__main__":
    main()
