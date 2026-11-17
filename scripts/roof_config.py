"""MODULE configuration: validated defaults, switches and tunable parameters.

Distances are metres, areas m2, fractions 0..1, angles degrees. Thresholds are
not probabilities. A JSON file may override any subset; unknown keys fail fast.
"""
import copy
import math

ALGORITHM_VERSION = 'modular-roofs-4.13.0'

DEFAULT_CONFIG = {
    # Legacy fixed-right-angle L template is opt-in only for reproducing old runs.
    'modules': {'annex_detection':True, 'annex_profiles':True, 'flat':True,
                'straight':True, 'skillion':True, 'bent':False, 'networks':True, 'pyramidal':True,
                'parallel_gables':True, 'primary_wall_envelope':True, 'flat_majority':True, 'flat_protrusions':True,
                'connected_wings':True, 'footprint_regularization':True, 'butterfly':True,
                'footprint_support':False, 'footprint_connector':True, 'observed_ridges':False, 'straight_skeleton':True},
    'footprint_connector': dict(enabled=True,min_area_m2=240.,min_body_area_m2=80.,
    min_body_area_fraction=.18,min_body_to_connector_area_ratio=1.4,
    min_connector_width_m=1.5,max_connector_width_m=7.,
    min_connector_length_m=6.,min_connector_aspect=2.,
    min_body_width_ratio=1.65,max_connector_area_fraction=.25,
    min_connector_rectangularity=.80,min_body_rectangularity=.50,
    min_source_edge_m=2.,max_cut_angle_difference_deg=30.,max_cut_candidates=32,
    bend_tolerance_deg=15.,min_arm_edge_m=3.,min_width_ratio=1.65,
    max_cut_width_m=14.,max_cut_to_narrow_width_ratio=1.35),
    'straight_skeleton': dict(min_area_m2=25.,min_cells=35,min_height_span_m=.6,
        simplify_m=.35,min_concavity_fraction=.035,min_rectangle_loss_fraction=.08,
        min_edges=5,max_edges=60,max_cells=12000,complexity_penalty_m=.065,
        extra_plane_penalty_m=.005,extra_gable_penalty_m=.005,
        reference_area_penalty_m=.25,evidence_inset_m=.8,evidence_strip_m=1.5,
        max_gable_candidates=6,max_nfev=65),
    'observed_ridges': dict(cell_m=.5,edge_exclusion_m=.65,min_wall_m=2.,max_axes=6,
    axis_merge_degrees=10.,slice_step_m=1.2,slice_width_m=1.6,profile_bin_m=.5,
    flank_window_m=4.5,min_flank_span_m=1.5,min_flank_bins=3,
    min_slope=.14,max_slope=2.5,max_profile_error_m=.28,
    min_prominence_m=.45,track_gap_slices=2,track_offset_m=1.2,
    track_height_step_m=.7,min_length_m=3.6,min_sections=4,
    max_height_span_m=.65,max_ridge_grade=.07,max_line_error_m=.4,
    max_direction_adjust_degrees=15.,max_lines=8),
    'footprint_support': {'remove_unsupported':True,'fill_notches':True,'cell_m':.5,
        'min_roof_height_m':2.5,'max_ground_height_m':1.5,'min_area_m2':4.,
        'max_removed_area_fraction':.20,'max_removed_total_fraction':.25,
        'max_roof_coverage_for_removal':.025,'min_ground_coverage_for_removal':.30,
        'min_cut_edge_m':1.,'max_removals':3,'min_remaining_area_fraction':.65,
        'max_notch_area_m2':30.,'max_notch_area_fraction':.08,
        'max_notch_opening_m':6.,'max_notch_depth_m':6.,'max_notch_chain_edges':6,
        'min_roof_coverage_for_fill':.65,'max_ground_coverage_for_fill':.10,
        'min_roof_cells':12,'max_notch_fills':3,'neighbor_band_m':1.,
        'max_neighbor_distance_m':1.5,'max_height_difference_m':.65,
        'neighbor_slope_allowance':.75,'min_continuity_fraction':.75},
    'butterfly': {'min_width_m':3., 'min_rise_m':.35, 'min_side_fraction':.12,
        'min_side_cells':8, 'min_support_fraction':.30, 'support_error_m':.6,
        'min_observed_rise_m':.20, 'max_slope_deg':75., 'max_nfev':65,
        'end_cap_required':True, 'end_cap_penalty_m':.015, 'min_cap_fraction':.02,
        'max_cap_fraction':.45, 'min_wall_m':2., 'wall_angle_deg':12., 'wall_offset_m':1.5,
        'local_direction_check':True, 'local_radius_m':1.5, 'local_max_p80_error_m':.25,
        'local_min_neighbors':6, 'local_min_cells':8, 'min_directional_fraction':.60,
        'min_directional_slope':.05},
    'footprint_regularization': {'max_depth_m':1.25, 'min_repeats':3, 'min_span_m':6.,
        'min_parallel_segment_m':.25, 'max_angle_deg':8., 'max_area_change_fraction':.10,
        'max_boundary_shift_m':1.5, 'max_passes':8},
    'flat_majority': {'radius_m':1.5, 'min_neighbors':6, 'max_slope_deg':7.,
        'max_p80_error_m':.25, 'min_patch_area_m2':4., 'min_patch_width_m':1.2,
        'min_coverage_fraction':.55, 'min_patch_area_fraction':.05, 'min_largest_patch_fraction':.20, 'min_neighbor_axis_ratio':.08,
        'complete_boundaries':True, 'boundary_min_support':3, 'boundary_max_residual_m':.25},
    'flat_protrusions': {'cell_size_m':.35, 'min_height_m':2., 'min_area_m2':1.,
        'min_cells':6, 'min_width_m':.6, 'height_quantile':.9, 'simplify_tolerance_m':.25, 'max_simplification_area_increase_fraction':.15,
        'regularize_footprints':True, 'regularization_min_retained_area_fraction':.80, 'regularization_max_vertices':8},
    'connected_wings': {'paired_ridge_variants':True, 'max_paired_layouts':8,
        'paired_min_coverage_fraction':.85, 'paired_ridge_offset_limit':.35, 'paired_complexity_penalty_m':.075,
        'paired_min_support_fraction':.15, 'paired_weak_support_penalty_m':.05,
        'paired_min_supported_span_m':2., 'paired_max_slope_deg':85., 'paired_min_roof_height_m':.5,
        'canonicalize_caps':True, 'cap_merge_angle_deg':3., 'cap_merge_height_m':.25,
        'finite_joined_variants':True, 'local_gable_inset_min_m':.8, 'local_gable_inset_max_m':1.5,
        'local_gable_min_cells':6, 'local_gable_min_bins':3, 'local_gable_min_raise_m':.2,
        'local_gable_min_improvement_m':.1, 'local_gable_support_error_m':.8,
        'local_gable_min_support_fraction':.5, 'local_gable_max_ends':4,
        'simplify_m':.65, 'min_wall_m':3., 'max_parallel_deviation_deg':16.,
        'min_width_m':3., 'max_width_m':30., 'min_length_m':3., 'max_wings':6,
        'min_new_area_fraction':.035, 'max_nfev':65, 'min_concavity_fraction':.04,
        'gable_variants':True, 'extend_junctions':True, 'outer_end_variants':True,
        'merge_wall_segments':True, 'wall_merge_distance_m':1.8, 'wall_merge_angle_deg':7.,
        'min_wing_aspect':0., 'snap_frame_max_deviation_deg':8.,
        'convex_courtyard_reference':True, 'separate_eave_variants':True,
        'eave_difference_threshold_m':1., 'min_wing_cells':20, 'separate_eave_penalty_m':.04,
        'complexity_penalty_m':.065,
        'snap_frame_max_shift_m':.30,'supported_subset_variants':True,'extend_supported_wings':True,'anchor_actual_end_walls':True,
        'ridge_support_distance_m':.9,'ridge_support_height_m':.9,
        'min_ridge_support_cells':8,'min_ridge_support_fraction':.35},
    'parallel_gables': {'symmetric_bays':True, 'max_slope_deg':65., 'max_ridges':4,'min_bay_width_m':3.,'min_segment_width_m':.6,
        'profile_bin_m':.6,'min_prominence_m':.5,'min_rise_m':.6,'min_support_cells':5,
        'support_distance_m':.8,'support_error_m':.6,'min_supported_span_fraction':.5,
        'max_fit_evaluations':80,'extra_ridge_penalty_m':.025},
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
                'simplification_tolerance_m':.10,
                'protect_main_eaves':True, 'main_eave_min_length_m':6.,
                'main_eave_parallel_deg':12., 'main_eave_reference_span_m':.20,
                'main_eave_height_tolerance_m':.35, 'main_eave_max_span_increase_m':.30,
                'main_eave_probe_inset_m':.35, 'main_eave_min_supported_fraction':.60,
                'main_eave_gable_match_distance_m':.20, 'main_eave_gable_match_fraction':.80,
                'courtyard_topology_tolerance_m':.025,
                'min_courtyard_area_m2':9., 'min_courtyard_area_fraction':.03,
                'quantile':.8, 'hip_end_penalty_m':.012,
                'complexity_m':{'flat':0., 'straight':.035, 'bent':.065, 'skillion':.025,
                                'pyramidal':.05, 'u_shaped':.095, 'ring':.12, 'parallel_gables':.07, 'butterfly':.035},
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
    connector=result['footprint_connector']
    if not 0<=connector['bend_tolerance_deg']<=30 or connector['min_width_ratio']<=1:
        raise ValueError('Footprint bends need tolerance <= 30 degrees and a width ratio > 1')
    if not 0<connector['min_connector_width_m']<=connector['max_connector_width_m']<=connector['max_cut_width_m']:
        raise ValueError('Footprint connector width limits must be positive and ordered')
    for key in ('min_body_area_fraction','max_connector_area_fraction','min_connector_rectangularity','min_body_rectangularity'):
        if not 0<connector[key]<=1:raise ValueError('footprint_connector.'+key+' must be in (0,1]')
    for key in ('min_area_m2','min_body_area_m2','min_connector_length_m','min_source_edge_m','min_arm_edge_m'):
        if connector[key]<=0:raise ValueError('footprint_connector.'+key+' must be positive')
    if connector['min_connector_aspect']<1 or connector['min_body_width_ratio']<=1 or connector['max_cut_to_narrow_width_ratio']<1:
        raise ValueError('Footprint connector proportions must express a narrow elongated part')
    skeleton=result['straight_skeleton']
    if not 0<=skeleton['evidence_inset_m']<skeleton['evidence_strip_m']:
        raise ValueError('straight_skeleton evidence band must have 0 <= inset < maximum')
    if skeleton['min_cells']<20 or skeleton['min_edges']<4 or skeleton['max_edges']<skeleton['min_edges']:
        raise ValueError('Invalid straight_skeleton point/edge bounds')
    if not 1<=skeleton['max_gable_candidates']<=6:
        raise ValueError('straight_skeleton max_gable_candidates must be 1..6')
    butterfly = result['butterfly']
    if min(butterfly[k] for k in ('min_width_m','min_rise_m','support_error_m')) <= 0:
        raise ValueError('butterfly dimensions must be positive')
    if not 0 < butterfly['min_side_fraction'] < .5 or not 0 < butterfly['min_support_fraction'] <= 1 or not 0 < butterfly['max_slope_deg'] < 85:
        raise ValueError('Invalid butterfly support or angle threshold')
    if not 0 <= butterfly['min_cap_fraction'] < butterfly['max_cap_fraction'] < 1 or not 0 < butterfly['min_directional_fraction'] <= 1:
        raise ValueError('Invalid butterfly cap/directional area threshold')
    if min(butterfly[k] for k in ('local_radius_m','local_max_p80_error_m','min_wall_m','wall_offset_m')) <= 0 or not 0 < butterfly['wall_angle_deg'] < 45:
        raise ValueError('Invalid butterfly wall or local plane settings')
    footprint = result['footprint_regularization']
    if min(footprint[k] for k in ('max_depth_m','min_span_m','min_parallel_segment_m','max_boundary_shift_m')) <= 0:
        raise ValueError('footprint_regularization distances must be positive')
    if not 0 <= footprint['max_angle_deg'] < 30 or not 0 < footprint['max_area_change_fraction'] < 1 or footprint['min_repeats'] < 3:
        raise ValueError('footprint_regularization needs at least three repeats, an area fraction in (0,1), and angle below 30 degrees')
    for group, keys in [('sampling',['cell_size_m']), ('annex',['profile_width_m','profile_inside_m','profile_cell_size_m']),
                        ('parallel_gables',['profile_bin_m','min_segment_width_m','min_bay_width_m']),
                        ('flat_majority',['radius_m']), ('flat_protrusions',['cell_size_m']), ('scoring',['error_cap_m'])]:
        if any(result[group][key] <= 0 for key in keys):
            raise ValueError(group+' distances must be positive')
    for key in ('max_area_fraction','max_total_area_fraction'):
        if not 0 < result['annex'][key] < 1:
            raise ValueError(key+' must be between zero and one')
    if not 0 < result['scoring']['quantile'] < 1:
        raise ValueError('scoring.quantile must be between zero and one')
    if result['scoring']['mean_weight']+result['scoring']['quantile_weight'] <= 0:
        raise ValueError('At least one score weight must be positive')
    if not 0 <= result['scoring']['main_eave_parallel_deg'] < 45 or result['scoring']['main_eave_min_length_m'] <= 0:
        raise ValueError('Main-eave protection needs positive edge length and an angle below 45 degrees')
    if result['scoring']['main_eave_probe_inset_m'] <= 0 or not 0 < result['scoring']['main_eave_min_supported_fraction'] <= 1:
        raise ValueError('Main-eave local support requires a positive inset and fraction in (0,1]')
    if result['scoring']['main_eave_gable_match_distance_m'] <= 0 or not 0 < result['scoring']['main_eave_gable_match_fraction'] <= 1:
        raise ValueError('Gable edge matching needs a positive distance and fraction in (0,1]')
    if not 0 <= result['scoring']['min_courtyard_area_fraction'] <= 1:
        raise ValueError('scoring.min_courtyard_area_fraction must be between zero and one')
    if not 0 <= result['annex']['max_slope_deg'] < 80:
        raise ValueError('annex.max_slope_deg must be below 80')
    if not 0 < result['parallel_gables']['max_slope_deg'] < 90:
        raise ValueError('parallel_gables.max_slope_deg must be between zero and 90 degrees')
    if not 2 <= result['parallel_gables']['max_ridges'] <= 8:
        raise ValueError('parallel_gables.max_ridges must be between 2 and 8')
    if not 0 <= result['parallel_gables']['min_supported_span_fraction'] <= 1:
        raise ValueError('parallel_gables.min_supported_span_fraction must be between zero and one')
    flat = result['flat_majority']
    if not 0 < flat['min_coverage_fraction'] < 1:
        raise ValueError('flat_majority.min_coverage_fraction must be between zero and one')
    for key in ('min_patch_area_fraction', 'min_largest_patch_fraction'):
        if not 0 <= flat[key] <= 1:
            raise ValueError('flat_majority.'+key+' must be between zero and one')
    if not 0 < flat['min_neighbor_axis_ratio'] <= 1 or flat['min_neighbors'] < 3:
        raise ValueError('flat_majority needs a two-dimensional neighbourhood of at least three points')
    if not 0 <= flat['max_slope_deg'] < 45:
        raise ValueError('flat_majority.max_slope_deg must be below 45')
    protrusions = result['flat_protrusions']
    if not 0 < protrusions['height_quantile'] < 1:
        raise ValueError('flat_protrusions.height_quantile must be between zero and one')
    if not 0 <= protrusions['max_simplification_area_increase_fraction'] <= 1:
        raise ValueError('flat_protrusions.max_simplification_area_increase_fraction must be between zero and one')
    if protrusions['min_area_m2'] <= 0 or protrusions['min_cells'] < 3:
        raise ValueError('flat_protrusions requires positive area and at least three cells')
    if not 0 < protrusions['regularization_min_retained_area_fraction'] <= 1 or protrusions['regularization_max_vertices'] < 4:
        raise ValueError('flat_protrusions regularization needs a retained fraction in (0,1] and at least four vertices')
    wings = result['connected_wings']
    if not 0 <= wings['local_gable_inset_min_m'] < wings['local_gable_inset_max_m'] or not 0 < wings['local_gable_min_support_fraction'] <= 1 or wings['local_gable_support_error_m'] <= 0:
        raise ValueError('Invalid local gable evidence band or support bounds')
    if not 0 < wings['paired_min_coverage_fraction'] <= 1 or not 0 < wings['paired_ridge_offset_limit'] < .5:
        raise ValueError('Paired wing coverage must be in (0,1] and ridge offset limit in (0,.5)')
    if not 0 < wings['paired_min_support_fraction'] <= 1 or not 0 < wings['paired_max_slope_deg'] < 90 or wings['paired_min_supported_span_m'] <= 0 or wings['paired_min_roof_height_m'] <= 0:
        raise ValueError('Invalid paired ridge support, span, roof height or slope bounds')
    if wings['min_width_m'] <= 0 or wings['max_width_m'] < wings['min_width_m'] or wings['min_wall_m'] <= 0 or wings['min_length_m'] <= 0:
        raise ValueError('connected_wings needs positive wall/span lengths and an ordered width interval')
    for key in ('min_new_area_fraction','min_concavity_fraction','min_ridge_support_fraction'):
        if not 0 <= wings[key] < 1:
            raise ValueError('connected_wings.'+key+' must be in [0,1)')
    for key in ('max_parallel_deviation_deg','wall_merge_angle_deg','snap_frame_max_deviation_deg','cap_merge_angle_deg'):
        if not 0 <= wings[key] < 45:
            raise ValueError('connected_wings.'+key+' must be below 45 degrees')
    if min(wings['ridge_support_distance_m'],wings['ridge_support_height_m'])<=0:
        raise ValueError('connected_wings ridge support distances must be positive')
    if not any(result['modules'][k] for k in ('flat','straight','skillion','bent','networks','pyramidal','parallel_gables','connected_wings','butterfly','straight_skeleton')):
        raise ValueError('At least one roof candidate module must be enabled')
    return result


def resolve_execution_config(overrides=None, *, mode):
    """Choose analytical work by execution purpose, after applying old configs.

    Report runs always include independent point-profile ridge diagnostics.
    Map production never runs them, even if a report config was reused.
    Core resolve_config defaults to diagnostics off for direct geometry callers.
    """
    if mode not in ('report', 'map'):
        raise ValueError('Roof execution mode must be report or map')
    result = resolve_config(overrides)
    result['modules']['observed_ridges'] = mode == 'report'
    return result


def point_error(absolute, scoring):
    import numpy as np
    return float(scoring['mean_weight']*np.mean(np.minimum(absolute, scoring['error_cap_m']))
                 +scoring['quantile_weight']*np.quantile(absolute, scoring['quantile']))
