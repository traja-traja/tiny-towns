"""MODULE flat_majority: evidence for simplifying the whole roof to one plane.

Input cells are median XYZ values in the global floor(XY / cell_size) grid.
Local planes establish horizontal surface evidence; clipped grid area, not
point count, establishes dominance. Different height levels are intentionally
collapsed later to the representative height of the largest accepted patch.
"""
import numpy as np
import shapely
from scipy.spatial import cKDTree


def _weighted_median(values, weights):
    order = np.argsort(values, kind='stable')
    cumulative = np.cumsum(weights[order])
    index = min(int(np.searchsorted(cumulative, cumulative[-1] / 2, side='left')), len(order)-1)
    # Select an observed height, never the mean between two separated levels.
    return float(values[order[index]])



def _patch_indices(mask, ij, cells, cell_size, cfg):
    """Join adjacent evidence cells without joining separate roof levels."""
    remaining = {tuple(ij[i]): int(i) for i in np.flatnonzero(mask)}
    while remaining:
        _, seed = remaining.popitem()
        stack, indices = [seed], []
        while stack:
            i = stack.pop()
            indices.append(i)
            x, y = ij[i]
            for dx, dy in ((-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)):
                key = (x+dx, y+dy)
                found = remaining.get(key)
                if found is None:
                    continue
                distance = np.linalg.norm(cells[i,:2]-cells[found,:2])
                max_step = 2*cfg['max_p80_error_m'] + distance*np.tan(np.radians(cfg['max_slope_deg']))
                if abs(cells[i,2]-cells[found,2]) <= max_step:
                    stack.append(remaining.pop(key))
        yield np.asarray(indices, dtype=int)


def _patch_width(indices, ij, cell_size):
    centers = (ij[indices]+.5)*cell_size
    centered = centers-centers.mean(axis=0)
    _, axes = np.linalg.eigh(centered.T @ centered/len(indices))
    widths = np.ptp(centered @ axes,axis=0)+cell_size*np.abs(axes).sum(axis=0)
    return float(np.min(widths))


