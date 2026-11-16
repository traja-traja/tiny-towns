import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import rebuild_cb_roofs as rebuild


class BaselinePreservationTests(unittest.TestCase):
    def test_incomplete_baseline_is_rejected_before_copying(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp); (work/'build').mkdir()
            (work/'build/preview-checkpoint.json').write_text('{"completed":{}}')
            with patch.object(rebuild, 'WORK', work), self.assertRaisesRegex(ValueError, 'complete'):
                rebuild.snapshot_baseline()
            self.assertFalse((work/'revisions/baseline/snapshot.json').exists())

    def test_resume_preserves_original_scene_and_detects_snapshot_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp); (work/'build').mkdir(); (work/'site').mkdir()
            (work/'build/preview-checkpoint.json').write_text(json.dumps({
                'completed': {s:{} for s in rebuild.build.STEPS}}))
            (work/'build/scene.json').write_text('{"original":true}')
            (work/rebuild.towns.MANIFEST).write_text('{}')
            (work/'site/index.html').write_text('Original map')
            with patch.object(rebuild, 'WORK', work), patch.object(rebuild.guard, 'check_budget'):
                dest, first = rebuild.snapshot_baseline()
                (work/'build/scene.json').write_text('{"revised":true}')
                (work/'site/index.html').write_text('Revised map')
                _, second = rebuild.snapshot_baseline()
                self.assertEqual(first, second)
                self.assertEqual((dest/'site/index.html').read_text(), 'Original map')
                self.assertEqual(json.loads((dest/'scene.json').read_text()), {'original':True})
                (dest/'scene.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'snapshot changed'):
                    rebuild.snapshot_baseline()


if __name__ == '__main__':
    unittest.main()
