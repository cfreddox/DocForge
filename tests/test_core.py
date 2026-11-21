from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image, ImageDraw
from docx import Document
from pypdf import PdfReader

from docforge.core import (ConversionError, common_targets, compress_pdf, convert, doctor,
                           merge_pdfs, missing_dependencies, parse_pages, rotate_pdf,
                           source_ext, split_pdf, targets_for, unique_path, validate_input,
                           _resource_fetcher)


@pytest.fixture
def sample_md(tmp_path):
    file = tmp_path / "Доклад к семинару.md"
    file.write_text("""# Заголовок проекта

Текст на **русском языке**, дата 2026 и формула `x = 5`.

## Раздел 2

- Первый пункт
- Второй пункт

| Поле | Значение |
|---|---|
| Вариант | 15 |
""", encoding="utf-8")
    return file


def _pdf_text(path):
    with fitz.open(path) as pdf:
        return "\n".join(p.get_text() for p in pdf)


def test_conversion_targets():
    assert "pdf" in targets_for("a.md")
    assert "md" in targets_for("a.pdf")
    assert "pdf" not in targets_for("a.pdf")
    assert "docx" in targets_for("a.pdf")
    assert "png" in targets_for("b.webp")
    assert targets_for("b.unsupported") == []
    assert "pdf" in common_targets(["a.md", "b.docx"])
    assert source_ext("q.JPEG") == "jpg"
    assert missing_dependencies("md", "pdf") == []


def test_bad_input_and_fake_pdf(tmp_path):
    with pytest.raises(ConversionError, match="не найден"):
        validate_input(tmp_path / "missing.pdf")
    p = tmp_path / "fake.pdf"
    p.write_text("Это не PDF", encoding="utf-8")
    with pytest.raises(ConversionError, match="не похож"):
        convert(p, "md")
    p = tmp_path / "fake.bin"
    p.write_bytes(b"123")
    with pytest.raises(ConversionError, match="не поддерживается"):
        convert(p, "pdf")


def test_parse_pages():
    assert parse_pages("all", 3) == [0, 1, 2]
    assert parse_pages("1,3-4", 5) == [0, 2, 3]
    with pytest.raises(ConversionError):
        parse_pages("0", 3)
    with pytest.raises(ConversionError):
        parse_pages("4", 3)
    with pytest.raises(ConversionError):
        parse_pages("2-1", 3)
    with pytest.raises(ConversionError):
        parse_pages("1,1", 3)
    with pytest.raises(ConversionError):
        parse_pages("abc", 3)


def test_unique_output_paths(tmp_path):
    path = tmp_path / "report.pdf"
    assert unique_path(path) == path
    path.touch()
    assert unique_path(path).name == "report (2).pdf"
    (tmp_path / "report (2).pdf").touch()
    assert unique_path(path).name == "report (3).pdf"
    folder = tmp_path / "images"
    folder.mkdir()
    assert unique_path(folder, is_dir=True).name == "images (2)"


def test_md_pdf_md_roundtrip_unicode(sample_md):
    pdf = convert(sample_md, "pdf")
    assert pdf.suffix == ".pdf"
    assert pdf.stat().st_size > 1000
    txt = _pdf_text(pdf)
    assert "Заголовок проекта" in txt
    assert "Вариант" in txt
    assert "Первый пункт" in txt
    reconstructed = convert(pdf, "md")
    assert reconstructed.is_dir()
    result = (reconstructed / "Доклад к семинару.md").read_text(encoding="utf-8")
    assert "Заголовок проекта" in result
    assert "русском языке" in result
    assert "Вариант" in result
    assert "# " in result


def test_pdf_txt_and_docx(sample_md):
    pdf = convert(sample_md, "pdf")
    text = convert(pdf, "txt")
    assert "Заголовок" in text.read_text(encoding="utf-8")
    docx = convert(pdf, "docx")
    doc = Document(docx)
    assert "Заголовок" in "\n".join(p.text for p in doc.paragraphs)


def test_md_docx_docx_md_and_html(sample_md):
    word = convert(sample_md, "docx")
    assert "Заголовок" in "\n".join(p.text for p in Document(word).paragraphs)
    reconstructed = convert(word, "md")
    assert reconstructed.is_dir()
    assert "Заголовок" in (reconstructed / f"{word.stem}.md").read_text(encoding="utf-8")
    html = convert(sample_md, "html")
    assert "<table>" in html.read_text(encoding="utf-8")
    pdf = convert(word, "pdf")
    assert "Заголовок" in _pdf_text(pdf)


