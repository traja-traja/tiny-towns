"""Sequential, resumable 2.3 km city preview without a shell or AI services.

The default only prints the plan. Execute AFTER the Velesin roof comparison:
    .venv/Scripts/python.exe scripts/build_preview_guarded.py --execute
Completed steps survive resource stops; invoke the same command to resume.
All generated files stay in .work/.preview/<city>. No publishing is performed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SEASONS = ("autumn", "winter", "spring", "summer")
VARIANTS = (*SEASONS, "lights")
LAYERS = (("buildings", "building"), ("transportation", "segment"),
          ("base", "land_use"), ("base", "water"), ("base", "land_cover"),
          ("base", "infrastructure"), ("base", "land"), ("addresses", "address"))
STEPS = ("harvest", "dmp-fetch", "dmp-heights", "forest", "zabaged", "fields", "prepare",
         *(f"render-{s}" for s in VARIANTS), *(f"dzi-{s}" for s in VARIANTS),
         *(f"trees-{s}" for s in SEASONS), *(f"preview-{s}" for s in SEASONS), "web")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".partial")
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    part.replace(path)


def confined(work, relative):
    """Reject links/junctions before downstream scripts remove output directories."""
    root = Path(work).resolve()
    result = root / relative
    if not result.resolve().is_relative_to(root):
        raise ValueError(f"Output escapes preview workspace: {result}")
    for component in (result, *result.parents):
        if component == root:
            break
        if component.exists():
            info = component.lstat()
            if component.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"Output is a link/junction: {component}")
    return result


def assert_preview(config):
    if config.get("ctverce") != [[0, 0]] or float(config.get("polovina", 0)) != 1150:
        raise ValueError("This runner requires one 2.3 x 2.3 km preview tile")
    if config.get("mhd", {}).get("gtfs"):
        raise ValueError("Basic preview must have GTFS disabled")


def png_present(path):
    try:
        with Path(path).open("rb") as handle:
            return handle.read(8) == b"\x89PNG\r\n\x1a\n" and Path(path).stat().st_size > 32
    except OSError:
        return False


def tile_present(path, image_format):
    if image_format == "png":
        return png_present(path)
    if image_format != "webp":
        return False
    try:
        with Path(path).open("rb") as handle:
            header = handle.read(12)
            return header[:4] == b"RIFF" and header[8:] == b"WEBP" and Path(path).stat().st_size > 20
    except OSError:
        return False


def render_complete(directory):
    directory = Path(directory)
    if (directory / "rozpracovano").exists():
        return False
    try:
        info = read_json(directory / "info.json")
        rows, cols = int(info["rows"]), int(info["cols"])
        return rows > 0 and cols > 0 and all(
            png_present(directory / f"{x}_{y}.png") for y in range(rows) for x in range(cols))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def parquet_present(path, *, require_rows=False):
    import pyarrow.parquet as pq
    try:
        metadata = pq.read_metadata(path)
        return metadata.num_rows > 0 if require_rows else metadata.num_columns > 0
    except (OSError, ValueError):
        return False


def terrain_tiles(bounds, z=14):
    x0, x1, y0, y1 = bounds
    def tile(lon, lat):
        n = 2 ** z
        return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    tx0, ty0 = tile(x0, y1)
    tx1, ty1 = tile(x1, y0)
    return [(z, x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)]


def data_bounds(geo):
    (x0, x1), (y0, y1) = geo.to_lonlat([-geo.HALF - 300, geo.HALF + 300],
                                        [-geo.HALF - 300, geo.HALF + 300])
    return tuple(map(float, (x0, x1, y0, y1)))


def bbox_filter(ds, bounds):
    x0, x1, y0, y1 = bounds
    return ((ds.field("bbox", "xmin") < x1) & (ds.field("bbox", "xmax") > x0)
            & (ds.field("bbox", "ymin") < y1) & (ds.field("bbox", "ymax") > y0))


def stream_parquet(dataset, target, bounds):
    """Limit Arrow prefetch, RAM and disk writes; keep incomplete files uncommitted."""
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
    import resource_guard as guard
    target = Path(target)
    if parquet_present(target, require_rows=target.stem == "building"):
        print(f"Reusing {target}", flush=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".partial")
    scan_options = ds.ParquetFragmentScanOptions(pre_buffer=False, use_buffered_stream=True, buffer_size=65536)
    scanner = dataset.scanner(filter=bbox_filter(ds, bounds), batch_size=8192,
                              batch_readahead=1, fragment_readahead=1, use_threads=False,
                              fragment_scan_options=scan_options)
    rows = 0
    last_notice = time.monotonic()
    try:
        with pq.ParquetWriter(part, scanner.projected_schema) as writer:
            for batch in scanner.to_batches():
                if batch.num_rows == 0:
                    continue
                guard.check_budget(reserve_bytes=max(batch.nbytes * 2, 8_000_000))
                writer.write_batch(batch)
                rows += batch.num_rows
                if time.monotonic() - last_notice > 30:
                    print(f"Scanning {target}: {rows} selected rows so far", flush=True)
                    last_notice = time.monotonic()
        if target.stem == "building" and rows == 0:
            raise ValueError(f"No buildings returned for preview: {target}")
        part.replace(target)
    except BaseException:
        if part.exists():
            part.unlink()  # Only this step's atomic temporary file.
        raise
    print(f"{target}: {rows} rows", flush=True)


def harvest():
    import geo
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pyarrow.fs as fs
    import resource_guard as guard
    from overture_stac_subset import build_index, select_paths
    pa.set_cpu_count(2)
    pa.set_io_thread_count(4)
    # Follow the staged engine's pinned release without importing fetch_data,
    # whose top-level code starts network work.
    match = re.search(r"^REL\s*=\s*['\"]([^'\"]+)['\"]", Path("fetch_data.py").read_text(encoding="utf-8"), re.M)
    if not match:
        raise ValueError("Missing pinned Overture release in fetch_data.py")
    release = match.group(1)
    proxy = os.environ.get("HTTPS_PROXY")
    s3 = fs.S3FileSystem(anonymous=True, region="us-west-2", **({"proxy_options": proxy} if proxy else {}))
    selections = {}
    def remote(theme, typ, target, bounds):
        if parquet_present(target, require_rows=typ == "building"):
            return
        index = build_index(release, theme, typ, Path('build/source-index'))
        paths = select_paths(index, bounds)
        selections[typ] = {'selected_files': paths, 'worldwide_files': len(index['files']), 'bounds': bounds}
        print(f"Reading Overture {theme}/{typ}: {len(paths)} selected files / {len(index['files'])} worldwide; buffered serial scan", flush=True)
        dataset = ds.dataset(paths, filesystem=s3, format="parquet", exclude_invalid_files=False)
        stream_parquet(dataset, target, bounds)
    bounds = data_bounds(geo)
    for theme, typ in LAYERS:
        remote(theme, typ, f"data_all/{typ}.parquet", geo.bbox_lonlat(400))
        stream_parquet(ds.dataset(f"data_all/{typ}.parquet", format="parquet"),
                       f"data/{typ}.parquet", bounds)
    remote("places", "place", "data/places.parquet", geo.bbox_lonlat(0))
    remote("divisions", "division_area", "data_all/division_area.parquet", geo.bbox_lonlat(0))
    for z, x, y in terrain_tiles(bounds):
        target = Path(f"data/dem/{z}_{x}_{y}.png")
        if not png_present(target):
            guard.download(f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
                           target, max_bytes=5_000_000)
        if not png_present(target):
            raise ValueError(f"Invalid terrain PNG: {target}")
    write_json("build/preview-source.json", {"release": release, "bounds": bounds,
               "terrain": "Terrarium z14", "method": "baseline", "preview_only": True,
               "file_selection": selections, "file_index": "Overture official STAC"})


def dmp_fetch():
    import laspy
    import pyarrow.parquet as pq
    import shapely
    import resource_guard as guard
    dest = Path("build/dmp")
    dest.mkdir(parents=True, exist_ok=True)
    atom = dest / "atom.xml"
    guard.download("https://atom.cuzk.gov.cz/DMP1G-SJTSK/DMP1G-SJTSK.xml", atom, max_bytes=80_000_000)
    buildings = {}
    for source in (Path("data/building.parquet"), Path("data_all/building.parquet")):
        for row in pq.read_table(source, columns=["id", "bbox"]).to_pylist():
            buildings[row["id"]] = row["bbox"]
    if not buildings:
        raise ValueError("Cannot select DMP tiles without buildings")
    tree = shapely.STRtree([shapely.box(b["xmin"], b["ymin"], b["xmax"], b["ymax"])
                           for b in buildings.values()])
    selected = []
    for entry in atom.read_text(encoding="utf-8").split("<entry>")[1:]:
        polygon = re.search(r"<georss:polygon>(.*?)<", entry)
        name = re.search(r"DMP1G-SJTSK_([A-Z0-9]+)\.xml", entry)
        if not polygon or not name:
            continue
        values = list(map(float, polygon.group(1).split()))
        box = shapely.box(min(values[1::2]), min(values[0::2]), max(values[1::2]), max(values[0::2]))
        if len(tree.query(box)):
            selected.append(name.group(1))
    if not selected:
        raise ValueError("No matching DMP tiles in ATOM feed")
    for name in sorted(set(selected)):
        target = dest / f"{name}.laz"
        if not target.exists():
            archive = dest / f"{name}.zip"
            guard.download(f"https://openzu.cuzk.cz/opendata/DMP1G/epsg-5514/{name}.zip",
                           archive, max_bytes=1_000_000_000)
            guard.safe_extract_zip(archive, dest)
            if not target.exists():
                raise ValueError(f"Expected LAS/LAZ file absent from archive: {target}")
            archive.unlink()  # Exact archive made by this runner; no recursive cleanup.
        with laspy.open(target) as reader:
            if reader.header.point_count < 1:
                raise ValueError(f"Empty DMP tile: {target}")
    write_json(dest / "preview-manifest.json", {"product": "DMP1G", "sheets": sorted(set(selected))})


class SerialPool:
    """Use the unchanged DMP estimator with one sheet resident in RAM."""
    def __init__(self, *args, **kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def imap_unordered(self, function, iterable):
        return map(function, iterable)


def run_python(script, *args):
    subprocess.run([sys.executable, "-X", "utf8", script, *args], check=True)


def validate_wfs(path):
    from xml.etree import ElementTree
    if ElementTree.parse(path).getroot().tag.split("}")[-1] != "FeatureCollection":
        raise ValueError(f"WFS response is not a feature collection: {path}")


def run_with_guarded_curl(script):
    """Keep existing deterministic processors, but make their downloads atomic."""
    import resource_guard as guard
    original = subprocess.run
    def run(command, *args, **kwargs):
        if command and Path(command[0]).stem.lower() == "curl":
            if "-o" not in command or not command[-1].startswith("https://"):
                raise ValueError("Unrecognized legacy download command")
            target = Path(command[command.index("-o") + 1])
            guard.download(command[-1], target, max_bytes=128_000_000)
            if target.suffix.lower() == ".xml":
                validate_wfs(target)
            return subprocess.CompletedProcess(command, 0)
        return original(command, *args, **kwargs)
    if script == "nastroje/zabaged.py":
        for path in Path("build/zabaged").glob("*.xml"):
            validate_wfs(path)
    subprocess.run = run
    try:
        sys.argv = [script]
        runpy.run_path(script, run_name="__main__")
    finally:
        subprocess.run = original


def internal_step(step, work):
    import resource_guard as guard
    guard.check_budget(force=True)
    for path in ("data", "data_all", "assets", "build", "site", "site/tiles", "site/preview", "site/stromy"):
        confined(work, path)
    if step == "harvest":
        harvest()
    elif step == "dmp-fetch":
        dmp_fetch()
    elif step == "dmp-heights":
        import multiprocessing
        original = multiprocessing.Pool
        multiprocessing.Pool = SerialPool
        try:
            sys.argv = ["dmp_vysky.py"]
            runpy.run_path("dmp_vysky.py", run_name="__main__")
        finally:
            multiprocessing.Pool = original
    elif step in ("forest", "zabaged", "fields", "prepare"):
        script, args = {"forest": ("nastroje/les.py", []), "zabaged": ("nastroje/zabaged.py", []),
                        "fields": ("nastroje/pole.py", []), "prepare": ("prep.py", ["data", "0,0"])}[step]
        if step in ("forest", "zabaged"):
            run_with_guarded_curl(script)
        else:
            run_python(script, *args)
    elif step.startswith(("render-", "trees-")):
        variant = step.split("-", 1)[1]
        args = [shutil.which("node") or "node", "render.mjs", "mpp=0.2", "dir=build", "alpha=1", "offline=1"]
        args.append(f"season={'autumn' if variant == 'lights' else variant}")
        if step.startswith("trees-"):
            args += ["stromy=site/stromy", "out=build/tree-export"]
        else:
            args += [f"out=build/tiles_{variant}", "gx0=-1646.34559672906", "gy1=988.7958500237901"]
            if variant == "lights":
                args.append("mode=lights")
        subprocess.run(args, check=True)
    elif step.startswith("dzi-"):
        variant = step.split("-", 1)[1]
        # dzi.py removes this exact directory recursively; inspect its descendants too.
        target = confined(work, f"site/tiles/{variant}")
        if target.exists():
            for path in target.rglob("*"):
                confined(work, path.relative_to(work))
        run_python("dzi.py", variant)
    elif step.startswith("preview-"):
        from PIL import Image
        variant = step.split("-", 1)[1]
        Path("site/preview").mkdir(parents=True, exist_ok=True)
        output = Path(f"site/preview/{variant}.webp")
        env = dict(os.environ, TRANSPARENT="1")
        subprocess.run([sys.executable, "compose.py", variant, "16", str(output)], check=True, env=env)
        meta = read_json(output.with_suffix(".json"))
        with Image.open(output) as image:
            width = 2400
            height = round(image.height * width / image.width)
            factor = image.width / width
            resized = image.resize((width, height), Image.Resampling.BOX)
        resized.save(output, "WEBP", quality=82, method=6)
        meta.update(mpp=meta["mpp"] * factor, w=width, h=height)
        write_json(output.with_suffix(".json"), meta)
    elif step == "web":
        run_python("overlay.py")
        # The legacy mhd.py deliberately exits nonzero when GTFS is absent.
        # This preview has transport disabled, so do not invoke that script.
        if (read_json("mesto.json").get("mhd") or {}).get("gtfs"):
            run_python("mhd.py")
        run_python("set_status.py", "hotovo")
        run_python("build_html.py")
        write_json("site/preview-build.json", {"preview_only": True, "size_m": [2300, 2300],
                   "roof_method": "baseline", "ai_processing": False,
                   "optional_playgrounds": "not downloaded", "complete": True})
    else:
        raise ValueError(f"Unknown step: {step}")


def validate_step(step, work):
    """Check actual files before accepting a checkpoint or declaring success."""
    work = Path(work)
    if step == "harvest":
        import geo
        return (all(parquet_present(work / folder / f"{kind}.parquet", require_rows=kind == "building")
                    for folder in ("data", "data_all") for _, kind in LAYERS)
                and parquet_present(work / "data/places.parquet")
                and parquet_present(work / "data_all/division_area.parquet")
                and all(png_present(work / f"data/dem/{z}_{x}_{y}.png") for z, x, y in terrain_tiles(data_bounds(geo))))
    if step == "dmp-fetch":
        manifest = read_json(work / "build/dmp/preview-manifest.json")
        return bool(manifest["sheets"]) and all((work / f"build/dmp/{n}.laz").stat().st_size > 227 for n in manifest["sheets"])
    if step == "dmp-heights":
        return bool(read_json(work / "assets/dmp_vysky.json")) and bool(read_json(work / "build/dmp_vysky.json"))
    if step == "forest":
        return (png_present(work / "build/les_maska.png") and bool(read_json(work / "build/les_maska.json"))
                and (work / "build/orto_cele.jpg").stat().st_size > 32)
    if step in ("zabaged", "fields"):
        data = read_json(work / "assets/zabaged.json")
        return all(key in data for key in (("orna", "ttp", "sad", "pole") if step == "fields" else ("orna", "ttp", "sad")))
    if step == "prepare":
        return (bool(read_json(work / "build/scene.json")) and bool(read_json(work / "build/info_src.json"))
                and png_present(work / "build/lightmap.png")
                and all(png_present(work / f"build/ground_{s}.png") for s in SEASONS))
    if step.startswith("render-"):
        return render_complete(work / f"build/tiles_{step.split('-', 1)[1]}")
    if step.startswith("dzi-"):
        variant = step.split("-", 1)[1]
        image = read_json(work / "site/tiles.json")[variant]["Image"]
        width, height = int(image["Size"]["Width"]), int(image["Size"]["Height"])
        tile = int(image["TileSize"])
        image_format = image["Format"]
        maximum = math.ceil(math.log2(max(width, height)))
        return all(tile_present(work / f"site/tiles/{variant}/{level}/{x}_{y}.{image_format}", image_format)
                   for level in range(maximum + 1)
                   for x in range(math.ceil(max(1, math.ceil(width / 2 ** (maximum - level))) / tile))
                   for y in range(math.ceil(max(1, math.ceil(height / 2 ** (maximum - level))) / tile)))
    if step.startswith("trees-"):
        season = step.split("-", 1)[1]
        return png_present(work / f"site/stromy/{season}.png") and bool(read_json(work / f"site/stromy/{season}.json"))
    if step.startswith("preview-"):
        season = step.split("-", 1)[1]
        from PIL import Image
        with Image.open(work / f"site/preview/{season}.webp") as image:
            image.verify()
        return read_json(work / f"site/preview/{season}.json")["w"] == 2400
    if step == "web":
        return (bool(read_json(work / "site/overlay.json")) and bool(read_json(work / "site/preview-build.json")["complete"])
                and (work / "site/index.html").stat().st_size > 1000)
    return False


def checked(step, work):
    try:
        return validate_step(step, work)
    except (OSError, ValueError, KeyError, TypeError):
        return False


@contextmanager
def in_workspace(work):
    previous = Path.cwd()
    os.chdir(work)
    sys.path.insert(0, str(work))
    try:
        yield
    finally:
        sys.path.remove(str(work))
        os.chdir(previous)


def main(argv=None):
    import towns
    import resource_guard as guard
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="ceske-budejovice")
    parser.add_argument("--execute", action="store_true", help="Run only after the roof comparison is complete")
    parser.add_argument("--stop-after", choices=STEPS)
    parser.add_argument("--memory-wait-seconds", type=float, default=3600)
    parser.add_argument("--internal-step", choices=STEPS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    city = towns.city_path(ROOT, args.city)
    assert_preview(towns.read_object(towns.profile_path(city, "preview")))
    work = towns.workspace_path(ROOT, args.city, "preview")
    if args.internal_step:
        if Path.cwd().resolve() != work.resolve():
            raise ValueError("Internal workers must start inside the prepared preview workspace")
        with in_workspace(work):
            internal_step(args.internal_step, work)
            if not validate_step(args.internal_step, work):
                raise ValueError(f"Output validation failed: {args.internal_step}")
        return 0
    if not args.execute:
        print(json.dumps({"workspace": str(work), "size_m": [2300, 2300], "steps": STEPS,
                          "limits": {"project_GB": 20, "minimum_free_C_GB": 25, "workers": 2},
                          "mode": "plan only; no downloads or rendering", "resume": "automatic checkpoints"}, indent=2))
        return 0
    guard.check_budget(force=True)
    work.mkdir(parents=True, exist_ok=True)
    with towns.workspace_lock(work):
        towns.stage(ROOT, city, work, "preview")
        towns.prepare_dependencies(ROOT, work)
        for name in ("build", "site", "data", "data_all"):
            confined(work, name)
        fingerprint = hashlib.sha256(Path(__file__).read_bytes() +
            (ROOT/'scripts/overture_stac_subset.py').read_bytes() +
            (work / towns.MANIFEST).read_bytes()).hexdigest()
        checkpoint = work / "build/preview-checkpoint.json"
        state = read_json(checkpoint) if checkpoint.is_file() else {}
        if state.get("inputs") != fingerprint:
            state = {"inputs": fingerprint, "city": args.city, "completed": {}, "preview_only": True}
        env = towns.command_env(ROOT)
        env.update({key: "2" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                                        "NUMEXPR_NUM_THREADS", "ARROW_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
                                        "IZO_DZI_VLAKNA", "TINY_TOWNS_WORKERS")})
        env.update(NODE_OPTIONS="--max-old-space-size=2048", PYTHONUNBUFFERED="1")
        invalidate = False
        with in_workspace(work):
            for index, step in enumerate(STEPS):
                guard.check_budget(force=True)
                if not invalidate and step in state["completed"] and checked(step, work):
                    print(f"Checkpoint verified: {step}", flush=True)
                else:
                    invalidate = True
                    # A changed or incomplete upstream output invalidates every dependent step.
                    for downstream in STEPS[index:]:
                        state["completed"].pop(downstream, None)
                    state["current_step"] = step
                    write_json(checkpoint, state)
                    minimum = 0.4 if step in ("harvest", "dmp-fetch") else 3.0 if step.startswith(("render-", "trees-", "dzi-")) else 1.0
                    print(f"Starting {step}; log: {work / 'build/preview-logs' / (step + '.log')}", flush=True)
                    metrics = guard.run_guarded(
                        [towns.venv_python(ROOT), "-X", "utf8", Path(__file__), "--city", args.city, "--internal-step", step],
                        cwd=work, log_path=work / "build/preview-logs" / f"{step}.log",
                        min_available_gb=minimum, max_ram_gb=4.0,
                        wait_memory_seconds=args.memory_wait_seconds, env=env)
                    if not checked(step, work):
                        raise ValueError(f"Incomplete output after successful process: {step}")
                    state["completed"][step] = {"finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                "metrics": metrics}
                    state.pop("current_step", None)
                    write_json(checkpoint, state)
                if step == args.stop_after:
                    print(f"Requested checkpoint reached: {step}")
                    return 0
    print(f"Complete local preview: {work / 'site/index.html'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; completed checkpoints are retained.", file=sys.stderr)
        raise SystemExit(130)
