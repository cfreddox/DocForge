"""DocForge 1.2: portable DOCX exports, Nautilus native menu, in-place update."""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import types
import zipfile
from pathlib import Path
from urllib.parse import unquote

import fitz
import pytest
from PIL import Image
from docx import Document

from docforge.core import ConversionError, convert


@pytest.fixture
def rich_docx(tmp_path: Path) -> Path:
    image = tmp_path / "Фото с пробелом.png"
    Image.new("RGB", (140, 90), "cyan").save(image)
    document = Document()
    document.add_heading("Заголовок для проекта", 1)
    document.add_paragraph("Текст на русском языке и слово конвертация")
    document.add_picture(str(image))
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Имя"
    table.cell(0, 1).text = "Оценка"
    table.cell(1, 0).text = "Петров"
    table.cell(1, 1).text = "5"
    output = tmp_path / "Сложный документ.docx"
    document.save(output)
    with zipfile.ZipFile(output, "a") as archive:
        archive.writestr("word/embeddings/preview [1].xlsx", b"sample spreadsheet contents")
    return output


def _markdown_images(md: str) -> list[str]:
    return re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md)


def test_docx_portable_markdown_bundle_images_tables_and_attachments(rich_docx):
    bundle = convert(rich_docx, "md")
    assert bundle.is_dir()
    assert bundle.name == "Сложный документ_markdown"
    md_file = bundle / "Сложный документ.md"
    markdown = md_file.read_text(encoding="utf-8")
    assert "Заголовок для проекта" in markdown
    assert "Текст на русском языке" in markdown
    assert "| Имя" in markdown and "Петров" in markdown
    image_links = _markdown_images(markdown)
    assert len(image_links) == 1, markdown
    assert image_links[0].startswith("assets/")
    assert (bundle / unquote(image_links[0])).is_file()
    assert not Path(unquote(image_links[0])).is_absolute()
    embedded = bundle / "attachments" / "001_preview [1].xlsx"
    assert embedded.read_bytes() == b"sample spreadsheet contents"
    assert "attachments/001_preview%20%5B1%5D.xlsx" in markdown
    # Bundle can be copied to a different directory without breaking references.
    moved = rich_docx.parent / "Перенесено"
    shutil.copytree(bundle, moved)
    assert (moved / unquote(image_links[0])).is_file()
    assert "Текст на русском языке" in (moved / md_file.name).read_text(encoding="utf-8")


def test_docx_md_repeat_no_overwrite_and_markdown_to_pdf(rich_docx):
    first = convert(rich_docx, "md")
    second = convert(rich_docx, "md")
    assert first != second
    assert first.is_dir() and second.is_dir()
    md = first / f"{rich_docx.stem}.md"
    # Render a new PDF: the image reference must work after extraction.
    output = convert(md, "pdf")
    with fitz.open(output) as pdf:
        assert len(pdf) >= 1
        assert any(page.get_images() for page in pdf)


def test_docx_md_custom_output_and_no_partials(tmp_path, rich_docx, monkeypatch):
    import docforge.core as core
    output = tmp_path / "Документы"
    first = convert(rich_docx, "md", output)
    assert first.parent == output
    saved = list(output.iterdir())
    def fail(*args, **kwargs):
        raise ConversionError("Тестовая ошибка")
    monkeypatch.setattr(core, "docx_to_md", fail)
    with pytest.raises(ConversionError, match="Тестовая"):
        convert(rich_docx, "md", output)
    assert list(output.iterdir()) == saved


