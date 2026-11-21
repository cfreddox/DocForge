"""Single persistent Linux drop zone across desktop and Nautilus launchers."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sys


@contextmanager
def single_zone():
    if sys.platform != 'linux':
        yield True
        return
    import fcntl
    base = Path(os.environ.get('XDG_RUNTIME_DIR') or (Path.home() / '.cache' / 'docforge'))
    base.mkdir(parents=True, exist_ok=True)
    with (base / 'zone.lock').open('a+b') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
