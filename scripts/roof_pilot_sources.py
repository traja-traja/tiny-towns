"""Prepare unchanged source points for the 30-footprint roof pilot.

The public CLI runs its worker under resource_guard (2 GB job commit,
1 GB available RAM, project/disk limits). prepare_sources() is also available
to a caller already running under that guard. No points are synthesized.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import zipfile

import laspy
import numpy as np
from pyproj import Transformer
import shapely
from shapely.geometry import Polygon, box, shape

import resource_guard as guard


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE = ROOT / "cities/velesin/roof-pilot/sample.json"
SOURCE_DIR = ROOT / ".work/roof-pilot/sources"
CROP_DIR = ROOT / ".work/roof-pilot/crops"
MANIFEST_PATH = SOURCE_DIR / "sources.json"
MASTER_FEED = SOURCE_DIR / "dmpok-atom.xml"
MASTER_URL = "https://atom.cuzk.gov.cz/DMPOK-SJTSK-LAZ/DMPOK-SJTSK-LAZ.xml"
EXISTING_DMP1G = ROOT / ".work/.preview/velesin/build/dmp"
CHUNK_SIZE = 100_000
BUFFER_METRES = 20.0
RECIPE_VERSION = 1
NS = {"a": "http://www.w3.org/2005/Atom", "g": "http://www.georss.org/georss"}


def log(event, **values):
    print(json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


def relative(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def fingerprint(path):
    path = Path(path)
    return {"path": relative(path), "bytes": path.stat().st_size, "sha256": guard.sha256(path)}


def write_json(path, document):
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    guard.check_budget(reserve_bytes=len(payload), force=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def sample_geometry(sample_path):
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    transform = Transformer.from_crs(4326, 5514, always_xy=True).transform
    buildings = []
    for feature in sample["features"]:
        geom = shapely.transform(shape(feature["geometry"]), transform, interleaved=False)
        if not geom.is_valid or geom.is_empty:
            raise ValueError(f"Invalid footprint: {feature['id']}")
        buildings.append({"id": feature["id"], "pilot_id": feature["properties"]["pilot_id"],
                          "geometry": geom, "buffer": geom.buffer(BUFFER_METRES)})
    union = shapely.union_all([item["buffer"] for item in buildings])
    shapely.prepare(union)
    return buildings, union


def georss_geometry(entry):
    value = entry.findtext("g:polygon", namespaces=NS)
    if value:
        coords = [float(v) for v in value.split()]
        return Polygon([(coords[i + 1], coords[i]) for i in range(0, len(coords), 2)])
    value = entry.findtext("g:box", namespaces=NS)
    if value:
        south, west, north, east = map(float, value.split())
        return box(west, south, east, north)
    raise ValueError("Dataset entry has no supported GeoRSS footprint")


def atom_metadata(entry):
    return {"id": entry.findtext("a:id", namespaces=NS),
            "title": entry.findtext("a:title", namespaces=NS),
            "updated": entry.findtext("a:updated", namespaces=NS),
            "rights": entry.findtext("a:rights", namespaces=NS),
            "georss_polygon_lat_lon": entry.findtext("g:polygon", namespaces=NS),
            "links": [dict(link.attrib) for link in entry.findall("a:link", NS)]}


def selected_dmpok_entries(union):
    to_ll = Transformer.from_crs(5514, 4326, always_xy=True).transform
    region = shapely.transform(union, to_ll, interleaved=False)
    selected = []
    for event, element in ET.iterparse(MASTER_FEED, events=("end",)):
        if element.tag != "{" + NS["a"] + "}entry":
            continue
        if georss_geometry(element).intersects(region):
            item = atom_metadata(element)
            candidates = [link["href"] for link in item["links"]
                          if link.get("type") == "application/atom+xml" and link.get("rel") == "alternate"]
            item["child_feed_url"] = candidates[0] if candidates else item["id"]
            item["sheet"] = Path(urlparse(item["child_feed_url"]).path).stem.rsplit("_", 1)[-1]
            selected.append(item)
        element.clear()
    if not selected:
        raise ValueError("No DMPOK dataset feed intersects the buffered sample")
    return sorted(selected, key=lambda item: item["sheet"])


def header_metadata(path):
    with laspy.open(path, laz_backend=laspy.LazBackend.Lazrs) as reader:
        header = reader.header
        parsed_crs = header.parse_crs()
        epsg = parsed_crs.to_epsg() if parsed_crs else None
        if epsg not in (None, 5514):
            raise ValueError(f"Unexpected CRS for {path}: {parsed_crs}")
        return {"point_count": int(header.point_count),
                "bounds": [header.mins.tolist(), header.maxs.tolist()],
                "crs_wkt": parsed_crs.to_wkt() if parsed_crs else None,
                "crs_epsg": epsg, "effective_horizontal_crs": "EPSG:5514",
                "crs_basis": "LAS header" if parsed_crs else "source product / EPSG:5514 download feed",
                "vertical_datum": "Bpv (source product specification)",
                "las_version": str(header.version), "point_format": int(header.point_format.id),
                "point_record_bytes": int(header.point_format.size),
                "scales": header.scales.tolist(), "offsets": header.offsets.tolist(),
                "creation_date": str(header.creation_date),
                "generating_software": header.generating_software,
                "system_identifier": header.system_identifier}


def header_intersects(header, union):
    lo, hi = header["bounds"]
    return box(lo[0], lo[1], hi[0], hi[1]).intersects(union)


def prepare_dmp1g(union):
    tiles = []
    for path in sorted(EXISTING_DMP1G.glob("*.laz")):
        header = header_metadata(path)
        if not header_intersects(header, union):
            continue
        tiles.append({"sheet": path.stem, "file": fingerprint(path), "header": header,
                      "acquisition": {"kind": "existing_local_cache", "download_seconds": 0,
                                      "extraction_seconds": 0,
                                      "original_source_url": "https://openzu.cuzk.cz/opendata/DMP1G/epsg-5514/" + path.stem + ".zip",
                                      "note": "Prior cache; historic download duration is not known."}})
    if not tiles:
        raise FileNotFoundError("No existing DMP1G LAZ intersects the pilot buffers")
    return tiles, {"download_seconds": 0.0, "extraction_seconds": 0.0}


def prepare_dmpok(union):
    master_download = guard.download(MASTER_URL, MASTER_FEED, max_bytes=50_000_000)
    entries = selected_dmpok_entries(union)
    log("dmpok_selected_feeds", sheets=[item["sheet"] for item in entries])
    tiles = []
    download_seconds = master_download["seconds"]
    extraction_seconds = 0.0
    for entry in entries:
        sheet = entry["sheet"]
        folder = SOURCE_DIR / "dmpok" / sheet
        child_path = folder / "feed.xml"
        child_download = guard.download(entry["child_feed_url"], child_path, max_bytes=5_000_000)
        download_seconds += child_download["seconds"]
        child_root = ET.parse(child_path).getroot()
        links = [dict(link.attrib) for link in child_root.findall(".//a:link", NS)]
        archive_urls = sorted({link["href"] for link in links if
                              link.get("type") in ("application/zip", "application/x-zip-compressed") or
                              urlparse(link.get("href", "")).path.lower().endswith(".zip")})
        if not archive_urls:
            raise ValueError(f"No actual ZIP URL in child dataset feed: {child_path}")
        for archive_index, url in enumerate(archive_urls):
            archive_name = Path(urlparse(url).path).name
            if not archive_name or archive_name in (".", ".."):
                raise ValueError(f"Invalid archive name from feed: {url}")
            archive_path = folder / archive_name
            log("download_start", source="dmpok", sheet=sheet, url=url)
            download = guard.download(url, archive_path, max_bytes=2_000_000_000)
            download_seconds += download["seconds"]
            log("download_complete", sheet=sheet, **download)
            destination = folder / ("extracted" if len(archive_urls) == 1 else f"extracted-{archive_index}")
            with zipfile.ZipFile(archive_path) as archive:
                members = [{"name": item.filename, "bytes": item.file_size, "compressed_bytes": item.compress_size,
                            "crc32": f"{item.CRC:08x}"} for item in archive.infolist()]
            start = time.perf_counter()
            guard.safe_extract_zip(archive_path, destination)
            extraction = time.perf_counter() - start
            extraction_seconds += extraction
            archive_hash = fingerprint(archive_path)
            paths = sorted(destination.rglob("*.laz")) + sorted(destination.rglob("*.las"))
            if not paths:
                raise ValueError(f"No LAS/LAZ in downloaded source archive: {archive_path}")
            for path in paths:
                header = header_metadata(path)
                if not header_intersects(header, union):
                    continue
                tiles.append({"sheet": sheet, "file": fingerprint(path), "header": header,
                              "atom_master_entry": entry, "atom_child_feed": atom_metadata(child_root),
                              "child_feed_file": fingerprint(child_path),
                              "archive": archive_hash, "archive_members": members,
                              "acquisition": {"kind": "official_atom_zip", "download": download,
                                              "child_feed_download": child_download,
                                              "download_seconds": download["seconds"] + child_download["seconds"],
                                              "extraction_seconds": extraction}})
            log("extract_complete", sheet=sheet, seconds=extraction,
                files=[relative(path) for path in paths])
    if not tiles:
        raise ValueError("Downloaded DMPOK files do not overlap the pilot in EPSG:5514")
    return tiles, {"download_seconds": download_seconds, "extraction_seconds": extraction_seconds}


def deduplicate(xyz, classification):
    # Exact decoded source coordinates + class. No rounding, voxelization or interpolation.
    records = np.empty(len(xyz), dtype=[("x", "<f8"), ("y", "<f8"), ("z", "<f8"), ("class", "u1")])
    for column, name in enumerate(("x", "y", "z")):
        records[name] = xyz[:, column]
    records["class"] = classification
    _, keep = np.unique(records, return_index=True)
    keep.sort()
    return xyz[keep], classification[keep], len(xyz) - len(keep)


def counts(values):
    return {str(int(k)): int(v) for k, v in zip(*np.unique(values, return_counts=True))}


def crop_source(name, tiles, buildings, union):
    started = time.perf_counter()
    xyz_parts, class_parts = [], []
    minx, miny, maxx, maxy = union.bounds
    total_kept = 0
    for tile in tiles:
        path = ROOT / tile["file"]["path"]
        log("crop_tile_start", source=name, sheet=tile["sheet"], points=tile["header"]["point_count"])
        started_tile = time.perf_counter()
        class_counts, cropped_counts = Counter(), Counter()
        processed, kept = 0, 0
        last_notice = time.monotonic()
        with laspy.open(path, laz_backend=laspy.LazBackend.Lazrs) as reader:
            for chunk in reader.chunk_iterator(CHUNK_SIZE):
                guard.check_budget()
                classification = np.asarray(chunk.classification, dtype=np.uint8)
                class_counts.update(counts(classification))
                x, y = np.asarray(chunk.x), np.asarray(chunk.y)
                in_bbox = (x >= minx) & (x <= maxx) & (y >= miny) & (y <= maxy)
                indices = np.flatnonzero(in_bbox)
                if len(indices):
                    indices = indices[shapely.intersects_xy(union, x[indices], y[indices])]
                if len(indices):
                    z = np.asarray(chunk.z)
                    xyz_parts.append(np.column_stack((x[indices], y[indices], z[indices])))
                    selected_classes = classification[indices].copy()
                    class_parts.append(selected_classes)
                    cropped_counts.update(counts(selected_classes))
                    kept += len(indices)
                    total_kept += len(indices)
                    # Sorting/dedup needs temporary copies; cap before approaching the 2 GB job limit.
                    if total_kept * 160 > 1_300_000_000:
                        raise guard.ResourceLimit("Crop exceeds the conservative in-memory point budget")
                processed += len(chunk)
                if time.monotonic() - last_notice >= 20:
                    log("crop_progress", source=name, sheet=tile["sheet"], processed=processed,
                        total=tile["header"]["point_count"], retained=kept)
                    last_notice = time.monotonic()
        if processed != tile["header"]["point_count"]:
            raise IOError(f"LAS point-count mismatch: {path}")
        tile["header"]["class_counts"] = dict(sorted(class_counts.items(), key=lambda x: int(x[0])))
        tile["crop"] = {"input_points_read": processed, "retained_before_deduplication": kept,
                        "class_counts_before_deduplication": dict(cropped_counts),
                        "seconds": time.perf_counter() - started_tile}
        log("crop_tile_complete", source=name, sheet=tile["sheet"], **tile["crop"])
    xyz = np.concatenate(xyz_parts) if xyz_parts else np.empty((0, 3), dtype=np.float64)
    classification = np.concatenate(class_parts) if class_parts else np.empty(0, dtype=np.uint8)
    del xyz_parts, class_parts
    xyz, classification, duplicates = deduplicate(xyz, classification)
    if not np.isfinite(xyz).all():
        raise ValueError(f"Non-finite source points in {name}")
    building_counts = []
    for building in buildings:
        geom = building["geometry"]
        inside = shapely.contains_xy(geom, xyz[:, 0], xyz[:, 1])
        annulus = building["buffer"].difference(geom)
        around = shapely.contains_xy(annulus, xyz[:, 0], xyz[:, 1])
        roof_count = int(np.count_nonzero(inside & (classification == 6)))
        ground_count = int(np.count_nonzero(around & (classification == 2)))
        building_counts.append({"building_id": building["id"], "pilot_id": building["pilot_id"],
                                "roof_class6_strict_points": roof_count,
                                "ground_class2_annulus20m_points": ground_count,
                                "roof_class6_points_per_footprint_m2": roof_count / geom.area,
                                "status": "available" if roof_count else "no_class6_roof_points"})
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    output = CROP_DIR / f"{name}.npz"
    temporary = output.with_suffix(".npz.tmp")
    guard.check_budget(reserve_bytes=xyz.nbytes + classification.nbytes + 1_000_000, force=True)
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, xyz=xyz, classification=classification)
    temporary.replace(output)
    result = {"crop_path": relative(output), "crop_file": fingerprint(output),
              "point_count": len(xyz), "class_counts": counts(classification),
              "bounds": [xyz.min(axis=0).tolist(), xyz.max(axis=0).tolist()] if len(xyz) else None,
              "duplicates_removed": duplicates,
              "deduplication": "exact decoded XYZ + classification; stable first occurrence",
              "selection": "all classes within union of original footprint buffers (20 m), boundary included",
              "roof_selection": "classification == 6 and strict interior of unbuffered original footprint",
              "ground_selection": "classification == 2 and strict interior of buffer(20 m) minus original footprint",
              "synthesized_points": 0, "building_counts": building_counts,
              "crop_seconds": time.perf_counter() - started}
    log("crop_complete", source=name, point_count=len(xyz), duplicates_removed=duplicates,
        class_counts=result["class_counts"], seconds=result["crop_seconds"], path=result["crop_path"])
    return result


def prepare_sources(sample_path=DEFAULT_SAMPLE, sources=("dmp1g", "dmpok"), *, force=False):
    """Return/write source manifest; call inside a resource-guarded worker."""
    guard.check_budget(force=True)
    sample_path = Path(sample_path).resolve()
    buildings, union = sample_geometry(sample_path)
    sample_hash = fingerprint(sample_path)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    if MANIFEST_PATH.is_file():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if manifest.get("sample_file") != sample_hash or manifest.get("recipe_version") != RECIPE_VERSION:
            if not force:
                raise ValueError("Existing source manifest uses a different sample/recipe; inspect and use --force")
            manifest = {}
    else:
        manifest = {}
    manifest.update({"schema_version": 1, "recipe_version": RECIPE_VERSION,
                     "manifest_path": relative(MANIFEST_PATH), "sample_file": sample_hash,
                     "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
                     "crs": "EPSG:5514", "vertical_datum": "Bpv",
                     "chunk_points": CHUNK_SIZE, "buffer_metres": BUFFER_METRES,
                     "buffer_union_bounds_epsg5514": list(union.bounds),
                     "buffer_union_area_m2": union.area,
                     "limits": {"max_project_bytes": guard.MAX_PROJECT_BYTES,
                                "min_free_disk_bytes": guard.MIN_FREE_BYTES,
                                "max_job_commit_bytes": 2_000_000_000,
                                "min_available_ram_to_start_bytes": 1_000_000_000},
                     "limitations": ["DMPOK samples are image-correlation surface samples, not independent laser returns.",
                                     "Roof and ground classifications are used unchanged; missing points have no synthetic substitute.",
                                     "File creation/publication dates are not asserted to be survey dates.",
                                     "Exact coordinate-and-class duplicates are removed; differing observations at identical XY are preserved."]})
    manifest.setdefault("sources", {})
    for name in sources:
        if name not in ("dmp1g", "dmpok"):
            raise ValueError(f"Unknown source: {name}")
        existing = manifest["sources"].get(name)
        if existing and not force:
            crop = ROOT / existing["crop_path"]
            if crop.is_file() and fingerprint(crop) == existing["crop_file"]:
                log("source_cached", source=name, path=relative(crop))
                continue
            raise ValueError(f"Recorded crop missing or changed for {name}; inspect and use --force")
        started = time.perf_counter()
        log("source_start", source=name)
        tiles, times = prepare_dmp1g(union) if name == "dmp1g" else prepare_dmpok(union)
        cropped = crop_source(name, tiles, buildings, union)
        manifest["sources"][name] = {"name": name, "tiles": tiles, **cropped,
                                     "times": {**times, "crop_seconds": cropped["crop_seconds"],
                                               "total_seconds": time.perf_counter() - started}}
        if name == "dmpok":
            manifest["sources"][name]["master_feed_file"] = fingerprint(MASTER_FEED)
        write_json(MANIFEST_PATH, manifest)
    write_json(MANIFEST_PATH, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", required=True)
    parser.add_argument("--source", choices=("both", "dmp1g", "dmpok"), default="both")
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    sources = ("dmp1g", "dmpok") if args.source == "both" else (args.source,)
    if args.worker:
        result = prepare_sources(args.sample, sources, force=args.force)
        log("prepare_complete", manifest_path=result["manifest_path"], sources=list(result["sources"]))
        return
    command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--prepare", "--worker",
               "--source", args.source, "--sample", str(args.sample.resolve())]
    if args.force:
        command.append("--force")
    result = guard.run_guarded(command, ROOT, SOURCE_DIR / f"prepare-{args.source}.log",
                               min_available_gb=1.0, max_ram_gb=2.0)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
