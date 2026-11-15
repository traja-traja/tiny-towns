"""Generate a city's Izomapa config from its boundary and cached Terrarium DEM."""

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import tempfile

import numpy as np
from PIL import Image
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon, shape


ROOT = Path(__file__).resolve().parent.parent
HALF = 1150.0
SIDE = 2 * HALF
KY = 110574.0
ZOOM = 12
TERRARIUM_URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium'
MERCATOR_MAX_LAT = 85.0511287798066


@dataclass(frozen=True)
class Grid:
    center: tuple

    @property
    def kx(self):
        return math.cos(math.radians(self.center[1])) * 111320.0

    def to_local(self, coordinates):
        scale = np.array([self.kx, KY])
        return (coordinates - self.center) * scale

    def bbox(self, cells):
        columns, rows = zip(*cells)
        west = (min(columns) * SIDE - HALF) / self.kx + self.center[0]
        east = (max(columns) * SIDE + HALF) / self.kx + self.center[0]
        south = (min(rows) * SIDE - HALF) / KY + self.center[1]
        north = (max(rows) * SIDE + HALF) / KY + self.center[1]
        return west, south, east, north


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def lon_lat(value, field):
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(coordinate) not in (int, float) for coordinate in value)
        or not -180 < value[0] < 180
        or not -MERCATOR_MAX_LAT < value[1] < MERCATOR_MAX_LAT
    ):
        raise ValueError(f'{field} must be a valid [longitude, latitude] pair')
    return tuple(value)


def boundary_geometry(data):
    if not isinstance(data, dict):
        raise ValueError('boundary.geojson must contain a GeoJSON object')
    if data.get('type') == 'FeatureCollection':
        features = data.get('features')
        if not isinstance(features, list) or not features:
            raise ValueError('boundary.geojson has no features')
        return shapely.union_all([boundary_geometry(feature) for feature in features])
    if data.get('type') == 'Feature':
        return boundary_geometry(data.get('geometry'))
    if data.get('type') not in ('Polygon', 'MultiPolygon'):
        raise ValueError('boundary.geojson must contain only polygonal geometry')
    if 'coordinates' not in data:
        raise ValueError('Boundary geometry has no coordinates')
    geometry = shape(data)
    if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty or not geometry.is_valid:
        raise ValueError(f'Invalid municipal boundary: {shapely.is_valid_reason(geometry)}')
    return geometry


def cell_box(cell):
    i, j = cell
    x, y = i * SIDE, j * SIDE
    return shapely.box(x - HALF, y - HALF, x + HALF, y + HALF)


def cells_intersecting(area):
    cells = {(0, 0)}
    # Search each component separately so separated parts do not require scanning the gap.
    for polygon in shapely.get_parts(area):
        west, south, east, north = polygon.bounds
        columns = range(math.ceil((west - HALF) / SIDE), math.floor((east + HALF) / SIDE) + 1)
        rows = range(math.ceil((south - HALF) / SIDE), math.floor((north + HALF) / SIDE) + 1)
        shapely.prepare(polygon)
        cells.update((i, j) for i in columns for j in rows if polygon.intersects(cell_box((i, j))))
    return sorted(cells, key=lambda cell: (-cell[1], cell[0]))


def area_coverage(area, tiles):
    omitted = area.difference(tiles).area
    return {
        'area_m2': area.area,
        'covered_area_m2': area.area - omitted,
        'omitted_area_m2': omitted,
        'coverage_percent': 100 * (1 - omitted / area.area),
    }


