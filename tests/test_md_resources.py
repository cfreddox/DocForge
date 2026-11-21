"""Regression: local Markdown resources survive actual export to PDF/DOCX/HTML."""
from __future__ import annotations

import zipfile
import json
from pathlib import Path
from urllib.parse import quote

import fitz
import pytest
from PIL import Image
from docx import Document

from docforge.core import ConversionError, convert
from docforge.md_assets import inspect_markdown


def _source(tmp_path: Path) -> tuple[Path, Path, Path]:
    assets = tmp_path / 'assets'
    assets.mkdir()
    picture = assets / 'фото [один].png'
    Image.new('RGB', (90, 60), '#52ad77').save(picture)
    attachments = tmp_path / 'attachments'
    attachments.mkdir()
    attachment = attachments / 'Таблица поставок.csv'
    attachment.write_text('Товар;Количество\nКнига;12\n', encoding='utf-8')
    md = tmp_path / 'Проект.md'
    md.write_text(f'''# Проект

Абзац до рисунка.

![Наш рисунок](assets/{quote(picture.name)})

Абзац после рисунка.

[Скачать таблицу](attachments/{quote(attachment.name)})

[Сайт проекта](https://example.org/)
''', encoding='utf-8')
    return md, picture, attachment


def test_ast_reports_images_and_attachments(tmp_path):
    md, image, attachment = _source(tmp_path)
    info = inspect_markdown(md)
    assert info.images == (image,)
    assert info.attachments == (attachment,)


def test_embeds_image_and_attachment_in_pdf(tmp_path):
    md, _, attachment = _source(tmp_path)
    result = convert(md, 'pdf')
    with fitz.open(result) as doc:
        assert sum(len(p.get_images()) for p in doc) >= 1
        assert 'docforge_001.csv' in doc.embfile_names()
        assert doc.embfile_get('docforge_001.csv') == attachment.read_bytes()
        assert json.loads(doc.embfile_get('docforge_manifest.json'))['docforge_001.csv'] == attachment.name
    assert result.is_file()


def test_embeds_image_and_attachment_in_docx(tmp_path):
    md, _, attachment = _source(tmp_path)
    result = convert(md, 'docx')
    doc = Document(result)
    assert len(doc.inline_shapes) == 1
    assert 'Вложения Markdown' in '\n'.join(p.text for p in doc.paragraphs)
    with zipfile.ZipFile(result) as archive:
        embedded = [name for name in archive.namelist() if name.startswith('word/embeddings/docforge/')]
        assert len(embedded) == 1
        assert archive.read(embedded[0]) == attachment.read_bytes()
        assert archive.testzip() is None


def test_html_is_portable_embedded_image(tmp_path):
    md, picture, _ = _source(tmp_path)
    out = convert(md, 'html')
    body = out.read_text(encoding='utf-8')
    assert 'data:image/png;base64' in body
    assert picture.name not in body


def test_missing_image_or_attachment_prevents_conversion(tmp_path):
    md, image, attachment = _source(tmp_path)
    image.unlink()
    with pytest.raises(ConversionError, match='Не найден локальный ресурс'):
        convert(md, 'pdf')
    assert not (tmp_path / 'Проект.pdf').exists()
    image.parent.mkdir(exist_ok=True)
    Image.new('RGB', (90, 60), 'green').save(image)
    attachment.unlink()
    with pytest.raises(ConversionError, match='Не найден локальный ресурс'):
        convert(md, 'docx')
    assert not (tmp_path / 'Проект.docx').exists()


def test_rejects_traversal_external_image_and_accepts_reference_links(tmp_path):
    outside = tmp_path.parent / 'secret_not_to_embed.bin'
    outside.write_bytes(b'secret')
    md = tmp_path / 'unsafe.md'
    md.write_text('![bad](../secret_not_to_embed.bin)', encoding='utf-8')
    with pytest.raises(ConversionError, match='выход за папку'):
        convert(md, 'pdf')
    md.write_text('![bad](https://example.org/p.png)', encoding='utf-8')
    with pytest.raises(ConversionError, match='Внешнее изображение'):
        convert(md, 'pdf')
    md.write_text('[посмотреть][local]\n\n[local]: images/pic.png\n', encoding='utf-8')
    (tmp_path/'images').mkdir()
    Image.new('RGB',(20,20),'yellow').save(tmp_path/'images'/'pic.png')
    # Linked files are attachments even when links use reference syntax.
    assert len(inspect_markdown(md).attachments) == 1


def test_html_link_attachment_embedded_as_data(tmp_path):
    md, _, attachment = _source(tmp_path)
    html_file = convert(md, 'html')
    html = html_file.read_text(encoding='utf-8')
    assert 'data:text/csv;base64' in html
    assert 'download="Таблица поставок.csv"' in html


def test_txt_produces_resources_sidecar(tmp_path):
    md, image, attachment = _source(tmp_path)
    txt = convert(md, 'txt')
    zip_file = txt.with_name(txt.stem + '_resources.zip')
    assert txt.exists() and zip_file.is_file()
    with zipfile.ZipFile(zip_file) as archive:
        paths = archive.namelist()
        assert any(image.name in item for item in paths)
        assert any(attachment.name in item for item in paths)


def test_epub_and_odt_preserve_nonimage_attachments(tmp_path):
    md, _, attachment = _source(tmp_path)
    for target in ('epub', 'odt'):
        result = convert(md, target)
        with zipfile.ZipFile(result) as archive:
            assert any(name.endswith(attachment.name) for name in archive.namelist())
            assert 'docforge-attachments/manifest.json' in archive.namelist()


def test_gui_add_md_detects_missing_image(tmp_path):
    import os, sys, subprocess
    md = tmp_path / 'broken.md'
    md.write_text('![missing](assets/not-there.png)', encoding='utf-8')
    code = '''
from docforge.gui import RootClass, MainWindow, setup_style, select_appearance
from docforge.appearance import load_settings
from tkinter import messagebox
from pathlib import Path
messagebox.showwarning=lambda *a,**k:None
root=RootClass();select_appearance(load_settings());setup_style(root)
app=MainWindow(root);app.add_files([Path(r"""%s""")])
assert 'проверьте вложения' in app.status.cget('text')
root.destroy()
'''
    env = os.environ.copy()
    env['XDG_CONFIG_HOME'] = str(tmp_path / 'config')
    run = subprocess.run(['xvfb-run','-a',sys.executable,'-c',code % md],
                         env=env,capture_output=True,text=True,timeout=25)
    assert run.returncode == 0, run.stderr


def test_gnome_top_panel_extension_removed():
    root = Path(__file__).resolve().parents[1]
    assert not (root/'gnome-extension').exists()
    assert not (root/'install-quick-settings.sh').exists()
    cleanup = (root/'remove-gnome-panel.sh').read_text()
    assert "UUID='docforge-quick@local'" in cleanup
    assert 'gnome-extensions disable' in cleanup


def test_cli_check_markdown(tmp_path):
    import sys
    import subprocess
    md, _, _ = _source(tmp_path)
    result = subprocess.run([sys.executable, '-m', 'docforge', 'check-md', str(md)],
                            capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stderr
    assert 'Изображений: 1' in result.stdout
    assert 'вложений: 1' in result.stdout
