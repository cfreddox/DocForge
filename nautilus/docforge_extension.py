"""DocForge native right-click integration for GNOME Files / Nautilus 43+.

This module is loaded by Nautilus' system Python, not DocForge's venv.
Nautilus 4 does not expose an API to embed arbitrary widgets into the file
view. MenuProvider launches DocForge's translucent chooser/zone instead.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import gi

gi.require_version("Nautilus", "4.0")
from gi.repository import GObject, Nautilus

_APP = Path.home() / ".local" / "bin" / "docforge"
_MARKDOWN_INPUTS = {".pdf", ".docx", ".odt", ".epub", ".txt", ".html", ".htm"}
_PDF_EXCLUDE = {".pdf"}
_SUPPORTED = {
    ".pdf", ".md", ".markdown", ".txt", ".docx", ".doc", ".odt",
    ".rtf", ".html", ".htm", ".epub", ".pptx", ".ppt", ".odp",
    ".xlsx", ".xls", ".ods", ".csv", ".png", ".jpg", ".jpeg",
    ".webp", ".bmp", ".tiff", ".tif",
}


def _selected_local_files(items):
    """Use local files only; don't pass remote gvsf URIs as shell arguments."""
    result = []
    for item in items:
        location = item.get_location()
        raw = location.get_path() if location is not None else None
        if not raw:
            continue
        path = Path(raw)
        if path.suffix.lower() in _SUPPORTED and path.is_file():
            result.append(str(path))
    return result


class DocForgeNautilus(GObject.GObject, Nautilus.MenuProvider):
    def _launch(self, _item, args):
        # shell=False avoids injection through filenames, including spaces.
        if not _APP.is_file() or not os.access(_APP, os.X_OK):
            return
        try:
            subprocess.Popen([str(_APP), *args], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError:
            return

    def _entry(self, ident, label, tip, args):
        item = Nautilus.MenuItem(name="DocForge::" + ident, label=label, tip=tip)
        item.connect("activate", self._launch, args)
        return item

    def get_file_items(self, files):
        paths = _selected_local_files(files)
        if not paths or len(paths) != len(files):
            return []
        submenu = Nautilus.Menu()
        submenu.append_item(self._entry("quick", "Выбрать формат…",
                                        "Стеклянное окно выбора конвертации", ["--quick", *paths]))
        extensions = {Path(path).suffix.lower() for path in paths}
        if len(paths) == 1 and extensions == {'.pdf'}:
            submenu.append_item(self._entry('edit', 'Редактировать PDF…',
                                            'Открыть локальный редактор PDF', ['edit', paths[0]]))
        if extensions <= _MARKDOWN_INPUTS:
            submenu.append_item(self._entry("to_md", "В Markdown (папка для PDF/DOCX)…",
                                            "PDF и DOCX сохраняются вместе с изображениями",
                                            ["convert", "--to", "md", "--notify", *paths]))
        if ".pdf" not in extensions and extensions <= _SUPPORTED - _PDF_EXCLUDE:
            submenu.append_item(self._entry("to_pdf", "В PDF…",
                                            "Преобразовать выбранные файлы в PDF",
                                            ["convert", "--to", "pdf", "--notify", *paths]))
        submenu.append_item(self._entry("zone", "Открыть стеклянную зону…",
                                        "Плавающая зона перетаскивания на главном мониторе",
                                        ["--dropzone"]))
        parent = Nautilus.MenuItem(name="DocForge::menu", label="DocForge · конвертер",
                                   tip="Локальная конвертация без загрузки файлов в сеть")
        parent.set_submenu(submenu)
        return [parent]

    def get_background_items(self, current_folder):
        return [self._entry("background_zone", "DocForge · стеклянная зона…",
                            "Зона для перетаскивания из Файлов", ["--dropzone"])]