def test_txt_pdf_and_no_overwrite(tmp_path):
    p = tmp_path / "Имя с пробелом.txt"
    p.write_text("Пример русского текста.\nВторая строка.\n", encoding="utf-8")
    first = convert(p, "pdf")
    second = convert(p, "pdf")
    assert first != second
    assert first.exists() and second.exists()
    assert "Пример русского" in _pdf_text(first)


def test_image_transparency_and_pdf_to_pages(tmp_path):
    img = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((50, 30, 150, 170), fill=(200, 40, 20, 255))
    imagefile = tmp_path / "пример.png"
    img.save(imagefile)
    jpeg = convert(imagefile, "jpg")
    with Image.open(jpeg) as actual:
        assert actual.mode == "RGB"
        assert actual.getpixel((0, 0)) == (255, 255, 255)
    pdf = convert(imagefile, "pdf")
    with fitz.open(pdf) as doc:
        assert len(doc) == 1
    pngs = convert(pdf, "png")
    jpgs = convert(pdf, "jpg")
    assert pngs.is_dir() and (pngs / "page_001.png").exists()
    assert jpgs.is_dir() and (jpgs / "page_001.jpg").exists()


def test_pdf_operations(sample_md):
    pdf = convert(sample_md, "pdf")
    combined = merge_pdfs([pdf, pdf])
    assert len(PdfReader(combined).pages) == 2
    rotated = rotate_pdf(combined, 90)
    assert len(PdfReader(rotated).pages) == 2
    assert all(p.get("/Rotate") == 90 for p in PdfReader(rotated).pages)
    parts = split_pdf(combined, "1-2")
    assert len(list(parts.glob("page_*.pdf"))) == 2
    assert len(PdfReader(parts / "page_001.pdf").pages) == 1
    compressed = compress_pdf(combined, "ebook")
    assert len(PdfReader(compressed).pages) == 2
    assert compressed.stat().st_size > 1000


def test_pdf_errors(sample_md):
    pdf = convert(sample_md, "pdf")
    with pytest.raises(ConversionError):
        merge_pdfs([pdf])
    with pytest.raises(ConversionError):
        rotate_pdf(pdf, 45)
    with pytest.raises(ConversionError):
        split_pdf(pdf, "7")
    with pytest.raises(ConversionError):
        compress_pdf(pdf, "bad")
    with pytest.raises(ConversionError):
        convert(pdf, "epub")


def test_resource_fetcher_rejects_network_and_outside(tmp_path):
    fetch = _resource_fetcher(tmp_path)
    with pytest.raises(ValueError, match="внешних"):
        fetch("https://example.com/tracker.png")
    with pytest.raises(ValueError, match="вне папки"):
        fetch("file:///etc/passwd")
    image = tmp_path / "picture.png"
    Image.new("RGB", (4, 4), "white").save(image)
    resource = fetch(image.as_uri())
    assert resource.read()
    resource.close()


def test_image_relative_markdown(sample_md):
    folder = sample_md.parent
    Image.new("RGB", (70, 20), "red").save(folder / "scene.png")
    with sample_md.open("a", encoding="utf-8") as stream:
        stream.write("\n![Изображение](scene.png)\n")
    pdf = convert(sample_md, "pdf")
    with fitz.open(pdf) as doc:
        assert doc[0].get_images()


def test_cli_subprocess(sample_md):
    cmd = [sys.executable, "-m", "docforge", "convert", "--to", "pdf", str(sample_md)]
    process = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert process.returncode == 0, process.stderr
    assert Path(process.stdout.strip()).exists()
    version = subprocess.run([sys.executable, "-m", "docforge", "--version"],
                              capture_output=True, text=True, check=False)
    assert version.returncode == 0
    assert "1.11.0" in version.stdout
    bad = subprocess.run([sys.executable, "-m", "docforge", "convert", "--to", "epub", str(sample_md.with_suffix(".pdf"))],
                         capture_output=True, text=True, check=False)
    assert bad.returncode == 1


def test_gui_drop_path_parser_no_display(tmp_path):
    import tkinter
    from docforge.gui import dropped_paths
    p1 = tmp_path / "файл один.md"
    p2 = tmp_path / "second.pdf"
    p1.write_text("hi")
    p2.write_bytes(b"%PDF-1.7")
    tcl = tkinter.Tcl()
    serialized = tcl.call("list", str(p1), str(p2))
    result = dropped_paths(SimpleNamespace(tk=tcl), SimpleNamespace(data=serialized))
    assert result == [p1, p2]


