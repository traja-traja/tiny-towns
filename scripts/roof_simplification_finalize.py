"""Attach explicit exploratory review without changing measured geometry."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import roof_simplification_common as common
import resource_guard as guard


def geometry_hash(document):
    value = [(r['id'],r['variant'],{k:r.get('model',{}).get(k) for k in
              ['vertices','faces','face_semantics']},r['metrics'],r.get('timing')) for r in document['runs']]
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def main():
    result = common.read(common.DEST/'results.json')
    before = geometry_hash(result)
    review = common.read(common.DEST/'review.json')
    buildings = {b['id']:b for b in result['buildings']}
    for row in result['runs']:
        if row.get('review',{}).get('note','').startswith('Training-only'):
            row['review']['note'] = 'Experimentální rozdělení podle fitovacích bodů; před použitím posoudit tvar a výškové spoje.'
        for decision in review['row_reviews']:
            if buildings[row['id']]['pilot_id']==decision['pilot_id'] and row['variant'] in decision['variants']:
                row['review'] = {k:decision[k] for k in ['status','note']}
    result['recommendations'] = review['recommendations']
    for note in review['findings']:
        if note not in result['notes']:
            result['notes'].append(note)
    result['review'] = {'scope':review['scope'],'source':'review.json',
                        'sha256':guard.sha256(common.DEST/'review.json'),
                        'at':datetime.now(timezone.utc).isoformat(),
                        'measured_geometry_metrics_timing_sha256':before}
    paths = [*common.WORK.glob('*.metrics.json'),*(common.WORK/'logs').glob('*.metrics.json'),
             *(common.ROOT/'.work/roof-simplification/qa').glob('*.metrics.json')]
    result['process_metrics'] = {p.relative_to(common.ROOT).as_posix():common.read(p) for p in paths}
    baseline = common.read(common.DEST/'unchanged-baseline-sha256.json')
    changed = [rel for rel,expected in baseline.items() if guard.sha256(common.ROOT/rel)!=expected]
    if changed:
        raise ValueError('Preserved baseline changed: '+str(changed))
    result['preserved_baseline_check'] = {'files':len(baseline),'changed':changed,'passed':True}
    result['resource_check'] = guard.check_budget(force=True)
    result['status'] = 'complete_exploratory_review'
    if geometry_hash(result)!=before:
        raise ValueError('Review modified a measured result')
    common.write(common.DEST/'results.json',result)
    print('Finalized70rows; measured geometry, metrics and timing unchanged;10baseline hashes verified.')


if __name__=='__main__':
    main()
