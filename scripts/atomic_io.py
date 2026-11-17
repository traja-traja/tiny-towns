"""Atomic files that tolerate a brief Windows reader/antivirus sharing lock.

The old destination stays intact until replacement succeeds. Retry only access
and sharing errors, for a bounded time; disk/full and other IO errors propagate.
"""
from pathlib import Path
import os
import tempfile
import time


def retry_sharing(operation, timeout=5.0):
    deadline = time.monotonic() + timeout
    delay = .02
    while True:
        try:
            return operation()
        except OSError as error:
            retryable = isinstance(error, PermissionError) or getattr(error, 'winerror', None) in (5, 32, 33)
            remaining = deadline - time.monotonic()
            if not retryable or remaining <= 0:
                raise
            time.sleep(min(delay, remaining))
            delay = min(.2, delay * 1.6)


def read_text(path, encoding='utf-8-sig'):
    return retry_sharing(lambda: Path(path).read_text(encoding=encoding))


def write_text(path, text, encoding='utf-8'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding=encoding, newline='\n',
                                     dir=path.parent, prefix=path.name + '.', suffix='.tmp',
                                     delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        retry_sharing(lambda: os.replace(temporary, path))
    finally:
        if temporary.exists():
            retry_sharing(lambda: temporary.unlink(missing_ok=True))
