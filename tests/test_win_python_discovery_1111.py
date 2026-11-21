"""Regression checks for Python discovery after Windows setup exits 0."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "windows/install.ps1").read_text(encoding="ascii")
PROBE = ROOT / "windows/probe_python.py"


def test_probe_script_runs_and_reports_python():
    result = subprocess.run([sys.executable, str(PROBE)], capture_output=True, text=True, check=False)
    if sys.version_info[:2] == (3, 13) and sys.maxsize > 2**32:
        assert result.returncode == 0, result.stderr
        assert "DOCFORGE_PYTHON=" in result.stdout
    else:
        assert result.returncode != 0


def test_existing_venv_verified_before_download():
    assert SCRIPT.index("Test-Python -executable $VenvExe") < SCRIPT.index("Download-File $DownloadSources.Python")
    assert "Reusing existing verified DocForge Python environment" in SCRIPT
    assert "--upgrade" in SCRIPT


def test_discover_registered_python_after_setup():
    assert "Find-Python -probe $Probe" in SCRIPT
    assert SCRIPT.count("Find-Python -probe $Probe") >= 2
    assert "HKCU:" in SCRIPT and "HKLM:" in SCRIPT
    assert "pyvenv.cfg" in SCRIPT
    assert "Get-Command py.exe" in SCRIPT
    assert "Get-Command python.exe -All" in SCRIPT
    assert "WindowsApps" in SCRIPT


def test_python_installer_result_not_trusted_without_probe():
    assert "if (($proc.ExitCode -ne 0) -and ($proc.ExitCode -ne 3010))" in SCRIPT
    assert "no verified 64-bit Python 3.13 with Tkinter" in SCRIPT
    assert "python-setup.log" in SCRIPT
    assert "Test-Python -executable $VenvExe -probe $Probe" in SCRIPT
    assert PROBE.is_file()


def test_powershell_file_is_ascii_and_preserves_install_rollback():
    assert SCRIPT.isascii()
    assert "Rolling back only files actually changed" in SCRIPT
    assert "code-backup-" in SCRIPT
    assert "python313" in SCRIPT
    assert "NoLaunch" in SCRIPT
