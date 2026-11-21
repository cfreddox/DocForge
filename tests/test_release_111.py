"""Release 1.11.0: persistent zone, install routes, document lines and publishing."""
from pathlib import Path
from types import SimpleNamespace

from docforge import __version__
from docforge.appearance import palette, DEFAULTS
from docforge.core import _markdown_page
from docforge.zone_lock import single_zone

ROOT = Path(__file__).resolve().parents[1]


def test_release_and_root_installers():
    assert __version__ == '1.11.0'
    assert 'START-HERE.cmd' in (ROOT / 'INSTALL-WINDOWS.cmd').read_text()
    assert 'install.sh' in (ROOT / 'INSTALL-LINUX.sh').read_text()
    assert (ROOT / 'README.md').exists()
    assert (ROOT / 'pyproject.toml').exists()


def test_safe_upgrade_routes():
    linux = (ROOT / 'install.sh').read_text()
    update = (ROOT / 'update.sh').read_text()
    windows = (ROOT / 'windows' / 'install.ps1').read_text()
    assert 'exec "$ROOT/update.sh"' in linux
    assert 'exec "$ROOT/install.sh"' in update
    assert "'.staging-'" in windows and 'code-backup-' in windows
    assert "'healthcheck.py'" in windows
    assert 'Rolling back only files actually changed' in windows
    assert '$backedUp += $name' in windows and '$deployed += $name' in windows
    assert 'venv313' in windows


def test_persistent_nautilus_zone_and_singleton(tmp_path, monkeypatch):
    nautilus = (ROOT / 'nautilus' / 'docforge_extension.py').read_text()
    assert '"--dropzone-once"' not in nautilus
    assert '"--dropzone"' in nautilus
    assert '--dropzone-once' not in (ROOT / 'install.sh').read_text()
    assert '--dropzone-once' not in (ROOT / 'update.sh').read_text()
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    with single_zone() as first:
        assert first
        with single_zone() as second:
            assert not second
    with single_zone() as again:
        assert again


def test_markdown_lines_remain_explicit():
    block = {'bbox': [0, 0, 200, 60], 'lines': [
        {'spans': [{'text': 'Первая строка', 'size': 10}]},
        {'spans': [{'text': 'Вторая строка', 'size': 10}]},
    ]}
    page = SimpleNamespace(get_text=lambda *a, **kw: {'blocks': [block]})
    text = _markdown_page(page, 10)
    assert 'Первая строка  \nВторая строка' in text


def test_word_editor_preserves_soft_break_code():
    source = (ROOT / 'docforge' / 'word_ui.py').read_text()
    assert "styles.append('soft-break')" in source
    assert "paragraph.add_run().add_break()" in source
    assert 'paragraph.paragraph_format.space_after = Pt(0)' in source


def test_contrast():
    for theme in ('liquid_dark', 'liquid_light', 'midnight'):
        config = dict(DEFAULTS, theme=theme)
        data = palette(config)
        def lum(hex_code):
            rgb = [int(hex_code[i:i+2], 16)/255 for i in (1,3,5)]
            values = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb]
            return sum(c*w for c,w in zip(values,(.2126,.7152,.0722)))
        a, b = lum(data['muted']), lum(data['panel'])
        contrast = (max(a,b)+.05)/(min(a,b)+.05)
        assert contrast >= 4.5, (theme, contrast)


def test_github_templates_and_ignore():
    mandatory = ['.gitignore','README.md','LICENSE','SECURITY.md','CONTRIBUTING.md',
                 'CODE_OF_CONDUCT.md',
                 '.github/ISSUE_TEMPLATE/bug_report.yml','.github/pull_request_template.md',
                 '.github/workflows/tests.yml','.github/workflows/build-windows.yml']
    assert all((ROOT / file).is_file() for file in mandatory)
    ignored = (ROOT / '.gitignore').read_text()
    assert 'venv313/' in ignored and '*.log' in ignored and 'dist/' in ignored
    assert '.ico' not in ignored


def test_word_editor_round_trip_soft_break_and_paragraph(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    if not shutil.which('xvfb-run'):
        import pytest
        pytest.skip('Xvfb unavailable')
    script = r'''
from docx import Document
from docforge.word_ui import WordEditorFrame
from pathlib import Path
import tkinter as tk
import sys
p=Path(sys.argv[1]); d=Document()
paragraph=d.add_paragraph('First'); paragraph.add_run().add_break(); paragraph.add_run('Second')
d.add_paragraph('Third'); d.save(p)
root=tk.Tk(); root.geometry('1080x800')
f=WordEditorFrame(root,p.with_suffix('.pdf'),existing_docx=p)
out=f._to_document()
assert [p.text for p in out.paragraphs] == ['First\nSecond','Third'], [repr(p.text) for p in out.paragraphs]
assert out.paragraphs[0].paragraph_format.space_after.pt == 0
root.destroy()
'''
    process = subprocess.run(['xvfb-run','-a',sys.executable,'-c',script,str(tmp_path/'soft.docx')],
                             text=True,capture_output=True,timeout=30,
                             env={**os.environ,'PYTHONPATH':str(ROOT)})
    assert process.returncode == 0, process.stderr
