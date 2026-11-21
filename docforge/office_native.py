"""Office document rendering without LibreOffice / Microsoft Office.

Preferred: office2pdf-python (Apache-2.0, Rust engine, wheels for Win/Linux).
Built-in fallback: PyMuPDF + Pandoc/openpyxl/python-pptx. Fallback output is
best-effort and cannot guarantee complex Microsoft Office print layout.
Every path writes to a staged destination; callers publish it atomically.
"""
from __future__ import annotations

import html
import importlib.util
import io
import logging
import math
import re
import tempfile
from pathlib import Path

LOG = logging.getLogger(__name__)


class NativeOfficeError(RuntimeError):
    pass


def preferred_available() -> bool:
    return importlib.util.find_spec('office2pdf') is not None


def _validate_pdf(destination: Path) -> None:
    import fitz
    if not destination.is_file() or destination.stat().st_size < 150:
        raise NativeOfficeError('Движок не создал PDF')
    with fitz.open(destination) as document:
        if document.page_count < 1:
            raise NativeOfficeError('PDF не содержит страниц')


def _office2pdf(source: Path, destination: Path) -> None:
    from office2pdf import convert_path, ConvertOptions
    result = convert_path(str(source), ConvertOptions(include_warnings=True))
    if not result.pdf:
        raise NativeOfficeError('Нативный движок вернул пустой результат')
    destination.write_bytes(result.pdf)
    for warning in getattr(result, 'warnings', ()) or ():
        LOG.warning('Office PDF: %s', warning)
    _validate_pdf(destination)


def _html_pdf(contents: str, destination: Path, *, resource_dir: Path | None = None,
              landscape: bool = False, css: str = '') -> None:
    import fitz
    width, height = (842, 595) if landscape else (595, 842)
    box = fitz.Rect(0, 0, width, height)
    body = fitz.Rect(39, 40, width - 39, height - 42)
    # A restricted archive allows relative file images but does not fetch the net.
    archive = fitz.Archive(str(resource_dir)) if resource_dir else None
    # Pandoc's standalone HTML contains browser-only selectors not accepted
    # by MuPDF's CSS parser. Strip the head; keep semantic body and our CSS.
    body_match = re.search(r'<body[^>]*>(.*?)</body\s*>', contents, flags=re.I | re.S)
    if body_match:
        contents = body_match.group(1)
    contents = re.sub(r'<style\b[^>]*>.*?</style\s*>', '', contents, flags=re.I | re.S)
    contents = re.sub(r'<script\b[^>]*>.*?</script\s*>', '', contents, flags=re.I | re.S)
    style = ("body {font-family: sans-serif; font-size: 11pt; color: #202733;} "
             "table {border-collapse:collapse; max-width:100%;} "
             "td,th {border: .7pt solid #a5b4c7; padding: 4pt;} "
             "img {max-width: 100%; height:auto;} " + css)
    writer = fitz.DocumentWriter(str(destination))
    try:
        story = fitz.Story(html=contents, user_css=style, archive=archive)
        story.write(writer, lambda _n, _f: (box, body, fitz.Identity))
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        writer.close()
    _validate_pdf(destination)


def _fallback_docx(source: Path, destination: Path) -> None:
    """Pandoc preserves semantic formatting (lists/tables/headings/images).

    It is *not* a Word layout engine, and cannot reproduce floating objects,
    section columns, sophisticated headers or tracked revisions exactly.
    """
    import subprocess
    # Embedding resources in the HTML avoids fragile temp media paths and
    # preserves image associations even with non-Latin/space-containing names.
    command = ['pandoc', str(source), '-f', 'docx', '-t', 'html5',
               '--standalone', '--embed-resources', '--wrap=none']
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=180, check=False, cwd=str(source.parent))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeOfficeError('Для резервного DOCX-рендера нужен Pandoc') from exc
    if proc.returncode:
        raise NativeOfficeError('Pandoc DOCX: ' + proc.stderr[-700:])
    _html_pdf(proc.stdout, destination, resource_dir=source.parent)


