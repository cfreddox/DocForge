"""Preflight and safe local resource inclusion for Markdown exports.

No remote resource downloads. Ordinary web links remain hyperlinks; local images
are required and local linked files become embedded PDF/DOCX attachments.
"""
from __future__ import annotations

import json
import base64
import html as html_lib
import mimetypes
import re
import subprocess
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class MarkdownResources:
    images: tuple[Path, ...]
    attachments: tuple[Path, ...]


class _ImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ('img', 'source'):
            src = dict(attrs).get('src')
            if src:
                self.images.append(src)

    handle_startendtag = handle_starttag


def _ast_urls(value: object, images: list[str], links: list[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _ast_urls(item, images, links)
    elif isinstance(value, dict):
        tag = value.get('t')
        content = value.get('c')
        if tag in ('Image', 'Link') and isinstance(content, list) and len(content) >= 3:
            target = content[2]
            if isinstance(target, list) and target and isinstance(target[0], str):
                (images if tag == 'Image' else links).append(target[0])
        if tag in ('RawInline', 'RawBlock') and isinstance(content, list) and len(content) > 1 and content[0] == 'html':
            parser = _ImageParser()
            parser.feed(content[1])
            images.extend(parser.images)
        for child in value.values():
            _ast_urls(child, images, links)


def _local_url_path(url: str, root: Path, *, image: bool) -> Path | None:
    if not url or url.startswith('#'):
        return None
    parsed = urlsplit(url)
    if parsed.scheme == 'file':
        raise ValueError(f'Абсолютная ссылка на локальный файл запрещена: {url}')
    if parsed.scheme or parsed.netloc:
        if image and parsed.scheme == 'data' and url.lower().startswith('data:image/'):
            return None
        if image:
            raise ValueError(f'Внешнее изображение не включено (скачайте его рядом с MD): {url}')
        return None  # HTTPS hyperlinks are not attachment requests.
    raw = unquote(parsed.path)
    if not raw or '\x00' in raw or re.match(r'^[A-Za-z]:[\\/]', raw):
        raise ValueError(f'Недопустимый путь в Markdown: {url}')
    relative = Path(raw.replace('\\', '/'))
    if relative.is_absolute():
        raise ValueError(f'Абсолютный путь запрещён: {url}')
    item = (root / relative).resolve()
    if not item.is_relative_to(root) or not item.is_file():
        raise ValueError(f'Не найден локальный ресурс или выход за папку Markdown: {url}')
    if not item.stat().st_size:
        raise ValueError(f'Пустой локальный ресурс: {url}')
    return item


def inspect_markdown(source: Path) -> MarkdownResources:
    """Use Pandoc's parsed AST: references, escaped spaces, and inline links."""
    root = source.resolve().parent
    process = subprocess.run(
        ['pandoc', str(source), '-f', 'gfm', '-t', 'json'],
        text=True, capture_output=True, errors='replace', timeout=45, check=False,
        cwd=str(root),
    )
    if process.returncode:
        raise ValueError('Не удалось проверить ссылки Markdown: ' + process.stderr.strip()[-600:])
    images_raw: list[str] = []
    links_raw: list[str] = []
    _ast_urls(json.loads(process.stdout), images_raw, links_raw)
    images: list[Path] = []
    attachments: list[Path] = []
    for url in images_raw:
        item = _local_url_path(url, root, image=True)
        if item and item not in images:
            images.append(item)
    for url in links_raw:
        item = _local_url_path(url, root, image=False)
        if item and item not in images and item not in attachments:
            attachments.append(item)
    return MarkdownResources(tuple(images), tuple(attachments))


def append_pdf_attachments(destination: Path, files: tuple[Path, ...]) -> None:
    if not files:
        return
    import pymupdf as fitz
    with fitz.open(destination) as doc:
        appendix = doc.new_page()
        appendix.insert_text((50, 60), 'DocForge - Attached files', fontsize=16)
        index = 0
        entries = {}
        for item in files:
            # Disallow multi-gigabyte unintended PDF attachments.
            if item.stat().st_size > 100 * 1024 * 1024:
                raise ValueError(f'Вложение превышает 100 МБ: {item.name}')
            # PyMuPDF's attachment identifier must be ASCII to round-trip
            # reliably; preserve the original Cyrillic name in PDF metadata.
            identifier = f'docforge_{index + 1:03}{item.suffix.lower()}'
            entries[identifier] = item.name
            doc.embfile_add(identifier, item.read_bytes(), filename=identifier,
                            ufilename=identifier, desc='Linked from Markdown')
            if index < 28:
                appendix.insert_text((55, 95 + index * 20),
                                     f'{index + 1}. {identifier} ({item.stat().st_size} bytes)', fontsize=9)
            index += 1
        doc.embfile_add('docforge_manifest.json', json.dumps(entries, ensure_ascii=False, indent=2).encode('utf-8'),
                        filename='docforge_manifest.json', desc='Original UTF-8 attachment names')
        output = destination.with_name(destination.stem + '-attachments-tmp.pdf')
        doc.save(str(output), garbage=3, deflate=True)
    output.replace(destination)


def append_docx_attachments(destination: Path, files: tuple[Path, ...]) -> None:
    if not files:
        return
    from docx import Document
    doc = Document(destination)
    doc.add_page_break()
    title = doc.add_paragraph('Вложения Markdown')
    title.runs[0].bold = True
    doc.add_paragraph('Файлы сохранены внутри DOCX в папке word/embeddings/docforge/. '
                      'Для извлечения откройте DOCX как ZIP-архив.')
    for item in files:
        if item.stat().st_size > 100 * 1024 * 1024:
            raise ValueError(f'Вложение превышает 100 МБ: {item.name}')
        doc.add_paragraph('• ' + item.name)
    doc.save(destination)
    # OPC allows arbitrary package parts with explicit content types. These
    # remain extractable from the DOCX ZIP; not a clickable Word OLE object.
    with zipfile.ZipFile(destination, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
        for index, item in enumerate(files, 1):
            part = f'word/embeddings/docforge/{index:03}_{item.name}'
            archive.write(item, part)
        content_types = archive.read('[Content_Types].xml')
        ns = 'http://schemas.openxmlformats.org/package/2006/content-types'
        root = ET.fromstring(content_types)
        for index, item in enumerate(files, 1):
            part = f'/word/embeddings/docforge/{index:03}_{item.name}'
            ET.SubElement(root, f'{{{ns}}}Override', {
                'PartName': part,
                'ContentType': mimetypes.guess_type(item.name)[0] or 'application/octet-stream',
            })
    # Rebuild archive to avoid duplicate Content_Types entries; .docx remains valid.
    rebuilt = destination.with_name(destination.stem + '-repacked.docx')
    with zipfile.ZipFile(destination) as original, zipfile.ZipFile(rebuilt, 'w', compression=zipfile.ZIP_DEFLATED) as target:
        for info in original.infolist():
            if info.filename == '[Content_Types].xml':
                continue
            target.writestr(info, original.read(info.filename))
        target.writestr('[Content_Types].xml', ET.tostring(root, encoding='utf-8', xml_declaration=True))
    rebuilt.replace(destination)


def embed_html_attachments(destination: Path, source: Path, files: tuple[Path, ...]) -> None:
    """Make referenced local files downloadable inside one standalone HTML."""
    if not files:
        return
    lookup = {str(p.resolve()): p for p in files}
    markup = destination.read_text(encoding='utf-8')
    import base64
    def replace_anchor(m: re.Match) -> str:
        tag = m.group(0)
        href = re.search(r'\bhref\s*=\s*([\"\'])(.*?)\1', tag, flags=re.I | re.S)
        if not href:
            return tag
        url = html_lib.unescape(href.group(2))
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return tag
        item = (source.resolve().parent / unquote(parsed.path)).resolve()
        if str(item) not in lookup:
            return tag
        if item.stat().st_size > 20 * 1024 * 1024:
            raise ValueError(f'HTML-вложение превышает 20 МБ: {item.name}')
        encoded = base64.b64encode(item.read_bytes()).decode('ascii')
        kind = mimetypes.guess_type(item.name)[0] or 'application/octet-stream'
        href_new = f'href="data:{kind};base64,{encoded}" download="{html_lib.escape(item.name, quote=True)}"'
        return tag[:href.start()] + href_new + tag[href.end():]
    markup = re.sub(r'<a\b[^>]*>', replace_anchor, markup, flags=re.I | re.S)
    destination.write_text(markup, encoding='utf-8')


def package_linked_files(destination: Path, files: tuple[Path, ...], *, prefix: str = 'docforge-attachments') -> None:
    """Preserve binary links inside ODT/EPUB ZIP payloads, without claiming UI OLE support."""
    if not files:
        return
    manifest = {}
    with zipfile.ZipFile(destination, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
        for index, path in enumerate(files, 1):
            if path.stat().st_size > 100 * 1024 * 1024:
                raise ValueError(f'Вложение слишком большое: {path.name}')
            key = f'{prefix}/{index:03}_{path.name}'
            archive.write(path, key)
            manifest[key] = path.name
        archive.writestr(f'{prefix}/manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))


def txt_resources_sidecar(destination: Path, resources: MarkdownResources) -> Path | None:
    """Plain TXT cannot contain binaries; return adjacent ZIP with original assets."""
    paths = tuple(dict.fromkeys([*resources.images, *resources.attachments]))
    if not paths:
        return None
    output = destination.with_name(destination.stem + '_resources.zip')
    entries = {}
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for i, path in enumerate(paths, 1):
            if path.stat().st_size > 100 * 1024 * 1024:
                raise ValueError(f'Вложение слишком большое: {path.name}')
            entry = f'resources/{i:03}_{path.name}'
            archive.write(path, entry)
            entries[entry] = path.name
        archive.writestr('manifest.json', json.dumps(entries, ensure_ascii=False, indent=2))
    return output
