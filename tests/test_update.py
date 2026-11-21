"""Tests for the in-place 1.1 update and portable Markdown exports."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image

from docforge.appearance import (DEFAULTS, clamp_primary, config_file, load_settings,
                                 on_primary, palette, primary_monitor, sanitize_settings,
                                 save_settings)
from docforge.core import ConversionError, convert
from docforge.glass import glass_panel


def build_pdf(path: Path, with_image: bool = False, with_attachment: bool = False):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 80), "PDF to portable Markdown")
        if with_image:
            source = path.parent / "small picture.png"
            Image.new("RGB", (140, 90), "royalblue").save(source)
            page.insert_image(fitz.Rect(70, 140, 220, 220), filename=str(source))
        if with_attachment:
            doc.embfile_add("data.txt", b"sample attachment\n", filename="../unsafe [name].txt")
        doc.save(path)
    return path


def test_markdown_bundle_and_repeated_conversion(tmp_path):
    source = build_pdf(tmp_path / "Важный документ.pdf", True)
    bundle = convert(source, "md")
    assert bundle.is_dir() and bundle.name == "Важный документ_markdown"
    md = bundle / "Важный документ.md"
    content = md.read_text(encoding="utf-8")
    assert "portable Markdown" in content
    assert "assets/image_001.png" in content
    assert (bundle / "assets" / "image_001.png").is_file()
    second = convert(source, "md")
    assert second.is_dir() and second != bundle
    assert (second / "Важный документ.md").exists()
    assert md.read_text(encoding="utf-8") == content
    new_pdf = convert(md, "pdf")
    assert new_pdf.is_file()
    with fitz.open(new_pdf) as doc:
        assert any(page.get_images() for page in doc)


def test_attached_files_are_portable_and_sanitized(tmp_path):
    source = build_pdf(tmp_path / "attachments.pdf", with_attachment=True)
    bundle = convert(source, "md")
    md = (bundle / "attachments.md").read_text(encoding="utf-8")
    files = list((bundle / "attachments").iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b"sample attachment\n"
    assert files[0].parent == bundle / "attachments"
    assert "../" not in str(files[0].relative_to(bundle))
    # Filename with spaces and brackets is URL encoded correctly.
    assert "attachments/001_unsafe%20%5Bname%5D.txt" in md


def test_pdf_md_custom_output_directory_and_cleanup(tmp_path):
    source = build_pdf(tmp_path / "document.pdf")
    dest = tmp_path / "prepared"
    exported = convert(source, "md", dest)
    assert exported.parent == dest
    assert (exported / "document.md").is_file()
    # If the export fails, no new visible folder should remain.
    empty = tmp_path / "empty.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(empty)
    with pytest.raises(ConversionError):
        convert(empty, "md", dest)
    assert sorted(p.name for p in dest.iterdir()) == ["document_markdown"]


def test_settings_persistence_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert load_settings() == DEFAULTS
    assert DEFAULTS["always_on_top"] is False
    path = save_settings({"theme": "liquid_light", "accent": "mint", "opacity": 0.77,
                          "scale": 1.25, "zone_size": "large", "always_on_top": False})
    assert path == config_file()
    actual = load_settings()
    assert actual["theme"] == "liquid_light"
    assert actual["opacity"] == 0.77
    assert actual["always_on_top"] is False
    assert os.stat(path).st_mode & 0o777 == 0o600
    # Settings from an older release remain compatible; malformed keys ignored.
    path.write_text('{"theme": "unknown", "opacity": 99, "scale": -5, "accent": "pink"}', encoding="utf-8")
    assert load_settings()["theme"] == DEFAULTS["theme"]
    assert load_settings()["accent"] == "pink"
    # Legacy config is migrated away from always-on-top, without losing the theme.
    path.write_text('{"always_on_top":true,"accent":"pink"}', encoding="utf-8")
    assert load_settings()["always_on_top"] is False
    assert load_settings()["accent"] == "pink"
    # An explicit choice made after the update must continue to work.
    save_settings({"always_on_top": True})
    assert load_settings()["always_on_top"] is True
    assert load_settings()["opacity"] == DEFAULTS["opacity"]
    path.write_text('{broken', encoding="utf-8")
    assert load_settings() == DEFAULTS


def test_palette_and_glass_image():
    for name in ("liquid_dark", "liquid_light", "midnight"):
        style = palette({**DEFAULTS, "theme": name})
        assert style["accent"].startswith("#")
        image = glass_panel(300, 150, name, style["accent"])
        assert image.size == (300, 150)
        assert image.mode == "RGBA"
        assert image.getpixel((150, 75))[3] == 255
        assert image.getpixel((0, 0))[3] == 0


def test_primary_display_coordinates(monkeypatch):
    import docforge.appearance as ap
    monkeypatch.setenv("DISPLAY", ":10")
    root = SimpleNamespace(winfo_screenwidth=lambda: 3200, winfo_screenheight=lambda: 1080)
    monitors = "Monitors: 2\n 0: +DP-1 1280/400x1024/300+0+0  DP-1\n 1: +*HDMI-1 1920/520x1080/300+1280+0  HDMI-1\n"
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=monitors))
    assert primary_monitor(root) == (1280, 0, 1920, 1080)
    assert on_primary(root, 400, 200) == "400x200+2040+440"
    assert clamp_primary(root, 0, -200, 400, 200) == (1280, 0)
    assert clamp_primary(root, 99999, 99999, 400, 200) == (2800, 880)


def test_gui_settings_and_float_windows_xvfb(tmp_path):
    if not __import__("shutil").which("xvfb-run"):
        pytest.skip("No virtual display")
    script = '''
from pathlib import Path
from docforge.gui import AppHost, MainWindow, DropZone, QuickDialog, SettingsDialog, RootClass, setup_style, select_appearance
from docforge.appearance import load_settings
root = RootClass()
select_appearance(load_settings()); setup_style(root)
app = MainWindow(root)
zone = DropZone(app.host)
assert zone.drop is not None
root.update_idletasks()
assert not zone.overrideredirect(), 'Drop zone must be managed by the window manager'
assert not bool(int(zone.attributes("-topmost"))), 'Zone must not be topmost by default'
assert float(zone.attributes("-alpha")) <= 1.0
sample = Path('example.md')
quick = QuickDialog(app.host, [sample])
assert not quick.overrideredirect(), 'Quick chooser must be managed by the window manager'
assert not bool(int(quick.attributes("-topmost")))
quick.destroy()
zone_once = DropZone(app.host, temporary=True)
assert zone_once.temporary is True
from tkinter import filedialog
filedialog.askopenfilenames = lambda **_kwargs: [str(sample)]
zone_once.open_file()
assert zone_once.winfo_exists(), 'One-shot zone must stay visible until format selection'
assert zone_once._expanded and zone_once._actions, 'Selecting a file must expand conversion petals'
config = SettingsDialog(root, app.apply_settings)
config.theme_var.set('liquid_light')
config.accent_var.set('mint')
config.opacity_var.set(82)
config._save()
assert load_settings()['theme'] == 'liquid_light'
assert zone.drop.winfo_exists()
assert app.status.winfo_exists()
root.after(250, root.destroy)
root.mainloop()
'''
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "cfg")
    result = subprocess.run(["xvfb-run", "-a", __import__("sys").executable, "-c", script],
                            env=env, capture_output=True, text=True, timeout=25, check=False)
    assert result.returncode == 0, result.stderr
