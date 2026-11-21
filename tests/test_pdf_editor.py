"""DocForge 1.6 PDF editor and platform integration regression suite."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz
import pytest
from PIL import Image

from docforge.pdf_editor import PdfEditSession, edit_pdf_script
from docforge.petals import actions_for


@pytest.fixture()
def pdf(tmp_path):
    p = tmp_path / 'Документ.pdf'
    d = fitz.open()
    a = d.new_page()
    a.insert_text((60, 65), 'ORIGINAL SECRET', fontsize=14)
    d.new_page().insert_text((60, 65), 'PAGE TWO', fontsize=14)
    d.save(p)
    d.close()
    return p


def test_editor_add_unicode_and_save_without_overwrite(pdf):
    s = PdfEditSession(pdf)
    s.add_text(0, 72, 125, 'Привет, DocForge!')
    destination = s.save()
    assert destination.exists() and destination != pdf
    with fitz.open(destination) as d:
        assert 'Привет' in d[0].get_text()
    assert 'Привет' not in fitz.open(pdf)[0].get_text()
    with pytest.raises(Exception, match='перезаписать'):
        s.save(pdf)
    s.close()


def test_redaction_actually_removes_text(pdf):
    s = PdfEditSession(pdf)
    s.redact(0, fitz.Rect(52, 44, 220, 80))
    output = s.save()
    s.close()
    with fitz.open(output) as d:
        assert 'ORIGINAL SECRET' not in d[0].get_text()


def test_editor_undo_redo(pdf):
    s = PdfEditSession(pdf)
    s.add_text(0, 40, 110, 'NOTE')
    assert 'NOTE' in s.doc[0].get_text()
    assert s.undo()
    assert 'NOTE' not in s.doc[0].get_text()
    assert s.redo()
    assert 'NOTE' in s.doc[0].get_text()
    s.close()


def test_page_delete_rotate_and_reorder(pdf):
    s = PdfEditSession(pdf)
    s.rotate(0)
    assert s.doc[0].rotation == 90
    assert s.move_page(0, 1) == 1
    assert 'PAGE TWO' in s.doc[0].get_text()
    s.delete_page(0)
    assert s.pages == 1
    with pytest.raises(Exception, match='единственную'):
        s.delete_page(0)
    saved = s.save()
    with fitz.open(saved) as d:
        assert len(d) == 1 and d[0].rotation == 90
    s.close()


def test_highlight_line_image_and_render(pdf, tmp_path):
    image = tmp_path / 'logo.png'
    Image.new('RGB', (90, 60), '#58b3fa').save(image)
    s = PdfEditSession(pdf)
    s.highlight(0, fitz.Rect(50, 50, 165, 80))
    s.draw_line(0, 40, 115, 160, 155)
    s.add_image(0, fitz.Rect(40, 180, 190, 290), image)
    assert s.render(0, .5).size[0] > 100
    result = s.save()
    with fitz.open(result) as doc:
        assert doc[0].get_images(full=True)
    s.close()


def test_script_command_edit(pdf):
    args = [sys.executable, '-m', 'docforge', 'edit-script', str(pdf), '--text', 'Added note', '--page', '1']
    p = subprocess.run(args, capture_output=True, text=True, timeout=20)
    assert p.returncode == 0, p.stderr
    result = Path(p.stdout.strip())
    with fitz.open(result) as doc:
        assert 'Added note' in doc[0].get_text()


def test_edit_petal_exists_for_pdf(pdf):
    actions = actions_for([pdf])
    assert any(a.operation == 'edit' for a in actions)
    assert all(a.operation != 'edit' for a in actions_for([pdf.with_suffix('.md')]))


def test_no_top_panel_extension_and_windows_installer():
    root = Path(__file__).resolve().parents[1]
    assert not (root / 'gnome-extension').exists()
    assert not (root / 'install-quick-settings.sh').exists()
    assert (root / 'remove-gnome-panel.sh').exists()
    assert 'remove-gnome-panel.sh' in (root / 'install.sh').read_text()
    assert 'remove-gnome-panel.sh' in (root / 'update.sh').read_text()
    assert (root / 'windows' / 'Setup-DocForge.ps1').exists()
    assert 'PyInstaller' in (root / 'windows' / 'build-release.ps1').read_text()


def test_editor_tk_smoke_under_xvfb(pdf, tmp_path):
    import shutil
    if not shutil.which('xvfb-run'):
        pytest.skip('X11 virtual display is unavailable')
    code = '''
import tkinter as tk
from docforge.pdf_editor import PdfEditorWindow
root=tk.Tk(); win=PdfEditorWindow(root, r"""%s""")
root.update(); assert win.session and win.session.pages==2
root.after(100, win.close);root.mainloop()
'''
    p = subprocess.run(['xvfb-run', '-a', sys.executable, '-c', code % str(pdf)],
                       capture_output=True, text=True, timeout=25)
    assert p.returncode == 0, p.stderr
