"""Resolve a mapped roof attribute after the renderer's legacy heuristics.

This policy deliberately does not infer roof geometry from building use,
floor count, tile index or a large percentile spread. ``flat_surface_evidence``
preserves the existing near-horizontal DMP rule; it is evidence with possible
source conflicts, not independently verified ground truth. Manual DOM/SAT
overrides are applied by the caller afterwards.
"""

SUPPORTED_SHAPES = frozenset({'flat', 'gabled', 'hipped', 'pyramidal'})


def resolve_roof_shape(source_shape, inferred_shape, *, flat_surface_evidence=False):
    """Keep an explicit mapped roof shape ahead of height/class heuristics.

Inputs use the renderer's already-normalized shape vocabulary. Unknown source
values leave the previous fallback untouched. Strong near-horizontal DMP
evidence retains its previous priority, including when a pitched source tag
disagrees with it.
    """
    if flat_surface_evidence:
        return 'flat'
    if source_shape in SUPPORTED_SHAPES:
        return source_shape
    return inferred_shape