def _fallback_pptx(source: Path, destination: Path) -> None:
    """Preserve slide dimensions, text and images in approximate shape geometry."""
    import fitz
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    from pptx.dml.color import RGBColor
    prs = Presentation(str(source))
    sx = 72 / 914400
    width, height = prs.slide_width*sx, prs.slide_height*sx
    pdf = fitz.open()
    try:
        for slide in prs.slides:
            page = pdf.new_page(width=width, height=height)
            try:
                color = slide.background.fill.fore_color.rgb
                if color:
                    page.draw_rect(page.rect, fill=tuple(v/255 for v in color), color=None)
            except (AttributeError, ValueError, TypeError):
                pass
            for shape in slide.shapes:
                rect = fitz.Rect(shape.left*sx, shape.top*sx,
                                 (shape.left+shape.width)*sx,
                                 (shape.top+shape.height)*sx)
                if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                    continue
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    try:
                        page.insert_image(rect, stream=shape.image.blob, keep_proportion=True)
                    except (ValueError, RuntimeError):
                        LOG.warning('Не удалось перенести изображение со слайда')
                    continue
                try:
                    fill = shape.fill
                    if fill.type and fill.type == 1 and fill.fore_color.rgb:
                        color = tuple(v/255 for v in fill.fore_color.rgb)
                        page.draw_rect(rect, color=None, fill=color)
                except (AttributeError, TypeError, ValueError):
                    pass
                if getattr(shape, 'has_text_frame', False):
                    paragraphs = []
                    for para in shape.text_frame.paragraphs:
                        content = html.escape(para.text)
                        if not content:
                            paragraphs.append('<p>&nbsp;</p>')
                            continue
                        fragments = []
                        for run in para.runs:
                            piece = html.escape(run.text)
                            if run.font.bold: piece = f'<b>{piece}</b>'
                            if run.font.italic: piece = f'<i>{piece}</i>'
                            fragments.append(piece)
                        paragraphs.append('<p>' + (''.join(fragments) or content) + '</p>')
                    try:
                        page.insert_htmlbox(rect, ''.join(paragraphs),
                                            css='p {font-family: sans-serif; font-size: 13pt; margin:0;}')
                    except (ValueError, RuntimeError):
                        LOG.warning('Невозможно разместить текст фигуры на слайде')
                if getattr(shape, 'has_table', False):
                    table = shape.table
                    for row_idx, row in enumerate(table.rows):
                        for col_idx, cell in enumerate(row.cells):
                            rc = fitz.Rect(rect.x0 + rect.width*col_idx/len(table.columns),
                                rect.y0 + rect.height*row_idx/len(table.rows),
                                rect.x0 + rect.width*(col_idx+1)/len(table.columns),
                                rect.y0 + rect.height*(row_idx+1)/len(table.rows))
                            page.draw_rect(rc, color=(.62,.69,.78), width=.5)
                            page.insert_htmlbox(rc, f'<p>{html.escape(cell.text)}</p>',
                                                css='p{font-family:sans-serif;font-size:9pt;margin:2pt}')
        if not prs.slides:
            raise NativeOfficeError('Презентация не содержит слайдов')
        pdf.save(str(destination), garbage=3, deflate=True)
    finally:
        pdf.close()
    _validate_pdf(destination)


def _cell_css(cell) -> str:
    css: list[str] = []
    if cell.font and cell.font.bold: css.append('font-weight:bold')
    if cell.font and cell.font.italic: css.append('font-style:italic')
    if cell.alignment and cell.alignment.horizontal in {'center','right','left','justify'}:
        css.append(f'text-align:{cell.alignment.horizontal}')
    try:
        rgb = cell.fill.fgColor.rgb
        if cell.fill.patternType == 'solid' and isinstance(rgb,str) and len(rgb)>=6:
            css.append(f'background:#{rgb[-6:]}')
    except (ValueError, TypeError, AttributeError):
        pass
    return ';'.join(css)


def _fallback_xlsx(source: Path, destination: Path) -> None:
    """Make printable tables per worksheet, with cached formula values.

    Charts, spreadsheet recalculation and conditional formatting aren't
    reproduced in the fallback (never silently claim full Excel fidelity).
    """
    import fitz
    from openpyxl import load_workbook
    try:
        book = load_workbook(source, data_only=True, read_only=False)
    except Exception as exc:
        raise NativeOfficeError('Не удалось прочитать книгу XLSX') from exc
    output = fitz.open()
    try:
        for sheet in book.worksheets:
            if sheet.sheet_state != 'visible':
                continue
            if sheet.max_row * sheet.max_column > 150000:
                raise NativeOfficeError('Большая таблица: нужен нативный office2pdf')
            merged = {}
            for rg in sheet.merged_cells.ranges:
                merged[(rg.min_row,rg.min_col)] = (rg.max_row-rg.min_row+1,rg.max_col-rg.min_col+1)
                for i in range(rg.min_row,rg.max_row+1):
                    for j in range(rg.min_col,rg.max_col+1):
                        if (i,j)!=(rg.min_row,rg.min_col): merged[(i,j)]=None
            rows = []
            # Skip excessive blank XLSX tail; retain structurally populated cells.
            lastrow = min(sheet.max_row, 3000)
            lastcol = min(sheet.max_column, 48)
            for row in sheet.iter_rows(min_row=1,max_row=lastrow,max_col=lastcol):
                cells = []
                for cell in row:
                    if (cell.row, cell.column) in merged and merged[(cell.row,cell.column)] is None:
                        continue
                    span=merged.get((cell.row,cell.column))
                    attrs = ''
                    if span:
                        if span[0]>1: attrs+=f' rowspan="{span[0]}"'
                        if span[1]>1: attrs+=f' colspan="{span[1]}"'
                    css = _cell_css(cell)
                    raw = cell.value
                    if isinstance(raw, bool): raw = 'TRUE' if raw else 'FALSE'
                    if raw is None: raw=''
                    cells.append(f'<td{attrs} style="{css}">{html.escape(str(raw))}</td>')
                rows.append('<tr>' + ''.join(cells) + '</tr>')
            title = html.escape(sheet.title)
            htm = f'<h2>{title}</h2><table>' + ''.join(rows) + '</table>'
            with tempfile.TemporaryDirectory(prefix='docforge-sheet-') as d:
                pdf = Path(d) / 'sheet.pdf'
                landscape = sheet.page_setup.orientation == 'landscape' or lastcol > 8
                _html_pdf(htm, pdf, landscape=landscape,
                          css='table {font-size: 8pt;} td {padding: 3pt;}')
                with fitz.open(pdf) as pages:
                    output.insert_pdf(pages)
        if output.page_count < 1:
            raise NativeOfficeError('В XLSX нет видимых листов')
        output.save(str(destination), garbage=3, deflate=True)
    finally:
        output.close()
        book.close()
    _validate_pdf(destination)