def _fake_gi(monkeypatch):
    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *args: None
    repo = types.ModuleType("gi.repository")
    class FakeMenuItem:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.submenu = None
            self.callback = None
        def set_submenu(self, value):
            self.submenu = value
        def connect(self, signal, callback, *args):
            assert signal == "activate"
            self.callback = lambda: callback(self, *args)
    class FakeMenu:
        def __init__(self):
            self.items = []
        def append_item(self, item):
            self.items.append(item)
    repo.GObject = types.SimpleNamespace(GObject=type("GObject", (), {}))
    repo.Nautilus = types.SimpleNamespace(MenuProvider=type("MenuProvider", (), {}),
                                         MenuItem=FakeMenuItem, Menu=FakeMenu)
    fake_gi.repository = repo
    monkeypatch.setitem(sys.modules, "gi", fake_gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repo)
    return repo


def test_nautilus_menu_launches_with_safe_filename(monkeypatch, tmp_path):
    _fake_gi(monkeypatch)
    filepath = tmp_path / "Книга ; $(touch attack).docx"
    filepath.write_bytes(b"test")
    program = tmp_path / "docforge"
    program.write_text("#!/bin/sh\nexit 0\n")
    program.chmod(0o755)
    module_path = Path(__file__).parent.parent / "nautilus" / "docforge_extension.py"
    spec = importlib.util.spec_from_file_location("nautilus_docforge_fake", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_APP", program)
    launches = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda args, **kwargs: launches.append((args, kwargs)))
    class Location:
        def __init__(self, value):
            self.value = value
        def get_path(self):
            return str(self.value)
    class FileInfo:
        def __init__(self, value):
            self.value = value
        def get_location(self):
            return Location(self.value)
    ext = module.DocForgeNautilus()
    menu = ext.get_file_items([FileInfo(filepath)])[0].submenu
    assert "формат" in menu.items[0].label
    menu.items[0].callback()
    assert launches[0][0] == [str(program), "--quick", str(filepath)]
    assert launches[0][1]["start_new_session"] is True
    assert ext.get_file_items([FileInfo(tmp_path / "bad.exe")]) == []
    background = ext.get_background_items(None)
    background[0].callback()
    assert launches[-1][0] == [str(program), "--dropzone"]
    assert not (tmp_path / "attack").exists()


def test_update_in_place_installs_files_integration_preserves_settings(tmp_path):
    source = Path(__file__).parent.parent
    app = tmp_path / "local" / "docforge"
    (app / "docforge").mkdir(parents=True)
    (app / "docforge" / "__init__.py").write_text('__version__ = "1.0.0"\n')
    (app / "venv" / "bin").mkdir(parents=True)
    (app / "venv" / "bin" / "python").touch()
    settings = tmp_path / "config" / "docforge" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"accent":"mint"}', encoding="utf-8")
    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(tmp_path / "local")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["DOCFORGE_TEST_SKIP_QT_SETUP"] = "1"  # Offline, test source update independently of pip.
    result = subprocess.run(["bash", str(source / "update.sh")], capture_output=True,
                            text=True, env=env, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert '1.11.0' in result.stdout
    assert (app / "docforge" / "core.py").is_file()
    assert (app / "venv" / "bin" / "python").exists()
    assert settings.read_text(encoding="utf-8") == '{"accent":"mint"}'
    ext = tmp_path / "local" / "nautilus-python" / "extensions" / "docforge_extension.py"
    assert ext.is_file()
    script = tmp_path / "local" / "nautilus" / "scripts" / "DocForge — стеклянная зона"
    assert script.is_file() and os.access(script, os.X_OK)


def test_clean_install_does_not_autostart_floating_window(tmp_path):
    """Fresh installations should not leave an always-visible zone after login."""
    source = Path(__file__).parent.parent
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update({"HOME": str(home), "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CONFIG_HOME": str(home / ".config")})
    result = subprocess.run(["bash", str(source / "install.sh"), "--skip-apt", "--skip-pip"],
                            capture_output=True, text=True, env=env, timeout=35, check=False)
    assert result.returncode == 0, result.stderr
    assert not (home / ".config/autostart/docforge-dropzone.desktop").exists()
    zone_script = home / ".local/share/nautilus/scripts/DocForge — стеклянная зона"
    assert "--dropzone" in zone_script.read_text(encoding="utf-8")
