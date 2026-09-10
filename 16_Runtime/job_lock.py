"""Cross-process exclusion for workers and library changes."""
from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def job_lock(job):
    lock = (Path(job) / '.worker.lock').open('a+b')
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                lock.seek(0)
                if not lock.read(1):
                    lock.write(b'0')
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Another worker is already running this job. Wait until it stops before editing or deleting it.') from error
        yield
    finally:
        lock.close()