def _xlsx_visible_text_sample(source: Path, *, limit: int = 12) -> list[str]:
    """Small, deterministic spot check of visible worksheet labels.

    Only check textual cell values; numbers can be formatted and formulas may
    need recalculation. A failed probe is not by itself evidence of visual loss.
    """
    from openpyxl import load_workbook
    book = load_workbook(source, read_only=True, data_only=True)
    try:
        samples: list[str] = []
        for sheet in book:
            if sheet.sheet_state != 'visible':
                continue
            for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 40),
                                       max_col=min(sheet.max_column, 16), values_only=True):
                for cell in row:
                    if isinstance(cell, str) and len(cell.strip()) >= 4:
                        samples.append(' '.join(cell.split()))
                        if len(samples) >= limit:
                            return samples
        return samples
    finally:
        book.close()


def _xlsx_text_check(source: Path, destination: Path) -> bool:
    """Check PDF text searchability against a few actual workbook labels."""
    import pymupdf
    samples = _xlsx_visible_text_sample(source)
    if not samples:
        return True  # numeric-only sheets are checked by successful PDF render
    with pymupdf.open(destination) as pdf:
        extracted = ' '.join(' '.join(page.get_text().split()) for page in pdf)
    return any(label.casefold() in extracted.casefold() for label in samples)


def office_to_pdf(source: Path, destination: Path, *, strict: bool = False) -> str:
    """Return actual engine name; no LibreOffice binaries or PATH are needed.

    Strict mode enforces the full native engine; best-effort falls back to
    simpler renderers with documented limitations.
    """
    source, destination = Path(source), Path(destination)
    fmt = source.suffix.lower()
    if fmt not in {'.docx', '.pptx', '.xlsx'}:
        raise NativeOfficeError('Нативный экспорт доступен для DOCX, PPTX и XLSX')
    if preferred_available():
        try:
            _office2pdf(source, destination)
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise NativeOfficeError(f'office2pdf не смог преобразовать документ: {exc}') from exc
        if fmt != '.xlsx' or _xlsx_text_check(source, destination):
            return 'office2pdf'
        # Some Windows native font fallbacks render workbook labels into PDF
        # without searchable Unicode mappings. Never pass an unverifiable PDF
        # silently as a successful conversion. Re-render the table using our
        # documented simplified engine and verify the source labels are present.
        LOG.warning('XLSX text layer is missing workbook labels; using validated simplified renderer')
        with tempfile.TemporaryDirectory(prefix='docforge-xlsx-verify-') as tmp:
            fallback = Path(tmp) / 'checked.pdf'
            _fallback_xlsx(source, fallback)
            if not _xlsx_text_check(source, fallback):
                raise NativeOfficeError('Нельзя подтвердить наличие текста XLSX в результате PDF')
            fallback.replace(destination)
        return 'simplified-verified'
    elif strict:
        raise NativeOfficeError('Точный движок office2pdf не установлен')
    if fmt == '.docx':
        _fallback_docx(source, destination)
    elif fmt == '.pptx':
        _fallback_pptx(source, destination)
    elif fmt == '.xlsx':
        _fallback_xlsx(source, destination)
    return 'simplified'


def text_html_to_pdf(html_doc: str, destination: Path, *, resource_dir: Path | None = None) -> None:
    _html_pdf(html_doc, destination, resource_dir=resource_dir)