@dataclass(frozen=True)
class City:
    directory: Path
    grid: Grid
    map_overrides: dict
    municipality: Polygon | MultiPolygon
    extensions: tuple
    target: Polygon | MultiPolygon
    full_cells: list

    @classmethod
    def load(cls, directory):
        profile = read_json(directory / 'profile.json')
        if not isinstance(profile, dict):
            raise ValueError('profile.json must contain a JSON object')
        grid = Grid(lon_lat(profile.get('center'), 'profile center'))
        map_overrides = profile.get('map')
        if (
            not isinstance(map_overrides, dict)
            or not isinstance(map_overrides.get('nazev'), str)
            or not map_overrides['nazev'].strip()
        ):
            raise ValueError('profile map.nazev must be a nonempty city name')

        boundary = boundary_geometry(read_json(directory / 'boundary.geojson'))
        west, south, east, north = boundary.bounds
        lon_lat([west, south], 'boundary minimum')
        lon_lat([east, north], 'boundary maximum')
        municipality = shapely.transform(boundary, grid.to_local)

        entries = profile.get('extensions', [])
        if not isinstance(entries, list):
            raise ValueError('profile extensions must be an array')
        extensions = []
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get('name'), str)
                or not entry['name'].strip()
            ):
                raise ValueError('Each extension requires a nonempty name')
            center = lon_lat(entry.get('center'), f'extension {entry["name"]} center')
            radius = entry.get('radius_m')
            if type(radius) not in (int, float) or not math.isfinite(radius) or radius <= 0:
                raise ValueError(f'Extension {entry["name"]} requires a positive radius_m')
            polygon = Point(grid.to_local(np.array(center))).buffer(radius, quad_segs=64)
            extensions.append(({'name': entry['name'], 'center': center, 'radius_m': radius}, polygon))

        target = shapely.union_all([municipality, *(polygon for _, polygon in extensions)])
        cells = cells_intersecting(target)
        city = cls(directory, grid, map_overrides, municipality, tuple(extensions), target, cells)
        report = city.coverage(cells)
        areas = [report['municipality'], *report['extensions'], report['target']]
        if any(area['omitted_area_m2'] != 0 for area in areas):
            raise ValueError('Full-map cells leave part of the requested area uncovered')
        return city

    def coverage(self, cells):
        tiles = shapely.union_all([cell_box(cell) for cell in cells])
        return {
            'center': self.grid.center,
            'cell_size_m': SIDE,
            'cell_count': len(cells),
            'full_cell_count': len(self.full_cells),
            'cells': cells,
            'municipality': area_coverage(self.municipality, tiles),
            'extensions': [
                {**extension, **area_coverage(polygon, tiles)}
                for extension, polygon in self.extensions
            ],
            'target': area_coverage(self.target, tiles),
        }

    def preview_cells(self, limit):
        nearest = sorted(self.full_cells, key=lambda cell: (cell[0] ** 2 + cell[1] ** 2, cell))
        selected = set(nearest[:limit])
        return [cell for cell in self.full_cells if cell in selected]


def mercator_tile(lon, lat):
    n = 2 ** ZOOM
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return math.floor(x), math.floor(y)


def terrain_tiles(bounds):
    west, south, east, north = bounds
    lon_lat([west, south], 'map minimum')
    lon_lat([east, north], 'map maximum')
    first_x, first_y = mercator_tile(west, north)
    last_x, last_y = mercator_tile(east, south)
    return [(x, y) for x in range(first_x, last_x + 1) for y in range(first_y, last_y + 1)]


def terrain_suffix(tile):
    x, y = tile
    return f'{ZOOM}/{x}/{y}.png'


def terrain_reference(directory, bounds, tiles):
    west, south, east, north = bounds
    paths = [directory / 'terrain-reference' / terrain_suffix(tile) for tile in tiles]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f'Missing {len(missing)} Terrarium tile(s), including {missing[0]}. See the plan command.')

    n = 2 ** ZOOM
    offsets = (np.arange(256) + 0.5) / 256
    samples = []
    for (x, y), path in zip(tiles, paths):
        with Image.open(path) as image:
            if image.format != 'PNG' or image.size != (256, 256):
                raise ValueError(f'Terrarium tile must be a 256 x 256 PNG: {path}')
            pixels = np.asarray(image.convert('RGB'), dtype=float)
        lon = (x + offsets) / n * 360 - 180
        lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * (y + offsets) / n))))
        inside = ((lat >= south) & (lat <= north))[:, None] & ((lon >= west) & (lon <= east))[None, :]
        heights = pixels[..., 0] * 256 + pixels[..., 1] + pixels[..., 2] / 256 - 32768
        samples.append(heights[inside])
    heights = np.concatenate(samples)
    if not heights.size:
        raise ValueError('No Terrarium samples fall inside the full map extent')
    minimum = float(heights.min())
    percentile = float(np.percentile(heights, 25))
    return {
        'dataset': 'Terrarium',
        'zoom': ZOOM,
        'tile_count': len(tiles),
        'sample_count': int(heights.size),
        'minimum_m': minimum,
        'percentile_25_m': percentile,
        'href': round(percentile, 1),
        'dno': math.floor(minimum - percentile - 30),
    }


