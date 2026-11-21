"""Conversion engine: no GUI imports and no network requests."""
from __future__ import annotations

import html as html_lib
from html.parser import HTMLParser
import importlib.util
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

SUPPORTED = {
    "pdf": ("md", "txt", "docx", "png", "jpg"),
    "md": ("pdf", "html", "docx", "odt", "epub", "txt"),
    "markdown": ("pdf", "html", "docx", "odt", "epub", "txt"),
    "txt": ("pdf", "md", "html", "docx", "odt", "epub"),
    "html": ("pdf", "md", "docx", "txt", "odt", "epub"),
    "htm": ("pdf", "md", "docx", "txt", "odt", "epub"),
    "docx": ("pdf", "md", "txt", "html", "odt", "epub"),
    "doc": (),  # Legacy binary Word: not supported without an office importer
    "odt": ("pdf", "docx", "md", "txt", "html"),
    "rtf": ("pdf", "docx", "odt", "txt"),
    "pptx": ("pdf",),
    "ppt": (),  # Legacy binary PowerPoint
    "odp": (),  # Requires an ODP drawing renderer
    "xlsx": ("pdf", "csv"),
    "xls": (),  # Legacy binary Excel
    "ods": (),  # Requires a Calc-compatible layout engine
    "csv": ("pdf", "xlsx"),
    "epub": ("pdf", "md", "txt", "html", "docx"),
    "png": ("pdf", "jpg", "webp"),
    "jpg": ("pdf", "png", "webp"),
    "jpeg": ("pdf", "png", "webp"),
    "webp": ("pdf", "png", "jpg"),
    "bmp": ("pdf", "png", "jpg", "webp"),
    "tiff": ("pdf", "png", "jpg", "webp"),
    "tif": ("pdf", "png", "jpg", "webp"),
}
IMAGE_TYPES = frozenset({"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif"})
OFFICE_TYPES = frozenset({"docx", "doc", "odt", "rtf", "pptx", "ppt", "odp", "xlsx", "xls", "ods", "csv"})
PANDOC_TYPES = frozenset({"md", "markdown", "txt", "html", "htm", "docx", "odt", "rtf", "epub"})
EXT_ALIASES = {"jpeg": "jpg", "markdown": "md", "htm": "html", "tif": "tiff"}
IMAGE_DEST = frozenset({"png", "jpg", "webp"})
LO_FILTER = {"pdf": "pdf", "docx": "docx", "odt": "odt", "pptx": "pptx", "odp": "odp", "xlsx": "xlsx", "ods": "ods", "csv": "csv", "txt": "txt"}


class ConversionError(RuntimeError):
    """A readable failure to show in the GUI or CLI."""


def normalize_ext(ext: str) -> str:
    ext = ext.lower().strip().lstrip(".")
    return EXT_ALIASES.get(ext, ext)


def source_ext(path: str | Path) -> str:
    return normalize_ext(Path(path).suffix)


def needs(source: str, target: str) -> tuple[str, ...]:
    """Runtime requirements with no LibreOffice or Microsoft Office.

    office2pdf is installed for the full renderer; built-in fallbacks allow
    basic office export if its platform wheel is unavailable.
    """
    src, dst = normalize_ext(source), normalize_ext(target)
    if src == "pdf":
        return ("fitz", "python-docx") if dst == "docx" else (("fitz",) if dst in {"md", "txt", "png", "jpg"} else ())
    if src in IMAGE_TYPES:
        return ("Pillow",)
    if dst == "pdf":
        if src == "docx":
            return ("fitz", "pandoc")  # fallback when native engine absent
        if src == "pptx":
            return ("fitz", "python-pptx")
        if src in {"xlsx", "csv"}:
            return ("fitz", "openpyxl")
        return ("pandoc", "fitz")
    if {src, dst} == {"csv", "xlsx"}:
        return ("openpyxl",)
    if src in PANDOC_TYPES:
        return ("pandoc",)
    return ()


def missing_dependencies(source: str, target: str) -> list[str]:
    modules = {"fitz": "fitz", "python-docx": "docx", "Pillow": "PIL",
               "python-pptx": "pptx", "openpyxl": "openpyxl"}
    missing = []
    for item in needs(source, target):
        if item in modules:
            if importlib.util.find_spec(modules[item]) is None:
                missing.append(item)
        elif not shutil.which(item):
            missing.append(item)
    return missing


def targets_for(path: str | Path, only_available: bool = True) -> list[str]:
    ext = source_ext(path)
    targets = list(SUPPORTED.get(ext, ()))
    if only_available:
        targets = [dest for dest in targets if not missing_dependencies(ext, dest)]
    return targets


