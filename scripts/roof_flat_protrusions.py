"""MODULE flat_protrusions: small, independently switchable flat-roof volumes.

Only call after a single flat base roof has been established. Elevated median
grid cells supply the footprint and one robust top per connected component;
this module does not classify roofs or reconstruct internal height tiers.
"""
from collections import Counter
from itertools import product
from time import perf_counter

import numpy as np
import shapely
from shapely.affinity import rotate
from shapely.geometry import box, mapping

from roof_v2 import _cells


DEFAULTS = {
    'cell_size_m': .35, 'min_height_m': 2., 'min_area_m2': 1.,
    'min_cells': 6, 'min_width_m': .6, 'height_quantile': .9,
    'simplify_tolerance_m': .25, 'max_simplification_area_increase_fraction': .15,
    'regularize_footprints': True, 'regularization_min_retained_area_fraction': .80,
    'regularization_max_vertices': 8,
}


def _components(ij):
    """Four-neighbour connectivity does not merge diagonally touching towers."""
    remaining = {tuple(key): i for i, key in enumerate(ij)}
    for seed in range(len(ij)):
        if tuple(ij[seed]) not in remaining:
            continue
        remaining.pop(tuple(ij[seed]))
        stack, members = [seed], []
        while stack:
            index = stack.pop()
            members.append(index)
            x, y = ij[index]
            for dx, dy in ((-1, 0), (0, -1), (0, 1), (1, 0)):
                found = remaining.pop((x + dx, y + dy), None)
                if found is not None:
                    stack.append(found)
        yield np.asarray(sorted(members), dtype=int)


def _polygons(geom):
    if geom.geom_type == 'Polygon':
        return [geom] if geom.area > 0 else []
    return [part for child in getattr(geom, 'geoms', ()) for part in _polygons(child)]


def _effective_width(poly):
    """Area / major extent rejects long thin lines, including diagonal pixels."""
    rectangle = poly.minimum_rotated_rectangle
    if rectangle.geom_type != 'Polygon':
        return 0.
    edges = np.diff(np.asarray(rectangle.exterior.coords), axis=0)
    major = float(np.linalg.norm(edges, axis=1).max())
    return float(poly.area / major) if major > 0 else 0.


def _separate_ring_contacts(poly, clearance):
    """Open tiny gaps where courtyard/notch rings meet at a single point.

    GEOS permits holes touching at a point in a valid polygon, but extruding
    such a contact produces a vertical edge with four faces. A local diamond
    cut opens that contact without moving the rest of the simplified outline.
    """
    rings = [poly.exterior, *poly.interiors]
    contacts = [a.intersection(b) for i, a in enumerate(rings) for b in rings[i + 1:]
                if a.intersects(b)]
    if not contacts:
        return poly, 0
    cuts = shapely.union_all(contacts).buffer(clearance, quad_segs=1)
    return poly.difference(cuts), len(contacts)


def _building_axis_degrees(poly):
    """The longest exterior wall anchors a stable pair of perpendicular axes."""
    edges = np.diff(np.asarray(poly.exterior.coords), axis=0)
    longest = edges[int(np.argmax(np.linalg.norm(edges, axis=1)))]
    return float(np.degrees(np.arctan2(longest[1], longest[0])) % 90.)


