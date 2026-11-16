"""České Budějovice source adapter; the original Velešín pilot stays unchanged.

Uses the same crop/classification/deduplication implementation, explicitly bound
to separate city paths. Large work is gated on the completed basic preview.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import resource_guard as guard
import roof_pilot_sources as shared

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work/cb-roof-pilot'
SAMPLE = ROOT / 'cities/ceske-budejovice/roof-pilot/sample.json'
PREVIEW = ROOT / '.work/.preview/ceske-budejovice'


def require_basic_preview():
    path = PREVIEW / 'site/preview-build.json'
    checkpoint = PREVIEW / 'build/preview-checkpoint.json'
    if not path.exists() or not checkpoint.exists():
        raise RuntimeError('The basic ČB preview must finish before the roof pilot.')
    if not json.loads(path.read_text(encoding='utf-8')).get('complete'):
        raise RuntimeError('The basic ČB preview does not report completion.')
    if 'web' not in json.loads(checkpoint.read_text(encoding='utf-8')).get('completed', {}):
        raise RuntimeError('The basic ČB preview web checkpoint has not completed.')


def configure():
    shared.DEFAULT_SAMPLE = SAMPLE
    shared.SOURCE_DIR = WORK / 'sources'
    shared.CROP_DIR = WORK / 'crops'
    shared.MANIFEST_PATH = WORK / 'sources/sources.json'
    # The validated 24 MB catalog is shared read-only; guard.download returns
    # its cache record when present. No duplicate download or content mutation.
    shared.MASTER_FEED = ROOT / '.work/roof-pilot/sources/dmpok-atom.xml'
    shared.EXISTING_DMP1G = PREVIEW / 'build/dmp'
    return shared


def plan():
    module = configure()
    buildings, union = module.sample_geometry(SAMPLE)
    if not module.MASTER_FEED.exists():
        raise FileNotFoundError('Expected previously downloaded official DMPOK catalog')
    entries = module.selected_dmpok_entries(union)
    old, _ = module.prepare_dmp1g(union)
    return {'buildings': len(buildings), 'buffer_union_area_m2': union.area,
            'buffer_union_bounds_epsg5514': list(union.bounds),
            'dmpok_sheets': [x['sheet'] for x in entries],
            'dmp1g_sheets': [x['sheet'] for x in old],
            'downloads_started': False, 'work': str(WORK)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--source', choices=('both', 'dmp1g', 'dmpok'), default='both')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if not args.prepare:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return
    require_basic_preview()
    module = configure()
    sources = ('dmp1g', 'dmpok') if args.source == 'both' else (args.source,)
    if args.worker:
        result = module.prepare_sources(SAMPLE, sources, force=args.force)
        print(json.dumps({'manifest': result['manifest_path'], 'sources': list(result['sources'])}))
        return
    for name in sources:
        command = [sys.executable, '-X', 'utf8', __file__, '--prepare', '--worker', '--source', name]
        if args.force:
            command.append('--force')
        metrics = guard.run_guarded(command, ROOT, WORK / 'sources' / f'prepare-{name}.log',
                                    min_available_gb=1, max_ram_gb=2)
        print(json.dumps(metrics, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