def detect_flat_majority(poly, cells, cell_size, cfg):
    """Return JSON-safe evidence; this function does not modify the footprint.

    A qualifying local neighbourhood has two-dimensional support, a small
    slope and residual, and also explains its centre cell. Connected patches
    below the configured area/width are ignored. Unknown grid squares never
    count as flat merely because nearby measured squares are flat.
    """
    cells = np.asarray(cells, dtype=float)
    result = {
        'enabled': True, 'accepted': False, 'height_m': None,
        'covered_area_fraction': 0., 'observed_area_fraction': 0.,
        'covered_area_m2': 0., 'footprint_area_m2': float(poly.area),
        'horizontal_cells': 0, 'accepted_cells': 0, 'patches': [],
        'reason': 'insufficient_cells',
        'min_coverage_fraction': float(cfg['min_coverage_fraction']),
        'min_patch_area_fraction': float(cfg['min_patch_area_fraction']),
        'min_largest_patch_fraction': float(cfg['min_largest_patch_fraction']),
        'largest_patch_area_fraction': 0.,
        'height_policy': 'area_weighted_median_observed_height_of_largest_horizontal_patch',
        'area_policy': 'occupied_global_grid_squares_clipped_to_original_footprint',
        'height_levels_preserved': False,
    }
    if poly.area <= 0 or cells.ndim != 2 or cells.shape[1] < 3:
        return result
    cells = cells[np.isfinite(cells[:, :3]).all(axis=1), :3]
    if len(cells) < cfg['min_neighbors']:
        return result
    ij = np.floor(cells[:, :2]/cell_size).astype(np.int64)
    if len(np.unique(ij, axis=0)) != len(ij):
        raise ValueError('Flat-majority detector requires one median point per grid cell')
    lower = ij * cell_size
    squares = shapely.box(lower[:, 0], lower[:, 1], lower[:, 0]+cell_size, lower[:, 1]+cell_size)
    areas = np.asarray(shapely.area(shapely.intersection(squares, poly)), dtype=float)
    result['observed_area_fraction'] = min(1., float(areas.sum()/poly.area))
    neighbours = cKDTree(cells[:, :2]).query_ball_point(cells[:, :2], cfg['radius_m'], workers=1)
    flat = np.zeros(len(cells), dtype=bool)
    slopes = np.full(len(cells), np.nan)
    local_planes = np.full((len(cells), 3), np.nan)
    for index, near in enumerate(neighbours):
        if len(near) < cfg['min_neighbors'] or areas[index] <= 0:
            continue
        points = cells[near]
        xy = points[:, :2] - cells[index, :2]
        centered = xy - xy.mean(axis=0)
        eigenvalues = np.linalg.eigvalsh(centered.T @ centered / len(xy))
        if eigenvalues[1] <= 1e-12 or eigenvalues[0]/eigenvalues[1] < cfg['min_neighbor_axis_ratio']:
            continue
        matrix = np.c_[xy, np.ones(len(xy))]
        plane = np.linalg.lstsq(matrix, points[:, 2], rcond=None)[0]
        slope = float(np.degrees(np.arctan(np.linalg.norm(plane[:2]))))
        residual = np.abs(matrix @ plane - points[:, 2])
        slopes[index] = slope
        local_planes[index] = plane
        flat[index] = (slope <= cfg['max_slope_deg']
                       and np.quantile(residual, .8) <= cfg['max_p80_error_m']
                       and abs(plane[2]-cells[index, 2]) <= cfg['max_p80_error_m'])
    result['seed_horizontal_cells'] = int(flat.sum())
    # MODULE boundary completion: one non-recursive pass over measured cells.
    # A mixed-height neighbourhood rejects even valid flat cells near a step.
    # Recover only cells explained by >=3 planes from substantial seed patches.
    # Newly recovered cells NEVER seed further growth; holes remain unknown.
    if cfg.get('complete_boundaries', True):
        seeds = np.zeros(len(cells), dtype=bool)
        for indices in _patch_indices(flat, ij, cells, cell_size, cfg):
            if (areas[indices].sum() >= cfg['min_patch_area_m2']
                    and _patch_width(indices, ij, cell_size) >= cfg['min_patch_width_m']):
                seeds[indices] = True
        for index in np.flatnonzero(~flat & (areas > 0)):
            near = np.asarray([i for i in neighbours[index] if seeds[i]], dtype=int)
            if len(near) < cfg.get('boundary_min_support', 3):
                continue
            delta = cells[index,:2]-cells[near,:2]
            predicted = np.sum(local_planes[near,:2]*delta, axis=1)+local_planes[near,2]
            supporting = near[np.abs(predicted-cells[index,2]) <= cfg.get('boundary_max_residual_m', .25)]
            if len(supporting) >= cfg.get('boundary_min_support', 3):
                flat[index] = True
                slopes[index] = float(np.median(slopes[supporting]))
    result['boundary_completed_cells'] = int(flat.sum())-result['seed_horizontal_cells']
    result['boundary_completion_radius_m'] = float(cfg['radius_m'])
    result['horizontal_cells'] = int(flat.sum())
    accepted_patches = []
    rejected_count = 0
    for indices in _patch_indices(flat, ij, cells, cell_size, cfg):
        area = float(areas[indices].sum())
        width = _patch_width(indices, ij, cell_size)
        if (area < cfg['min_patch_area_m2'] or width < cfg['min_patch_width_m']
                or area/poly.area < cfg['min_patch_area_fraction']):
            rejected_count += 1
            continue
        accepted_patches.append({
            'area_m2': area, 'area_fraction': float(area/poly.area),
            'height_m': _weighted_median(cells[indices, 2], areas[indices]),
            'cells': int(len(indices)), 'minimum_width_m': width,
            'median_slope_deg': float(np.median(slopes[indices])),
            'height_p10_p90_m': [float(v) for v in np.quantile(cells[indices, 2], [.1, .9])],
        })
    accepted_patches.sort(key=lambda patch: (-patch['area_m2'], patch['height_m']))
    covered = sum(patch['area_m2'] for patch in accepted_patches)
    fraction = min(1., covered/poly.area)
    largest_fraction = accepted_patches[0]['area_fraction'] if accepted_patches else 0.
    accepted = bool(fraction >= cfg['min_coverage_fraction']
                    and largest_fraction >= cfg['min_largest_patch_fraction'])
    result.update(
        accepted=accepted, patches=accepted_patches, rejected_small_patches=rejected_count,
        covered_area_m2=float(covered), covered_area_fraction=float(fraction),
        largest_patch_area_fraction=float(largest_fraction),
        accepted_cells=sum(patch['cells'] for patch in accepted_patches),
        height_m=accepted_patches[0]['height_m'] if accepted else None,
        reason=('horizontal_area_majority' if accepted else
                'horizontal_area_below_threshold' if fraction < cfg['min_coverage_fraction'] else
                'largest_horizontal_patch_below_threshold'),
    )
    return result
