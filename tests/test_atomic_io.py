"""Exercise actual Windows sharing locks and preservation of committed files."""
import ctypes
import errno
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import atomic_io


class AtomicIOTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Actual Windows sharing semantics')
    def test_reader_without_delete_sharing_releases_then_replacement_succeeds(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'active.json'
            target.write_text('old committed value', encoding='utf-8')
            # Allow ordinary readers/writers, but intentionally omit FILE_SHARE_DELETE.
            handle = kernel.CreateFileW(str(target), 0x80000000, 1 | 2, None, 3, 128, None)
            self.assertNotIn(handle, (None, ctypes.c_void_p(-1).value))
            failed_attempt = threading.Event()
            release_result = []
            original_replace = os.replace

            def release_reader():
                failed_attempt.wait(timeout=2)
                time.sleep(.04)
                release_result.append(kernel.CloseHandle(handle))

            def replace_observed(source, destination):
                try:
                    return original_replace(source, destination)
                except PermissionError:
                    self.assertEqual(target.read_text(encoding='utf-8'), 'old committed value')
                    failed_attempt.set()
                    raise

            thread = threading.Thread(target=release_reader)
            thread.start()
            try:
                with patch.object(atomic_io.os, 'replace', side_effect=replace_observed):
                    atomic_io.write_text(target, 'new committed value')
            finally:
                thread.join(timeout=3)
            self.assertTrue(failed_attempt.is_set(), 'Test must observe a real sharing violation')
            self.assertEqual(release_result, [1])
            self.assertEqual(target.read_text(encoding='utf-8'), 'new committed value')
            self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_nonsharing_error_is_not_retried_and_keeps_old_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'checkpoint.json'
            target.write_text('old committed value', encoding='utf-8')
            error = OSError(errno.ENOSPC, 'Disk full')
            with patch.object(atomic_io.os, 'replace', side_effect=error) as replace:
                with self.assertRaises(OSError) as caught:
                    atomic_io.write_text(target, 'uncommitted value')
            self.assertIs(caught.exception, error)
            self.assertEqual(replace.call_count, 1)
            self.assertEqual(target.read_text(encoding='utf-8'), 'old committed value')
            self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_permanent_access_error_has_a_bounded_retry_budget(self):
        error = PermissionError('still locked')
        with patch('atomic_io.time.sleep') as sleep:
            with self.assertRaises(PermissionError) as caught:
                atomic_io.retry_sharing(lambda: (_ for _ in ()).throw(error), timeout=0)
        self.assertIs(caught.exception, error)
        sleep.assert_not_called()

    def test_short_read_lock_is_retried(self):
        with patch.object(Path, 'read_text', side_effect=[PermissionError('locked'), 'complete JSON']) as read:
            with patch('atomic_io.time.sleep'):
                self.assertEqual(atomic_io.read_text('checkpoint.json'), 'complete JSON')
        self.assertEqual(read.call_count, 2)


if __name__ == '__main__':
    unittest.main()
