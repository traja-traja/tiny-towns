"""Small, guarded photographic colour experiment; no city renderer or AI calls.

Run with the project Python. Three manually reviewed photographs are compared
using one sample, Lab medians and trimmed Lab medians. Outputs are explicitly
schematic material demonstrations, not measured architectural elevations.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import html
import io
import json
import os
from pathlib import Path
import statistics
import sys
import time

# Bound BLAS before importing NumPy; the Windows job also limits commit memory.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"
import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFont

import resource_guard as guard

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work/cb-facades"
DEST = ROOT / "cities/ceske-budejovice/experiments/facades"
METHODS = ("single_sample", "lab_median", "lab_trimmed_median")
METHOD_LABELS = {"single_sample": "Jeden vzorek", "lab_median": "Lab medián", "lab_trimmed_median": "Ořezaný Lab medián"}
SELECTED = {"radnice": "radnice-2023", "puklicuv": "puklic-2012", "krajinska10": "krajinska10-2012"}

# Pixel rectangles were chosen by visual inspection at the exact documented
# preview resolution, before inspecting computed palette/holdout statistics.
# Results persist normalized polygons as well as these reproducible locations.
ROIS = {
    "radnice": {
        "size": [960, 720],
        "main": {"train": [[421, 430, 430, 442], [632, 432, 642, 443], [632, 480, 642, 494]],
                 "holdout": [[632, 500, 641, 511], [421, 480, 429, 491]]},
        "decor": {"train": [[337, 434, 346, 443], [382, 437, 391, 447], [300, 432, 307, 439]],
                  "holdout": [[337, 444, 344, 449], [382, 449, 391, 455]]},
    },
    "puklicuv": {
        "size": [500, 750],
        "main": {"train": [[259, 553, 278, 565], [314, 553, 334, 565], [182, 350, 191, 369]],
                 "holdout": [[282, 553, 302, 565], [350, 553, 370, 563]]},
        "decor": {"train": [[252, 282, 270, 285], [310, 282, 328, 285], [350, 282, 368, 285]],
                  "holdout": [[275, 282, 290, 285], [375, 282, 390, 285]]},
    },
    "krajinska10": {
        "size": [500, 691],
        "main": {"train": [[187, 170, 199, 187], [187, 235, 199, 251], [187, 375, 199, 389]],
                 "holdout": [[187, 254, 199, 267], [187, 396, 199, 409]]},
        "decor": {"train": [[211, 177, 215, 192], [211, 315, 215, 329], [211, 423, 215, 435]],
                  "holdout": [[211, 255, 215, 269], [211, 379, 215, 391]]},
    },
}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    guard.check_budget(reserve_bytes=2_000_000)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def relative(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def rgb_to_lab(rgb):
    """IEC sRGB transfer, sRGB/D65 XYZ matrix, CIE 1976 Lab (2 degree)."""
    x = np.asarray(rgb, dtype=np.float64) / 255.0
    linear = np.where(x <= .04045, x / 12.92, ((x + .055) / 1.055) ** 2.4)
    xyz = linear @ np.array([[.4124564, .3575761, .1804375],
                             [.2126729, .7151522, .0721750],
                             [.0193339, .1191920, .9503041]]).T
    xyz /= [.95047, 1.0, 1.08883]
    delta = 6 / 29
    f = np.where(xyz > delta ** 3, np.cbrt(xyz), xyz / (3 * delta ** 2) + 4 / 29)
    return np.stack((116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])), axis=-1)


def lab_to_rgb(lab):
    l, a, b = np.asarray(lab, dtype=float)
    fy = (l + 16) / 116
    f = np.array([fy + a / 500, fy, fy - b / 200])
    delta = 6 / 29
    xyz = np.where(f > delta, f ** 3, 3 * delta ** 2 * (f - 4 / 29)) * [.95047, 1, 1.08883]
    linear = xyz @ np.array([[3.2404542, -1.5371385, -.4985314],
                            [-.9692660, 1.8760108, .0415560],
                            [.0556434, -.2040259, 1.0572252]]).T
    clipped = bool(np.any((linear < -1e-6) | (linear > 1 + 1e-6)))
    x = np.maximum(linear, 0)
    srgb = np.where(x <= .0031308, 12.92 * x, 1.055 * x ** (1 / 2.4) - .055)
    return np.rint(np.clip(srgb, 0, 1) * 255).astype(np.uint8), clipped


def decode(path):
    payload = path.read_bytes()
    with Image.open(io.BytesIO(payload)) as source:
        if max(source.size) > 1600:
            raise ValueError("Reference preview exceeds the 1600 px limit")
        source.load()
        profile = source.info.get("icc_profile")
        if profile:
            image = ImageCms.profileToProfile(source, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                              ImageCms.createProfile("sRGB"), outputMode="RGB")
            policy = "embedded_ICC_converted_to_sRGB"
        else:
            image = source.convert("RGB")
            policy = "assumed_sRGB_no_embedded_ICC"
    return image, np.asarray(image).copy(), policy


def masks_for(key, width, height):
    spec = ROIS[key]
    if spec["size"] != [width, height]:
        raise ValueError("Photo dimensions changed; review masks before running")
    masks, normalized = {}, {}
    occupied = np.zeros((height, width), dtype=bool)
    for role in ("main", "decor"):
        masks[role], normalized[role] = {}, {}
        for split in ("train", "holdout"):
            group, polygons = [], []
            for x0, y0, x1, y1 in spec[role][split]:
                mask = np.zeros((height, width), dtype=bool)
                mask[y0:y1, x0:x1] = True
                if mask.sum() < 12 or np.any(mask & occupied):
                    raise ValueError("Insufficient or overlapping manual patch")
                occupied |= mask
                group.append(mask)
                polygons.append([[x0 / width, y0 / height], [x1 / width, y0 / height],
                                 [x1 / width, y1 / height], [x0 / width, y1 / height]])
            masks[role][split] = group
            normalized[role][split] = polygons
    return masks, normalized


def estimate(array, masks, method):
    result = {}
    for role in ("main", "decor"):
        groups = masks[role]["train"]
        if method == "single_sample":
            yy, xx = np.nonzero(groups[0])
            # Center of the FIRST manually chosen patch; no holdout selection.
            y, x = int(np.median(yy)), int(np.median(xx))
            lab = rgb_to_lab(array[y, x])
            total, kept = 1, 1
            sample = [x, y]
        else:
            values = rgb_to_lab(array[np.logical_or.reduce(groups)])
            total = len(values)
            if method == "lab_trimmed_median":
                low, high = np.quantile(values[:, 0], [.1, .9])
                values = values[(values[:, 0] >= low) & (values[:, 0] <= high)]
            kept = len(values)
            lab = np.median(values, axis=0)
            sample = None
        rgb, clipped = lab_to_rgb(lab)
        result[role] = {"srgb_hex": "#" + "".join(f"{int(v):02x}" for v in rgb),
                        "srgb": rgb.tolist(), "lab": lab.tolist(), "pixels_input": total,
                        "pixels_kept": kept, "trimmed_fraction": 1 - kept / total,
                        "gamut_clipped": clipped, "single_pixel_xy": sample}
    return result


def diagnostic(array, masks, palette):
    result = {"metric": "CIE76 Euclidean Lab distance", "independence": "spatial patches within same JPEG; not independent survey", "holdout_delta_e76": {}, "patches": {}}
    for role in ("main", "decor"):
        target = np.asarray(palette[role]["lab"])
        holdout = [np.median(rgb_to_lab(array[m]), axis=0) for m in masks[role]["holdout"]]
        distances = [float(np.linalg.norm(target - p)) for p in holdout]
        training = [np.median(rgb_to_lab(array[m]), axis=0) for m in masks[role]["train"]]
        result["holdout_delta_e76"][role] = {"per_patch": distances, "median": statistics.median(distances), "max": max(distances), "count": len(distances)}
        result["patches"][role] = {"train_lab_medians": [p.tolist() for p in training],
                                  "holdout_lab_medians": [p.tolist() for p in holdout],
                                  "training_pairwise_max_delta_e76": float(max(np.linalg.norm(a - b) for a in training for b in training))}
    return result


def font(size):
    for name in ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf"):
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def annotated_photo(image, key, photo, path):
    w, h = image.size
    out = Image.new("RGB", (max(640, w), h + 150), "#f5f5f0")
    out.paste(image, (0, 0))
    draw = ImageDraw.Draw(out)
    colors = {("main", "train"): "#00ff70", ("decor", "train"): "#ff3060",
              ("main", "holdout"): "#20bbff", ("decor", "holdout"): "#ffff10"}
    for role in ("main", "decor"):
        for split in ("train", "holdout"):
            color = colors[role, split]
            for x0, y0, x1, y1 in ROIS[key][role][split]:
                draw.rectangle((x0 - 1, y0 - 1, x1, y1), outline=color, width=2)
    lines = ["ROI review: hlavní / dekor = zelená / červená; odložené = modrá / žlutá.",
             f"Foto: {photo['author']} · {photo['date_taken']} · {photo['license']}",
             "Změny: obrysy vzorků + tento popisek. Barvy snímku nebyly upraveny.",
             "Nejde o zaměřenou fasádu ani kalibrovanou barvu omítky.",
             "Úplný zdroj a licence: výsledný results.json + source-review.json"]
    for i, line in enumerate(lines):
        draw.text((10, h + 8 + i * 25), line, fill="#182c32", font=font(13))
    out.save(path)


def svg_for(name, palette, method, photo):
    main, decor = palette["main"]["srgb_hex"], palette["decor"]["srgb_hex"]
    esc = html.escape
    shapes = [f'<rect x="40" y="100" width="520" height="390" fill="{main}"/>']
    # Identical generic layout across all buildings isolates palette effects.
    for y in (110, 225, 345, 475):
        shapes.append(f'<rect x="40" y="{y}" width="520" height="9" fill="{decor}"/>')
    for x in (73, 195, 317, 439):
        for y in (145, 265, 385):
            shapes.append(f'<rect x="{x}" y="{y}" width="80" height="64" fill="{main}" stroke="{decor}" stroke-width="9"/>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="650" viewBox="0 0 600 650" role="img" aria-labelledby="title desc">
<title id="title">{esc(name)} – {esc(METHOD_LABELS[method])}, schematické dvě barvy</title>
<desc id="desc">SCHEMATIC / NOT MEASURED. Stejný generický rozvrh rámů pro všechny domy; nejde o skutečný počet, tvary ani polohy oken. Fotografie není barevně kalibrovaná.</desc>
<metadata>{esc(json.dumps({'source': photo['file_page_url'], 'author': photo['author'], 'date': photo['date_taken'], 'source_license': photo['license'], 'license_url': photo['license_url'], 'changes': 'Two representative image colours; generic schematic facade, no photograph embedded.'}, ensure_ascii=False))}</metadata>
<rect width="600" height="650" fill="#f4f6f3"/>
<g font-family="Arial,sans-serif" fill="#17343a"><text x="40" y="35" font-size="21">{esc(name)}</text><text x="40" y="62" font-size="15">{esc(METHOD_LABELS[method])} · SCHEMATIC / NOT MEASURED</text></g>
{''.join(shapes)}
<g font-family="Arial,sans-serif" fill="#17343a" font-size="13">
<text x="40" y="520">Omítka {main} · dekor {decor} · odhad vzhledu fotografie</text>
<text x="40" y="545">Generické rámy a římsy; počet a tvary oken nejsou dokumentované.</text>
<text x="40" y="568">Foto {esc(photo['author'])}, {esc(photo['date_taken'])}; {esc(photo['license'])}.</text>
<text x="40" y="590">Barvy nejsou kalibrované sRGB materiálu ani potvrzení stavu 2026.</text>
<a href="{esc(photo['file_page_url'])}"><text x="40" y="615" fill="#146b69">Zdroj fotografie a atribuce</text></a>
<a href="{esc(photo['license_url'])}"><text x="355" y="615" fill="#146b69">Licence zdroje</text></a>
</g></svg>'''


def memory_peak():
    if os.name != "nt":
        return {"peak_working_set_bytes": None, "note": "Windows counter unavailable"}
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [(x, ctypes.c_size_t) for x in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
    c = Counters(); c.cb = ctypes.sizeof(c)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    process = kernel.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(c), c.cb):
        raise OSError("Cannot read process memory counters")
    return {"peak_working_set_bytes": c.PeakWorkingSetSize, "peak_pagefile_usage_bytes": c.PeakPagefileUsage,
            "private_usage_bytes_at_end": c.PrivateUsage, "note": "Working set is resident RAM; pagefile/commit counter is a different quantity."}


def worker():
    start = time.perf_counter()
    guard.check_budget(reserve_bytes=20_000_000, force=True)
    WORK.mkdir(parents=True, exist_ok=True); DEST.mkdir(parents=True, exist_ok=True)
    review = json.loads((DEST / "source-review.json").read_text(encoding="utf-8"))
    photos = {p["id"]: p for p in review["photographs"]}
    buildings = {b["key"]: b for b in review["buildings"]}
    manifest, rows = [], []
    previous = json.loads((WORK / "sources.json").read_text(encoding="utf-8")) if (WORK / "sources.json").exists() else []
    known_hashes = {p["photo_id"]: p["sha256"] for p in previous}
    for key, photo_id in SELECTED.items():
        p = photos[photo_id]; path = WORK / (photo_id + ".jpg")
        dl = guard.download(p["preview_url"], path, expected_sha256=known_hashes.get(photo_id), max_bytes=2_000_000)
        if sum(f.stat().st_size for f in WORK.glob("*.jpg")) > 10_000_000:
            raise guard.ResourceLimit("Reference photographs exceed 10 MB")
        photo = {k: p[k] for k in ("file_page_url", "author", "license", "license_url", "date_taken")}
        photo.update(photo_id=photo_id, path=relative(path), sha256=guard.sha256(path), download=dl)
        manifest.append(photo)
        decode_seconds = []
        for _ in range(3):
            then = time.perf_counter(); image, array, policy = decode(path)
            decode_seconds.append(time.perf_counter() - then)
        photo.update(width=image.width, height=image.height, color_management=policy)
        masks, normalized = masks_for(key, image.width, image.height)
        runs = []
        for method in METHODS:
            # One explicit warmup, followed by the three recorded repetitions.
            estimate(array, masks, method)
            times, palettes = [], []
            for _ in range(3):
                then = time.perf_counter(); palette = estimate(array, masks, method)
                times.append(time.perf_counter() - then); palettes.append(palette)
            if any(p != palettes[0] for p in palettes[1:]):
                raise AssertionError("Deterministic estimator changed between repetitions")
            svg_path = DEST / f"{key}-{method}.svg"
            export_start = time.perf_counter()
            svg_path.write_text(svg_for(buildings[key]["name"], palette, method, photo), encoding="utf-8")
            export_seconds = time.perf_counter() - export_start
            runs.append({"method": method, "repetition_seconds": times, "median_seconds": statistics.median(times),
                         "min_seconds": min(times), "max_seconds": max(times), "warmup_count": 1,
                         "timing_scope": "pixel extraction + sRGB/Lab conversion + estimator + palette formatting; excludes JPEG decoding, manual ROI selection, diagnostics and export",
                         "palette": palette, "diagnostic": diagnostic(array, masks, palette),
                         "svg_path": relative(svg_path), "svg_export_seconds": export_seconds,
                         "schematic": True, "not_measured": True, "real_window_layout": False})
        roi = DEST / f"{key}-roi.png"
        then = time.perf_counter(); annotated_photo(image, key, photo, roi); roi_seconds = time.perf_counter() - then
        rows.append({"key": key, "building_id": buildings[key]["building_id"], "name": buildings[key]["name"],
                     "photo": photo, "masks": {"coordinate_system": "normalized [u,v], image top-left; pixel rectangles use half-open bounds", "normalized_polygons": normalized, "pixel_rectangles": ROIS[key],
                                                  "selection": "manual semantic patches; final locations verified in enlarged original pixels; never optimize positions to minimize holdout distance",
                                                  "visual_revision": "Krajinska patches moved after overlay review to exclude drainpipe/edge shadow, before inspecting scores" if key == "krajinska10" else "Decor patches relocated after suspicious preliminary palette prompted pixel-level visual review: earlier thin strips hit cornice shadow or adjacent painted field. Superseded results retained under .work/cb-facades/history. Final patches chosen by visible material role, not by distance search.",
                                                  "training_patches_per_role": 3, "holdout_patches_per_role": 2},
                     "decode_seconds": decode_seconds, "decode_median_seconds": statistics.median(decode_seconds),
                     "decode_timing_scope": "read local JPEG + decode + optional embedded ICC transform + RGB array copy; each trial reloads file, OS disk cache not flushed",
                     "runs": runs, "roi_png_path": relative(roi), "roi_export_seconds": roi_seconds,
                     "limitations": p["lighting_risks"] + p["does_not_support"]})
        print(key, "completed", flush=True)
        del image, array, masks
        guard.check_budget()
    write_json(WORK / "sources.json", manifest)
    peak = memory_peak()
    if peak.get("peak_working_set_bytes", 0) > 200_000_000:
        raise guard.ResourceLimit("Worker exceeded 200 MB resident RAM")
    result = {"schema": "cb-facade-experiments/1", "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "completed_small_photographic_experiment", "buildings": rows,
              "resources": {**peak, "worker_elapsed_seconds": time.perf_counter() - start,
                            "reference_bytes_used": sum((ROOT / p["path"]).stat().st_size for p in manifest),
                            "all_cached_photo_bytes": sum(f.stat().st_size for f in WORK.glob("*.jpg")),
                            "output_bytes_before_results": sum(f.stat().st_size for f in DEST.iterdir() if f.suffix in (".svg", ".png")),
                            "disk_budget": guard.check_budget(force=True)},
              "notes": ["Three source images, three deterministic methods, three recorded repetitions per method; no generative model was used.",
                        "CIE76 distances compare held-out patches in the same photograph, not material truth or independent photographs.",
                        "No shadow removal, white-balance estimation, facade rectification or automatic semantic segmentation was performed.",
                        "Source image years are 2023 and 2012. No claim about exact current facade colour is made.",
                        "Schematic SVGs use identical generic framing to isolate palette changes; they do not document the buildings' actual windows, arcades or proportions.",
                        "K-means, cross-photo colour validation and real vector tracing remain research proposals and have no measured results here.",
                        "Manual research/ROI-selection time was not instrumented and is explicitly unknown; machine milliseconds must not be presented as end-to-end production time."]}
    write_json(DEST / "results.json", result)
    print(json.dumps({"status": result["status"], "peak_working_set_bytes": peak["peak_working_set_bytes"]}))


def self_check():
    colors = np.array([[0, 0, 0], [255, 255, 255], [255, 0, 0], [52, 130, 162], [220, 195, 170]])
    for rgb, lab in zip(colors, rgb_to_lab(colors)):
        got, _ = lab_to_rgb(lab)
        if np.max(np.abs(got.astype(int) - rgb)) > 1:
            raise AssertionError("sRGB/Lab roundtrip failed")
    if not np.allclose(rgb_to_lab([255, 255, 255]), [100, 0, 0], atol=.001):
        raise AssertionError("D65 white conversion failed")
    for key, spec in ROIS.items():
        masks_for(key, *spec["size"])
    print("PASS: colour roundtrip, D65 white, masks do not overlap")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        self_check(); return
    if args.worker:
        with guard.keep_awake():
            worker()
        return
    existing = DEST / "results.json"
    if existing.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        write_json(WORK / "history" / f"results-{stamp}.json", json.loads(existing.read_text(encoding="utf-8")))
    result = guard.run_guarded([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker"],
                               ROOT, WORK / "run.log", min_available_gb=.4, max_ram_gb=.20,
                               wait_memory_seconds=5, reserve_bytes=20_000_000)
    write_json(WORK / "process-metrics.json", result)
    path = DEST / "results.json"
    if path.exists() and result.get("returncode", result.get("exit_code", 0)) == 0:
        data = json.loads(path.read_text(encoding="utf-8")); data["resources"]["guard"] = result
        write_json(path, data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