def test_pdf_md_exports_embedded_images(tmp_path):
    picture = tmp_path / "photo.png"
    Image.new("RGB", (210, 150), "navy").save(picture)
    pdf = convert(picture, "pdf")
    # A fully scanned PDF has no text; Tesseract may or may not recognize it.
    # Add one text page so extraction is deterministic.
    import fitz
    with fitz.open(pdf) as doc:
        with fitz.open() as merged:
            merged.insert_pdf(doc)
            extra = merged.new_page()
            extra.insert_text((40, 40), "Reference text")
            input_pdf = tmp_path / "with-image.pdf"
            merged.save(str(input_pdf))
    markdown = convert(input_pdf, "md")
    assert markdown.is_dir()
    content = (markdown / "with-image.md").read_text(encoding="utf-8")
    assert "Reference text" in content
    assert "![Изображение" in content
    assert list((markdown / "assets").glob("image_*"))
    assert "assets/image_001." in content
    # Reconvert from the self-contained folder: all links must resolve locally.
    roundtrip = convert(markdown / "with-image.md", "pdf")
    with fitz.open(roundtrip) as doc:
        assert any(page.get_images() for page in doc)


def test_ocr_scanned_pdf(tmp_path):
    if not __import__("shutil").which("tesseract"):
        pytest.skip("No Tesseract")
    from PIL import ImageFont
    image = Image.new("RGB", (900, 160), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 55)
    ImageDraw.Draw(image).text((30, 40), "Hello OCR 123", fill="black", font=font)
    image_path = tmp_path / "scan.png"
    image.save(image_path)
    pdf = convert(image_path, "pdf")
    output = convert(pdf, "txt")
    assert "Hello" in output.read_text(encoding="utf-8")


def test_gui_launch_under_virtual_display(sample_md):
    if not __import__("shutil").which("xvfb-run"):
        pytest.skip("Xvfb not available")
    script = '''
from pathlib import Path
from docforge.gui import MainWindow, RootClass, setup_style
root = RootClass()
setup_style(root)
ui = MainWindow(root, [Path(r"%s")])
assert ui.format_var.get() == 'PDF'
root.after(220, root.destroy)
root.mainloop()
''' % str(sample_md)
    result = subprocess.run(["xvfb-run", "-a", sys.executable, "-c", script],
                            text=True, capture_output=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


def test_quick_conversion_under_virtual_display(sample_md):
    if not __import__("shutil").which("xvfb-run"):
        pytest.skip("Xvfb not available")
    script = '''
from pathlib import Path
from docforge.gui import AppHost, QuickDialog, RootClass, setup_style
root = RootClass(); setup_style(root); host = AppHost(root)
root.withdraw()
quick = QuickDialog(host, [Path(r"%s")])
quick._start('pdf')
def finish():
    assert quick.out is not None and quick.out.is_file(), 'Quick conversion failed'
    root.destroy()
root.after(2000, finish)
root.mainloop()
''' % str(sample_md)
    result = subprocess.run(["xvfb-run", "-a", sys.executable, "-c", script],
                            text=True, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr



def test_txt_to_md_preserves_line_breaks(tmp_path):
    text = tmp_path / "notes.txt"
    text.write_text("""Первая строка
Вторая строка

Третий абзац
Четвертая строка
""", encoding="utf-8")
    md = convert(text, "md")
    body = md.read_text(encoding="utf-8")
    assert "Первая строка  \nВторая строка" in body
    assert "\n\nТретий абзац  \nЧетвертая строка" in body
    pdf = convert(text, "pdf")
    extracted = _pdf_text(pdf)
    assert "Первая строка" in extracted and "Вторая строка" in extracted and "Третий абзац" in extracted


def test_pdf_md_does_not_repeat_same_image(tmp_path):
    import fitz
    pic = tmp_path / "img.png"
    Image.new("RGB", (80, 50), "orange").save(pic)
    pdf = tmp_path / "dup-image.pdf"
    doc = fitz.open()
    p1 = doc.new_page()
    rect = fitz.Rect(50, 50, 220, 160)
    p1.insert_image(rect, filename=str(pic))
    p2 = doc.new_page()
    p2.insert_text((50, 50), "Вторая страница")
    p2.insert_image(rect, filename=str(pic))
    doc.save(str(pdf))
    doc.close()
    bundle = convert(pdf, "md")
    md = (bundle / "dup-image.md").read_text(encoding="utf-8")
    assert md.count("![Изображение страницы") == 1
    assert (bundle / "assets").is_dir()
