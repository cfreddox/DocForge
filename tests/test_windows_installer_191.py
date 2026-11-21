"""Regression test: Windows PowerShell must not forward quoted Python snippets."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installer_uses_python_file_not_python_c_for_renderer():
    source = (ROOT / "windows" / "install.ps1").read_text(encoding="ascii")
    assert "Run-Checked $VenvExe @((Join-Path $Root 'windows\\verify_renderer.py'))" in source
    assert "Run-Checked $VenvExe @('-c', 'from office2pdf" not in source
    assert "office2pdf ready" not in source
    # Any -c invocations remaining must not require string literal quoting.
    for line in source.splitlines():
        if "Run-Checked" in line and "'-c'" in line:
            assert '"' not in line, line


def test_renderer_probe_parses_and_matches_real_api():
    src = (ROOT / "windows" / "verify_renderer.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert "from office2pdf import ConvertOptions, convert_path" in src
    assert "ConvertOptions(include_warnings=True)" in src


def test_installer_unchanged_core_dependencies():
    source = (ROOT / "windows" / "install.ps1").read_text(encoding="ascii")
    assert "-r',(Join-Path $Root 'windows\\requirements-windows.txt')" in source
    assert "Run-Checked $VenvExe @((Join-Path $Target 'healthcheck.py'))" in source
    assert "Copy-Item -LiteralPath (Join-Path $Root 'docforge')" in source
