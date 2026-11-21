"""Windows installer regression tests that can also run under Linux.

These checks validate Windows-facing source/logic but cannot substitute for
running PowerShell 5.1 and Windows Explorer on a Windows computer.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fitz
from PIL import Image

from docforge import core

ROOT = Path(__file__).resolve().parents[1]


def test_powershell_51_script_has_no_non_ascii_literals():
    # Windows PS5.1 parses no-BOM UTF-8 as ANSI. Pure ASCII has no such risk.
    installer = (ROOT / 'windows' / 'install.ps1').read_bytes()
    assert installer.isascii()
    assert b'NoProfile' not in installer  # Launcher flag is in the CMD entry point.
    assert b'Get-AuthenticodeSignature' in installer
    assert b'Expand-Archive' in installer
    assert b'Invoke-WebRequest' in installer
    assert b'LOCALAPPDATA' in installer
    assert b'python313' in installer
    assert b'Get-Command py.exe' in installer  # fallback for nonstandard Python installs
    assert b'Include_tcltk=1' in installer
    assert b'InstallAllUsers=0' in installer
    assert b'LibreOffice' not in installer
    assert b'OfficeMsi' not in installer
    assert b'msiexec' not in installer
    assert b'office2pdf' in installer
    assert b'Pandoc' in installer
    assert b'healthcheck.py' in installer
    assert b'cmdPath' in installer
    assert b'Get-Date -Format' in installer  # Backup when replacing old app.


def test_entrypoint_uses_builtin_powershell_51_and_reports_error():
    launcher = (ROOT / 'windows' / 'START-HERE.cmd').read_bytes()
    assert launcher.isascii()
    assert b'powershell.exe -NoProfile -ExecutionPolicy Bypass' in launcher
    assert b'install.ps1' in launcher
    assert b'Setup-DocForge.ps1' in launcher
    assert b'exit /b %STATUS%' in launcher


def test_install_bundle_does_not_require_external_python():
    requirements = (ROOT / 'windows' / 'requirements-windows.txt').read_text()
    assert 'PySide6-Essentials' in requirements
    assert 'PyMuPDF' in requirements
    assert 'tkinterdnd2' in requirements
    assert 'weasyprint' not in requirements.lower()
    assert 'office2pdf-python' in requirements
    for filename in ('launcher.py', 'healthcheck.py', 'docforge.cmd'):
        assert (ROOT / 'windows' / filename).is_file()
    launcher = (ROOT / 'windows' / 'launcher.py').read_text()
    assert 'binpaths.txt' in launcher and 'os.environ' in launcher
    assert 'logs' in launcher


def test_windows_dependency_plan_uses_native_no_libreoffice():
    with patch.object(core, 'sys', SimpleNamespace(platform='win32')):
        assert core.needs('md','pdf') == ('pandoc', 'fitz')
        assert core.needs('txt','pdf') == ('pandoc', 'fitz')
        assert core.needs('docx','pdf') == ('fitz','pandoc')
        assert core.needs('pptx','pdf') == ('fitz', 'python-pptx')
        assert core.needs('xlsx','pdf') == ('fitz', 'openpyxl')
    with patch.object(core, 'sys', SimpleNamespace(platform='linux')):
        assert core.needs('md','pdf') == ('pandoc', 'fitz')


def test_windows_route_markdown_pdf_preserves_image(tmp_path):
    photo = tmp_path / 'фото с пробелом.png'
    Image.new('RGB', (128, 72), (30, 90, 155)).save(photo)
    source = tmp_path / 'документ.md'
    source.write_text('# Windows route\n\nТест с вложением.\n\n![Picture](фото%20с%20пробелом.png)\n', encoding='utf-8')
    with patch.object(core, 'sys', SimpleNamespace(platform='win32')):
        output = core.convert(source, 'pdf')
    with fitz.open(output) as pdf:
        assert len(pdf) > 0
        text = ''.join(p.get_text() for p in pdf)
        assert 'Windows route' in text
        assert any(page.get_images(full=True) for page in pdf)


def test_windows_route_txt_pdf_does_not_collapse_lines(tmp_path):
    source = tmp_path / 'строки.txt'
    source.write_text('Первая строка\nВторая строка\n\nТретий абзац\n', encoding='utf-8')
    with patch.object(core, 'sys', SimpleNamespace(platform='win32')):
        output = core.convert(source, 'pdf')
    with fitz.open(output) as doc:
        text = '\n'.join(page.get_text() for page in doc)
    assert 'Первая строка' in text
    assert 'Вторая строка' in text
    assert 'Третий абзац' in text