def _regularized_outline(part, footprint, obstacles, angle, settings):
    """Fit a four-corner rectangle, then at most two joined orthogonal boxes.

    This is a small deterministic candidate search, not a bounding-box fill:
    every candidate must retain measured area and obey the added-area limit.
    Unobserved raster holes may disappear; actual building courtyards cannot.
    """
    local = rotate(part, -angle, origin=(0, 0))
    boundary = rotate(footprint, -angle, origin=(0, 0))
    blockers = rotate(obstacles, -angle, origin=(0, 0))
    xmin, ymin, xmax, ymax = local.bounds
    tolerance = settings['simplify_tolerance_m']
    min_retained = settings['regularization_min_retained_area_fraction']
    max_added = settings['max_simplification_area_increase_fraction']
    max_vertices = settings['regularization_max_vertices']
    best = None

    def consider(candidate, method):
        nonlocal best
        candidate = candidate.intersection(boundary).simplify(1e-8, preserve_topology=True)
        if candidate.geom_type != 'Polygon' or not candidate.is_valid or candidate.is_empty:
            return
        vertices = len(candidate.exterior.coords) - 1
        if vertices > max_vertices or candidate.area + 1e-9 < settings['min_area_m2']:
            return
        if not blockers.is_empty and candidate.distance(blockers) < 1e-7:
            return
        supported = float(candidate.intersection(local).area)
        retained = supported / local.area
        added = max(0., float(candidate.area - supported))
        if retained + 1e-9 < min_retained or added > local.area * max_added + 1e-9:
            return
        score = (local.area - supported + added, vertices, candidate.bounds)
        if best is None or score < best[0]:
            if _effective_width(candidate) + 1e-9 < settings['min_width_m']:
                return
            best = (score, candidate, {'simplification': method,
                    'regularization_axis_degrees': angle,
                    'retained_observed_area_fraction': float(retained),
                    'added_area_m2': added, 'added_area_fraction': float(added / local.area),
                    'repaired_ring_contacts': 0})

    # Independent edge trimming handles one-sided raster noise without moving
    # the whole block. The observed-area gate prevents excessive trimming.
    def offsets(span):
        return sorted(set(min(float(value), span * .49) for value in
                          (0., tolerance, 2 * tolerance, (1 - min_retained) * span)))

    dx, dy = offsets(xmax - xmin), offsets(ymax - ymin)
    for left, right, bottom, top in product(dx, dx, dy, dy):
        consider(box(xmin + left, ymin + bottom, xmax - right, ymax - top),
                 'building_aligned_rectangle')
    if best is not None:
        return rotate(best[1], angle, origin=(0, 0)), best[2]

    # A simple L/step is two rectangles sharing a full or partial edge. Keep
    # the joining coordinate fixed while trimming only the outside edges.
    for axis in (0, 1):
        low, high = ((xmin, xmax) if axis == 0 else (ymin, ymax))
        for cut in np.linspace(low, high, 7)[1:-1]:
            masks = ((box(xmin, ymin, cut, ymax), box(cut, ymin, xmax, ymax)) if axis == 0
                     else (box(xmin, ymin, xmax, cut), box(xmin, cut, xmax, ymax)))
            pieces = [local.intersection(mask) for mask in masks]
            if any(piece.is_empty for piece in pieces):
                continue
            for trim_a, trim_b in product((0., tolerance, 2 * tolerance), repeat=2):
                rectangles = []
                for side, (piece, trim) in enumerate(zip(pieces, (trim_a, trim_b))):
                    a, b, c, d = piece.bounds
                    if axis == 0:
                        bounds = (a + trim if side == 0 else cut, b + trim,
                                  cut if side == 0 else c - trim, d - trim)
                    else:
                        bounds = (a + trim, b + trim if side == 0 else cut,
                                  c - trim, cut if side == 0 else d - trim)
                    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                        break
                    rectangles.append(box(*bounds))
                if len(rectangles) == 2:
                    consider(rectangles[0].union(rectangles[1]), 'building_aligned_orthogonal')
    if best is None:
        return None, {'regularization_fallback': 'no_simple_outline_with_sufficient_area_agreement'}
    return rotate(best[1], angle, origin=(0, 0)), best[2]


