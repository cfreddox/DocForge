"""Windows setup smoke test with real output files, no office suite dependency."""
from __future__ import annotations

import tempfile
from pathlib import Path

from launcher import configure_runtime

configure_runtime()

import pymupdf as fitz  # noqa: E402
import tkinter  # noqa: E402
import tkinterdnd2  # noqa: E402
import PySide6.QtCore  # noqa: E402
import pystray  # noqa: E402
import office2pdf  # noqa: E402
from docx import Document  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches  # noqa: E402
from docforge import __version__  # noqa: E402
from docforge.core import convert  # noqa: E402


def smoke() -> None:
    with tempfile.TemporaryDirectory(prefix='docforge-win-health-') as temp:
        folder = Path(temp)
        samples = []
        md = folder / 'sample.md'
        md.write_text('# DocForge test\n\nLocal conversion with no office suite.\n', encoding='utf-8')
        samples.append((md, 'DocForge test'))
        doc = Document()
        doc.add_heading('Native DOCX sample', level=1)
        doc.add_paragraph('The report paragraph is visible.')
        word = folder / 'sample.docx'
        doc.save(word)
        samples.append((word, 'Native DOCX sample'))
        slides = Presentation()
        slide = slides.slides.add_slide(slides.slide_layouts[6])
        shape = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        shape.text = 'Native PPTX sample'
        presentation = folder / 'sample.pptx'
        slides.save(presentation)
        samples.append((presentation, 'Native PPTX sample'))
        book = Workbook()
        book.active.append(['Native XLSX sample', 2026])
        workbook = folder / 'sample.xlsx'
        book.save(workbook)
        samples.append((workbook, 'Native XLSX sample'))
        for src, expected in samples:
            result = convert(src, 'pdf')
            with fitz.open(result) as pdf:
                assert len(pdf) >= 1, src.name
                extracted = '\n'.join(page.get_text() for page in pdf)
                if expected not in extracted:
                    raise RuntimeError(f'{src.name}: expected text {expected!r} is missing from PDF; extracted={extracted[:300]!r}')
        print(f'OK: DocForge {__version__}; Markdown, DOCX, PPTX, XLSX to PDF; GUI imports')


if __name__ == '__main__':
    smoke()
