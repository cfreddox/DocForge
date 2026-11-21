"""CLI and entrypoints invoked by Nautilus, desktop file and terminal."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .core import (ConversionError, compress_pdf, convert, doctor, merge_pdfs, rotate_pdf, split_pdf)


def notify(title: str, body: str) -> None:
    if shutil.which("notify-send") and (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
        subprocess.run(["notify-send", "--app-name=DocForge", title, body[:240]], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docforge", description="Локальный конвертер документов и PDF")
    parser.add_argument("--version", action="version", version=f"DocForge {__version__}")
    group = parser.add_subparsers(dest="command")
    conv = group.add_parser("convert", help="Преобразовать файлы")
    conv.add_argument("files", type=Path, nargs="+", help="Входные файлы")
    conv.add_argument("--to", required=True, help="Формат: pdf, md, docx, txt, png, ...")
    conv.add_argument("--out-dir", type=Path, help="Папка для готовых файлов")
    conv.add_argument("--notify", action="store_true", help="Показать системное уведомление")

    merge = group.add_parser("merge", help="Объединить два или больше PDF")
    merge.add_argument("files", type=Path, nargs="+")
    merge.add_argument("--out-dir", type=Path)
    merge.add_argument("--notify", action="store_true")

    split = group.add_parser("split", help="Сохранить страницы PDF по отдельности")
    split.add_argument("file", type=Path)
    split.add_argument("--pages", default="all", help="all или диапазон 1,3-5")
    split.add_argument("--out-dir", type=Path)
    split.add_argument("--notify", action="store_true")

    rotate = group.add_parser("rotate", help="Повернуть страницы PDF")
    rotate.add_argument("files", type=Path, nargs="+")
    rotate.add_argument("--degrees", type=int, default=90, choices=[90, 180, 270])
    rotate.add_argument("--out-dir", type=Path)
    rotate.add_argument("--notify", action="store_true")

    comp = group.add_parser("compress", help="Сжать PDF (Ghostscript)")
    comp.add_argument("files", type=Path, nargs="+")
    comp.add_argument("--level", choices=["screen", "ebook", "printer"], default="ebook")
    comp.add_argument("--out-dir", type=Path)
    comp.add_argument("--notify", action="store_true")

    editor = group.add_parser('edit', help='Открыть локальный редактор PDF')
    editor.add_argument('file', nargs='?', type=Path)
    es = group.add_parser('edit-script', help='Редактировать PDF из скрипта без GUI')
    es.add_argument('file', type=Path)
    es.add_argument('--text')
    es.add_argument('--replace', help='Заменить существующий текст через DOCX (не наложение)')
    es.add_argument('--with', dest='replacement', help='Новый текст для --replace')
    es.add_argument('--page', type=int, default=1)
    es.add_argument('--x', type=float, default=72)
    es.add_argument('--y', type=float, default=72)
    es.add_argument('--rotate', type=int, default=0, choices=[0,90,180,270])
    es.add_argument('--output', type=Path)
    qt = group.add_parser('quick-to', help='Быстрое преобразование через выбор файла')
    qt.add_argument('target', choices=['pdf', 'md', 'docx', 'txt'])
    group.add_parser('tray', help='Значок DocForge в трее Windows')
    inspect = group.add_parser('check-md', help='Проверить изображения и вложения Markdown')
    inspect.add_argument('file', type=Path)
    group.add_parser("doctor", help="Проверить зависимости")
    group.add_parser("gui", help="Открыть главное окно")
    zone = group.add_parser("dropzone", help="Запустить плавающую зону")
    group.add_parser("dropzone-once", help="Совместимый псевдоним постоянной зоны")
    quick = group.add_parser("quick", help="Быстрый выбор выходного формата")
    quick.add_argument("files", type=Path, nargs="+")
    gui = group.add_parser("open", help="Открыть файлы в главном окне")
    gui.add_argument("files", type=Path, nargs="*")
    return parser


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else list(argv)
    # Short modes used in the .desktop entry and Nautilus scripts.
    aliases = {"--main": ["gui"], "--dropzone": ["dropzone"], "--dropzone-once": ["dropzone-once"],
               "--quick": ["quick"], "--open": ["open"], "--edit": ["edit"]}
    if values and values[0] in aliases:
        values = aliases[values[0]] + values[1:]
    args = create_parser().parse_args(values)
    try:
        if args.command == 'check-md':
            from .md_assets import inspect_markdown
            from .core import source_ext
            if source_ext(args.file) != 'md':
                raise ConversionError('Нужен Markdown-файл .md или .markdown')
            resources = inspect_markdown(args.file)
            print(f'Все ссылки доступны. Изображений: {len(resources.images)}; вложений: {len(resources.attachments)}')
            return 0
        if args.command == 'edit':
            from .pdf_editor import show_pdf_editor
            show_pdf_editor(args.file, content_mode=True)
            return 0
        if args.command == 'edit-script':
            if args.replace is not None:
                if args.replacement is None:
                    raise ConversionError('Для --replace укажите параметр --with')
                from .word_workflow import replace_pdf_content
                print(replace_pdf_content(args.file, args.replace, args.replacement, output=args.output))
            else:
                from .pdf_editor import edit_pdf_script
                print(edit_pdf_script(args.file, text=args.text, page=args.page,
                                      x=args.x, y=args.y, rotate=args.rotate, output=args.output))
            return 0
        if args.command == 'quick-to':
            from .quick_actions import quick_convert
            quick_convert(args.target)
            return 0
        if args.command == 'tray':
            from .windows_tray import run_tray
            run_tray()
            return 0
        if args.command == "doctor":
            dependencies = doctor()
            for component, available in dependencies.items():
                print(f"{'OK' if available else 'НЕТ'}  {component}")
            required = ["pandoc", "PyMuPDF", "pypdf", "Pillow", "python-docx", "office2pdf", "openpyxl", "python-pptx", "tkinterdnd2", "PySide6"]
            if sys.platform != "win32":
                required += ["gs"]
            return 0 if all(dependencies.get(name) for name in required) else 2
        if args.command in (None, "gui", "dropzone", "dropzone-once", "quick", "open"):
            if args.command in ("dropzone", "dropzone-once", "quick"):
                try:
                    from .liquid_qt import show_liquid_zone
                except ImportError as exc:
                    raise ConversionError(
                        "Не установлен Qt-компонент стеклянной зоны (PySide6-Essentials). "
                        "Повторите установку или выполните: "
                        "~/.local/share/docforge/venv/bin/pip install PySide6-Essentials"
                    ) from exc
                mode = "dropzone" if args.command == "dropzone-once" else args.command
                from .zone_lock import single_zone
                with single_zone() as allowed:
                    if allowed:
                        show_liquid_zone(mode, getattr(args, "files", None))
                return 0
            from .gui import show_gui
            modes = {None: "main", "gui": "main", "dropzone": "dropzone",
                     "dropzone-once": "dropzone_once", "quick": "quick", "open": "main"}
            show_gui(modes[args.command], getattr(args, "files", None))
            return 0
        if args.command == "convert":
            outputs = [convert(path, args.to, args.out_dir) for path in args.files]
        elif args.command == "merge":
            outputs = [merge_pdfs(args.files, args.out_dir)]
        elif args.command == "split":
            outputs = [split_pdf(args.file, args.pages, args.out_dir)]
        elif args.command == "rotate":
            outputs = [rotate_pdf(p, args.degrees, args.out_dir) for p in args.files]
        elif args.command == "compress":
            outputs = [compress_pdf(p, args.level, args.out_dir) for p in args.files]
        else:
            raise ConversionError("Неизвестная команда")
        for result in outputs:
            print(result)
        if getattr(args, "notify", False):
            notify("DocForge: готово", f"Обработано: {len(outputs)}; результат: {outputs[-1].name}")
        return 0
    except (ConversionError, OSError, ValueError) as exc:
        print(f"Ошибка DocForge: {exc}", file=sys.stderr)
        if getattr(args, "notify", False):
            notify("DocForge: ошибка", str(exc))
        return 1
    except Exception as exc:
        # Report unexpected errors (no false claims of a successful conversion).
        print(f"Неожиданная ошибка: {type(exc).__name__}: {exc}", file=sys.stderr)
        if getattr(args, "notify", False):
            notify("DocForge: ошибка", str(exc))
        return 1