def detect_flat_protrusions(poly, xyz, base_height, cfg=None):
    """Return flat region dictionaries and compact JSON-safe diagnostics.

    Distances and heights use the input metric coordinate system. Every median
    cell has equal weight in the height quantile, regardless of point density.
    Areas come from occupied grid squares clipped to the actual footprint.
    Simplification may fill small raster notches within a bounded added area.
    It cannot join separate components, cover courtyard holes, or leave the
    building. Added geometry never counts towards the observed-area threshold.
    """
    settings = {**DEFAULTS, **(cfg or {})}
    cell_size = float(settings['cell_size_m'])
    base_height = float(base_height)
    if not np.isfinite(base_height) or not np.isfinite(cell_size) or cell_size <= 0:
        raise ValueError('Finite base height and positive cell_size_m are required')
    for key in ('min_height_m', 'min_area_m2', 'min_width_m', 'simplify_tolerance_m',
                'max_simplification_area_increase_fraction'):
        if not np.isfinite(settings[key]) or settings[key] < 0:
            raise ValueError(f'{key} must be finite and nonnegative')
    if settings['min_cells'] < 1 or not 0 <= settings['height_quantile'] <= 1:
        raise ValueError('min_cells >= 1 and height_quantile in [0, 1] are required')
    if (not 0 < settings['regularization_min_retained_area_fraction'] <= 1
            or settings['regularization_max_vertices'] < 4):
        raise ValueError('regularization requires retained area in (0, 1] and at least four vertices')
    points = np.asarray(xyz, dtype=float)
    if points.size == 0:
        points = np.empty((0, 3))
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError('xyz must have shape (N, 3)')
    diagnostic = {
        'module': 'flat_protrusions', 'base_height_m': base_height,
        'thresholds': {key: bool(settings[key]) if isinstance(DEFAULTS[key], bool)
                       else float(settings[key]) for key in DEFAULTS},
        'connectivity': 4, 'height_method': 'quantile_of_cell_medians',
        'width_method': 'observed_area_divided_by_major_extent',
        'input_points': int(len(points)), 'finite_points': 0,
        'inside_points': 0, 'cells': 0, 'high_cells': 0,
        'connected_components': 0, 'accepted_count': 0, 'rejected_count': 0,
        'observed_area_m2': 0., 'simplified_area_m2': 0., 'components': [],
    }
    points = points[np.isfinite(points).all(axis=1)]
    diagnostic['finite_points'] = int(len(points))
    if poly.is_empty or not poly.is_valid or poly.area <= 0:
        diagnostic['reason'] = 'empty_or_invalid_footprint'
        return [], diagnostic
    points = points[shapely.intersects_xy(poly, points[:, 0], points[:, 1])]
    diagnostic['inside_points'] = int(len(points))
    if not len(points):
        diagnostic['reason'] = 'no_inside_points'
        return [], diagnostic

    # MODULE cell evidence: filter raw points before median aggregation.
    raw_ij = np.floor(points[:, :2] / cell_size).astype(np.int64)
    source_counts = Counter(map(tuple, raw_ij))
    cells = _cells(points, cell_size)
    # Coordinate-wise medians can land in a tiny courtyard even if raw points
    # did not. Do not allow such a cell to seed a volume inside that courtyard.
    cells = cells[shapely.intersects_xy(poly, cells[:, 0], cells[:, 1])]
    diagnostic['cells'] = int(len(cells))
    high = cells[cells[:, 2] - base_height > settings['min_height_m']]
    diagnostic['high_cells'] = int(len(high))
    if not len(high):
        diagnostic['reason'] = 'no_cells_above_height_threshold'
        return [], diagnostic
    ij = np.floor(high[:, :2] / cell_size).astype(np.int64)
    regions, candidates = [], []

    # MODULE component footprints: never substitute an inflated bounding box.
    for component_id, indices in enumerate(_components(ij)):
        diagnostic['connected_components'] += 1
        origins = ij[indices] * cell_size
        ends = (ij[indices] + 1) * cell_size
        squares = shapely.box(origins[:, 0], origins[:, 1],
                              ends[:, 0], ends[:, 1])
        observed = shapely.union_all(shapely.intersection(squares, poly))
        parts = sorted(_polygons(observed), key=lambda part: part.bounds)
        for fragment_id, part in enumerate(parts):
            selected = indices[shapely.intersects_xy(part, high[indices, 0], high[indices, 1])]
            width = _effective_width(part)
            item = {
                'component_id': int(component_id), 'fragment_id': int(fragment_id),
                'cells': int(len(selected)),
                'source_points_in_cells': int(sum(source_counts[tuple(ij[i])] for i in selected)),
                'observed_area_m2': float(part.area), 'effective_width_m': width,
                'simplified_area_m2': 0., 'accepted': False,
            }
            reasons = []
            if len(selected) < settings['min_cells']:
                reasons.append('too_few_cells')
            if part.area + 1e-9 < settings['min_area_m2']:
                reasons.append('insufficient_observed_area')
            if width + 1e-9 < settings['min_width_m']:
                reasons.append('too_narrow')
            if reasons:
                item['reasons'] = reasons
                diagnostic['components'].append(item)
                diagnostic['rejected_count'] += 1
                continue

            height_above = float(np.quantile(high[selected, 2] - base_height,
                                            settings['height_quantile']))
            top_height = base_height + height_above
            item.update(top_height_m=top_height, height_above_base_m=height_above)
            candidates.append((part, item))

    # MODULE simple geometry: remove raster notches without re-clipping to the
    # raster. That former intersection reintroduced steps and diagonal point
    # contacts (four vertical faces at one edge in the extruded roof mesh).
    emitted = []
    building_axis = _building_axis_degrees(poly)
    for index, (part, item) in enumerate(candidates):
        obstacles = shapely.union_all([p for j, (p, _) in enumerate(candidates) if j != index] + emitted)
        simple = None
        if settings['regularize_footprints']:
            started = perf_counter()
            simple, regularization = _regularized_outline(part, poly, obstacles, building_axis, settings)
            item.update(regularization)
            item['regularization_seconds'] = float(perf_counter() - started)
        for tolerance in (() if simple is not None else
                          (settings['simplify_tolerance_m'], settings['simplify_tolerance_m'] / 2, 0.)):
            proposed = part.simplify(tolerance, preserve_topology=True).intersection(poly)
            repaired_contacts = 0
            if proposed.geom_type == 'Polygon':
                proposed, repaired_contacts = _separate_ring_contacts(
                    proposed, max(1e-4, min(cell_size * .1, settings['simplify_tolerance_m'] * .1)))
            if (proposed.geom_type != 'Polygon' or not proposed.is_valid
                    or proposed.area + 1e-9 < settings['min_area_m2']
                    or _effective_width(proposed) + 1e-9 < settings['min_width_m']):
                continue
            added_area = float(proposed.difference(part).area)
            if added_area > part.area * settings['max_simplification_area_increase_fraction'] + 1e-9:
                continue
            # A zero-area contact is also forbidden: extruding it creates a
            # nonmanifold shared vertical edge even though 2D overlap is zero.
            if not obstacles.is_empty and proposed.distance(obstacles) < 1e-7:
                continue
            simple = proposed
            item.update(simplification='bounded_topology_preserving',
                        simplification_tolerance_m=float(tolerance),
                        repaired_ring_contacts=int(repaired_contacts),
                        added_area_m2=added_area,
                        added_area_fraction=float(added_area / part.area))
            break
        if simple is None:
            item['reasons'] = ['unable_to_simplify_without_component_contact']
            diagnostic['components'].append(item)
            diagnostic['rejected_count'] += 1
            continue
        item.update(accepted=True, reasons=[], simplified_area_m2=float(simple.area),
                    exterior_vertices=int(len(simple.exterior.coords) - 1),
                    interior_vertices=int(sum(len(ring.coords) - 1 for ring in simple.interiors)))
        emitted.append(simple)
        regions.append({'polygon': mapping(simple), 'plane': [0., 0., item['top_height_m']]})
        diagnostic['components'].append(item)
        diagnostic['accepted_count'] += 1
        diagnostic['observed_area_m2'] += float(part.area)
        diagnostic['simplified_area_m2'] += float(simple.area)
    diagnostic['reason'] = 'accepted' if regions else 'all_components_rejected'
    return regions, diagnostic
