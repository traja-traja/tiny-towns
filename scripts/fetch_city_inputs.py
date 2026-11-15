"""Stáhne hranici obce a výšková data pro celou mapu i zkušební výřez."""

import argparse
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import io
import json
import re
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image
from shapely import GEOSException

if __package__:
    from . import configure_city, towns
else:
    import configure_city
    import towns


RUIAN_URL = "https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer"
TERRAIN_REFERENCE_URL = "https://registry.opendata.aws/terrain-tiles/"
TIMEOUT = 20


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def municipality_code(value):
    if type(value) not in {str, int} or not re.fullmatch(r"[0-9]{6}", str(value)):
        raise ValueError(f"Neplatný šestimístný kód obce: {value!r}")
    return int(value)


def download(url):
    request = Request(url, headers={"User-Agent": "Tiny Towns / Izomapa"})
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except (OSError, HTTPException) as error:
        raise ValueError(f"Stažení selhalo ({url}): {error}") from error


def service_json(url):
    try:
        result = json.loads(download(url))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError(f"Služba vrátila neplatný JSON ({url})") from error
    if not isinstance(result, dict):
        raise ValueError(f"Služba nevrátila objekt JSON ({url})")
    if "error" in result:
        raise ValueError(f"Služba RÚIAN vrátila chybu ({url}): {result['error']}")
    return result


def polygon_layer(metadata):
    matches = [layer for layer in metadata.get("layers", [])
               if isinstance(layer, dict) and str(layer.get("name", "")).strip().casefold() in {"obec", "obce"}
               and layer.get("geometryType") == "esriGeometryPolygon"]
    if len(matches) != 1 or type(matches[0].get("id")) is not int or matches[0]["id"] < 0:
        raise ValueError("Metadata RÚIAN neobsahují právě jednu polygonovou vrstvu obcí s platným ID.")
    layer = matches[0]
    fields = {field["name"].casefold(): field["name"] for field in layer.get("fields", [])
              if isinstance(field, dict) and isinstance(field.get("name"), str)}
    if not {"kod", "nazev"} <= fields.keys():
        raise ValueError("V polygonové vrstvě obcí chybí pole KOD nebo NAZEV.")
    return layer["id"], fields["kod"], fields["nazev"]


def boundary_properties(document, code, code_field):
    features = [document]
    if isinstance(document, dict) and document.get("type") == "FeatureCollection":
        features = document.get("features")
    if (not isinstance(features, list) or len(features) != 1
            or not isinstance(features[0], dict) or features[0].get("type") != "Feature"):
        raise ValueError(f"Očekávám právě jeden prvek GeoJSON pro obec {code}.")
    feature = features[0]
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"V prvku GeoJSON pro obec {code} chybí vlastnosti.")
    properties = {key.casefold(): value for key, value in properties.items()}
    if municipality_code(properties.get(code_field.casefold())) != code:
        raise ValueError(f"Kód obce v hranici nesouhlasí s požadavkem na obec {code}.")

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"Hranice obce {code} musí být Polygon nebo MultiPolygon.")
    polygon = configure_city.boundary_geometry(geometry)
    west, south, east, north = polygon.bounds
    configure_city.lon_lat([west, south], "minimum hranice")
    configure_city.lon_lat([east, north], "maximum hranice")
    return properties


def write_json(path, data):
    configure_city.write_output(path, configure_city.json_text(data).encode("utf-8"), overwrite=True)


