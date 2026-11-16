"""MODULE configuration: validated defaults, switches and tunable parameters.

Distances are metres, areas m2, fractions 0..1, angles degrees. Thresholds are
not probabilities. A JSON file may override any subset; unknown keys fail fast.
"""
import copy
import math

DEFAULT_CONFIG = {
    'modules': {'annex_detection':True, 'annex_profiles':True, 'flat':True,
                'straight':True, 'skillion':True, 'bent':True, 'networks':True, 'pyramidal':True,
                'parallel_gables':True},
    'parallel_gables': {'max_ridges':4,'min_bay_width_m':3.,'min_segment_width_m':.6,
        'profile_bin_m':.6,'min_prominence_m':.5,'min_rise_m':.6,'min_support_cells':5,
        'support_distance_m':.8,'support_error_m':.6,'max_fit_evaluations':80,'extra_ridge_penalty_m':.025},
    'annex': {'min_depth_m':2., 'min_area_m2':4., 'max_area_fraction':.30,
              'max_total_area_fraction':.35, 'min_attachment_m':1., 'max_candidates':2,
              'min_cells':12, 'min_height_step_m':.6, 'max_join_above_main_m':.5, 'min_error_improvement_m':.25,
              'flat_p80_error_m':.25, 'max_p80_error_m':.6, 'max_slope_deg':15.,
              'plane_complexity_penalty_m':.08,
              'profile_width_m':1., 'profile_inside_m':3., 'profile_edge_exclusion_m':.25,
              'profile_cell_size_m':.35,
              'profile_min_cells':4, 'profile_max_p80_error_m':.65,
              'profile_min_step_m':.3},
    'sampling': {'cell_size_m':.7, 'min_cells':20},
    'scoring': {'mean_weight':.6, 'quantile_weight':.4, 'error_cap_m':1.5,
                'simplification_tolerance_m':.05,
                'quantile':.8, 'hip_end_penalty_m':.012,
                'complexity_m':{'flat':0., 'straight':.035, 'bent':.065, 'skillion':.025,
                                'pyramidal':.05, 'u_shaped':.095, 'ring':.12, 'parallel_gables':.07},
                'weak_branch_penalty_m':.10},
}


def resolve_config(overrides=None):
    result = copy.deepcopy(DEFAULT_CONFIG)
    def merge(target, patch, prefix=''):
        if not isinstance(patch, dict):
            raise ValueError(prefix+' must be an object')
        for key, value in patch.items():
            name = prefix+key
            if key not in target:
                raise ValueError('Unknown roof setting: '+name)
            expected = target[key]
            if isinstance(expected, dict):
                merge(expected, value, name+'.')
            elif isinstance(expected, bool):
                if not isinstance(value, bool):
                    raise ValueError(name+' must be boolean')
                target[key] = value
            else:
                if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value < 0:
                    raise ValueError(name+' must be a finite non-negative number')
                if isinstance(expected, int) and (not isinstance(value, int) or value < 1):
                    raise ValueError(name+' must be a positive integer')
                target[key] = value
    merge(result, overrides or {})
    for group, keys in [('sampling',['cell_size_m']), ('annex',['profile_width_m','profile_inside_m','profile_cell_size_m']),
                        ('parallel_gables',['profile_bin_m','min_segment_width_m','min_bay_width_m']),
                        ('scoring',['error_cap_m'])]:
        if any(result[group][key] <= 0 for key in keys):
            raise ValueError(group+' distances must be positive')
    for key in ('max_area_fraction','max_total_area_fraction'):
        if not 0 < result['annex'][key] < 1:
            raise ValueError(key+' must be between zero and one')
    if not 0 < result['scoring']['quantile'] < 1:
        raise ValueError('scoring.quantile must be between zero and one')
    if result['scoring']['mean_weight']+result['scoring']['quantile_weight'] <= 0:
        raise ValueError('At least one score weight must be positive')
    if not 0 <= result['annex']['max_slope_deg'] < 80:
        raise ValueError('annex.max_slope_deg must be below 80')
    if not 2 <= result['parallel_gables']['max_ridges'] <= 8:
        raise ValueError('parallel_gables.max_ridges must be between 2 and 8')
    if not any(result['modules'][k] for k in ('flat','straight','skillion','bent','networks','pyramidal','parallel_gables')):
        raise ValueError('At least one roof candidate module must be enabled')
    return result


def point_error(absolute, scoring):
    import numpy as np
    return float(scoring['mean_weight']*np.mean(np.minimum(absolute, scoring['error_cap_m']))
                 +scoring['quantile_weight']*np.quantile(absolute, scoring['quantile']))
