from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_python_repair_is_after_normal_discovery():
    src = (ROOT / "windows/install.ps1").read_text()
    assert src.index("$candidate = Find-Python") < src.index("$repairArgs =")
    assert "'/repair /quiet /norestart /log" in src
    assert "Get-AuthenticodeSignature" in src
    assert "if (-not $candidate)" in src


def test_manual_repair_asks_permission():
    src = (ROOT / "windows/repair-python.ps1").read_text()
    assert "Read-Host 'Continue? Type YES'" in src
    assert "Get-AuthenticodeSignature" in src
    assert "'/repair /quiet /norestart /log" in src
    assert "Remove-Item" not in src


def test_root_launcher_exists():
    src = (ROOT / "REPAIR-PYTHON-WINDOWS.cmd").read_text()
    assert r"windows\repair-python.ps1" in src
