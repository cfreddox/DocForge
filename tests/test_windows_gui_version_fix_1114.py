from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_graphical_setup_does_not_pin_smoke_test_to_old_version():
    source = (ROOT / "windows" / "Setup-DocForge.ps1").read_text(encoding="utf-8-sig")
    assert "OK: DocForge 1\\.10\\.0" not in source
    assert "[0-9]+\\.[0-9]+\\.[0-9]+" in source


def test_success_marker_matches_current_and_future_versions():
    pattern = r"(?m)^OK: DocForge [0-9]+\.[0-9]+\.[0-9]+;.*GUI imports"
    for version in ("1.10.0", "1.11.0", "1.11.4", "2.0.0"):
        assert re.search(pattern, f"OK: DocForge {version}; Markdown, DOCX, PPTX, XLSX to PDF; GUI imports")
    assert not re.search(pattern, "ERROR: DocForge 1.11.0; GUI imports")


def test_setup_still_checks_install_completion_and_files():
    source = (ROOT / "windows" / "Setup-DocForge.ps1").read_text(encoding="utf-8-sig")
    assert "Test-DocForgeInstalled" in source
    assert "Test-DocForgeLogFailure" in source
    assert "SUCCESS\\." in source
    assert "Installed location:" in source
