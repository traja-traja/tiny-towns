"""Compose the measured CB experiments into one offline review document.

This script does not reconstruct buildings or fetch references. It refuses to
publish a gallery until all three measured experiment result files exist.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "cities/ceske-budejovice/experiments"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def serializable(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    return value


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def median(values):
    values = [v for v in values if finite(v)]
    return statistics.median(values) if values else None


def resolve_file(value, owner=DEST):
    """Resolve an explicitly supplied project path, never guess another image."""
    path = Path(value)
    candidates = [path] if path.is_absolute() else [ROOT / path, owner / path]
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_relative_to(ROOT) and candidate.is_file():
            return candidate
    raise FileNotFoundError(value)


def image_data(path, *, preview_size=None):
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}[path.suffix.lower()]
    if preview_size:
        from PIL import Image, ImageOps
        if path.stat().st_size > 20_000_000:
            raise ValueError(f"Source reference exceeds 20 MB: {path}")
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail(preview_size, Image.Resampling.LANCZOS)
            stream = BytesIO()
            image.save(stream, format="JPEG", quality=84, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
    if path.stat().st_size > 4_000_000:
        raise ValueError(f"Review image exceeds 4 MB: {path}")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def fingerprint(path):
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def summary_rows(runs):
    rows = []
    for variant in dict.fromkeys(r["variant"] for r in runs):
        # A fit to an explicitly delimited roof part has a different evaluation
        # population and must not enter the whole-building summary table.
        if variant not in {"roofer_lod22_reference", "roofer_lod22_regular", "roofer_lod13_volumes"}:
            continue
        group = [r for r in runs if r["variant"] == variant]
        good = [r for r in group if (r.get("model") or {}).get("faces")]
        fallbacks = sum((r["model"].get("attributes", {}).get("rf_extrusion_mode")
                         or r["model"].get("metrics", {}).get("roofer_extrusion_mode")
                         or "standard") != "standard" for r in good)
        rows.append({"variant": variant, "expected": len(group), "models": len(good),
                     "fallback_models": fallbacks,
                     "median_rmse_m": median((r.get("metrics") or {}).get("holdout_rmse_m") for r in good),
                     "median_common_rmse_m": median((r.get("metrics") or {}).get("common_support_rmse_m") for r in good),
                     "median_coverage": median((r.get("metrics") or {}).get("coverage_fraction") for r in good),
                     "median_native_roof_surfaces": median((r.get("metrics") or {}).get("native_roof_surface_count") for r in good),
                     "median_triangles": median(len(r["model"]["faces"]) for r in good),
                     "median_bytes": median((r.get("metrics") or {}).get("model_json_bytes") for r in good)})
    return rows


def roof_pairwise(runs):
    """Individual changes prevent a shift in marginal medians hiding regressions."""
    base = {r["id"]: r for r in runs if r["variant"] == "roofer_lod22_reference"
            and (r.get("model") or {}).get("faces")
            and finite(r.get("metrics", {}).get("common_support_rmse_m"))}
    summaries = []
    for variant in ("roofer_lod22_regular", "roofer_lod13_volumes"):
        pairs = []
        for run in runs:
            if run["variant"] != variant or run["id"] not in base or not (run.get("model") or {}).get("faces"):
                continue
            old, new = base[run["id"]]["metrics"], run.get("metrics", {})
            if not finite(new.get("common_support_rmse_m")):
                continue
            delta = new["common_support_rmse_m"] - old["common_support_rmse_m"]
            before, after = old.get("native_roof_surface_count"), new.get("native_roof_surface_count")
            pairs.append({"id": run["id"], "name": run["name"], "rmse_before_m": old["common_support_rmse_m"],
                          "rmse_after_m": new["common_support_rmse_m"], "rmse_delta_m": delta,
                          "native_roof_surfaces_before": before, "native_roof_surfaces_after": after,
                          "native_roof_surface_delta": after - before if finite(before) and finite(after) else None})
        summaries.append({"variant": variant, "pairs": sorted(pairs, key=lambda p: p["rmse_delta_m"], reverse=True),
                          "n": len(pairs), "epsilon_m": 1e-6,
                          "improved": sum(p["rmse_delta_m"] < -1e-6 for p in pairs),
                          "worse": sum(p["rmse_delta_m"] > 1e-6 for p in pairs),
                          "unchanged": sum(abs(p["rmse_delta_m"]) <= 1e-6 for p in pairs),
                          "median_delta_m": median(p["rmse_delta_m"] for p in pairs),
                          "median_native_roof_surface_delta": median(p["native_roof_surface_delta"] for p in pairs),
                          "median_native_surfaces_before": median(p["native_roof_surfaces_before"] for p in pairs),
                          "median_native_surfaces_after": median(p["native_roof_surfaces_after"] for p in pairs),
                          "sum_native_surfaces_before": sum(p["native_roof_surfaces_before"] for p in pairs if finite(p["native_roof_surfaces_before"])),
                          "sum_native_surfaces_after": sum(p["native_roof_surfaces_after"] for p in pairs if finite(p["native_roof_surfaces_after"]))})
    return summaries


def benchmark_summary(document):
    """Report raw and paired medians separately; do not resample geometry."""
    rows = []
    for source in ("dmp1g", "dmpok"):
        cohorts = {}
        groups = {}
        for method in ("baseline", "templates", "roofer"):
            runs = [r for r in document["runs"] if r["source"] == source and r["method"] == method]
            groups[method] = runs
            cohorts[method] = {r["id"] for r in runs if r.get("status") == "ok"
                               and (r.get("model") or {}).get("faces")
                               and finite(r.get("metrics", {}).get("holdout_rmse_m"))}
        paired = set.intersection(*cohorts.values())
        for method, runs in groups.items():
            valid_models = [r for r in runs if r.get("status") == "ok" and (r.get("model") or {}).get("faces")]
            errors = [r["metrics"]["holdout_rmse_m"] for r in runs if r["id"] in cohorts[method]]
            paired_errors = [r["metrics"]["holdout_rmse_m"] for r in runs if r["id"] in paired]
            times = [r.get("elapsed_seconds") for r in runs if finite(r.get("elapsed_seconds"))]
            rows.append({"source": source, "method": method, "models": len(valid_models), "expected": len(runs),
                         "rmse_n": len(errors), "median_rmse_m": median(errors),
                         "paired_n": len(paired), "paired_median_rmse_m": median(paired_errors),
                         "paired_ids": sorted(paired), "model_time_sum_seconds": sum(times) if times else None,
                         "timing_scope": "sum_of_per_building_3_repeat_medians" if method != "roofer" else "sum_of_roofer_internal_building_times_one_batch"})
    return rows


def performance_rows(docs):
    rows = []
    for variant in ("roofer_lod22_reference", "roofer_lod22_regular", "roofer_lod13_volumes"):
        # Each process measurement is copied onto every building record. Count
        # unique batches, not those repeated references to the same batch.
        batches = {}
        selected = [r for r in docs["roofs"]["runs"] if r["variant"] == variant]
        for run in selected:
            for repeat in run.get("repeats", []):
                key = (repeat.get("run_dir"), repeat.get("repeat_index"))
                batches[key] = repeat
        records = list(batches.values())
        peaks = [r.get("peak_job_commit_bytes") for r in records if finite(r.get("peak_job_commit_bytes"))]
        rows.append({"key": variant, "scope": f"CLI dávka {len(selected)} půdorysů; medián {len(records)} běhů",
                     "wall_seconds": median(r.get("cli_batch_seconds") for r in records),
                     "cpu_seconds": median(r.get("cpu_batch_seconds") for r in records),
                     "peak_commit_bytes": max(peaks) if peaks else None, "peak_working_set_bytes": None})
    outer_names = {"comparison": "Celé porovnání střech", "hypar": "Bazén · celý proces fitu části",
                   "tower_diagnostic": "Věž · celý diagnostický proces"}
    for metrics in docs["roofs"].get("process_metrics", []):
        rows.append({"key": outer_names.get(metrics.get("scope_id"), metrics.get("scope_id", "Vnější proces")),
                     "scope": "Vnější proces včetně přípravy, vyhodnocení a vnořených výpočtů; NESČÍTAT s řádky CLI",
                     "wall_seconds": metrics.get("elapsed_seconds"), "cpu_seconds": metrics.get("cpu_seconds"),
                     "peak_commit_bytes": metrics.get("peak_job_commit_bytes"), "peak_working_set_bytes": None})
    for kind, name, scope in (("arcades", "Podloubí", "Celý proces: 21 modelů, opakování, export a geometrické testy"),
                              ("facades", "Fasády", "Celý proces: 3 fotografie, 9 barevných testů a export; bez ruční rešerše")):
        if kind == "facades":
            resources = docs[kind].get("resources", {})
            metrics = resources.get("guard", {})
        else:
            resources = docs[kind].get("environment", {})
            metrics = docs[kind].get("resource_guard", {})
        rows.append({"key": name, "scope": scope, "wall_seconds": metrics.get("elapsed_seconds"),
                     "cpu_seconds": metrics.get("cpu_seconds"), "peak_commit_bytes": metrics.get("peak_job_commit_bytes"),
                     "peak_working_set_bytes": resources.get("peak_working_set_bytes")})
    return rows


def build_data():
    paths = {kind: DEST / kind / "results.json" for kind in ("roofs", "arcades", "facades")}
    docs = {kind: read(path) for kind, path in paths.items()}
    pilot_path = ROOT / "cities/ceske-budejovice/roof-pilot/results.json"
    pilot_summary = benchmark_summary(read(pilot_path))
    paths["pilot30_results"] = pilot_path
    if not docs["roofs"].get("runs") or not docs["arcades"].get("models") or not docs["facades"].get("buildings"):
        raise ValueError("A measured experiment has no results; no final report was written")
    roof_variants = {"roofer_lod22_reference", "roofer_lod22_regular", "roofer_lod13_volumes"}
    for bid in {r["id"] for r in docs["roofs"]["runs"]}:
        present = {r["variant"] for r in docs["roofs"]["runs"] if r["id"] == bid}
        if not roof_variants <= present:
            raise ValueError(f"Missing a roof variant for {bid}; a recorded failed run is required too")
    for building in docs["facades"]["buildings"]:
        building["gallery_review"] = {
            "status": "review" if building["key"] == "radnice" else "historical_photo_test",
            "message": ("Paleta radnice není připravena k automatickému nasazení. Rozdíl hlavní barvy mezi oblastmi fotografie zůstává velký; potřebuje lepší podklad nebo další ruční ověření."
                        if building["key"] == "radnice" else
                        "Test stability barev jedné historické fotografie. Současný nátěr tím není ověřen."),
            "basis": "facades/README.md; qualitative review after the measured experiment"
        }
        if {r["method"] for r in building["runs"]} != {"single_sample", "lab_median", "lab_trimmed_median"}:
            raise ValueError("Facade comparison is missing a measured method")
    sample_path = ROOT / "cities/ceske-budejovice/roof-pilot/sample.json"
    sample = read(sample_path)
    samples = []
    for feature in sample["features"]:
        samples.append(dict(feature["properties"], id=feature["id"]))
    identities = {b["id"]: b for b in samples}
    all_ids = {r["id"] for r in docs["roofs"]["runs"]}
    all_ids.update(m["building_id"] for m in docs["arcades"]["models"])
    all_ids.update(b["building_id"] for b in docs["facades"]["buildings"])
    if not all_ids <= identities.keys():
        raise ValueError("Experiment contains an identity outside the agreed pilot")
    if len(all_ids) > 20:
        raise ValueError("User's maximum of 20 detailed buildings exceeded")
    arcades = docs["arcades"]
    mesh_inputs = []
    for model in arcades["models"]:
        if not isinstance(model.get("vertices"), list) or not isinstance(model.get("faces"), list):
            mesh_path = resolve_file(model["mesh_path"], DEST / "arcades")
            info = fingerprint(mesh_path)
            if model.get("sha256") and model["sha256"] != info["sha256"]:
                raise ValueError(f"Arcade mesh no longer matches measured result: {mesh_path}")
            mesh = read(mesh_path)
            model["recorded_vertex_count"], model["recorded_face_count"] = model["vertices"], model["faces"]
            model["vertices"], model["faces"] = mesh["vertices"], mesh["faces"]
            model.setdefault("material_groups", mesh.get("material_groups"))
            model.setdefault("coordinate_system", mesh.get("coordinate_system"))
            mesh_inputs.append(info)
        model["name"] = model.get("name") or identities[model["building_id"]]["name"]
        model["variant"] = ("arch" + str(model["arch_segments"])) if model.get("kind") == "arch" else model.get("kind", model["variant_id"])
    image_inputs = []
    for building in docs["facades"]["buildings"]:
        for run in building["runs"]:
            svg = resolve_file(run["svg_path"], DEST / "facades")
            run["svg_data"] = image_data(svg)
            image_inputs.append(fingerprint(svg))
        if building.get("roi_png_path"):
            roi = resolve_file(building["roi_png_path"], DEST / "facades")
            building["roi_data"] = image_data(roi)
            image_inputs.append(fingerprint(roi))
    reviews = {}
    for kind in ("roofs", "arcades", "facades"):
        path = DEST / kind / ("method-review.json" if kind == "roofs" else "source-review.json")
        if path.is_file():
            reviews[kind] = read(path)
            paths[kind + "_research"] = path
        readme_path = DEST / kind / "README.md"
        if readme_path.is_file():
            paths[kind + "_readme"] = readme_path
    for case in reviews.get("roofs", {}).get("photo_review", {}).get("cases", []):
        if case.get("local_reference") and str(case.get("licence", "")).startswith("CC BY"):
            path = resolve_file(case["local_reference"])
            case["image_data"] = image_data(path, preview_size=(1280, 960))
            case["gallery_modifications"] = "Orientační metadata EXIF a zmenšení na náhled nejvýše 1280 × 960 px; původní soubor zůstal beze změny."
            image_inputs.append(fingerprint(path))
    round2_path = DEST / "round-2-candidates.json"
    round2 = read(round2_path) if round2_path.is_file() else None
    if round2 is not None:
        paths["round_2_candidates"] = round2_path
    audit_path = DEST / "roof-heights/results.json"
    height_audit = read(audit_path) if audit_path.is_file() else None
    if height_audit is not None:
        paths["roof_height_audit"] = audit_path
        paths["roof_height_readme"] = DEST / "roof-heights/README.md"
        paths["roof_height_fit_results"] = DEST / "roof-heights/fit-results.json"
        # The separate fit report owns these 72 meshes. Keep their measured
        # metadata here, without duplicating a second interactive mesh gallery.
        for run in height_audit.get("fits", {}).get("runs", []):
            model = run.get("model")
            if not isinstance(model, dict):
                continue
            model["gallery_mesh_counts"] = {key: len(model.get(key, [])) for key in ("vertices", "faces")}
            for key in ("vertices", "faces", "face_semantics"):
                model.pop(key, None)
            model["gallery_geometry_omitted"] = "See roof-heights/fit-report.html and original results.json"
    rebuild_path = DEST / "roof-heights/map-rebuild.json"
    map_rebuild = read(rebuild_path) if rebuild_path.is_file() else None
    if map_rebuild is not None:
        paths["map_rebuild"] = rebuild_path
    parser_audit_path = DEST / "roofs/parser-audit.json"
    parser_audit = read(parser_audit_path) if parser_audit_path.is_file() else None
    if parser_audit is not None:
        paths["parser_audit"] = parser_audit_path
    provenance_path = DEST / "roofs/provenance-audit.json"
    if provenance_path.is_file():
        paths["roof_code_provenance_audit"] = provenance_path
    map_comparison = None
    map_work = ROOT / ".work/.preview/ceske-budejovice"
    before_image = map_work / "revisions/baseline/qa-comparison/na-mlynske-367.png"
    after_image = map_work / "qa/na-mlynske-367.png"
    if map_rebuild and map_rebuild.get("status") == "complete" and before_image.is_file() and after_image.is_file():
        map_comparison = {"label": "Na Mlýnské stoce 367", "before": image_data(before_image),
                          "after": image_data(after_image), "kind": "screenshots_of_actual_rendered_map_tiles",
                          "view": "same_frozen_baseline_anchor_and_zoom_summer_clear_noon", "controls": []}
        image_inputs.extend((fingerprint(before_image), fingerprint(after_image)))
        for key, qa_path in (("before", map_work / "revisions/baseline/qa-comparison/preview-ui.json"),
                             ("after", map_work / "qa/preview-ui.json")):
            if not qa_path.is_file():
                raise FileNotFoundError(f"Missing actual map camera QA record: {qa_path}")
            paths["map_camera_qa_" + key] = qa_path
        for name, label in (("marianske-baara-1810.png", "Mariánské náměstí / Baara 1810"), ("namesti-67.png", "Náměstí Přemysla Otakara II. 67")):
            before = map_work / "revisions/baseline/qa-comparison" / name
            after = map_work / "qa" / name
            if before.is_file() and after.is_file():
                map_comparison["controls"].append({"name": label,
                    "before_href": "../../../" + before.relative_to(ROOT).as_posix(),
                    "after_href": "../../../" + after.relative_to(ROOT).as_posix()})
                image_inputs.extend((fingerprint(before), fingerprint(after)))
    part_path = DEST / "roofs/pool-hypar-part.geojson"
    if part_path.is_file():
        paths["explicit_hypar_part"] = part_path
    protocol = {
        "schema": "cb-experiment-protocol/1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "city": "ceske-budejovice", "scope": "isolated_experiments_not_deployed_to_city_renderer",
        "separate_height_audit_footprints": height_audit.get("sample_count") if height_audit else None,
        "separate_map_policy_rebuild_status": map_rebuild.get("status") if map_rebuild else "not_recorded",
        "pilot_footprints": len(samples), "detailed_footprints": len(all_ids), "maximum_detailed_footprints": 20,
        "building_ids": sorted(all_ids),
        "inputs": [fingerprint(p) for p in paths.values()] + [fingerprint(sample_path)],
        "embedded_images": image_inputs,
        "embedded_meshes": mesh_inputs,
        "comparison_rules": [
            "Stejné souřadnice, měřítko a pohled při porovnání variant jedné budovy.",
            "Párované CB30 mediány používají průnik ID s platnou RMSE u všech tří metod zvlášť pro každý zdroj; původní nepárované mediány a jejich počty zůstávají uvedeny.",
            "Střešní RMSE je shoda se zadrženými body stejného zdroje; není nezávislé zaměření ani ověření typu střechy.",
            "Časy stahování, přípravy, vlastního modelování, exportu a celého procesu se nezaměňují.",
            "CPU čas je součet práce procesorů; elapsed/wall čas zahrnuje i čekání. Chybějící CPU měření se nedopočítává z wall času.",
            "Peak committed memory a peak working set jsou různé veličiny; ponecháváme přesné názvy ze záznamů.",
            "Doložený počet arkád je oddělen od odhadnuté hloubky, výšky, profilů a přesných rozměrů.",
            "Průchodnost je ověřena na vygenerované geometrii; neprokazuje dnešní fyzickou či veřejnou přístupnost místa.",
            "Barevné testy rekonstruují odstíny fotografie, ne kalibrovanou barvu skutečné omítky.",
            "Dvě barevné vektorové vrstvy a generická ostění jsou schéma pro test; nejsou dokumentace skutečných oken.",
            "Výběr je záměrně obtížný, nereprezentuje náhodný vzorek všech domů.",
            "O nasazení na další budovy se rozhodne až podle kompromisu tvaru, jednoduchosti, rychlosti a kontroly zdrojů."
        ],
        "resource_limits": {"project_max_bytes": 20_000_000_000, "min_free_C_bytes": 25_000_000_000,
                            "bulk_ai_processing": False, "parallel_city_renders": False},
        "hardware_and_execution": {
            "processor_identifier": "Intel64 Family 6 Model 154 Stepping 3, GenuineIntel",
            "logical_processors_reported_by_environment": 16,
            "physical_memory_bytes_GlobalMemoryStatusEx": 16_863_059_968,
            "guard_job_affinity_max_logical_processors": 2,
            "normal_benchmark_OMP_BLAS_threads": 1,
            "basic_preview_threads": 2,
            "priority": "below_normal",
            "commercial_CPU_model": None,
            "not_an_isolated_lab_machine": True,
            "wall_time_context": "Běžný počítač uživatele; souběh uživatelských procesů a některých lehkých agentových úloh."
        },
        "method_families": {
            "roofs": "Roofer LoD2.2 default / regularizace / LoD1.3 výškové objemy; stejné trénovací body a holdout.",
            "arcades": "Plný objem / pilíře s překladem / oblouky 8 a 16 segmentů; hloubky 2 a 3,5 m jako scénáře.",
            "facades": "Jednotlivý vzorek / Lab medián / ořezaný Lab medián; ručně vymezené oblasti hlavní omítky a dekoru.",
            "pool_hypar": "Šestiparametrová kvadratická sedlová plocha pouze na explicitně vymezené části hlavní haly; jiná hodnoticí oblast než celý areál.",
            "tower_diagnostic": "Samostatný diagnostický Roofer běh po vypnutí vyřazování nedostatečných dat. Původní selhání se nepřepisuje; vznik meshe není ověřená oprava a výstup není určen k nasazení."
        },
        "result_counts": {"roof_runs": len(docs["roofs"]["runs"]), "arcade_models": len(arcades["models"]),
                          "roof_primary_runs": sum(r["variant"] in {"roofer_lod22_reference", "roofer_lod22_regular", "roofer_lod13_volumes"} for r in docs["roofs"]["runs"]),
                          "roof_extra_runs": sum(r["variant"] not in {"roofer_lod22_reference", "roofer_lod22_regular", "roofer_lod13_volumes"} for r in docs["roofs"]["runs"]),
                          "facade_buildings": len(docs["facades"]["buildings"])}
    }
    return serializable({"created_at": protocol["created_at"], "samples": samples, "protocol": protocol,
                         "roofs": docs["roofs"], "arcades": arcades, "facades": docs["facades"],
                         "research": reviews, "round2": round2, "height_audit": height_audit, "map_rebuild": map_rebuild,
                         "map_comparison": map_comparison,
                         "parser_audit": parser_audit,
                         "roof_summary": summary_rows(docs["roofs"]["runs"]),
                         "roof_pairwise": roof_pairwise(docs["roofs"]["runs"]),
                         "performance": performance_rows(docs), "pilot30_summary": pilot_summary})


HTML = r'''<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>České Budějovice · testy modelů</title><style>
:root{--ink:#203831;--muted:#5a6f66;--line:#d9e1d9;--paper:#fafbf7;--green:#215c48;--warm:#ad653c}*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}main{max-width:1520px;margin:auto;padding:40px 30px}h1{font-size:clamp(28px,3.5vw,45px);line-height:1.15;margin:10px 0 18px;letter-spacing:-.04em}h2{font-size:25px;line-height:1.2;margin:0 0 14px}h3{font-size:17px;margin:0}p{max-width:1000px;margin:9px 0}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.14em;color:var(--green)}.lede{font-size:18px;max-width:980px}.meta,.small{overflow-wrap:anywhere;font-size:12px;color:var(--muted)}nav{display:flex;flex-wrap:wrap;gap:9px;margin:24px 0}nav a,button{color:var(--green);background:#edf2ea;border:1px solid var(--line);border-radius:6px;padding:9px 14px;text-decoration:none;font:inherit;cursor:pointer}a{color:var(--green)}section{margin-top:32px;padding-top:28px;border-top:1px solid var(--line)}.notice{background:#fff4dd;border-left:4px solid #d19a3f;padding:12px 16px;border-radius:4px;max-width:none}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}.stat{padding:15px 18px;background:#eef2e9;border-radius:8px}.stat strong{display:block;font-size:29px;line-height:1.2}.stat span{color:var(--muted);font-size:12px}.controls{display:flex;gap:20px;flex-wrap:wrap;align-items:end;margin:20px 0 12px}.control{min-width:0;display:flex;flex-direction:column;gap:5px;flex:1 1 180px}.control.wide{flex:3 1 360px}label{font-size:12px;font-weight:650}select{width:100%;min-height:40px;border:1px solid var(--line);border-radius:5px;padding:8px;background:white;color:var(--ink);font:inherit}input[type=range]{width:100%;accent-color:var(--green);min-height:24px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:18px}.grid.arcades{grid-template-columns:repeat(4,minmax(0,1fr))}.card{min-width:0;border:1px solid var(--line);border-radius:9px;overflow:hidden;background:white}.head{display:flex;justify-content:space-between;gap:9px;padding:15px 16px;align-items:start}.badge{font-size:10px;padding:3px 6px;border-radius:4px;background:#e5eee1;white-space:nowrap}.badge.bad{background:#f8e5cd}.badge.critical{background:#fbe0dc;color:#8a2d22}.critical-note{background:#fff0ed;color:#8a2d22;border-left:3px solid #a34332;padding:10px}.view{position:relative;height:310px;background:linear-gradient(#f3f5f0,#e9eee5)}canvas{width:100%;height:100%;display:block}.empty{position:absolute;inset:0;display:grid;place-items:center;color:var(--muted);font-size:13px}.card-data{padding:12px 16px;font-size:12px}.values{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px 10px}.values span{display:block;color:var(--muted);font-size:10px}.values b{font-weight:600;overflow-wrap:anywhere}.warn{color:#94572e}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:11px;color:var(--muted);background:#eff3eb;white-space:nowrap}tbody tr:hover{background:#f1f4ed}details{margin:14px 0}summary{cursor:pointer;font-weight:600;font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f3ed;border:1px solid var(--line);padding:15px;border-radius:5px;font-size:11px;max-height:520px;overflow:auto}.facade-view{background:#eef1e9;min-height:310px;display:grid;place-items:center;padding:12px}.facade-view img{display:block;width:100%;height:300px;object-fit:contain}.swatches{display:flex;gap:12px;margin:12px 0}.swatch{display:flex;gap:8px;align-items:center;font-size:12px}.color{display:block;width:32px;height:32px;border:1px solid #0002;border-radius:4px}.reference{display:grid;grid-template-columns:minmax(240px,440px) minmax(0,1fr);gap:20px;margin-top:20px}.reference img{max-width:100%;max-height:650px;object-fit:contain;background:white}.refs{padding-left:20px}.refs li{margin:8px 0;overflow-wrap:anywhere}.map-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}.map-pair img{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:6px}.comparison{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.comparison article{padding:16px;background:#eef2e9;border-radius:7px}.comparison p{font-size:13px}.row-note{font-size:12px;margin-top:15px}.foot{margin-top:32px;padding-top:20px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}@media(max-width:1100px){.grid.arcades{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){main{padding:25px 15px}.stats{grid-template-columns:repeat(2,1fr)}.grid,.grid.arcades,.comparison,.reference,.map-pair{grid-template-columns:1fr}.control.wide{flex-basis:100%}.view{height:350px}.lede{font-size:16px}.head{padding:12px}}
</style></head><body><main>
<header><div class="eyebrow">Izomapa · srovnávací experimenty</div><h1>České Budějovice: od objemu k detailu</h1><p class="lede">Výškový audit našel konkrétní příčinu příliš vysoké fasády: známou sedlovou střechu přepisovalo pravidlo pro vysoké domy na plochou. Další měření ukazují, kde stačí jednoduchá střecha a kde je potřeba rozdělit dům na části.</p><p class="meta" id="created"></p><div class="stats"><div class="stat"><strong id="pilot-count"></strong><span>půdorysů v základním pilotu</span></div><div class="stat"><strong id="detail-count"></strong><span>objektů v detailních testech (limit 20)</span></div><div class="stat"><strong id="arcade-count"></strong><span>domy s testem podloubí</span></div><div class="stat"><strong id="facade-count"></strong><span>fasády s barevným testem</span></div></div>
<p class="notice">Podrobné testy 18 střech, podloubí a fasád nejsou nasazené do městské mapy. Samostatnou opravu pravidla pro střechy dokládá sekce mapového preview níže. Barvy, odhadnuté rozměry arkád a jednoduchá ostění nejsou zaměřená dokumentace.</p><nav><a href="roof-components/report.html">Nové: věrnost, věžičky a objemy ↗</a><a href="roof-simplification/report.html">Nové: jednodušší střechy 6 objektů ↗</a><a href="#roofs">Střechy a objemy</a><a href="#height-audit">Audit výšek</a><a href="#arcades">Podloubí</a><a href="#facades">Fasády</a><a href="#protocol">Protokol a zdroje</a><a id="round2-nav" href="#round2">Druhé kolo</a><a href="../roof-pilot/report.html">Základní pilot 30 půdorysů ↗</a></nav></header>
<section id="height-findings"><h2>Proč některé fasády působily příliš vysoké</h2><div class="comparison" id="height-finding-cards"></div><p class="notice">Počet řad oken je další samostatný problém: styl 1 opakuje pásy po 2,8 m bez znalosti skutečných podlaží a podkroví. Ani správná střecha proto sama neopraví členění fasády.</p><p class="small">Výšky fitu jsou vrcholy modelu nad odhadnutým terénem, nikoli zaměřená římsa. Holdout kontroluje jiné body stejného zdroje, ne nezávislé geodetické zaměření. Neznámé střechy kolem obou náměstí dál vyžadují místní výběr a kontrolu; nejde o plošnou opravu všech domů.</p><p><a href="roof-heights/fit-report.html">Otočné porovnání 12 auditních případů ↗</a> · <a href="#height-audit">Podrobnosti a kontrola kvality</a></p></section>
<section id="map-versions"><h2>Mapové preview a stav nasazení</h2><p id="map-status"></p><p id="map-scope" class="small"></p><p id="map-links"><a href="../../../.work/.preview/ceske-budejovice/revisions/baseline/site/">Původní základní mapa</a> · <a href="../../../.work/.preview/ceske-budejovice/site/">Mapa po opravě pravidla pro střechy</a></p><p class="small">Galerii lze otevřít přímo jako soubor. Pro interaktivní mapu spusťte dvojklikem <a href="../otevrit-nahled.cmd">otevrit-nahled.cmd</a> v nadřazené složce města a okno terminálu nechte otevřené. Spouštěč otevře místní přehled a mapu; nic nestahuje.</p><p class="small">Oprava pravidla pro výšku stěn a zachování doloženého typu střechy je odlišná od detailních experimentů níže: varianty Rooferu, nové arkády a barevné fasády se tímto do mapy automaticky nepřenášejí.</p><div id="map-pair-section"><h3>Na Mlýnské stoce 367 · skutečné dlaždice před a po</h3><p class="small">Shodný střed kamery podle archivovaného bodu původní mapy i shodné přiblížení; léto, jasno a poledne. Jde o skutečný výstup městského rendereru po opravě pravidla, nikoli o níže uvedený experimentální fit.</p><div class="map-pair"><div><p><strong>Před opravou pravidla</strong></p><img id="map-before" alt="Původní mapové dlaždice domu Na Mlýnské stoce 367"></div><div><p><strong>Po opravě pravidla</strong></p><img id="map-after" alt="Nové mapové dlaždice téhož domu po opravě pravidla"></div></div><p class="small" id="map-control-links"></p><p class="small">Ověření kamery a překryvů: <a href="../../../.work/.preview/ceske-budejovice/revisions/baseline/qa-comparison/preview-ui.json">původní mapa</a> · <a href="../../../.work/.preview/ceske-budejovice/qa/preview-ui.json">nová mapa</a>.</p></div><details><summary>Záznam přegenerování mapy</summary><pre id="map-rebuild-details"></pre></details></section><section id="decision"><h2>Co z porovnání vybírat</h2><div class="comparison"><article><h3>Střechy</h3><p id="roof-conclusion"></p><p>Vedle chyby výšky kontrolovat hlavní hřeben, počet objemů a rozpoznatelnost stavby. Více trojúhelníků samo o sobě nepřináší lepší model.</p></article><article><h3>Podloubí</h3><p id="arcade-conclusion"></p><p>Fotografie dokládá otvory. Hloubka a výška jsou zde explicitní scénáře; letecké body samy prostor pod střechou spolehlivě nedoloží.</p></article><article><h3>Fasády</h3><p>Ruční výběr čistých ploch je nutnou součástí těchto testů. Medián omezuje vliv jednotlivých pixelů, neodstraňuje barevný nádech osvětlení.</p><p>Paletu přenášet jako přibližný vzhled; historickou fotografii nevydávat za potvrzení dnešního nátěru.</p></article></div></section>
<section id="pilot30"><h2>Základní pilot · 30 půdorysů</h2><p>Výchozí aproximace rendereru, parametrické šablony a Roofer na dvou zdrojích ČÚZK. Párovaný sloupec porovnává stejná ID budov napříč třemi metodami každého zdroje; původní nepárované hodnoty zůstávají vedle něj.</p><div class="table-wrap"><table><thead><tr><th>Zdroj</th><th>Metoda</th><th>Modely</th><th>RMSE · všechny platné</th><th>RMSE · stejná kohorta</th><th>Součet modelovacích časů</th></tr></thead><tbody id="pilot30-summary"></tbody></table></div><p class="small">Modely zahrnují náhradní objemy. Počet platných chyb se může lišit od počtu modelů. Základ a šablony: součet mediánů tří opakování na budovu; Roofer: součet interních časů jednoho běhu. Stahování, načtení a procesní režie jsou oddělené v <a href="../roof-pilot/report.html">úplném pilotním reportu</a>. Epochy obou zdrojů se nemusí shodovat.</p><details><summary>Párované kohorty a přesné souhrnné hodnoty</summary><pre id="pilot30-details"></pre></details></section><section id="roofs"><h2>1 · Střechy a jednoduché objemy</h2><p>Porovnání rekonstrukce LoD2.2, silnější regularizace a výškových objemů LoD1.3. Všechny varianty používají stejné vstupní body. LoD1.3 záměrně nahrazuje skloněné střechy vodorovnými úrovněmi.</p><div id="roof-warnings"></div><details><summary>Audit převodu nativních ploch do zobrazené triangulace</summary><p class="small">Vynechané nebo neplatné plochy se zaznamenávají odděleně od výškové shody. <a href="roofs/parser-audit.json">Původní audit převodu</a>.</p><pre id="parser-audit-details"></pre></details><div class="table-wrap"><table><thead><tr><th>Varianta</th><th>Modely</th><th>Z toho náhradní</th><th>Medián RMSE</th><th>RMSE společných bodů</th><th>Pokrytí</th><th>Nativní střešní plochy</th><th>Medián trojúhelníků</th><th>Medián JSON</th></tr></thead><tbody id="roof-summary"></tbody></table></div><p class="small">Počet modelů znamená existenci vykreslitelné geometrie; zahrnuje náhradní objemy a neúplné převody. Úplnost a typ střechy je nutné posoudit podle varování u každé karty. RMSE měří shodu s odloženými body stejného zdroje. Souhrny mají vždy jinou roli než vizuální ověření skutečné střechy. U tří profilů Rooferu se zobrazuje geometrie a chyba prvního běhu; časy jsou mediány dostupných opakování a jejich počet je uveden u modelu.</p>
<h3>Párovaná změna každé budovy vůči výchozímu LoD2.2</h3><div class="table-wrap"><table><thead><tr><th>Varianta</th><th>Stejné objekty</th><th>Lepší / horší / stejné RMSE</th><th>Medián změny RMSE</th><th>Plochy: součet před → po</th><th>Medián změny počtu ploch</th></tr></thead><tbody id="roof-pairwise"></tbody></table></div><p class="small">Záporná změna RMSE znamená lepší shodu. Porovnávají se stejné body stejné budovy; rovnost má toleranci 0,000001 m. Samostatné mediány v horní tabulce nejsou mediánem změn a mohou zakrýt zhoršení většiny objektů.</p><details><summary>Jednotlivé párované změny včetně největšího zhoršení</summary><pre id="roof-pairwise-details"></pre></details><div class="controls"><div class="control wide"><label for="roof-building">Budova</label><select id="roof-building"></select></div><div class="control"><label for="roof-rotation">Otočení <span id="roof-angle"></span></label><input id="roof-rotation" type="range" min="0" max="360" value="35"></div><div class="control"><label for="roof-tilt">Pohled shora / z ulice</label><input id="roof-tilt" type="range" min="15" max="88" value="60"></div></div><p class="meta" id="roof-meta"></p><div class="grid" id="roof-models"></div><p class="small">Měřítko i kamera jsou společné. Výšky nejsou zveličené; barvy pouze rozlišují typ ploch.</p><div class="reference" id="roof-reference"><div><img id="roof-photo" alt="Referenční fotografie pro vizuální posouzení tvaru střechy"><p class="small" id="roof-photo-attribution"></p></div><div><h3>Fotografická kontrola rozpoznatelných znaků</h3><p id="roof-observed"></p><p id="roof-photo-limits" class="small"></p><p id="roof-photo-comparison" class="small"></p></div></div><p id="roof-no-photo" class="small"></p><details><summary>Parametry, opakování a úplné metriky vybrané budovy</summary><pre id="roof-details"></pre></details></section>
<section id="height-audit"><h2>Samostatná diagnostika · vysoké ploché domy</h2><p>Audit okolí Mariánského náměstí a náměstí Přemysla Otakara II. rozlišuje výšku stěny, střešní objem a podlaží v podkroví. Hledá příčinu případů, kdy se například tři běžná a dvě podkrovní podlaží mohou změnit v příliš vysoký hranol.</p><p class="notice">Jde o samostatný diagnostický vzorek. Není přičten k původním 30 půdorysům ani k detailnímu porovnání 18 objektů. Záznam chyby sám o sobě neznamená, že byla celá mapa opravena.</p><p><a href="roof-heights/README.md">Výsledky a vysvětlení auditu</a> · <a href="roof-heights/results.json">Naměřené údaje</a> · <a href="roof-heights/fit-report.html">12 případů × 6 porovnání</a></p><p id="height-quality" class="notice"></p><p id="height-audit-status" class="small"></p><div class="table-wrap"><table><thead><tr><th>Případ změněný pravidlem</th><th>Před: stěna + střecha</th><th>Po: stěna + střecha</th><th>Stav</th></tr></thead><tbody id="height-audit-rows"></tbody></table></div><p class="small">Tabulka používá zachycenou scénu nového preview, je-li k dispozici; původní izolovaný test zůstává v úplném záznamu. Skutečné dlaždice dokládá sekce mapového preview výše. Pásy oken ve vykreslování nejsou údaj o skutečném počtu podlaží. Ostatní diagnostické objekty nejsou automaticky označeny za chybné.</p><details><summary>Úplný diagnostický záznam</summary><pre id="height-audit-details"></pre></details></section><section id="arcades"><h2>2 · Podloubí jako skutečný otvor</h2><p>Plný objem je srovnávací základ. Ve variantách podloubí chybí přední přízemní pás a zůstávají pilíře, překlady nebo segmentované oblouky. Geometrický test ověřuje průchod otvorem a kolizi s pilířem.</p><div class="controls"><div class="control wide"><label for="arcade-building">Dům v Krajinské</label><select id="arcade-building"></select></div><div class="control"><label for="arcade-depth">Odhadnutá hloubka</label><select id="arcade-depth"><option value="2">2,0 m</option><option value="3.5">3,5 m</option></select></div><div class="control"><label for="arcade-rotation">Otočení <span id="arcade-angle"></span></label><input id="arcade-rotation" type="range" min="0" max="360" value="0"></div><div class="control"><label for="arcade-tilt">Pohled shora / z ulice</label><input id="arcade-tilt" type="range" min="15" max="88" value="80"></div></div><p><label><input id="arcade-closeup" type="checkbox" checked> Detail přízemí (ořez pohledu, geometrie se nemění)</label></p><p class="meta" id="arcade-meta"></p><div class="grid arcades" id="arcade-models"></div><p id="arcade-photo-reference" class="small"></p><p class="small">Přepínání hloubky ukazuje nejistotu měření. Zadní objem je v diagramu tmavší pro čitelnost otvorů; nejde o naměřené barvy fasády. Test neověřuje aktuální veřejnou přístupnost prostoru ani vlastnictví.</p><details><summary>Předpoklady, časy a testy průchodnosti</summary><pre id="arcade-details"></pre></details></section>
<section id="facades"><h2>3 · Dvě barvy a jednoduché členění fasády</h2><p>Stejná fotografie a ručně vybrané oblasti pro tři postupy výpočtu palety. Dva odstíny určují hlavní plochu a světlé členění. Rozvrh vektorového průčelí je záměrně schematický, bez tvrzení o skutečných rozměrech a tvarech oken.</p><p class="notice">Čas ručního hledání fotografií a vymezování oblastí nebyl měřen. Milisekundové časy níže popisují samotný výpočet barev, nikoli celkovou pracnost jednoho domu.</p><p id="facade-review" class="notice"></p><p class="small">Plochy pro výpočet byly při vizuální kontrole zpřesňovány. <a href="facades/README.md">Audit oprav a starších běhů</a> výslovně uvádí také nezachovaný první průzkumný výstup; jeho chybějící hodnoty nejsou doplněny odhadem.</p><div class="controls"><div class="control wide"><label for="facade-building">Fasáda</label><select id="facade-building"></select></div></div><p class="meta" id="facade-meta"></p><div class="grid" id="facade-models"></div><div class="reference"><div><img id="roi-photo" alt="Referenční fotografie s vyznačenými oblastmi pro výpočet barev"><p class="small" id="photo-attribution"></p></div><div><h3>Co lze a nelze vyčíst</h3><ul id="facade-limits"></ul><p class="small">ΔE76 vůči vyhrazeným oblastem téže fotografie je diagnostika stability barvy v obraze. Není to chyba vůči fyzicky změřené omítce.</p><details><summary>Masky, barvy, časy a diagnostika</summary><pre id="facade-details"></pre></details></div></div></section>
<section id="round2"><h2>Kandidáti pro druhé kolo · dosud netestováno</h2><p class="notice">Tento seznam rozšiřuje další plán, ne aktuální měření. Kandidáti nejsou součástí třiceti půdorysů ani počtu detailních experimentů výše. U Slavie je nutné rozlišit stav před obnovou a po obnově; starší bodové mračno nedokládá nové detaily.</p><p><a href="round-2-README.md">Podklady pro výběr druhého kola</a> · <a href="round-2-candidates.json">Úplný seznam kandidátů</a></p><div class="table-wrap"><table><thead><tr><th>Kandidát</th><th>Zaměření dalšího testu</th><th>Stav podkladů / časová nejistota</th></tr></thead><tbody id="round2-list"></tbody></table></div><details><summary>Manifest druhého kola</summary><pre id="round2-details"></pre></details></section><section id="protocol"><h2>Protokol, výkon a podklady</h2><p>Všechny výsledky vznikly lokálními skripty. Časy mají v záznamech rozsah měření: vlastní metoda, export, načtení nebo celý proces. Paměťová čísla se nepovažují za zaměnitelná — commit a rezidentní pracovní sada jsou odlišné veličiny.</p><h3>Procesní náklady</h3><div class="table-wrap"><table><thead><tr><th>Experiment</th><th>Rozsah měření</th><th>Wall čas</th><th>CPU čas</th><th>Špička commit</th><th>Špička pracovní sady</th></tr></thead><tbody id="performance"></tbody></table></div><p class="small">Vnější procesy už obsahují vnořené CLI dávky; jejich časy ani CPU nesčítejte. Řádky podloubí a fasád měří jiné pracovní úseky než střešní CLI dávky; nejde o vzájemný rychlostní žebříček. Chybějící údaj je ponechán prázdný. Paměťové špičky jsou maxima, časy dávkových opakování mediány. Wall je skutečně uplynulý čas procesu; CPU je součet práce jeho procesorů. Commit znamená paměť se zajištěným krytím v RAM nebo stránkovacím souboru, pracovní sada je právě rezidentní paměť.</p><p class="small">Provenance detailního střešního testu: devět hlavních dávek zachovává kontrolní součty trénovacích dat a půdorysů, nativní výstupy, příkaz a verzi Rooferu. Chybí však snímek přesného Python wrapperu při spuštění. Dodatečný SHA aktuálního skriptu tuto mezeru nenahrazuje. Kontrolní součty tohoto přehledu zachycují vstupní soubory při sestavení galerie.</p><ul id="rules"></ul><details><summary>Úplný protokol a kontrolní součty vstupů</summary><pre id="protocol-details"></pre></details><details><summary>Procesní metriky střech</summary><pre id="roof-process"></pre></details><details><summary>Procesní metriky podloubí</summary><pre id="arcade-process"></pre></details><details><summary>Procesní metriky fasád</summary><pre id="facade-process"></pre></details><p><a href="roofs/README.md">Metody a výsledky střech</a> · <a href="roofs/provenance-audit.json">Audit provenance kódu</a> · <a href="roofs/parser-audit.json">Vynechané plochy při převodu</a> · <a href="arcades/README.md">Protokol podloubí</a> · <a href="facades/README.md">Protokol fasád a historie ROI</a></p><h3>Ověřované primární zdroje a fotografie</h3><ul class="refs" id="references"></ul><details><summary>Úplné rešerše a licence</summary><pre id="research-details"></pre></details></section>
<footer class="foot"><p><a href="../../velesin/roof-pilot/report.html">První srovnávací pilot ve Velešíně</a> · <a href="../roof-pilot/report.html">České Budějovice: 30 půdorysů a dva bodové zdroje</a></p>Samostatná HTML galerie funguje bez síťových požadavků. Žádná zobrazená varianta se tímto dokumentem automaticky nenasazuje do městské mapy. Fotografie a odvozené výřezy zachovávají uvedené autory a licence.</footer>
</main><script type="application/json" id="experiment-data">__DATA__</script><script>
'use strict';
const D=JSON.parse(document.getElementById('experiment-data').textContent),$=id=>document.getElementById(id);
const names={roofer_tower_allow_insufficient:'Věž · diagnostika, nepoužít',templates:'Parametrické šablony',roofer:'Roofer',flat:'plochá',gabled:'sedlová',hypar_explicit_part:'Sedlová plocha · pouze vybraná část',roofer_lod22_reference:'LoD2.2 · výchozí',roofer_lod22_regular:'LoD2.2 · jednodušší',roofer_lod13_volumes:'LoD1.3 · výškové objemy',baseline:'Plný objem',pillars_lintel:'Pilíře a překlad',arch8:'Oblouk · 8 segmentů',arch16:'Oblouk · 16 segmentů',single_sample:'Jeden vzorek',lab_median:'Lab medián',lab_trimmed_median:'Ořezaný Lab medián'};
const num=(v,n=2)=>Number.isFinite(v)?v.toLocaleString('cs-CZ',{maximumFractionDigits:n,minimumFractionDigits:n}):'—',secs=v=>Number.isFinite(v)?num(v,v<.01?5:v<1?3:2)+' s':'—',bytes=v=>Number.isFinite(v)?(v>1e6?num(v/1e6)+' MB':num(v/1e3,1)+' kB'):'—',pct=v=>Number.isFinite(v)?num(v*100,1)+' %':'—';
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function compact(v){if(Array.isArray(v))return v.map(compact);if(v&&typeof v==='object'){const o={};for(const[k,x]of Object.entries(v))if(!['vertices','faces','face_semantics','svg_data','roi_data','image_data'].includes(k))o[k]=compact(x);return o;}return v;}
function values(parent,items){const d=el('div',undefined,'values');for(const [name,value]of items){const x=el('div');x.append(el('span',name),el('b',value));d.append(x);}parent.append(d);}
function option(select,id,label){const o=el('option',label);o.value=id;select.append(o);}
function json(id,v){$(id).textContent=JSON.stringify(compact(v),null,2);}
const mapComplete=D.map_rebuild?.status==='complete';$('map-links').hidden=!mapComplete;$('map-status').textContent=mapComplete?'Oprava pravidla pro střechy je aplikována v novém preview. Původní mapa je zachována pro porovnání.':'Přegenerování mapy není v této verzi protokolu doloženo jako dokončené. Zatím rozlišujte připravený patch, diagnostiku a skutečný render.';const sceneDiff=D.height_audit?.whole_scene_diff;if(mapComplete&&sceneDiff)$('map-scope').textContent='Porovnání celé scény: změnilo se '+sceneDiff.changed_unique_overture_ids+' z '+sceneDiff.after_unique_overture_ids+' identifikátorů budov ('+sceneDiff.changed_parts+' z '+sceneDiff.after_parts+' modelovaných částí). '+(sceneDiff.roof_shape_transitions_unique_overture_ids?.['flat->gabled']||0)+' střech přešlo z ploché na sedlovou a '+(sceneDiff.roof_shape_transitions_unique_overture_ids?.['flat->hipped']||0)+' na valbovou. Jde o konzervativní opravu pravidla, nikoli o nasazení detailních fitů či plošné doplnění neznámých střech.';json('map-rebuild-details',D.map_rebuild||{status:'not_recorded'});$('map-pair-section').hidden=!D.map_comparison;if(D.map_comparison){$('map-before').src=D.map_comparison.before;$('map-after').src=D.map_comparison.after;const controls=$('map-control-links');controls.append(document.createTextNode('Kontrolní budovy s konzervativně zachovanou geometrií: '));for(const c of D.map_comparison.controls){const before=el('a',c.name+' · před'),after=el('a','po');before.href=c.before_href;after.href=c.after_href;before.target=after.target='_blank';before.rel=after.rel='noopener';controls.append(before,document.createTextNode(' / '),after,document.createTextNode(' · '));}}$('created').textContent='Vytvořeno '+new Date(D.created_at).toLocaleString('cs-CZ',{timeZone:'Europe/Prague'})+' · místní čas Praha';
$('pilot-count').textContent=D.protocol.pilot_footprints;$('detail-count').textContent=D.protocol.detailed_footprints;
$('arcade-count').textContent=new Set(D.arcades.models.map(m=>m.building_id)).size;$('facade-count').textContent=D.facades.buildings.length;
if(D.roofs.status!=='complete')$('roof-warnings').append(el('p','Střešní experiment má stav '+(D.roofs.status||'neuvedeno')+'. Počet dokončených opakování a případná selhání jsou uvedeny v metrikách.','notice'));if(D.roofs.repetition_plan_completed===false)$('roof-warnings').append(el('p','Všechny základní profily mohou mít výsledek, ale plán tří opakování není úplný. Rozhodující jsou počty opakování u jednotlivých variant.','notice'));for(const warning of D.roofs.warnings||[])$('roof-warnings').append(el('p',typeof warning==='string'?warning:JSON.stringify(warning),'notice'));json('pilot30-details',D.pilot30_summary);for(const r of D.pilot30_summary){const row=el('tr');for(const value of [r.source==='dmpok'?'DMP OK':'DMP 1G',r.method==='baseline'?'Základní aproximace':r.method==='templates'?'Parametrické šablony':'Roofer',r.models+' / '+r.expected,num(r.median_rmse_m)+' m (n='+r.rmse_n+')',num(r.paired_median_rmse_m)+' m (n='+r.paired_n+')',secs(r.model_time_sum_seconds)])row.append(el('td',value));$('pilot30-summary').append(row);}for(const r of D.roof_summary){const tr=el('tr');for(const v of [names[r.variant]||r.variant,r.models+' / '+r.expected,num(r.fallback_models,0),num(r.median_rmse_m)+' m',num(r.median_common_rmse_m)+' m',pct(r.median_coverage),num(r.median_native_roof_surfaces,0),num(r.median_triangles,0),bytes(r.median_bytes)])tr.append(el('td',v));$('roof-summary').append(tr);}
const ref=D.roof_summary.find(r=>r.variant==='roofer_lod22_reference'),reg=D.roof_summary.find(r=>r.variant==='roofer_lod22_regular');
const paired=D.roof_pairwise.find(r=>r.variant==='roofer_lod22_regular');$('roof-conclusion').textContent=paired?'Regularizace snížila součet nativních střešních ploch na stejné kohortě '+num(paired.sum_native_surfaces_before,0)+' → '+num(paired.sum_native_surfaces_after,0)+'. U '+paired.n+' společných objektů má '+paired.improved+' lepší, '+paired.worse+' horší a '+paired.unchanged+' stejné RMSE; medián párované změny je '+(paired.median_delta_m>0?'+':'')+num(paired.median_delta_m,3)+' m.':'Párované výsledky zatím nejsou k dispozici.';
for(const r of D.roof_pairwise){const row=el('tr');for(const value of [names[r.variant]||r.variant,num(r.n,0),r.improved+' / '+r.worse+' / '+r.unchanged,(r.median_delta_m>0?'+':'')+num(r.median_delta_m,3)+' m',num(r.sum_native_surfaces_before,0)+' → '+num(r.sum_native_surfaces_after,0),num(r.median_native_roof_surface_delta,0)])row.append(el('td',value));$('roof-pairwise').append(row);}json('roof-pairwise-details',D.roof_pairwise);const passed=D.arcades.models.filter(m=>m.tests?.all_passed===true).length;
$('arcade-conclusion').textContent=passed+' z '+D.arcades.models.length+' modelů prošlo všemi zapsanými geometrickými testy včetně očekávaného chování plného objemu. Počet segmentů porovnávejte i podle úhlu pohledu a velikosti na mapě.';
const viewers={};
function meshView(prefix,runs){const container=$(prefix+'-models');container.replaceChildren();const cards=[];for(const run of runs){const model=run.model||run,card=el('article',undefined,'card'),head=el('div',undefined,'head'),title=prefix==='arcade'&&run.kind==='baseline'?'Plný objem':names[run.variant||run.kind]||run.variant||run.kind||run.variant_id;head.append(el('h3',title));const valid=Array.isArray(model.vertices)&&model.vertices.length&&Array.isArray(model.faces)&&model.faces.length;const auditFindings=prefix==='roof'?(D.parser_audit?.skipped_surfaces||[]).filter(a=>a.id===run.id&&a.variant===run.variant):[],roofGap=auditFindings.some(a=>a.semantic==='RoofSurface');const mode=model.attributes?.rf_extrusion_mode??model.metrics?.roofer_extrusion_mode,fallback=prefix==='roof'&&mode&&mode!=='standard';const tag=el('span',valid?(run.diagnostic_only?'Diagnostika · nepoužít':roofGap?'Nekompletní střecha':fallback?'Náhradní objem':'Model'):'Bez geometrie','badge'+(run.diagnostic_only?' critical':valid&&!fallback&&!roofGap?'':' bad'));head.append(tag);const view=el('div',undefined,'view'),canvas=el('canvas');canvas.setAttribute('aria-label',title);view.append(canvas);if(!valid)view.append(el('div','Model nebyl vytvořen','empty'));const data=el('div',undefined,'card-data');const met=run.metrics||{},tim=run.timing||{};if(prefix==='roof'){values(data,[['RMSE',num(met.holdout_rmse_m)+' m'],['Pokrytí',pct(met.coverage_fraction??met.holdout_coverage)],['Trojúhelníky',num(model.faces?.length,0)],['Vrcholů',num(met.used_vertex_count??model.vertices?.length,0)],['Nativní střešní plochy',num(met.native_roof_surface_count,0)],['Objemy CityJSON',num(met.cityjson_solid_count,0)],['JSON modelu',bytes(met.model_json_bytes)],['Čas metody',secs(tim.median_seconds??tim.median_internal_seconds??run.elapsed_seconds)],['Dokončená opakování',num(tim.completed_repeats??run.repeats?.length,0)]]);if(fallback)data.append(el('p','Roofer použil '+mode+'. Tuto geometrii nelze považovat za úspěšnou rekonstrukci požadovaného detailu střechy.','warn'));const lod=model.lods||[];if(lod.length)data.append(el('p','LoD '+lod.join(', '),'small'));}else{values(data,[['Generace · medián 3',secs(tim.median_seconds)],['Trojúhelníky',num(model.faces?.length,0)],['Vrcholů',num(model.vertices?.length,0)],['JSON modelu',bytes(run.bytes)],['Hloubka scénáře',Number.isFinite(run.depth_m)?num(run.depth_m,1)+' m':'—'],['Geometrické testy',run.tests?.all_passed===true?'Prošly':run.tests?.all_passed===false?'Selhání':'Neuvedeno']]);}
for(const a of auditFindings)data.append(el('p','Převod vynechal '+a.semantic+'; projekční výpočet plochy '+num(a.projected_area_m2,2)+' m². '+a.error+'. Nativní geometrie ani parser nebyly tímto přehledem opraveny.',a.semantic==='RoofSurface'?'critical-note':'warn'));if(run.diagnostic_only)data.append(el('p','NEPOUŽÍT jako opravu věže: vznikl mesh po vypnutí vyřazování nedostatečných dat, ale jeho shoda s externím holdoutem je velmi slabá. RMSE '+num(met.holdout_rmse_m,3)+' m versus interní hodnota Rooferu '+num(met.roofer_reported_rmse_lod22_m,3)+' m. Příčina rozdílu není tímto testem prokázána. Původní tři profily zůstávají bez geometrie.','critical-note'));if(run.variant==='hypar_explicit_part')data.append(el('p','Pouze explicitně vymezená část střechy. RMSE a pokrytí se nevztahují k celému areálu ani se přímo nesrovnávají s ostatními kartami.','warn'));if(run.repeat_geometry_identical===false)data.append(el('p','Geometrie se mezi opakováními liší; zobrazen je první zaznamenaný model.','warn'));if(run.error)data.append(el('p',run.error,'warn'));const warnings=[...(run.warnings||[]),...(model.warnings||[])];if(warnings.length)data.append(el('p',warnings.map(x=>typeof x==='string'?x:JSON.stringify(x)).join(' · '),'warn'));card.append(head,view,data);container.append(card);cards.push({canvas,model:valid?model:null});}viewers[prefix]=cards;draw(prefix);}
function projector(prefix){const yaw=Number($(prefix+'-rotation').value)*Math.PI/180,tilt=Number($(prefix+'-tilt').value)*Math.PI/180,c=Math.cos(yaw),s=Math.sin(yaw),ct=Math.cos(tilt),st=Math.sin(tilt);return v=>{const x=c*v[0]-s*v[1],y=s*v[0]+c*v[1];return[x,ct*y-st*v[2],st*y+ct*v[2]];};}
function shade(vs,f,semantic){const a=vs[f[0]],b=vs[f[1]],c=vs[f[2]],u=b.map((x,j)=>x-a[j]),v=c.map((x,j)=>x-a[j]),n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],len=Math.hypot(...n)||1,level=.79+.21*Math.abs((n[0]*.4+n[1]*.5+n[2]*.77)/len),roof=semantic==='roof'||(!semantic&&Math.abs(n[2]/len)>.2),base=semantic==='ground'?[165,174,160]:semantic==='rear_body'?[145,157,145]:roof?[178,119,83]:[207,215,199];return'rgb('+base.map(x=>Math.round(x*level)).join(',')+')';}
function faceRole(model,index,prefix){if(model.face_semantics?.[index])return model.face_semantics[index];if(prefix!=='arcade')return null;const group=(model.material_groups||[]).find(g=>index>=g.start_face&&index<g.start_face+g.face_count);return group?.name==='rear_body'?'rear_body':'volume';}
function draw(prefix){const cards=viewers[prefix]||[],project=projector(prefix);let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;for(const card of cards)if(card.model){const used=new Set(card.model.faces.flat());for(const i of used){const original=card.model.vertices[i],fit=prefix==='arcade'&&$('arcade-closeup').checked?[original[0],original[1],Math.min(4.8,original[2])]:original;const p=project(fit);xmin=Math.min(xmin,p[0]);xmax=Math.max(xmax,p[0]);ymin=Math.min(ymin,p[1]);ymax=Math.max(ymax,p[1]);}}const w=Math.max(1,xmax-xmin),h=Math.max(1,ymax-ymin);let scale=Infinity;for(const card of cards){const r=card.canvas.getBoundingClientRect();if(r.width>0)scale=Math.min(scale,(r.width-32)/w,(r.height-45)/h);}if(!Number.isFinite(scale)||scale<=0)scale=1;for(const card of cards){const c=card.canvas,r=c.getBoundingClientRect(),dpr=Math.min(2,devicePixelRatio||1);c.width=Math.max(1,Math.round(r.width*dpr));c.height=Math.max(1,Math.round(r.height*dpr));const ctx=c.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,r.width,r.height);if(!card.model)continue;const m=card.model,ps=m.vertices.map(v=>{const p=project(v);return[(p[0]-(xmin+xmax)/2)*scale+r.width/2,(p[1]-(ymin+ymax)/2)*scale+r.height/2-5,p[2]];});const faces=m.faces.map((f,i)=>({f,i,z:f.reduce((s,k)=>s+ps[k][2],0)/f.length})).sort((a,b)=>a.z-b.z);ctx.lineWidth=.45;ctx.lineJoin='round';for(const {f,i}of faces){ctx.beginPath();f.forEach((k,j)=>j?ctx.lineTo(ps[k][0],ps[k][1]):ctx.moveTo(ps[k][0],ps[k][1]));ctx.closePath();ctx.fillStyle=shade(m.vertices,f,faceRole(m,i,prefix));ctx.fill();ctx.strokeStyle='rgba(50,63,54,.25)';ctx.stroke();}const desired=r.width*.22/scale,pow=10**Math.floor(Math.log10(Math.max(.001,desired))),length=([1,2,5,10].filter(v=>v*pow<=desired).pop()||1)*pow;ctx.strokeStyle='#5c7467';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(15,r.height-18);ctx.lineTo(15+length*scale,r.height-18);ctx.stroke();ctx.fillStyle='#5c7467';ctx.font='10px system-ui';ctx.fillText(num(length,length<1?1:0)+' m',15,r.height-23);}$(prefix+'-angle').textContent=$(prefix+'-rotation').value+'°';}
const roofIds=[...new Set(D.roofs.runs.map(r=>r.id))];for(const id of roofIds)option($('roof-building'),id,D.roofs.runs.find(r=>r.id===id).name||id);
function roofUpdate(){const id=$('roof-building').value,runs=D.roofs.runs.filter(r=>r.id===id);$('roof-meta').textContent=id+' · DMP OK · lokální metry, stejný střed a terén';meshView('roof',runs);json('roof-details',runs);const photo=(D.research.roofs?.photo_review?.cases||[]).find(c=>c.ids?.includes(id));$('roof-reference').hidden=!photo;$('roof-no-photo').textContent=photo?'':'Pro tento objekt není v tomto dílčím testu vložena fotografická kontrola; geometrie je porovnávána s mračnem bodů.';if(photo){$('roof-photo').src=photo.image_data||'';$('roof-photo').hidden=!photo.image_data;const attr=$('roof-photo-attribution');attr.replaceChildren(document.createTextNode((photo.author||'')+' · '+(photo.photo_date||'')+' · '+(photo.licence||'')+' · '));const link=el('a','Zdroj fotografie');link.href=photo.url;link.target='_blank';link.rel='noopener';attr.append(link);if(photo.licence_url){const license=el('a','Licence');license.href=photo.licence_url;license.target='_blank';license.rel='noopener';attr.append(document.createTextNode(' · '),license);}if(photo.gallery_modifications)attr.append(document.createTextNode('. '+photo.gallery_modifications));$('roof-observed').textContent=photo.observed||'';$('roof-photo-limits').textContent=photo.limits||'';const comparison=photo.model_comparison;$('roof-photo-comparison').textContent=comparison==='pending'?'Porovnání konkrétních modelů s fotografií zatím není uzavřené.':typeof comparison==='string'?comparison:JSON.stringify(comparison||{});}}
const arcadeIds=[...new Set(D.arcades.models.map(m=>m.building_id))];for(const id of arcadeIds)option($('arcade-building'),id,D.arcades.models.find(r=>r.building_id===id).name||id);
function arcadeUpdate(reset=false){const id=$('arcade-building').value,depth=Number($('arcade-depth').value),runs=D.arcades.models.filter(m=>m.building_id===id&&(m.kind==='baseline'||m.variant_id==='baseline'||Math.abs(m.depth_m-depth)<.01)),building=(D.arcades.buildings||[]).find(b=>b.building_id===id||b.id===id);if(reset&&building?.facade_frame?.inward_v_xy){const v=building.facade_frame.inward_v_xy;$('arcade-rotation').value=(Math.round(Math.atan2(-v[0],-v[1])*180/Math.PI)+360)%360;}$('arcade-meta').textContent=id+' · scénář hloubky '+num(depth,1)+' m · přesné rozměry nejsou zaměřené';meshView('arcade',runs);json('arcade-details',{building,runs});const photo=(D.research.arcades?.photos||[]).find(p=>p.building_id===id),box=$('arcade-photo-reference');box.replaceChildren();if(photo){const link=el('a','Referenční fotografie: '+(photo.author||'')+' · '+(photo.date||''));link.href=photo.url;link.target='_blank';link.rel='noopener';box.append(link,document.createTextNode(' · '));const lic=el('a',photo.license||'Licence');lic.href=photo.license_url;lic.target='_blank';lic.rel='noopener';box.append(lic,document.createTextNode('. '+(photo.observed||'')+' '+(photo.metric_use||'')));}}
for(const b of D.facades.buildings)option($('facade-building'),b.building_id,b.name||b.key);
function facadeUpdate(){const b=D.facades.buildings.find(b=>b.building_id===$('facade-building').value),grid=$('facade-models');grid.replaceChildren();for(const r of b.runs){const card=el('article',undefined,'card'),head=el('div',undefined,'head');head.append(el('h3',names[r.method]||r.method),el('span',b.gallery_review?.status==='review'?'Ruční kontrola':'Test fotografie','badge'+(b.gallery_review?.status==='review'?' bad':'')));const view=el('div',undefined,'facade-view'),img=el('img');img.src=r.svg_data;img.alt='Schematická fasáda – '+(names[r.method]||r.method);view.append(img);const body=el('div',undefined,'card-data'),swatches=el('div',undefined,'swatches');for(const role of ['main','decor']){const sw=el('div',undefined,'swatch'),color=el('i',undefined,'color'),hex=r.palette?.[role]?.srgb_hex;color.style.backgroundColor=hex||'transparent';sw.append(color,el('span',(role==='main'?'Omítka ':'Členění ')+(hex||'—')));swatches.append(sw);}body.append(swatches);const fullSvg=el('a','Samostatné SVG');fullSvg.href='facades/'+r.svg_path.split(/[\/]/).pop();fullSvg.target='_blank';fullSvg.rel='noopener';body.append(fullSvg);values(body,[['Výpočet · medián 3',secs(r.median_seconds)],['ΔE76 omítka',num(r.diagnostic?.holdout_delta_e76?.main?.median??r.diagnostic?.holdout_delta_e76?.main)],['ΔE76 členění',num(r.diagnostic?.holdout_delta_e76?.decor?.median??r.diagnostic?.holdout_delta_e76?.decor)]]);card.append(head,view,body);grid.append(card);}$('facade-review').textContent=b.gallery_review?.message||'';const photo=b.photo||{};$('facade-meta').textContent=(b.name||b.key)+' · fotografie '+(photo.date_taken||'datum neuvedeno')+' · barvy obrazu, ne materiálové zaměření';$('roi-photo').src=b.roi_data||'';$('roi-photo').hidden=!b.roi_data;const attr=$('photo-attribution');attr.replaceChildren();attr.append(document.createTextNode((photo.author||'Autor neuveden')+' · '+(photo.date_taken||'')+' · '));const link=el('a',photo.license||'Licence');link.href=photo.license_url||photo.file_page_url;link.target='_blank';link.rel='noopener';attr.append(link,document.createTextNode(' · '));const source=el('a','Zdroj fotografie');source.href=photo.file_page_url;source.target='_blank';source.rel='noopener';attr.append(source,document.createTextNode('. Změny: zmenšení a vyznačení oblastí pro výpočet barev.'));const limits=$('facade-limits');limits.replaceChildren();for(const text of b.limitations||[])limits.append(el('li',typeof text==='string'?text:JSON.stringify(text)));json('facade-details',b);}
for(const prefix of ['roof','arcade'])for(const control of ['rotation','tilt'])$(prefix+'-'+control).addEventListener('input',()=>draw(prefix));
$('roof-building').addEventListener('change',roofUpdate);$('arcade-building').addEventListener('change',()=>arcadeUpdate(true));$('arcade-depth').addEventListener('change',()=>arcadeUpdate());$('facade-building').addEventListener('change',facadeUpdate);
for(const r of D.performance){const row=el('tr');for(const value of [names[r.key]||r.key,r.scope,secs(r.wall_seconds),secs(r.cpu_seconds),bytes(r.peak_commit_bytes),bytes(r.peak_working_set_bytes)])row.append(el('td',value));$('performance').append(row);}for(const rule of D.protocol.comparison_rules)$('rules').append(el('li',rule));json('protocol-details',D.protocol);json('research-details',D.research);json('parser-audit-details',D.parser_audit||{status:'not_available'});
for(const [prefix,doc]of [['roof',D.roofs],['arcade',D.arcades],['facade',D.facades]]){const info={};for(const [k,v]of Object.entries(doc))if(!['runs','models','buildings','samples'].includes(k))info[k]=v;json(prefix+'-process',info);}
const urls=new Map();function collect(v){if(!v||typeof v!=='object')return;if(Array.isArray(v)){v.forEach(collect);return;}for(const key of ['url','file_page_url','license_url','source_url'])if(typeof v[key]==='string'&&/^https?:/.test(v[key])){const label=v.title||v.name||v.id||v.author||v.type||v[key];urls.set(v[key],{label,note:v.supports||v.description||v.license||''});}Object.values(v).forEach(collect);}collect(D.research);collect(D.round2);for(const [url,v]of urls){const li=el('li'),a=el('a',v.label);a.href=url;a.target='_blank';a.rel='noopener';li.append(a);if(v.note)li.append(document.createTextNode(' — '+(Array.isArray(v.note)?v.note.join(' '):v.note)));$('references').append(li);}
function heightFindings(){
 const audit=D.height_audit;if(!audit){$('height-findings').hidden=true;return;}
 const review=audit.fits?.paired_review||[],policy=audit.policy_preview?.rows||[];
 const picked=id=>review.find(r=>r.id===id),dense=r=>(r?.methods||[]).find(m=>m.source==='dmpok'&&m.method==='templates');
 const cards=$('height-finding-cards');
 function card(title,text,detail){const article=el('article');article.append(el('h3',title),el('p',text),el('p',detail,'small'));cards.append(article);}
 function range(m){const d=m?.height_diagnostics||{};return num(d.roof_vertex_min_above_ground_m)+' → '+num(d.roof_vertex_max_above_ground_m)+' m';}
 const mill=picked('4360399b-b4fe-442c-aebf-299791112d22'),millFit=dense(mill),change=policy.find(r=>r.id===mill?.id);
 if(change)card(change.name,'Původní pravidlo přepsalo zdrojový typ „sedlová“ na „plochá“. Oprava zachovává střechu: '+num(change.before.wall_height_m,1)+' m plné stěny → '+num(change.after.wall_height_m,1)+' m stěny + '+num(change.after.roof_height_m,1)+' m střechy.',
  'Samostatný fit sedlové šablony z DMPOK má střešní rozsah '+range(millFit)+' a holdout RMSE '+num(millFit?.holdout_rmse_m,3)+' m. Podporuje opravu v rámci dostupných dat; aktuální mapové dlaždice jsou doloženy níže.');
 const tuma=picked('703989e7-ed6e-4fe0-af7f-2e333d74f71f'),tumaFit=dense(tuma);
 if(tuma)card(tuma.name,'Jednoduchá sedlová šablona je nadějný kandidát: střešní rozsah '+range(tumaFit)+', holdout RMSE '+num(tumaFit?.holdout_rmse_m,3)+' m.',
  'Výsledek čeká na kontrolu průčelí a orientace. Tento fit nebyl automaticky aplikován do mapy a sám neurčuje počet obytných podlaží.');
 const baara=picked('9e12c98b-650e-42cb-be78-330800d0130a');
 if(baara)card(baara.name,'Členitý objekt potřebuje samostatné střešní části. Jeden objem „3 + 2 podlaží“ není ověřený.',
  'Tři viditelné řady oken mohou odpovídat třem vysokým podlažím. Nejnižší bod členité střešní geometrie není automaticky římsa uliční fasády. Konzervativní pravidlo tento dům nemění.');
 const quality=audit.fits?.quality_summary||{},runs=audit.fits?.runs||[];
 $('height-quality').textContent='Samostatný audit: '+audit.sample_count+' půdorysů, '+runs.length+' běhů. Kontrola kvality: '+(quality.reject_geometric_envelope||0)+' modelů odmítnuto pro výškový rozsah, '+(quality.unavailable||0)+' bez geometrie, '+(quality.fallback_only||0)+' pouze náhradní objem a '+(quality.review_not_ground_truth||0)+' k revizi. Odmítnuté modely DMP1G mají špičky nad P99 zdroje + 3 m nebo pod terénem; kontrola neměnila geometrii ani RMSE. Původní LAS body třídy 6 obsahují i nízké body uvnitř půdorysů.';
}
heightFindings();
$('arcade-closeup').addEventListener('change',()=>draw('arcade'));if(D.height_audit){json('height-audit-details',D.height_audit);const policy=D.height_audit.policy_preview,rendered=D.height_audit.rendered_comparison,actual=rendered?.status==='captured_actual_scene';$('height-audit-status').textContent=(actual?'Zachycena skutečná scéna nového preview. ':'K dispozici je izolovaný datový test. ')+(policy?'Pravidlo mění '+policy.changed_count+' z '+policy.rows.length+' diagnostických případů. ':'')+'Tento audit má vlastní metodiku a identifikátory; není rozšířením původního vzorku 30/18.';for(const r of (actual?rendered.rows:policy?.rows)||[]){if(!r.changed)continue;const tr=el('tr');for(const value of [r.name,num(r.before.wall_height_m,1)+' + '+num(r.before.roof_height_m,1)+' m ('+(names[r.before.roof]||r.before.roof)+')',num(r.after.wall_height_m,1)+' + '+num(r.after.roof_height_m,1)+' m ('+(names[r.after.roof]||r.after.roof)+')',actual?'Scéna nového preview':r.status==='isolated_policy_preview_not_rendered'?'Izolovaný datový test':r.status])tr.append(el('td',value));$('height-audit-rows').append(tr);}}else{$('height-audit-status').textContent='Diagnostika je samostatný navazující výstup; výsledky zatím nejsou součástí této verze galerie.';}if(D.round2){json('round2-details',D.round2);for(const c of D.round2.candidates||[]){const tr=el('tr'),notes=Array.isArray(c.temporal_notes)?c.temporal_notes.join(' '):c.temporal_notes||'',state=el('td','Dosud netestováno. '+notes);for(const ref of c.source_refs||[]){const p=el('p',undefined,'small'),a=el('a',ref.title||ref.publisher||'Zdroj');a.href=ref.url;a.target='_blank';a.rel='noopener';p.append(a);state.append(p);}tr.append(el('td',c.name||c.title||c.id),el('td',c.why||c.reason||c.category||''),state);$('round2-list').append(tr);}}else{$('round2').hidden=true;$('round2-nav').hidden=true;}roofUpdate();arcadeUpdate(true);facadeUpdate();let frame;window.addEventListener('resize',()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{draw('roof');draw('arcade');});});
</script></body></html>'''


def write_report(data):
    import resource_guard as guard
    DEST.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(serializable(data), ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    guard.check_budget(reserve_bytes=len(payload.encode("utf-8")) + len(HTML.encode("utf-8")) + 200_000, force=True)
    output = DEST / "report.html"
    output.write_text(HTML.replace("__DATA__", payload), encoding="utf-8")
    (DEST / "protocol.json").write_text(json.dumps(data["protocol"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DEST / "README.md").write_text(readme(data), encoding="utf-8")
    return output


def readme(data):
    p = data["protocol"]
    return f'''# České Budějovice – izolované experimenty

Otevři `report.html`: samostatná galerie bez síťových požadavků. Pro interaktivní mapu spusť dvojklikem [`../otevrit-nahled.cmd`](../otevrit-nahled.cmd) a nech okno terminálu otevřené. Spouštěč otevře místní přehled a mapu; nic nestahuje. Zobrazuje skutečně vygenerované výsledky a rozlišuje naměřené metriky, fotografické pozorování a předpoklady. Podrobné testy 18 střech, podloubí a fasád nejsou nasazené v městské mapě. Samostatnou opravu pravidla pro střechy dokládá mapové preview a `roof-heights/map-rebuild.json`.

- Základní pilot: {p['pilot_footprints']} půdorysů, viz `../roof-pilot/report.html`.
- První srovnání ve Velešíně: `../../velesin/roof-pilot/report.html`.
- Podrobné testy: {p['detailed_footprints']} různých půdorysů, limit uživatele je 20.
- Střešní varianty: {p['result_counts']['roof_runs']} záznamů ({p['result_counts']['roof_primary_runs']} hlavních, {p['result_counts']['roof_extra_runs']} cílených doplňujících pokusů).
- Podloubí: {p['result_counts']['arcade_models']} modelů.
- Fasády: {p['result_counts']['facade_buildings']} domy.

## Obnovení přehledu

Z kořene projektu:

```powershell
.venv\\Scripts\\python.exe -X utf8 scripts\\cb_experiment_report.py
```

Skript pouze čte výsledky. Nespouští rekonstrukci, nestahuje data a neupravuje renderer. Vyžaduje všechny tři dokončené soubory `roofs/results.json`, `arcades/results.json`, `facades/results.json`, společný výběr budov a existující SVG/ROI náhledy fasád. Ověřuje společné identity a limit 20 detailních půdorysů. `protocol.json` obsahuje kontrolní součty vstupů, včetně vložených obrázků.

## Ověření offline galerie

```powershell
.venv\\Scripts\\python.exe -X utf8 scripts\\resource_guard.py run --log .work\\cb-experiments\\qa\\gallery-ui.log --max-ram-gb 1 --min-available-gb 1 -- node scripts\\check_cb_experiments.mjs
```

`../../../.work/cb-experiments/qa/gallery-ui.json` zachovává výsledek konkrétního UI běhu: všech 18 střešních voleb včetně chybějící geometrie, tři domy s podloubím v obou hloubkách, změnu kamery, devět SVG a tři ROI, pět fotografických kontrol, lokální odkazy, nulové síťové požadavky a šířku 390 px bez přetečení. Snímky jsou ve stejném adresáři. Procesní měření sestavení a UI kontroly jsou v přilehlých `report-build-final.log.metrics.json` a `gallery-ui.log.metrics.json`; jejich časy nejsou náklady rekonstrukce střech. Browser QA se spouští až po dokončení těžkých výpočtů a finálního mapového porovnání.

## Jak rozhodovat

| Oblast | Co porovnat | Co metrika neprokazuje |
| --- | --- | --- |
| Střechy | Hlavní hřeben a tvar, shoda holdout bodů, pokrytí, složitost, čas | Nízké RMSE samo nepotvrzuje skutečný typ střechy ani nezávislou přesnost |
| Výškové objemy | Počet hlavních hmot, počet ploch, velikost modelu | LoD1.3 nereprodukuje skloněné střešní roviny |
| Podloubí | Prázdný prostor, průchodnost paprsku, pilíře, 8/16 segmentů a 2/3,5 m hloubky | Odhadnutá hloubka ani úspěšný test neprokazují dnešní stav a přístupnost |
| Fasády | Stabilita dvou barev, odlehlé pixely, soulad se zdrojovou fotografií | Nejde o kalibrovanou materiálovou barvu; členění SVG je schematické |

Devět hlavních střešních dávek má zachované kontrolní součty trénovacích dat a půdorysů, nativní výstupy, příkaz a verzi Rooferu. Nemá však execution snapshot Python wrapperu; dodatečný SHA aktuálního souboru nedokazuje přesné bajty načtené při startu. Kontrolní součty protokolu zachycují vstupy v okamžiku sestavení galerie.

Ruční čas rešerše a vymezení fasádních oblastí nebyl měřen. Milisekundy barevného algoritmu nejsou celková pracnost budovy.

Čas metody, načtení, exportu a celého procesu se nesčítá ani nezaměňuje bez vysvětlení. Peak committed memory je jiná veličina než resident working set. Výběr obsahuje záměrně obtížné objekty a nelze jej bez dalšího zobecnit na celé město.

## Zdroje a licence

Rešerše jsou v `roofs/method-review.json`, `arcades/source-review.json` a `facades/source-review.json`; galerie je také obsahuje. U fotografie je uveden autor, datum, konkrétní stránka a licence. Commons fotografie a jejich zmenšené či anotované výřezy zachovávají původní licenci; pro CC BY-SA výřezy platí stejná licence. Vektorové fasády představují vlastní schematické barevné testy, nejsou fototextury ani zaměřené výkresy.

## Samostatný audit výšek

`roof-heights/README.md`, `roof-heights/results.json` a samostatná otočná galerie `roof-heights/fit-report.html` dokumentují 12 cílených diagnostických případů kolem dvou náměstí. Audit není rozšířením 30/18 půdorysů. U Na Mlýnské stoce 367 původní pravidlo přepisovalo známý sedlový typ na plochý; konzervativní oprava zachovává střešní objem. Dr. Tůmy je kandidát jednoduché sedlové šablony, Baara vyžaduje rozdělení částí; ani jeden fit není automatické nasazení. Pásy oken po 2,8 m jsou samostatná procedurální heuristika, nikoli skutečný počet podlaží. Aktuální nasazení dokládá `roof-heights/map-rebuild.json` a vložený pár snímků skutečných dlaždic; ostatní experimenty zůstávají izolované.

## Druhé kolo

`round-2-candidates.json` a `round-2-README.md` obsahují další kandidáty. Jde o dosud netestované objekty, bez přičítání k aktuálním 30 půdorysům nebo detailním testům. U Slavie rozlišujeme stav před obnovou a po ní; staré mračno nemůže potvrzovat nové detaily.

## Limity zdrojů

Celý projekt má limit 20 GB a práce se zastaví při volném místě na C: pod 25 GB. Dílčí pracovní procesy používají resource_guard. Výsledky zahrnují procesní protokoly; galerie sama nevykonává výpočetně náročné rekonstrukce. Hromadná data se nezpracovávají AI modelem.
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    data = build_data()
    if args.check_only:
        print(json.dumps(data["protocol"]["result_counts"], ensure_ascii=False))
    else:
        output = write_report(data)
        print(json.dumps({"report": str(output), "bytes": output.stat().st_size,
                          "detailed_footprints": data["protocol"]["detailed_footprints"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
