"""Select relevant GeoParquet files from Overture's official STAC metadata.

This avoids opening the footer of every worldwide data file for a city crop.
The original per-row bbox predicate must still be applied to selected files.
No data file is downloaded in full by this helper. Release remains pinned.
Source: https://docs.overturemaps.org/getting-data/cloud-sources/
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

import resource_guard as guard

ROOT_URL = 'https://stac.overturemaps.org/catalog.json'


def fetch_json(url):
    if urlparse(url).netloc != 'stac.overturemaps.org':
        raise ValueError('Unexpected STAC metadata host')
    for attempt in range(3):
        try:
            with urlopen(url, timeout=40) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('Unexpectedly large STAC metadata document')
            return json.loads(raw)
        except (OSError, TimeoutError):
            if attempt == 2: raise
            time.sleep(attempt + 1)


def child(document, base, name):
    links = [urljoin(base, x['href']) for x in document.get('links', []) if x.get('rel') == 'child']
    match = [url for url in links if f'/{name}/' in url and url.endswith(('catalog.json','collection.json'))]
    if len(match) != 1:
        raise ValueError(f'Cannot resolve unique STAC child {name}')
    return match[0]


def build_index(release, theme, typ, cache_dir):
    cache_dir = Path(cache_dir)
    target = cache_dir / f'{release}-{theme}-{typ}.json'
    if target.exists():
        index = json.loads(target.read_text(encoding='utf-8'))
        if index.get('complete') and index.get('release') == release and index.get('type') == typ:
            return index
        raise ValueError('Incomplete or mismatched STAC index')
    guard.check_budget(reserve_bytes=30_000_000, force=True)
    started = time.perf_counter()
    release_url = child(fetch_json(ROOT_URL), ROOT_URL, release)
    theme_url = child(fetch_json(release_url), release_url, theme)
    collection_url = child(fetch_json(theme_url), theme_url, typ)
    collection = fetch_json(collection_url)
    links = [urljoin(collection_url, x['href']) for x in collection['links'] if x.get('rel') == 'item']
    expected = collection.get('partition:file_count')
    if not links or (expected is not None and int(expected) != len(links)):
        raise ValueError('STAC file inventory is incomplete')
    prefix = f'/release/{release}/theme={theme}/type={typ}/'
    def item(url):
        document = fetch_json(url)
        asset = document.get('assets', {}).get('aws', {})
        parsed = urlparse(asset.get('href', ''))
        if parsed.netloc != 'overturemaps-us-west-2.s3.us-west-2.amazonaws.com' or not parsed.path.startswith(prefix) or not parsed.path.endswith('.parquet'):
            raise ValueError('Unexpected GeoParquet asset path')
        bbox = document.get('bbox')
        if bbox is not None and (len(bbox) != 4 or not all(math.isfinite(v) for v in bbox)
                                 or bbox[0] > bbox[2] or bbox[1] > bbox[3]):
            bbox = None  # Missing/ambiguous bounds must never exclude a file.
        return {'id': document['id'], 'bbox': bbox, 'stac_url': url,
                'path': 'overturemaps-us-west-2' + parsed.path,
                'bytes': asset.get('file:size')}
    print(f'STAC {theme}/{typ}: reading {len(links)} small metadata records', flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = []
        for record in pool.map(item, links):
            items.append(record)
            if len(items) % 100 == 0:
                guard.check_budget(); print(f'STAC metadata {len(items)}/{len(links)}', flush=True)
    if len({r['path'] for r in items}) != len(items):
        raise ValueError('Duplicate data files in STAC index')
    index = {'complete': True, 'release': release, 'theme': theme, 'type': typ,
             'collection_url': collection_url, 'created_at': datetime.now(timezone.utc).isoformat(),
             'elapsed_seconds': time.perf_counter()-started, 'files': items}
    cache_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix('.json.partial')
    partial.write_text(json.dumps(index, indent=2), encoding='utf-8'); partial.replace(target)
    return index


def select_paths(index, bounds):
    x0, x1, y0, y1 = bounds
    def overlaps(item):
        b = item['bbox']
        return b is None or (b[0] <= x1 and b[2] >= x0 and b[1] <= y1 and b[3] >= y0)
    selected = [item['path'] for item in index['files'] if overlaps(item)]
    # Keep a schema source for empty regional layers; the row filter returns zero.
    return selected or [index['files'][0]['path']]


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', required=True); parser.add_argument('--theme', required=True)
    parser.add_argument('--type', required=True); parser.add_argument('--cache', required=True)
    args = parser.parse_args()
    index = build_index(args.release,args.theme,args.type,args.cache)
    print(json.dumps({'files': len(index['files']), 'seconds': index['elapsed_seconds']}))