def common_targets(paths: list[str | Path], only_available: bool = True) -> list[str]:
    if not paths:
        return []
    candidates = set(targets_for(paths[0], only_available))
    for path in paths[1:]:
        candidates &= set(targets_for(path, only_available))
    preferred = ["pdf", "md", "docx", "txt", "html", "png", "jpg", "odt", "epub", "webp", "pptx", "xlsx", "ods", "odp", "csv"]
    return sorted(candidates, key=lambda x: (preferred.index(x) if x in preferred else len(preferred), x))


def unique_path(path: Path, is_dir: bool = False) -> Path:
    if not path.exists():
        return path
    for i in range(2, 10001):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}") if not is_dir else path.with_name(f"{path.name} ({i})")
        if not candidate.exists():
            return candidate
    raise ConversionError("Слишком много файлов с совпадающими именами")


def validate_input(path: str | Path, allowed: set[str] | None = None) -> Path:
    p = Path(path).expanduser().absolute()
    if not p.is_file():
        raise ConversionError(f"Файл не найден: {p}")
    if not os.access(p, os.R_OK):
        raise ConversionError(f"Файл не читается: {p}")
    ext = source_ext(p)
    if ext not in SUPPORTED or (allowed is not None and ext not in allowed):
        raise ConversionError(f"Формат .{p.suffix.lstrip('.')} не поддерживается")
    if ext == "pdf":
        with p.open("rb") as stream:
            if b"%PDF-" not in stream.read(1024):
                raise ConversionError(f"Файл не похож на PDF: {p.name}")
    return p


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 240) -> None:
    try:
        proc = subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True,
                              text=True, errors="replace", timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ConversionError(f"Не найдена программа: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(f"Превышено время обработки ({timeout} сек.)") from exc
    if proc.returncode:
        detail = (proc.stderr or proc.stdout or "неизвестная ошибка").strip()[-1300:]
        raise ConversionError(f"Ошибка {Path(command[0]).name}: {detail}")


def _resource_fetcher(root: Path):
    """WeasyPrint fetcher that never requests network or unrelated local files."""
    from weasyprint.urls import URLFetcher
    permitted = root.resolve()

    class LocalFetcher(URLFetcher):
        def __init__(self):
            super().__init__(allowed_protocols={"file", "data"})

        def fetch(self, url: str, headers=None):
            parts = urlparse(url)
            if parts.scheme == "data":
                if not url.startswith(("data:image/png;", "data:image/jpeg;", "data:image/gif;", "data:image/webp;")):
                    raise ValueError("Разрешены только встроенные изображения")
            elif parts.scheme == "file":
                local = Path(unquote(parts.path)).resolve()
                if not local.is_relative_to(permitted):
                    raise ValueError("Ресурс находится вне папки документа")
            else:
                raise ValueError("Загрузка внешних ресурсов из документов отключена")
            return super().fetch(url, headers=headers)

        def __call__(self, url: str):
            # Also useful in standalone tests; WeasyPrint itself uses .fetch().
            return self.fetch(url)

    return LocalFetcher()

DOC_CSS = """
@page { size: A4; margin: 21mm 19mm 20mm; @bottom-center { content: counter(page); font-size: 9pt; color: #64748b; } }
html, body { font-family: 'DejaVu Sans', 'Liberation Sans', sans-serif; font-size: 10.5pt; color: #172033; line-height: 1.52; }
h1,h2,h3,h4 { color: #173c74; line-height: 1.25; break-after: avoid; margin: 1.15em 0 .48em; }
h1 { font-size: 22pt; border-bottom: 2px solid #3b82f6; padding-bottom: 8px; }
h2 { font-size: 16pt; } h3 { font-size: 12.5pt; }
p, ul, ol { margin: .55em 0 .85em; } li { margin: .2em 0; }
pre, code { font-family: 'DejaVu Sans Mono', monospace; font-size: 8.8pt; }
pre { background: #f1f5f9; padding: 10px 12px; border-radius: 5px; white-space: pre-wrap; overflow-wrap: anywhere; }
code { background: #f1f5f9; padding: 1px 3px; }
pre code { background: transparent; padding: 0; }
blockquote { border-left: 3px solid #4f86d9; margin: 14px 0; padding-left: 13px; color: #475569; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 9.3pt; }
th, td { border: 1px solid #bdcad9; padding: 6px 8px; overflow-wrap: anywhere; }
th { background: #e9f1ff; } tr { break-inside: avoid; }
img { max-width: 100%; height: auto; } a { color: #2159a8; }
"""


def _txt_to_markdown_preserving_lines(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    blocks: list[str] = []
    chunk: list[str] = []
    for line in lines:
        if line.strip() == "":
            if chunk:
                blocks.append("  \n".join(chunk))
                chunk = []
            blocks.append("")
        else:
            chunk.append(line)
    if chunk:
        blocks.append("  \n".join(chunk))
    out: list[str] = []
    for item in blocks:
        if item == "":
            if out and out[-1] != "":
                out.append("")
        else:
            out.append(item)
    return "\n\n".join(out).rstrip() + "\n"


def txt_to_html(source: Path) -> str:
    value = html_lib.escape(source.read_text(encoding='utf-8', errors='replace'))
    return (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        '<body><pre style="white-space: pre-wrap; overflow-wrap: anywhere; '
        'font-family: \'DejaVu Sans Mono\', \'Liberation Mono\', monospace; font-size: 10.5pt; color: #172033;">'
        + value + '</pre></body></html>'
    )


def pandoc_to_html(source: Path, dialect: str | None = None) -> str:
    if source_ext(source) == 'txt':
        return txt_to_html(source)
    from_fmt = dialect or ({"md": "gfm", "markdown": "gfm", "htm": "html"}.get(source_ext(source)))
    cmd = ["pandoc", str(source), "-t", "html5", "--standalone", "--wrap=none",
           f"--resource-path={source.resolve().parent}"]
    if source_ext(source) == "epub":
        cmd.append("--embed-resources")
    if from_fmt:
        cmd += ["-f", from_fmt]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False,
                                cwd=str(source.resolve().parent))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConversionError(f"Pandoc не выполнил преобразование: {exc}") from exc
    if result.returncode:
        raise ConversionError(f"Pandoc: {result.stderr.strip()[-900:]}")
    return result.stdout


def text_to_pdf(source: Path, destination: Path) -> None:
    """HTML/CSS/Markdown/TXT to PDF using bundled native components.

    Unlike the old Windows route, this never creates a DOCX merely to run an
    installed office suite. The same PyMuPDF Story engine works on both OSes.
    """
    from .office_native import text_html_to_pdf
    document = pandoc_to_html(source)
    try:
        text_html_to_pdf(document, destination, resource_dir=source.parent)
    except Exception as exc:
        raise ConversionError(f'Не удалось создать PDF: {exc}') from exc


def pandoc_convert(source: Path, target: str, destination: Path) -> None:
    if source_ext(source) == 'txt':
        preserved = _txt_to_markdown_preserving_lines(source.read_text(encoding='utf-8', errors='replace'))
        if target == 'md':
            destination.write_text(preserved, encoding='utf-8')
            return
        with tempfile.TemporaryDirectory(prefix='docforge-txt-') as tmp:
            md = Path(tmp) / f'{source.stem}.md'
            md.write_text(preserved, encoding='utf-8')
            return pandoc_convert(md, target, destination)
    cmd = ["pandoc", str(source), "-o", str(destination),
           f"--resource-path={source.resolve().parent}"]
    if source_ext(source) in {"md", "markdown"}:
        cmd += ["-f", "gfm"]
    if target == "md":
        cmd += ["-t", "gfm", "--wrap=none"]
        # Extract referenced images instead of silently losing them.
        if source_ext(source) in {"docx", "odt", "epub"}:
            cmd += [f"--extract-media={destination.with_suffix('').name}_assets"]
    elif target == "txt":
        cmd += ["-t", "plain", "--wrap=none"]
    elif target == "html":
        cmd += ["-t", "html5", "--standalone", "--embed-resources"]
    run(cmd, cwd=source.parent)



class _OneImageTag(HTMLParser):
    """Read one Pandoc HTML <img> safely; only its src and alt are used."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.src = ""
        self.alt = ""

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            values = dict(attrs)
            self.src = values.get("src", "") or ""
            self.alt = values.get("alt", "") or ""

    handle_startendtag = handle_starttag


def _markdown_image_tags(content: str, root: Path) -> str:
    """Turn Pandoc's sized HTML image tags into portable Markdown links.

    Only rewrite image references to actual files under the export directory.
    External and non-existent images stay unchanged rather than becoming fake links.
    """
    def image_to_md(match: re.Match) -> str:
        parser = _OneImageTag()
        parser.feed(match.group())
        raw_url = html_lib.unescape(parser.src)
        parsed = urlparse(raw_url)
        if parsed.scheme or parsed.netloc or not raw_url or raw_url.startswith(("/", "\\")):
            return match.group()
        relative = Path(unquote(parsed.path))
        local = (root / relative).resolve()
        if not local.is_relative_to(root.resolve()) or not local.is_file():
            return match.group()
        # quote() escapes brackets, whitespace and other Markdown punctuation.
        url = quote(relative.as_posix(), safe="/-._~")
        return f"![{_markdown_link_label(parser.alt or 'Изображение')}]({url})"

    return re.sub(r"<img\b[^>]*>", image_to_md, content, flags=re.I | re.S)


def docx_to_md(source: Path, destination: Path) -> None:
    """Export DOCX to Markdown with local media and embedded attachments.

    destination must be located in the final bundle's staging directory.
    All Pandoc resource paths are relative to that directory and survive moves.
    """
    root = destination.parent
    run(["pandoc", str(source), "-f", "docx", "-t", "gfm", "--standalone", "--wrap=none",
         "--extract-media=assets", "-o", destination.name], cwd=root)
    if not destination.is_file():
        raise ConversionError("Pandoc не создал Markdown")
    content = _markdown_image_tags(destination.read_text(encoding="utf-8"), root)
    attachments: list[str] = []
    # Word documents may carry embedded spreadsheets / OLE objects. Keep them
    # alongside the Markdown instead of silently discarding them. Never trust
    # archive paths and bound extracted data to limit archive-bomb damage.
    try:
        with zipfile.ZipFile(source) as archive:
            total = 0
            index = 0
            for entry in archive.infolist():
                if entry.is_dir() or not entry.filename.startswith("word/embeddings/"):
                    continue
                if entry.file_size > 25 * 1024 * 1024 or index >= 100:
                    continue
                if total + entry.file_size > 100 * 1024 * 1024:
                    break
                index += 1
                original = entry.filename.replace("\\", "/").rsplit("/", 1)[-1]
                name = _unique_attachment_name(original, index)
                attachments_dir = root / "attachments"
                attachments_dir.mkdir(exist_ok=True)
                # Stream with a strict cap; ZIP metadata may not be trustworthy.
                with archive.open(entry) as infile, (attachments_dir / name).open("xb") as outfile:
                    actual = 0
                    while True:
                        fragment = infile.read(min(1024 * 1024, 25 * 1024 * 1024 + 1 - actual))
                        if not fragment:
                            break
                        actual += len(fragment)
                        if actual > 25 * 1024 * 1024 or total + actual > 100 * 1024 * 1024:
                            raise ConversionError("Слишком большой файл внутри DOCX")
                        outfile.write(fragment)
                total += actual
                attachments.append(f"- [{_markdown_link_label(original)}](attachments/{quote(name)})")
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ConversionError(f"Не удалось извлечь вложения DOCX: {exc}") from exc
    if attachments:
        content = content.rstrip() + "\n\n## Вложения\n\n" + "\n".join(attachments) + "\n"
    if not content.strip() and not (root / "assets").exists() and not attachments:
        raise ConversionError("В DOCX нет извлекаемого текста или изображений")
    destination.write_text(content.rstrip() + "\n", encoding="utf-8")

def native_office_convert(source: Path, target: str, destination: Path) -> None:
    """Route office formats without LibreOffice; error on unsupported formats."""
    from .office_native import office_to_pdf, NativeOfficeError
    src = source_ext(source)
    try:
        if target == 'pdf' and src in {'docx', 'pptx', 'xlsx'}:
            office_to_pdf(source, destination)
        elif target == 'pdf' and src == 'csv':
            from openpyxl import Workbook
            import csv
            with tempfile.TemporaryDirectory(prefix='docforge-csv-') as folder:
                book = Workbook()
                sheet = book.active
                with source.open('r', encoding='utf-8-sig', newline='') as stream:
                    for row in csv.reader(stream):
                        sheet.append(row)
                tmp = Path(folder) / 'spreadsheet.xlsx'
                book.save(tmp)
                book.close()
                office_to_pdf(tmp, destination)
        elif src == 'csv' and target == 'xlsx':
            from openpyxl import Workbook
            import csv
            book = Workbook()
            sheet = book.active
            with source.open('r', encoding='utf-8-sig', newline='') as stream:
                for row in csv.reader(stream):
                    sheet.append(row)
            book.save(destination)
            book.close()
        elif src == 'xlsx' and target == 'csv':
            from openpyxl import load_workbook
            import csv
            book = load_workbook(source, read_only=True, data_only=True)
            try:
                with destination.open('w', encoding='utf-8-sig', newline='') as stream:
                    writer = csv.writer(stream)
                    for row in book.active.iter_rows(values_only=True):
                        writer.writerow(['' if v is None else v for v in row])
            finally:
                book.close()
        else:
            raise ConversionError(f'Для {src.upper()} → {target.upper()} требуется другой движок; LibreOffice не используется')
    except NativeOfficeError as exc:
        raise ConversionError(str(exc)) from exc


def image_convert(source: Path, target: str, destination: Path) -> None:
    from PIL import Image, ImageOps
    with Image.open(source) as image:
        frame = ImageOps.exif_transpose(image)
        if target == "pdf":
            if getattr(frame, "n_frames", 1) > 1:
                frames = []
                for index in range(frame.n_frames):
                    frame.seek(index)
                    frames.append(ImageOps.exif_transpose(frame.copy()).convert("RGB"))
                frames[0].save(destination, "PDF", resolution=150, save_all=True, append_images=frames[1:])
            else:
                bg = Image.new("RGB", frame.size, "white")
                if frame.mode in ("RGBA", "LA") or "transparency" in frame.info:
                    rgba = frame.convert("RGBA")
                    bg.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    bg.paste(frame.convert("RGB"))
                bg.save(destination, "PDF", resolution=150)
        elif target in IMAGE_DEST:
            if target == "jpg":
                rgb = Image.new("RGB", frame.size, "white")
                if frame.mode in ("RGBA", "LA") or "transparency" in frame.info:
                    rgba = frame.convert("RGBA")
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    rgb.paste(frame.convert("RGB"))
                rgb.save(destination, "JPEG", quality=92)
            else:
                frame.save(destination, format={"png": "PNG", "webp": "WEBP"}[target])
        else:
            raise ConversionError(f"Конвертация изображения в {target} недоступна")


def _pdf_pages(source: Path):
    import fitz
    try:
        return fitz.open(str(source))
    except Exception as exc:
        raise ConversionError(f"Не удалось открыть PDF: {exc}") from exc


def _ocr_page(page) -> str:
    if not shutil.which("tesseract"):
        return ""
    import fitz
    with tempfile.TemporaryDirectory(prefix="docforge-ocr-") as tmp:
        image_file = Path(tmp) / "ocr.png"
        page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(str(image_file))
        langs = ["rus+eng", "eng"]
        for lang in langs:
            p = subprocess.run(["tesseract", str(image_file), "stdout", "-l", lang],
                               capture_output=True, text=True, timeout=90, check=False)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip()
    return ""


def _extract_pdf_text(page) -> str:
    text = page.get_text("text", sort=True).strip()
    if len(text) < 12:
        return _ocr_page(page) or text
    return text


def pdf_to_text(source: Path, destination: Path) -> None:
    doc = _pdf_pages(source)
    try:
        parts = [_extract_pdf_text(page) for page in doc]
        if not any(part.strip() for part in parts):
            raise ConversionError("В PDF не найден текст. Для скан-копий установите tesseract-ocr и языковые пакеты")
        destination.write_text("\n\n".join(parts).rstrip() + "\n", encoding="utf-8")
    finally:
        doc.close()


def _markdown_page(page, font_baseline: float) -> str:
    """Lightweight reading-order text extraction with heading heuristics."""
    blocks = sorted((b for b in page.get_text("dict", sort=True)["blocks"] if "lines" in b),
                    key=lambda b: (round(b["bbox"][1] / 4), b["bbox"][0]))
    paragraphs: list[str] = []
    for block in blocks:
        lines = []
        sizes = []
        for line in block["lines"]:
            words = [span for span in line["spans"] if span["text"].strip()]
            if words:
                lines.append("".join(span["text"] for span in line["spans"]).strip())
                sizes.extend(span["size"] for span in words)
        if not lines:
            continue
        value = "  \n".join(lines).strip()
        if not value:
            continue
        if re.match(r"^[•●▪◦]\s*", value):
            value = re.sub(r"^[•●▪◦]\s*", "- ", value)
        elif re.match(r"^\d+[.)]\s+", value):
            pass
        elif sizes and len(value) < 145 and len(lines) <= 2:
            fontsize = statistics.median(sizes)
            if fontsize > font_baseline * 1.48:
                value = "# " + value
            elif fontsize > font_baseline * 1.20:
                value = "## " + value
        paragraphs.append(value)
    return "\n\n".join(paragraphs)


def _markdown_link_label(name: str) -> str:
    """Escape a Markdown link label, including embedded bracket characters."""
    return name.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _unique_attachment_name(name: str, index: int) -> str:
    """Never trust a filename embedded inside an untrusted PDF."""
    name = str(name).replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "_", name).strip(" .")
    if not name or name in {".", ".."}:
        name = f"attachment_{index:03}.bin"
    return f"{index:03}_{name[:120]}"


def pdf_to_md(source: Path, destination: Path) -> None:
    """Create a portable .md and its local assets in destination's directory.

    Public convert() stages the complete tree inside a private temporary folder
    and only publishes it after successful conversion.
    """
    doc = _pdf_pages(source)
    try:
        samples = []
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span["text"].strip():
                            samples.extend([span["size"]] * min(30, len(span["text"].strip())))
        baseline = statistics.median(samples) if samples else 11.0
        pages = []
        assets_dir = destination.parent / "assets"
        seen_images: dict[int, str] = {}
        for number, page in enumerate(doc, 1):
            md = _markdown_page(page, baseline)
            if not md.strip():
                md = _ocr_page(page)
            images = []
            page_images: set[int] = set()
            for info in page.get_images(full=True):
                xref = info[0]
                if xref in page_images:
                    continue
                page_images.add(xref)
                first_occurrence = xref not in seen_images
                if xref in seen_images:
                    name = seen_images[xref]
                else:
                    try:
                        content = doc.extract_image(xref)
                        extension = content["ext"].lower()
                        if extension not in {"png", "jpg", "jpeg"}:
                            import fitz
                            pix = fitz.Pixmap(doc, xref)
                            if pix.n not in (1, 3):
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            content = {"image": pix.tobytes("png"), "ext": "png"}
                            extension = "png"
                        name = f"image_{len(seen_images)+1:03}.{extension}"
                        assets_dir.mkdir(exist_ok=True)
                        (assets_dir / name).write_bytes(content["image"])
                        seen_images[xref] = name
                    except Exception:
                        continue  # Some PDF encodings cannot be decoded; keep other content.
                if first_occurrence:
                    images.append(f"![Изображение страницы {number}](assets/{quote(name)})")
            if images:
                md = md + "\n\n" + "\n\n".join(images)
            pages.append(md.strip())

        attachments = []
        if hasattr(doc, "embfile_count"):
            try:
                count = min(doc.embfile_count(), 200)
            except Exception:
                count = 0
            for index in range(count):
                try:
                    info = doc.embfile_info(index)
                    original_name = info.get("filename") or info.get("ufilename") or f"attachment_{index+1}.bin"
                    # Never extract huge / suspicious-size embedded files automatically.
                    if info.get("size", 0) > 25 * 1024 * 1024:
                        continue
                    data = doc.embfile_get(index)
                    if len(data) > 25 * 1024 * 1024:
                        continue
                    target = destination.parent / "attachments"
                    target.mkdir(exist_ok=True)
                    name = _unique_attachment_name(original_name, index + 1)
                    (target / name).write_bytes(data)
                    attachments.append(f"- [{_markdown_link_label(str(original_name))}](attachments/{quote(name)})")
                except Exception:
                    continue

        if not any(p.strip() for p in pages) and not seen_images and not attachments:
            raise ConversionError("В PDF нет извлекаемого текста, изображений или вложений. Для сканов установите Tesseract OCR")
        content = "\n\n---\n\n".join(pages).rstrip()
        if attachments:
            content += "\n\n## Вложения\n\n" + "\n".join(attachments)
        destination.write_text(content.strip() + "\n", encoding="utf-8")
    finally:
        doc.close()


def pdf_to_docx(source: Path, destination: Path) -> None:
    """Generate a genuine editable DOCX, never a PDF with overlaid text.

    Prefer the layout-aware pdf2docx engine if installed; otherwise perform a
    best-effort extraction of text, font emphasis, page breaks, and images.
    """
    from .word_workflow import make_editable_copy
    make_editable_copy(source, output=destination)


def pdf_to_images(source: Path, output_dir: Path, target: str, dpi: int = 150) -> None:
    import fitz
    doc = _pdf_pages(source)
    try:
        if len(doc) == 0:
            raise ConversionError("PDF не содержит страниц")
        digits = max(3, len(str(len(doc))))
        for index, page in enumerate(doc, 1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False,
                                    colorspace=fitz.csRGB)
            filename = output_dir / f"page_{index:0{digits}}.{target}"
            if target == "jpg":
                pixmap.pil_save(str(filename), format="JPEG", quality=90)
            else:
                pixmap.save(str(filename))
    finally:
        doc.close()


def convert(source: str | Path, target: str, out_dir: str | Path | None = None) -> Path:
    """Convert one file, never overwrite an existing path, return created file/folder."""
    src = validate_input(source)
    dest_type = normalize_ext(target)
    src_type = source_ext(src)
    if dest_type not in SUPPORTED[src_type]:
        raise ConversionError(f"Преобразование {src_type.upper()} → {dest_type.upper()} не поддерживается")
    missing = missing_dependencies(src_type, dest_type)
    if missing:
        raise ConversionError("Не хватает компонентов: " + ", ".join(missing) + ". Выполните install.sh")
    resources = None
    if src_type == 'md' and dest_type in {'pdf', 'docx', 'html', 'odt', 'epub', 'txt'}:
        from .md_assets import inspect_markdown
        try:
            resources = inspect_markdown(src)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise ConversionError(f"Ошибка вложений Markdown: {exc}") from exc
    folder = Path(out_dir).expanduser().absolute() if out_dir else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.is_dir():
        raise ConversionError("Неверная папка назначения")
    if src_type == "pdf" and dest_type in {"png", "jpg"}:
        dest = unique_path(folder / f"{src.stem}_{dest_type}_pages", is_dir=True)
        dest.mkdir()
        try:
            pdf_to_images(src, dest, dest_type)
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        return dest
    if src_type in {"pdf", "docx"} and dest_type == "md":
        # Portable name_markdown bundle for both PDF and DOCX sources.
        with tempfile.TemporaryDirectory(prefix=".docforge-markdown-", dir=folder) as tmp:
            stage = Path(tmp) / "bundle"
            stage.mkdir()
            markdown_file = stage / f"{src.stem}.md"
            if src_type == "pdf":
                pdf_to_md(src, markdown_file)
            else:
                docx_to_md(src, markdown_file)
            if not markdown_file.is_file() or not markdown_file.stat().st_size:
                raise ConversionError("Не удалось создать Markdown")
            # Create an exclusive destination; never replace older export folders.
            destination = unique_path(folder / f"{src.stem}_markdown", is_dir=True)
            destination.mkdir(exist_ok=False)
            try:
                for item in stage.iterdir():
                    shutil.move(str(item), str(destination / item.name))
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise
        return destination
    dest = unique_path(folder / f"{src.stem}.{dest_type}")
    # Use a temporary target and rename only after successful conversion.
    with tempfile.TemporaryDirectory(prefix="docforge-convert-", dir=folder) as tmp:
        staged = Path(tmp) / dest.name
        if src_type == "pdf":
            if dest_type == "txt":
                pdf_to_text(src, staged)
            elif dest_type == "docx":
                pdf_to_docx(src, staged)
        elif src_type in IMAGE_TYPES:
            image_convert(src, dest_type, staged)
        elif dest_type == "pdf" and src_type in {"docx", "pptx", "xlsx", "csv"}:
            native_office_convert(src, dest_type, staged)
        elif dest_type == "pdf":
            text_to_pdf(src, staged)
        elif {src_type, dest_type} == {"csv", "xlsx"}:
            native_office_convert(src, dest_type, staged)
        elif src_type in OFFICE_TYPES and src_type not in PANDOC_TYPES:
            native_office_convert(src, dest_type, staged)
        else:
            # Extract media relative to final destination by using the output dir as cwd.
            # Pandoc's --extract-media path can be outside stage; move it on success.
            pandoc_convert(src, dest_type, staged)
        if not staged.is_file() or staged.stat().st_size == 0:
            raise ConversionError("Конвертация завершилась, но выходной файл пуст")
        if resources and resources.attachments:
            try:
                if dest_type == 'pdf':
                    from .md_assets import append_pdf_attachments
                    append_pdf_attachments(staged, resources.attachments)
                elif dest_type == 'docx':
                    from .md_assets import append_docx_attachments
                    append_docx_attachments(staged, resources.attachments)
                elif dest_type == 'html':
                    from .md_assets import embed_html_attachments
                    embed_html_attachments(staged, src, resources.attachments)
                elif dest_type in {'odt', 'epub'}:
                    from .md_assets import package_linked_files
                    package_linked_files(staged, resources.attachments)
            except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
                raise ConversionError(f"Не удалось встроить вложения Markdown: {exc}") from exc
        # A text file has no binary attachments. Put linked resources into an
        # adjacent ZIP so the export can still travel together with its assets.
        sidecar = None
        if resources and dest_type == 'txt':
            from .md_assets import txt_resources_sidecar
            sidecar = txt_resources_sidecar(staged, resources)
        shutil.move(str(staged), str(dest))
        if sidecar:
            shutil.move(str(sidecar), str(unique_path(folder / f'{dest.stem}_resources.zip')))
        media = Path(tmp) / f"{dest.stem}_assets"
        if media.exists():
            saved_assets = unique_path(folder / media.name, is_dir=True)
            shutil.move(str(media), str(saved_assets))
    return dest


def _pdf_only(items: list[str | Path], minimum: int = 1) -> list[Path]:
    paths = [validate_input(p, {"pdf"}) for p in items]
    if len(paths) < minimum:
        raise ConversionError(f"Требуется как минимум {minimum} PDF-файл(а)")
    return paths


def merge_pdfs(items: list[str | Path], out_dir: str | Path | None = None) -> Path:
    from pypdf import PdfReader, PdfWriter
    inputs = _pdf_only(items, minimum=2)
    folder = Path(out_dir).expanduser().absolute() if out_dir else inputs[0].parent
    folder.mkdir(parents=True, exist_ok=True)
    output = unique_path(folder / "Объединённый.pdf")
    writer = PdfWriter()
    try:
        for path in inputs:
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ConversionError(f"PDF защищён паролем: {path.name}")
            writer.append(reader)
        if len(writer.pages) == 0:
            raise ConversionError("Ни одной страницы для объединения")
        with output.open("xb") as stream:
            writer.write(stream)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
        writer.close()
    return output


def parse_pages(spec: str, total: int) -> list[int]:
    """1-based ranges, rejects duplicates and pages outside document."""
    if total < 1:
        raise ConversionError("PDF не содержит страниц")
    if spec.strip().lower() in {"all", "все", "*"}:
        return list(range(total))
    indices: list[int] = []
    for part in spec.split(","):
        item = part.strip()
        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", item)
        if not match:
            raise ConversionError("Страницы задаются как 1,3-5 или all")
        start = int(match[1]); end = int(match[2] or match[1])
        if not (1 <= start <= end <= total):
            raise ConversionError(f"Недопустимый диапазон {item}; в документе {total} стр.")
        for page in range(start - 1, end):
            if page in indices:
                raise ConversionError("Номера страниц не должны повторяться")
            indices.append(page)
    return indices


def split_pdf(source: str | Path, spec: str = "all", out_dir: str | Path | None = None) -> Path:
    from pypdf import PdfReader, PdfWriter
    src = _pdf_only([source])[0]
    reader = PdfReader(src)
    if reader.is_encrypted:
        raise ConversionError("PDF защищён паролем")
    pages = parse_pages(spec, len(reader.pages))
    folder = Path(out_dir).expanduser().absolute() if out_dir else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    dest = unique_path(folder / f"{src.stem}_страницы", is_dir=True)
    dest.mkdir()
    try:
        for index in pages:
            writer = PdfWriter()
            writer.add_page(reader.pages[index])
            with (dest / f"page_{index+1:03}.pdf").open("xb") as stream:
                writer.write(stream)
            writer.close()
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def rotate_pdf(source: str | Path, degrees: int = 90, out_dir: str | Path | None = None) -> Path:
    from pypdf import PdfReader, PdfWriter
    if degrees not in {90, 180, 270}:
        raise ConversionError("Допустимые углы поворота: 90, 180, 270")
    src = _pdf_only([source])[0]
    reader = PdfReader(src)
    if reader.is_encrypted:
        raise ConversionError("PDF защищён паролем")
    folder = Path(out_dir).expanduser().absolute() if out_dir else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    dest = unique_path(folder / f"{src.stem}_повёрнут_{degrees}.pdf")
    writer = PdfWriter()
    try:
        for page in reader.pages:
            writer.add_page(page)
            writer.pages[-1].rotate(degrees)
        with dest.open("xb") as stream:
            writer.write(stream)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        writer.close()
    return dest


def compress_pdf(source: str | Path, level: str = "ebook", out_dir: str | Path | None = None) -> Path:
    if level not in {"screen", "ebook", "printer"}:
        raise ConversionError("Уровень сжатия: screen, ebook или printer")
    src = _pdf_only([source])[0]
    if not shutil.which("gs"):
        raise ConversionError("Для сжатия PDF требуется Ghostscript (gs)")
    folder = Path(out_dir).expanduser().absolute() if out_dir else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    dest = unique_path(folder / f"{src.stem}_сжатый.pdf")
    with tempfile.TemporaryDirectory(prefix="docforge-gs-", dir=folder) as tmp:
        intermediate = Path(tmp) / "result.pdf"
        run(["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.6", "-dSAFER", "-dNOPAUSE",
             "-dBATCH", "-dQUIET", "-dDetectDuplicateImages=true", f"-dPDFSETTINGS=/{level}",
             f"-sOutputFile={intermediate}", str(src)], timeout=300)
        if not intermediate.is_file() or intermediate.stat().st_size == 0:
            raise ConversionError("Ghostscript не создал выходной файл")
        shutil.move(str(intermediate), str(dest))
    return dest


def doctor() -> dict[str, bool]:
    found = {tool: bool(shutil.which(tool)) for tool in ["pandoc", "gs", "tesseract"]}
    for display, mod in [("PyMuPDF", "fitz"), ("pypdf", "pypdf"),
                         ("Pillow", "PIL"), ("python-docx", "docx"),
                         ("office2pdf", "office2pdf"), ("python-pptx", "pptx"),
                         ("openpyxl", "openpyxl"), ("tkinterdnd2", "tkinterdnd2"),
                         ("PySide6", "PySide6")]:
        found[display] = importlib.util.find_spec(mod) is not None
    return found