def native_config(city, cells, terrain):
    name = city.map_overrides['nazev']
    adjective = f'Izometrick{"á" if name.endswith("a") else "é" if name[-1] in "oeěí" else "ý"}'
    return {
        'nazev': name,
        'titulek': f'{adjective} {name}',
        'h1': [adjective, name],
        'podtitul': f'{name} z otevřených dat, ve stylu SimCity 2000.',
        'popis': f'Izometrická pixel-art mapa města {name}.',
        'url': '',
        'mhd': {'gtfs': None, 'zdroj': None, 'zdroj_url': None},
        'vanocni_strom': None,
        **city.map_overrides,
        'stred': city.grid.center,
        'polovina': HALF,
        'ctverce': cells,
        'href': terrain['href'],
        'dno': terrain['dno'],
    }


def json_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def write_output(path, content, *, overwrite):
    if not overwrite:
        stream = path.open('xb')
        try:
            with stream:
                stream.write(content)
        except OSError:
            path.unlink(missing_ok=True)
            raise
        return

    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(content)
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def positive_int(value):
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return count


def main(argv=None, *, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan', help='list the full map cells and required DEM tiles')
    plan.add_argument('slug')
    generate = commands.add_parser('generate', help='create a native Izomapa config and coverage report')
    generate.add_argument('slug')
    generate.add_argument('--preview', type=positive_int, metavar='N', help='keep up to N nearest cells')
    generate.add_argument('--replace', action='store_true', help='replace an existing config after saving a .bak copy')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', args.slug):
        parser.error('invalid city slug')
    directory = root / 'cities' / args.slug
    try:
        city = City.load(directory)
        bounds = city.grid.bbox(city.full_cells)
        tiles = terrain_tiles(bounds)
        if args.command == 'plan':
            report = city.coverage(city.full_cells)
            report['bounds_lon_lat'] = bounds
            report['terrain_tiles'] = [
                {
                    'path': (directory.relative_to(root) / 'terrain-reference' / terrain_suffix(tile)).as_posix(),
                    'url': f'{TERRARIUM_URL}/{terrain_suffix(tile)}',
                }
                for tile in tiles
            ]
            print(json_text(report), end='')
            return 0

        suffix = '.preview' if args.preview else ''
        path = directory / f'mesto{suffix}.json'
        if path.exists() and not args.replace:
            raise ValueError(f'{path} already exists. Use --replace to save a backup and update it.')
        cells = city.preview_cells(args.preview) if args.preview else city.full_cells
        terrain = terrain_reference(directory, bounds, tiles)
        report = city.coverage(cells)
        report['mode'] = 'preview' if args.preview else 'full'
        report['terrain'] = terrain
        report['terrain_bounds_lon_lat'] = bounds
        config_bytes = json_text(native_config(city, cells, terrain)).encode('utf-8')
        report_bytes = json_text(report).encode('utf-8')
        replace_existing = args.replace and path.exists()
        previous_config = None
        if replace_existing:
            previous_config = path.read_bytes()
            write_output(path.with_suffix('.json.bak'), previous_config, overwrite=True)
        write_output(path, config_bytes, overwrite=replace_existing)
        try:
            write_output(directory / f'coverage{suffix}.json', report_bytes, overwrite=True)
        except OSError:
            if previous_config is None:
                path.unlink()
            else:
                write_output(path, previous_config, overwrite=True)
            raise
    except (OSError, ValueError, TypeError, shapely.GEOSException) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')

    percentage = report['municipality']['coverage_percent']
    print(f'{path} ({len(cells)} cells, {percentage:.6f}% municipal coverage)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
