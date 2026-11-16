"""Link the new independent comparison without regenerating the old results."""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = '<a href="roof-simplification/report.html">Nové: jednodušší střechy 6 objektů ↗</a>'
for relative in ['scripts/cb_experiment_report.py',
                 'cities/ceske-budejovice/experiments/report.html']:
    path = ROOT / relative
    original = path.read_text(encoding='utf8')
    if LINK in original:
        continue
    if original.count('<nav><a href="#roofs">') != 1:
        raise ValueError('Unexpected old report navigation')
    changed = original.replace('<nav><a href="#roofs">', '<nav>'+LINK+'<a href="#roofs">',1)
    if path.suffix == '.html':
        pattern = r'<script type="application/json" id="experiment-data">(.*?)</script>'
        before = re.search(pattern,original,re.S).group(1)
        after = re.search(pattern,changed,re.S).group(1)
        assert before == after
        print('Old embedded payload unchanged:',hashlib.sha256(before.encode()).hexdigest())
    path.write_text(changed,encoding='utf8')
    print('Linked:',relative)
