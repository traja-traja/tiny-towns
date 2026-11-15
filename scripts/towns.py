"""Příprava a sestavení samostatných map Tiny Towns."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ENGINE_FILES = frozenset("""
    build_html.py compose.py dmp_fetch.py dmp_vysky.py dzi.py fetch_data.py
    geo.py mhd.py novy_mesto.py overlay.py package-lock.json package.json
    postav.sh prep.py preview.py render.html render.mjs render_all.sh
    render_chunk.sh render_ctverec.sh render_par.sh road_route.py set_status.py
""".split())
ENGINE_DIRS = ("functions", "hlaseni", "nastroje", "web")
CITY_FILES = ("mesto.json", "mista.json")
CITY_DIRS = ("assets", "obce")
DEPS = (".venv", "node_modules")
THREE_BUILD = ("node_modules", "three", "build")
MANIFEST = ".towns-inputs.json"
WINDOWS_ACTIVATE = """# Pripravil scripts/towns.py.
VIRTUAL_ENV="$(cd {relative} && pwd)/.venv"
PATH="$VIRTUAL_ENV/Scripts:$PATH"
export VIRTUAL_ENV PATH
unset PYTHONHOME
"""


class TownError(Exception):
    pass


def file_info(path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def local_path(base, *parts):
    """Keep inputs and writable workspace paths off symlinks and Windows junctions."""
    for index, part in enumerate(parts):
        base = base / part
        info = file_info(base)
        if info is not None and is_link(info):
            raise TownError(f"Cesta nesmí být odkaz: {base}")
        if info is not None and index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise TownError(f"Očekávám složku: {base}")
    return base


def city_path(root, slug):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or PureWindowsPath(slug).is_reserved():
        raise TownError(f"Neplatné označení města: {slug!r}")
    city = local_path(root, "cities", slug)
    if not city.is_dir():
        raise TownError(f"Neznámé město: {slug}")
    return city


def read_object(path):
    if not path.is_file():
        raise TownError(f"Chybí soubor: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise TownError(f"Neplatný JSON v {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TownError(f"Očekávám objekt JSON: {path}")
    return value


def profile_path(city, profile):
    return local_path(city, "mesto.preview.json" if profile == "preview" else "mesto.json")


def workspace_path(root, slug, profile):
    if profile == "preview":
        return local_path(root, ".work", ".preview", slug)
    return local_path(root, ".work", slug)


def geography(config):
    try:
        lon, lat = config["stred"]
        half = float(config.get("polovina", 1150.0))
        height, floor = float(config["href"]), float(config["dno"])
        cells = [tuple(cell) for cell in config["ctverce"]]
        valid = (
            type(lon) in (int, float) and type(lat) in (int, float)
            and -180 <= lon <= 180 and -90 < lat < 90
            and half > 0 and all(map(math.isfinite, (half, height, floor)))
            and all(len(cell) == 2 and all(type(value) is int for value in cell) for cell in cells)
            and (0, 0) in cells and len(set(cells)) == len(cells)
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise TownError("Neplatná geometrie v mesto.json (stred, polovina, href, dno a ctverce včetně [0, 0]).")
    return (float(lon), float(lat), half, height, floor, tuple(sorted(cells)))


def eligible_name(name):
    return (
        not name.startswith(".") and not PureWindowsPath(name).is_reserved()
        and name.rstrip(" .") == name
        and not any(char in name for char in '\\:<>"|?*')
        and name not in {"__pycache__", "node_modules", "wrangler.jsonc", "wrangler.toml"}
    )


def managed_path(name):
    path = PurePosixPath(name)
    if path.parts[:3] == THREE_BUILD:
        return len(path.parts) == 4 and path.as_posix() == name and eligible_name(path.name) and path.suffix == ".js"
    return name in ENGINE_FILES or name in CITY_FILES or (
        len(path.parts) > 1 and path.as_posix() == name
        and path.parts[0] in ENGINE_DIRS + CITY_DIRS
        and all(eligible_name(part) for part in path.parts)
    )


def input_files(base, files, directories):
    def visit(rel):
        path = local_path(base, *rel.parts)
        info = file_info(path)
        if info is None:
            return
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir()):
                if eligible_name(child.name):
                    yield from visit(rel / child.name)
        elif stat.S_ISREG(info.st_mode) and managed_path(rel.as_posix()):
            yield rel.as_posix(), path
        else:
            raise TownError(f"Neplatný vstupní soubor: {path}")

    for name in sorted(files):
        path = local_path(base, name)
        if path.is_file():
            yield name, path
        elif path.exists():
            raise TownError(f"Očekávám soubor: {path}")
    for name in directories:
        yield from visit(PurePosixPath(name))


def browser_modules(root):
    """Node can resolve ancestor packages, but the renderer serves Three.js over HTTP."""
    build = local_path(root, *THREE_BUILD)
    if build.is_dir():
        for file in sorted(build.glob("*.js")):
            name = file.relative_to(root).as_posix()
            if managed_path(name):
                yield name, local_path(build, file.name)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def replace_file(destination, write):
    """Keep the previous file usable until its replacement has been written."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        write(temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def stage(root, city, work, profile):
    config_path = profile_path(city, profile)
    area = geography(read_object(config_path))
    area_hash = hashlib.sha256(json.dumps(area).encode("ascii")).hexdigest()
    manifest = local_path(work, MANIFEST)
    recorded = read_object(manifest) if manifest.exists() else {}
    previous = recorded.get("files", {})
    if not isinstance(previous, dict) or any(
        not managed_path(name) or not isinstance(code, str) or not re.fullmatch(r"[0-9a-f]{64}", code)
        for name, code in previous.items()
    ):
        raise TownError(f"Neplatný seznam připravených souborů: {manifest}")
    assets = local_path(work, "assets")
    if assets.exists() and not assets.is_dir():
        raise TownError(f"Očekávám složku: {assets}")
    cache_paths = [path for path in work.iterdir() if path.name in {"build", "data", "site"}
                   or path.name.startswith("data_")]
    for path in cache_paths:
        if not local_path(work, path.name).is_dir():
            raise TownError(f"Očekávám složku: {path}")
    other_assets = assets.is_dir() and any(
        path.is_file() and f"assets/{path.name}" not in previous for path in assets.iterdir()
    )
    if (cache_paths or other_assets) and recorded.get("area") != area_hash:
        raise TownError(f"Geometrie mapy se změnila nebo chybí. Přesuň {work} do zálohy a spusť prepare znovu.")

    sources = dict(input_files(root, ENGINE_FILES, ENGINE_DIRS))
    sources.update(input_files(city, ("mista.json",), CITY_DIRS))
    sources["mesto.json"] = config_path
    if os.name == "nt":
        sources.update(browser_modules(root))
    desired = {name: digest(source) for name, source in sources.items()}

    changes = []
    for name in sorted(previous.keys() | desired.keys()):
        target = local_path(work, *PurePosixPath(name).parts)
        info = file_info(target)
        if info is not None and not stat.S_ISREG(info.st_mode):
            raise TownError(f"Očekávám soubor: {target}")
        actual = digest(target) if info is not None else None
        if actual == desired.get(name):
            continue
        if actual is not None and actual != previous.get(name):
            raise TownError(f"Pracovní soubor byl změněn: {target}. Ulož úpravy do {city} nebo soubor přesuň.")
        changes.append((target, sources.get(name)))

    for target, source in changes:
        if source is None:
            target.unlink()
        else:
            replace_file(target, lambda temporary: shutil.copy2(source, temporary))
    assets.mkdir(exist_ok=True)
    replace_file(manifest, lambda temporary: temporary.write_text(
        json.dumps({"area": area_hash, "files": desired}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    ))


@contextmanager
def workspace_lock(work):
    """Prevent simultaneous writes to one map while leaving the other map independent."""
    lock = local_path(work, ".towns.lock")
    with lock.open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise TownError(f"Pracovní složku právě používá jiný příkaz: {work}") from exc
        yield


def prepare_dependencies(root, work):
    if os.name == "nt":
        if venv_python(root).is_file():
            activate = local_path(work, ".venv", "Scripts", "activate")
            content = WINDOWS_ACTIVATE.format(relative=Path(os.path.relpath(root, work)).as_posix())
            if not activate.exists():
                replace_file(activate, lambda temporary: temporary.write_bytes(content.encode("ascii")))
            elif activate.read_text(encoding="utf-8") != content:
                raise TownError(f"Pracovní soubor byl změněn: {activate}")
        return
    for name in DEPS:
        source = root / name
        if not source.is_dir():
            continue
        destination = work / name
        info = file_info(destination)
        if info is None:
            destination.symlink_to(os.path.relpath(source, work), target_is_directory=True)
        elif not is_link(info) or destination.resolve() != source.resolve():
            raise TownError(f"Složka {destination} koliduje se sdílenými závislostmi v {source}.")


def bash_path():
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            for install in Path(git).resolve().parents[:3]:
                bash = install / "bin" / "bash.exe"
                if bash.is_file():
                    return str(bash)
        raise TownError("Hledám Git Bash pro Windows. Ověř, že je git v PATH.")
    return shutil.which("bash") or shutil.which("sh") or "sh"


def command_env(root):
    env = dict(os.environ, PYTHONUTF8="1")
    env.pop("IZO_MESTO", None)
    env["PATH"] = str(venv_python(root).parent) + os.pathsep + env.get("PATH", "")
    browsers = root / ".runtime" / "browsers"
    if browsers.is_dir():
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
    return env


def venv_python(root):
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_command(root, work, args):
    args = list(args)
    if args[0] in {"python", "python3"}:
        python = venv_python(root)
        if not python.is_file():
            raise TownError("Chybí sdílené prostředí .venv. Spusť setup.sh z kořene projektu.")
        args[0] = str(python)
    elif args[0] in {"bash", "sh"}:
        args[0] = bash_path()
    result = subprocess.run(args, cwd=work, env=command_env(root))
    if result.returncode:
        raise TownError(f"Příkaz v {work} skončil s kódem {result.returncode}: {' '.join(args)}")


def status(root, slug, profile):
    city = city_path(root, slug)
    config = read_object(profile_path(city, profile))
    area = geography(config)
    work = workspace_path(root, slug, profile)
    site = local_path(work, "site")
    state = "nepřipraveno"
    if local_path(work, MANIFEST).is_file():
        state = "připraveno"
    if local_path(site, "tiles").is_dir() and all(
        local_path(site, name).is_file() for name in ("index.html", "tiles.json", "overlay.json")
    ):
        state = "web dostupný"
    print(f"{slug}: {config.get('nazev', slug)}, čtverců {len(area[-1])}, {state} ({site})")


def port_number(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port musí být od 1 do 65535.")
    return port


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("status", "Zobrazí stav jedné mapy nebo všech map."),
        ("prepare", "Připraví samostatné prostředí pro město."),
        ("build", "Sestaví mapu pomocí izomapy."),
        ("run", "Spustí příkaz v pracovním adresáři města."),
        ("preview", "Spustí místní HTTP server s mapou."),
    ):
        child = commands.add_parser(command, help=help_text)
        child.add_argument("--profile", choices=("full", "preview"), default="full",
                           help="Výchozí celá mapa nebo předem připravený výřez pro náhled.")
        if command == "status":
            child.add_argument("slug", nargs="?")
        else:
            child.add_argument("slug")
        if command == "build":
            child.add_argument("--render-only", action="store_true", help="Použije stažená data.")
        if command == "run":
            child.add_argument("args", nargs=argparse.REMAINDER)
        if command == "preview":
            child.add_argument("--port", type=port_number, default=8000)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            cities = local_path(root, "cities")
            slugs = [args.slug] if args.slug else sorted(
                path.name for path in cities.iterdir() if path.is_dir() and not path.name.startswith(".")
            )
            for slug in slugs:
                status(root, slug, args.profile)
            return 0

        city = city_path(root, args.slug)
        work = workspace_path(root, args.slug, args.profile)
        if args.command == "preview":
            site = local_path(work, "site")
            if not local_path(site, "index.html").is_file():
                raise TownError(f"Chybí náhled: {site / 'index.html'}. Nejdřív sestav mapu.")
            print(f"{args.slug}: http://127.0.0.1:{args.port}", flush=True)
            run_command(root, work, [sys.executable, "-m", "http.server", "--bind", "127.0.0.1",
                                     "--directory", str(site), str(args.port)])
            return 0

        if args.command == "run" and not args.args:
            parser.error("Za označením města zadej příkaz.")
        work.mkdir(parents=True, exist_ok=True)
        with workspace_lock(work):
            stage(root, city, work, args.profile)
            prepare_dependencies(root, work)
            if args.command == "build":
                if (not venv_python(root).is_file() or not (root / "node_modules" / "playwright").is_dir()
                        or not (root.joinpath(*THREE_BUILD) / "three.module.js").is_file()):
                    raise TownError("Chybí závislosti. Spusť setup.sh z kořene projektu.")
                command = ["sh", "./postav.sh"]
                if args.render_only:
                    command.append("render")
                run_command(root, work, command)
                print(f"Hotovo: {work / 'site'}")
            elif args.command == "run":
                run_command(root, work, args.args)
            else:
                print(f"Připraveno: {work}")
        return 0
    except (OSError, TownError) as exc:
        print(f"Chyba: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
