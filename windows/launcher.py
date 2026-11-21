"""Entry point for DocForge's Windows-local runtime.

The installer writes binpaths.txt next to this file. We do not change the
system PATH, require an external Python, or run remote code at launch time.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HOME = Path(__file__).resolve().parent


def configure_runtime() -> None:
    search = [
        HOME / 'tools' / 'pandoc',
    ]
    pathfile = HOME / 'binpaths.txt'
    if pathfile.is_file():
        search.extend(
            Path(item.strip()) for item in
            pathfile.read_text(encoding='utf-8-sig').splitlines() if item.strip()
        )
    current = os.environ.get('PATH', '')
    os.environ['PATH'] = os.pathsep.join(str(p) for p in search if p.is_dir()) + os.pathsep + current
    sys.path.insert(0, str(HOME))
    os.chdir(HOME)


def main() -> int:
    configure_runtime()
    logs = HOME / 'logs'
    logs.mkdir(exist_ok=True)
    log = logs / 'last-launch.log'
    with log.open('w', encoding='utf-8') as stream:
        stream.write(f'[{datetime.now().isoformat()}] DocForge startup; '
                     f'Python: {sys.executable}; Args: {sys.argv[1:]!r}\n')
        stream.flush()
        try:
            # pythonw.exe hides stderr; save both ordinary errors and tracebacks.
            with redirect_stdout(stream), redirect_stderr(stream):
                from docforge.cli import main as run
                code = run()
            stream.write(f'Exit code: {code}\n')
            stream.flush()
            return int(code or 0)
        except BaseException as exc:
            stream.write(f'[{datetime.now().isoformat()}] {type(exc).__name__}: {exc}\n')
            traceback.print_exc(file=stream)
            stream.flush()
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
