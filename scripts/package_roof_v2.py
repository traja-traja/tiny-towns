"""Package the reviewed experiment, not full city sources or intermediate tiles."""
from pathlib import Path
import zipfile
import json
from resource_guard import check_budget, keep_awake

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'cities/ceske-budejovice/experiments/roof-v2'
CACHE = ROOT/'.work/cb-roof-v2'


def main():
    check_budget(100_000_000, force=True)
    result = json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    tiles = json.loads((OUT/'tiles/manifest.json').read_text(encoding='utf-8'))
    if result['status'] != 'complete' or tiles['status'] != 'rendered':
        raise ValueError('Cannot package unfinished or failed results')
    files = set()
    for pattern in ('roof_v2*', 'cb_roof_v2.py', 'package_roof_v2.py'):
        files.update(p for p in (ROOT/'scripts').glob(pattern) if p.is_file())
    for pattern in ('test_roof_v2*.py', 'test_cb_roof_v2.py'):
        files.update((ROOT/'tests').glob(pattern))
    for p in OUT.rglob('*'):
        if not p.is_file() or p.suffix == '.zip':
            continue
        relative = p.relative_to(OUT)
        if any(str(relative).replace('\\','/').startswith(f'tiles/{folder}/')
               for folder in ('prepared', 'after', 'diagnostic')):
            continue
        files.add(p)
    for p in CACHE.glob('*.npz'):
        files.add(p)
    for name in ('run.log.metrics.json', 'prepare.log.metrics.json'):
        files.add(CACHE/name)
    files.add(ROOT/'.work/cb-roof-inference/roofs-dmpok.json')
    final = OUT/'cb-roof-v2.zip'
    temporary = CACHE/'cb-roof-v2.zip.tmp'
    with keep_awake(), zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in sorted(files):
            archive.write(p, p.relative_to(ROOT).as_posix())
    temporary.replace(final)
    check_budget(force=True)
    print(json.dumps({'file':str(final),'bytes':final.stat().st_size,'files':len(files)}))


if __name__ == '__main__':
    main()