def fetch_boundary(directory, code, replace):
    path = towns.local_path(directory, "boundary.geojson")
    provenance = towns.local_path(directory, "boundary-source.json")
    if path.exists() and not replace:
        payload = path.read_bytes()
        boundary_properties(json.loads(payload.decode("utf-8")), code, "kod")
        if provenance.exists():
            recorded_hash = towns.read_object(provenance).get("sha256")
            if recorded_hash != hashlib.sha256(payload).hexdigest():
                raise ValueError(f"Otisk {path} nesouhlasí s {provenance.name}. Použij --replace pro nový import hranice.")
        print(f"Použita existující hranice: {path}")
        return
    metadata_url = f"{RUIAN_URL}/layers?f=json"
    layer, code_field, name_field = polygon_layer(service_json(metadata_url))
    query = urlencode({
        "where": f"{code_field}={code}",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    })
    url = f"{RUIAN_URL}/{layer}/query?{query}"
    document = service_json(url)
    properties = boundary_properties(document, code, code_field)
    name = properties.get(name_field.casefold())
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"V prvku RÚIAN pro obec {code} chybí název obce.")
    payload = configure_city.json_text(document).encode("utf-8")
    configure_city.write_output(path, payload, overwrite=replace)
    write_json(provenance, {
        "attribution": "© ČÚZK",
        "layer_id": layer,
        "metadata_url": metadata_url,
        "municipality_code": code,
        "municipality_name": name,
        "retrieved_at": timestamp(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "url": url,
    })
    print(f"Stažena hranice obce {name}: {path}")


def validate_tile(payload, path):
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if image.format != "PNG" or image.size != (256, 256):
                raise ValueError("očekávám PNG o rozměrech 256 × 256")
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValueError(f"Neplatná výšková dlaždice {path}: {error}") from error


def fetch_terrain(directory):
    city = configure_city.City.load(directory)
    tiles = configure_city.terrain_tiles(city.grid.bbox(city.full_cells))
    provenance = towns.local_path(directory, "terrain-source.json")
    previous = towns.read_object(provenance) if provenance.exists() else {}
    previous_tiles = previous.get("tiles", [])
    if not isinstance(previous_tiles, list):
        raise ValueError(f"Neplatný seznam dlaždic v {provenance}")
    recorded = {
        (entry["url"], entry["sha256"]): entry for entry in previous_tiles
        if isinstance(entry, dict) and isinstance(entry.get("url"), str) and isinstance(entry.get("sha256"), str)
    }
    entries = []
    downloaded = 0
    for tile in tiles:
        suffix = configure_city.terrain_suffix(tile)
        path = towns.local_path(directory, "terrain-reference", *suffix.split("/"))
        url = f"{configure_city.TERRARIUM_URL}/{suffix}"
        missing = not path.exists()
        payload = download(url) if missing else path.read_bytes()
        validate_tile(payload, path)
        sha256 = hashlib.sha256(payload).hexdigest()
        entry = {
            **recorded.get((url, sha256), {}),
            "path": path.relative_to(directory).as_posix(),
            "sha256": sha256,
            "url": url,
            "bytes": len(payload),
        }
        if missing:
            path.parent.mkdir(parents=True, exist_ok=True)
            configure_city.write_output(path, payload, overwrite=False)
            entry["retrieved_at"] = timestamp()
            downloaded += 1
        entries.append(entry)
    write_json(provenance, {
        **previous,
        "dataset": "Terrarium",
        "attribution_reference": TERRAIN_REFERENCE_URL,
        "verified_at": timestamp(),
        "zoom": configure_city.ZOOM,
        "tiles": entries,
    })
    print(f"Ověřeno {len(tiles)} výškových dlaždic, nově staženo {downloaded}.")


def main(argv=None, *, root=configure_city.ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", help="Adresář obce v cities/")
    parser.add_argument("--replace", action="store_true", help="Aktualizuj hranici a přegeneruj stávající konfigurace.")
    args = parser.parse_args(argv)
    try:
        directory = towns.city_path(root, args.slug)
        profile = towns.read_object(towns.local_path(directory, "profile.json"))
        fetch_boundary(directory, municipality_code(profile.get("municipality_code")), args.replace)
        fetch_terrain(directory)
        for suffix, options in (("", []), (".preview", ["--preview", "1"])):
            config = towns.local_path(directory, f"mesto{suffix}.json")
            if config.is_file() and not args.replace:
                print(f"Zachována konfigurace: {config}")
                continue
            towns.local_path(directory, f"coverage{suffix}.json")
            if args.replace:
                towns.local_path(directory, f"mesto{suffix}.json.bak")
                options.append("--replace")
            configure_city.main(["generate", args.slug, *options], root=root)
    except (OSError, ValueError, TypeError, GEOSException, towns.TownError) as error:
        print(f"Chyba: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
