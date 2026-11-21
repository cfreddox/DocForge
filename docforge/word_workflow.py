"""Editable PDF -> DOCX -> PDF workflow.

An original PDF has no general-purpose editable paragraph structure.  This
module creates an *independent* DOCX working copy and exports a new PDF from
that copy.  It never draws replacement text over the source PDF, and never
writes back to the original document.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess

import pymupdf as fitz
from docx import Document
from docx.shared import Pt, Inches

from .core import ConversionError, native_office_convert, unique_path


def _simple_pdf_to_docx(source: Path, output: Path) -> None:
    """Text-and-picture fallback when pdf2docx is not installed.

    Preserve the actual reading order of text/image blocks, paragraphs, font
    emphasis, and explicit page breaks.  This does not promise original PDF
    positioning or recover raster-scanned text without OCR.
    """
    word = Document()
    inserted = False
    with fitz.open(source) as pdf:
        if pdf.needs_pass:
            raise ConversionError("PDF защищён паролем")
        if len(pdf) < 1:
            raise ConversionError("PDF не содержит страниц")
        section = word.sections[0]
        page = pdf[0]
        if 200 < page.rect.width < 2000 and 200 < page.rect.height < 2000:
            section.page_width = Pt(page.rect.width)
            section.page_height = Pt(page.rect.height)
        section.left_margin = Pt(36)
        section.right_margin = Pt(36)
        section.top_margin = Pt(40)
        section.bottom_margin = Pt(40)
        for page_number, page in enumerate(pdf):
            if page_number:
                word.add_page_break()
            blocks = page.get_text('dict', sort=True).get('blocks', [])
            for block in blocks:
                if block.get('type') == 1 and block.get('image'):
                    try:
                        data = bytes(block['image'])
                        width = min(max(0.7, (block['bbox'][2] - block['bbox'][0]) / 72),
                                    max(1, (page.rect.width - 72) / 72))
                        word.add_paragraph().add_run().add_picture(BytesIO(data), width=Inches(width))
                        inserted = True
                    except (OSError, ValueError, TypeError):
                        continue
                    continue
                if block.get('type') != 0:
                    continue
                p = None
                for line in block.get('lines', []):
                    spans = line.get('spans', [])
                    if not spans or not any(span.get('text', '').strip() for span in spans):
                        continue
                    if p is None:
                        p = word.add_paragraph()
                    elif p.runs:
                        p.add_run().add_break()
                    for span in spans:
                        text = span.get('text', '')
                        if not text:
                            continue
                        run = p.add_run(text)
                        run.bold = bool(span.get('flags', 0) & 16)
                        run.italic = bool(span.get('flags', 0) & 2)
                        run.font.size = Pt(max(6, min(float(span.get('size', 11)), 60)))
                        inserted |= bool(text.strip())
    if not inserted:
        raise ConversionError('В PDF нет извлекаемого текста или изображений. Для скана сначала выполните OCR.')
    word.save(output)


def make_editable_copy(source: str | Path, *, output: str | Path | None = None,
                       use_layout_converter: bool = True) -> Path:
    """Produce a unique standalone DOCX. Prefer pdf2docx layout conversion."""
    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != '.pdf':
        raise ConversionError('Для редактирования выберите существующий PDF')
    destination = Path(output).expanduser().resolve() if output else source.with_name(source.stem + '_editable.docx')
    if destination.suffix.lower() != '.docx':
        raise ConversionError('Редактируемая копия должна иметь формат DOCX')
    if destination == source:
        raise ConversionError('Исходный PDF нельзя перезаписывать')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = unique_path(destination)
    # Optional pdf2docx is far better for columns, tables and images.
    # We never silently produce an empty or invalid Word file.
    if use_layout_converter and importlib.util.find_spec('pdf2docx') is not None:
        converter = None
        try:
            from pdf2docx import Converter
            converter = Converter(str(source))
            converter.convert(str(destination), start=0, end=None)
            Document(destination)  # validate output
            if destination.stat().st_size > 0:
                return destination
        except Exception:
            destination.unlink(missing_ok=True)
        finally:
            if converter is not None:
                converter.close()
    try:
        _simple_pdf_to_docx(source, destination)
        Document(destination)
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def export_edited_pdf(docx_path: str | Path, *, output: str | Path | None = None) -> Path:
    """Return a new PDF rendered from edited document contents, never overlay."""
    docx_path = Path(docx_path).expanduser().resolve()
    if not docx_path.is_file() or docx_path.suffix.lower() != '.docx':
        raise ConversionError('Сначала сохраните редактируемый DOCX')
    dest = (Path(output).expanduser().resolve() if output else
            docx_path.with_name(docx_path.stem.removesuffix('_editable') + '_edited.pdf'))
    if dest.suffix.lower() != '.pdf':
        raise ConversionError('Результат должен быть PDF')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = unique_path(dest)
    try:
        native_office_convert(docx_path, 'pdf', dest)
        with fitz.open(dest) as pdf:
            if len(pdf) < 1:
                raise ConversionError('Экспортированный PDF пуст')
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return dest


def open_in_word_processor(docx: str | Path) -> subprocess.Popen:
    """Open DOCX with an already available handler; not required for PDF export."""
    docx = Path(docx).resolve()
    if not docx.is_file():
        raise ConversionError('Редактируемая копия DOCX не найдена')
    if os.name == 'nt':
        # os.startfile uses the registered DOCX application if present.
        os.startfile(str(docx))  # type: ignore[attr-defined]
        return None  # type: ignore[return-value]
    raise ConversionError('Для расширенного редактирования DOCX используйте установленный текстовый редактор либо встроенный редактор DocForge')


def replace_pdf_content(source: str | Path, old: str, new: str,
                        *, output: str | Path | None = None) -> Path:
    """Script-friendly real text replacement via a DOCX working copy.

    Match text across runs when necessary, including table cells.  This
    deliberately changes the DOCX content rather than overlaying PDF glyphs.
    """
    if not old:
        raise ConversionError('Для замены укажите непустой исходный текст')
    working=make_editable_copy(source)
    document=Document(working)
    count=0
    paragraphs=list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    for paragraph in paragraphs:
        if old not in paragraph.text:
            continue
        local_count=paragraph.text.count(old)
        count+=local_count
        # Prefer replacing inside the original run to retain formatting.
        if any(old in run.text for run in paragraph.runs):
            for run in paragraph.runs:
                run.text=run.text.replace(old,new)
        else:
            paragraph.text=paragraph.text.replace(old,new)
    if not count:
        raise ConversionError(f'Фрагмент «{old[:80]}» не найден в распознанном тексте PDF')
    document.save(working)
    return export_edited_pdf(working,output=output)
