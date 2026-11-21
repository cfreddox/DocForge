"""Offline, cross-platform PDF editor for DocForge.

All editing operations are performed in-memory with PyMuPDF. Saving creates a
new document; the input PDF is never overwritten. The Tk interface works on
Linux and Windows 10/11 and does not require Qt.
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import pymupdf as fitz
from PIL import Image, ImageTk

from .core import ConversionError, unique_path

BG = '#202c42'
CARD = '#304057'
FIELD = '#394b65'
TEXT = '#f6f9ff'
MUTED = '#b8c9df'
ACCENT = '#69a5ff'
BORDER = '#526982'


def _rgb(color: str) -> tuple[float, float, float]:
    value = color.lstrip('#')
    if len(value) != 6:
        raise ValueError('Цвет должен иметь формат #RRGGBB')
    return tuple(int(value[i:i+2], 16) / 255 for i in (0, 2, 4))


def _font_path() -> Path | None:
    candidates = [
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'),
        Path(os.getenv('WINDIR', 'C:/Windows')) / 'Fonts' / 'arial.ttf',
        Path(os.getenv('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf',
    ]
    return next((p for p in candidates if p.is_file()), None)


class PdfEditSession:
    """Undoable PyMuPDF document operations independent of the GUI."""

    def __init__(self, source: str | Path):
        self.source = Path(source).expanduser().resolve()
        if not self.source.is_file() or self.source.suffix.lower() != '.pdf':
            raise ConversionError('Выберите существующий PDF-файл')
        try:
            self.doc = fitz.open(self.source)
        except Exception as exc:
            raise ConversionError(f'Не удалось открыть PDF: {exc}') from exc
        if self.doc.needs_pass:
            self.doc.close()
            raise ConversionError('Защищённый паролем PDF пока не поддерживается редактором')
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self.dirty = False

    @property
    def pages(self) -> int:
        return len(self.doc)

    def _check(self, index: int) -> fitz.Page:
        if not 0 <= index < len(self.doc):
            raise ConversionError('Номер страницы вне диапазона')
        return self.doc[index]

    def _checkpoint(self) -> None:
        self._undo.append(self.doc.tobytes(garbage=2, deflate=True))
        if len(self._undo) > 15:
            self._undo.pop(0)
        self._redo.clear()
        self.dirty = True

    def _restore(self, content: bytes) -> None:
        self.doc.close()
        self.doc = fitz.open(stream=content, filetype='pdf')

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.doc.tobytes(garbage=2, deflate=True))
        self._restore(self._undo.pop())
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.doc.tobytes(garbage=2, deflate=True))
        self._restore(self._redo.pop())
        self.dirty = True
        return True

    def add_text(self, index: int, x: float, y: float, text: str,
                 *, fontsize: float = 14, color: str = '#1d3762') -> None:
        page = self._check(index)
        if not text.strip() or fontsize <= 0 or fontsize > 144:
            raise ConversionError('Введите текст и допустимый размер шрифта')
        self._checkpoint()
        page = self._check(index)
        fontfile = _font_path()
        name = 'helv'
        if fontfile:
            name = 'DocForgeUnicode'
            page.insert_font(fontname=name, fontfile=str(fontfile))
        # Points supplied by GUI are within the PDF page; baseline is shifted
        # slightly below click for predictable typing.
        page.insert_text(fitz.Point(float(x), float(y)), text, fontname=name,
                         fontsize=fontsize, color=_rgb(color), overlay=True)

    def add_image(self, index: int, rect: fitz.Rect, image: str | Path) -> None:
        page = self._check(index)
        image = Path(image)
        if not image.is_file():
            raise ConversionError('Изображение не найдено')
        if rect.width < 3 or rect.height < 3:
            raise ConversionError('Слишком маленькая область изображения')
        self._checkpoint()
        page = self._check(index)
        page.insert_image(rect, filename=str(image), keep_proportion=True, overlay=True)

    def highlight(self, index: int, rect: fitz.Rect, *, color: str = '#ffe27a') -> None:
        page = self._check(index)
        if rect.is_empty or rect.width < 2 or rect.height < 2:
            raise ConversionError('Выделите область на странице')
        self._checkpoint()
        page = self._check(index)
        annot = page.add_rect_annot(rect)
        annot.set_colors(stroke=_rgb(color), fill=_rgb(color))
        annot.set_border(width=0.2)
        annot.set_opacity(0.35)
        annot.update()

    def redact(self, index: int, rect: fitz.Rect) -> None:
        page = self._check(index)
        if rect.is_empty or rect.width < 2 or rect.height < 2:
            raise ConversionError('Выделите область удаления')
        self._checkpoint()
        page = self._check(index)
        page.add_redact_annot(rect, fill=(1, 1, 1))
        # Unlike a white rectangle, redaction really removes underlying content.
        page.apply_redactions()
        self.doc.reload_page(page)  # PyMuPDF requires page refresh after redaction

    def draw_line(self, index: int, x1: float, y1: float, x2: float, y2: float,
                  *, color: str = '#2d89f7', width: float = 2) -> None:
        page = self._check(index)
        self._checkpoint()
        page = self._check(index)
        page.draw_line((x1, y1), (x2, y2), color=_rgb(color), width=width)

    def rotate(self, index: int, degrees: int = 90) -> None:
        page = self._check(index)
        if degrees not in (-90, 90, 180, 270):
            raise ConversionError('Поворот: 90, 180 или 270 градусов')
        self._checkpoint()
        page = self._check(index)
        page.set_rotation((page.rotation + degrees) % 360)

    def delete_page(self, index: int) -> None:
        self._check(index)
        if self.pages == 1:
            raise ConversionError('Нельзя удалить единственную страницу PDF')
        self._checkpoint()
        self.doc.delete_page(index)

    def move_page(self, index: int, direction: int) -> int:
        self._check(index)
        destination = index + direction
        if destination < 0 or destination >= self.pages:
            return index
        self._checkpoint()
        order = list(range(self.pages))
        order.insert(destination, order.pop(index))
        self.doc.select(order)
        return destination

    def render(self, index: int, scale: float = 1.0) -> Image.Image:
        page = self._check(index)
        if scale < 0.15 or scale > 3.0:
            raise ConversionError('Масштаб должен быть между 15% и 300%')
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)

    def save(self, output: str | Path | None = None) -> Path:
        chosen = Path(output).expanduser().resolve() if output else self.source.with_name(self.source.stem + '_edited.pdf')
        if chosen == self.source:
            raise ConversionError('Исходный PDF нельзя перезаписать. Сохраните новую копию.')
        chosen.parent.mkdir(parents=True, exist_ok=True)
        chosen = unique_path(chosen)
        self.doc.save(str(chosen), garbage=4, deflate=True)
        self.dirty = False
        return chosen

    def close(self) -> None:
        self.doc.close()


def edit_pdf_script(source: str | Path, *, text: str | None = None,
                    page: int = 1, x: float = 72, y: float = 72,
                    rotate: int = 0, output: Path | None = None) -> Path:
    """Scriptable noninteractive editor for Nautilus/PowerShell workflows."""
    session = PdfEditSession(source)
    try:
        if text:
            session.add_text(page - 1, x, y, text)
        if rotate:
            session.rotate(page - 1, rotate)
        if not text and not rotate:
            raise ConversionError('Для пакетного редактирования укажите --text или --rotate')
        return session.save(output)
    finally:
        session.close()


class PdfEditorWindow:
    """Preview, thumbnails, annotation tools, undo/redo and Save As."""

    def __init__(self, root: tk.Tk, file: str | Path | None = None):
        self.root = root
        self.root.title('DocForge — Редактор документов')
        self.root.configure(bg=BG)
        self.root.geometry('1260x810')
        self.root.minsize(920, 610)
        self.session: PdfEditSession | None = None
        self.page = 0
        self.scale = 1.0
        self.tool = tk.StringVar(value='cursor')
        self.color = tk.StringVar(value='#2d89f7')
        self.font_size = tk.IntVar(value=14)
        self._preview = None
        self._thumbs: list[ImageTk.PhotoImage] = []
        self._drag_start: tuple[float, float] | None = None
        self._overlay: int | None = None
        self._page_origin = (0, 0)
        self.word_editor = None
        self._word_mode = False
        self._build()
        if file:
            self.open_pdf(Path(file))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Control-z>', lambda e: self._undo_active())
        self.root.bind('<Control-y>', lambda e: self._redo_active())
        self.root.bind('<Control-s>', lambda e: self._save_active())
        self.root.bind('<Control-o>', lambda e: self.open_dialog())

    def _label(self, parent, title: str, size=10, bold=False):
        return tk.Label(parent, text=title, bg=parent.cget('bg'), fg=TEXT,
                        font=('Segoe UI', size, 'bold' if bold else 'normal'))

    def _button(self, parent, text: str, command, primary=False):
        return tk.Button(parent, text=text, command=command,
                         bg='#487ff1' if primary else FIELD, fg='white',
                         activebackground='#689ffd', activeforeground='white',
                         relief='flat', bd=0, padx=12, pady=9, cursor='hand2',
                         font=('Segoe UI', 10))

    def _build(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill='x', padx=17, pady=(14, 9))
        self._label(header, '◆  DocForge  /  Редактор PDF', 17, True).pack(side='left')
        self._button(header, 'Сохранить как…', self.save, True).pack(side='right', padx=5)
        self._button(header, 'Открыть PDF…', self.open_dialog).pack(side='right', padx=5)
        self._button(header, 'Главная', self.home).pack(side='right', padx=5)

        self._nav = tk.Frame(self.root, bg=BG)
        self._nav.pack(fill='x', padx=17, pady=(0,8))
        for label, command in [('Главная', self.home), ('Конвертация', self.home),
                               ('Редактор PDF', self.pdf_mode), ('Содержимое · Word', self.edit_content),
                               ('Инструменты', self.pdf_mode)]:
            self._button(self._nav, label, command).pack(side='left',padx=4)
        tools = tk.Frame(self.root, bg=CARD)
        self.pdf_toolbar = tools
        tools.pack(fill='x', padx=17, pady=(0, 11))
        self._button(tools, '✎ Изменить содержимое', self.edit_content, True).pack(side='left', padx=(3,9),pady=5)
        for label, mode in [('Курсор', 'cursor'), ('Надпись поверх', 'text'),
                            ('Выделить', 'highlight'), ('Линия', 'line'),
                            ('Удалить содержимое', 'redact'), ('Изображение', 'image')]:
            item = self._button(tools, label, lambda m=mode: self._tool(m))
            item.pack(side='left', padx=3, pady=5)
        self._button(tools, '↶', self.undo).pack(side='right', padx=5)
        self._button(tools, '↷', self.redo).pack(side='right', padx=5)

        body = tk.PanedWindow(self.root, orient='horizontal', bg=BG, sashwidth=7,
                              sashrelief='flat', bd=0)
        body.pack(fill='both', expand=True, padx=17, pady=(0, 8))
        self.pdf_body = body
        left = tk.Frame(body, bg=CARD, width=177)
        body.add(left, minsize=130, width=175)
        self._label(left, 'СТРАНИЦЫ', 10, True).pack(anchor='w', padx=13, pady=(14, 8))
        preview_list = tk.Frame(left, bg=CARD)
        preview_list.pack(fill='both', expand=True, padx=9)
        self.page_list = tk.Canvas(preview_list, bg=CARD, highlightthickness=0, bd=0,
                                   width=146)
        thumbs_scroll = tk.Scrollbar(preview_list, orient='vertical', command=self.page_list.yview)
        self.page_list.configure(yscrollcommand=thumbs_scroll.set)
        thumbs_scroll.pack(side='right', fill='y')
        self.page_list.pack(side='left', fill='both', expand=True)
        self.page_list.bind('<MouseWheel>', lambda e: self.page_list.yview_scroll(-int(e.delta/120), 'units'))
        page_controls = tk.Frame(left, bg=CARD)
        page_controls.pack(fill='x', pady=8)
        for title, command in [('↑', lambda: self.move(-1)), ('↓', lambda: self.move(1)),
                               ('⟳', self.rotate), ('×', self.delete)]:
            self._button(page_controls, title, command).pack(side='left', expand=True, padx=2)
        center = tk.Frame(body, bg='#1a2536')
        body.add(center, minsize=380, stretch='always')
        self.canvas = tk.Canvas(center, bg='#1a2536', highlightthickness=0, bd=0)
        bar_y = tk.Scrollbar(center, orient='vertical', command=self.canvas.yview)
        bar_x = tk.Scrollbar(center, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=bar_y.set, xscrollcommand=bar_x.set)
        bar_y.pack(side='right', fill='y')
        bar_x.pack(side='bottom', fill='x')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.bind('<ButtonPress-1>', self._start)
        self.canvas.bind('<B1-Motion>', self._move)
        self.canvas.bind('<ButtonRelease-1>', self._release)
        self.canvas.bind('<Configure>', lambda e: self.root.after_idle(self._show_page))
        right = tk.Frame(body, bg=CARD)
        body.add(right, minsize=210, width=242)
        self._label(right, 'СВОЙСТВА', 12, True).pack(anchor='w', padx=13, pady=(14, 13))
        self._label(right, 'Размер текста').pack(anchor='w', padx=13)
        tk.Spinbox(right, from_=8, to=72, textvariable=self.font_size, width=11,
                   bg=FIELD, fg=TEXT, buttonbackground=FIELD, relief='flat').pack(anchor='w', padx=13, pady=8)
        self._label(right, 'Цвет элемента').pack(anchor='w', padx=13)
        palette = tk.Frame(right, bg=CARD)
        palette.pack(fill='x', padx=13, pady=7)
        for color in ['#2d89f7', '#ffdf5d', '#fb647e', '#24bcaa', '#b47bfa', '#26354f']:
            tk.Button(palette, bg=color, width=2, height=1, bd=0,
                      command=lambda c=color: self.color.set(c)).pack(side='left', padx=2)
        self._label(right, 'Масштаб').pack(anchor='w', padx=13, pady=(15, 3))
        self.zoom_var = tk.IntVar(value=100)
        tk.Scale(right, from_=35, to=200, resolution=5, orient='horizontal',
                 variable=self.zoom_var, bg=CARD, fg=TEXT, troughcolor=FIELD,
                 highlightthickness=0, command=self._zoom).pack(fill='x', padx=10)
        self._label(right, 'Подсказка', 11, True).pack(anchor='w', padx=13, pady=(24, 6))
        self.hint = tk.Label(right, text='Выберите инструмент и укажите место на странице.',
                             wraplength=198, justify='left', bg=CARD, fg=MUTED)
        self.hint.pack(anchor='w', padx=13)
        self._button(right, 'Повернуть 90°', self.rotate).pack(fill='x', padx=12, pady=(35, 5))
        self._button(right, 'Удалить страницу', self.delete).pack(fill='x', padx=12)
        footer = tk.Frame(self.root, bg=BG)
        self.footer = footer
        footer.pack(fill='x', padx=19, pady=(0, 11))
        self.status = self._label(footer, 'Откройте PDF, чтобы начать редактирование')
        self.status.pack(side='left')
        self.page_status = self._label(footer, '')
        self.page_status.pack(side='right')

    def _save_active(self):
        if self._word_mode and self.word_editor is not None:
            return self.word_editor.save_docx()
        return self.save()

    def _undo_active(self):
        if self._word_mode and self.word_editor is not None:
            return self.word_editor.undo()
        return self.undo()

    def _redo_active(self):
        if self._word_mode and self.word_editor is not None:
            return self.word_editor.redo()
        return self.redo()

    def home(self):
        """Open main dashboard without closing this document unexpectedly."""
        from . import __version__
        import subprocess
        command = ([sys.executable] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-m', 'docforge'])
        try:
            subprocess.Popen(command + ['gui'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            messagebox.showerror('DocForge', str(exc), parent=self.root)

    def edit_content(self):
        """Switch to real DOCX editing; the PDF original is untouched."""
        if not self.session:
            self.open_dialog()
            if not self.session:
                return
        if self._word_mode:
            return
        try:
            from .word_ui import WordEditorFrame
            self.word_editor = WordEditorFrame(self.root, self.session.source)
        except Exception as exc:
            messagebox.showerror('Редактирование содержимого PDF', str(exc), parent=self.root)
            return
        self.pdf_body.pack_forget()
        self.pdf_toolbar.pack_forget()
        self.word_editor.pack(fill='both', expand=True, padx=17, pady=(0,8),before=self.footer)
        self._word_mode = True
        self.status.config(text='Режим: редактирование содержания DOCX → новый PDF')

    def pdf_mode(self):
        if not self._word_mode:
            return
        if self.word_editor is not None and self.word_editor.modified:
            if not messagebox.askyesno('Несохранённые правки',
                                       'Сохранить изменения в редактируемой копии DOCX?',parent=self.root):
                pass
            else:
                if self.word_editor.save_docx() is None:
                    return
        self.word_editor.destroy()
        self.word_editor = None
        self._word_mode = False
        self.pdf_toolbar.pack(fill='x', padx=17, pady=(0,11),before=self.footer)
        self.pdf_body.pack(fill='both', expand=True, padx=17, pady=(0,8),before=self.footer)
        self.status.config(text='Режим: PDF-инструменты')

    def _tool(self, mode):
        self.tool.set(mode)
        self.hint.config(text={
            'cursor':'Выбор и просмотр документа',
            'text':'Щёлкните по странице и введите текст',
            'image':'Щёлкните по странице и выберите PNG/JPG',
            'highlight':'Потяните мышью для выделения прямоугольника',
            'redact':'Потяните мышью, чтобы безвозвратно удалить содержимое области',
            'line':'Потяните мышью, чтобы нарисовать линию',
        }[mode])

    def open_dialog(self):
        path = filedialog.askopenfilename(parent=self.root, title='Открыть PDF',
                                          filetypes=[('PDF', '*.pdf')])
        if path:
            self.open_pdf(Path(path))

    def open_pdf(self, path: Path):
        if self._word_mode:
            self.pdf_mode()
        if self.session:
            self.session.close()
        try:
            self.session = PdfEditSession(path)
        except ConversionError as exc:
            self.session = None
            messagebox.showerror('Редактор PDF', str(exc), parent=self.root)
            return
        self.page = 0
        self._refresh()
        self.status.configure(text=f'Открыт: {path.name}')

    def _refresh(self):
        self.page_list.delete('all')
        self._thumbs.clear()
        if self.session:
            self.page = min(self.page, self.session.pages - 1)
            y = 12
            for n in range(self.session.pages):
                preview = self.session.render(n, .17)
                photo = ImageTk.PhotoImage(preview)
                self._thumbs.append(photo)
                h = preview.height
                tag = f'page-{n}'
                self.page_list.create_rectangle(8, y-4, 144, y+h+29,
                    fill=FIELD if n == self.page else CARD,
                    outline=ACCENT if n == self.page else BORDER,
                    width=2 if n == self.page else 1, tags=(tag,))
                self.page_list.create_image(18, y+3, image=photo, anchor='nw', tags=(tag,))
                self.page_list.create_text(73, y+h+14, text=f'{n+1}',
                    fill=TEXT, font=('Segoe UI', 10), tags=(tag,))
                self.page_list.tag_bind(tag, '<Button-1>', lambda _e, idx=n: self._go_page(idx))
                y += h+41
            self.page_list.configure(scrollregion=(0, 0, 150, y+5))
        self._show_page()

    def _go_page(self, index: int):
        if self.session and 0 <= index < self.session.pages:
            self.page = index
            self._refresh()

    def _zoom(self, value):
        self.scale = float(value) / 100
        self._show_page()

    def _show_page(self):
        if not hasattr(self, 'canvas') or not self.canvas.winfo_exists():
            return
        self.canvas.delete('all')
        if not self.session or self.session.pages < 1:
            return
        try:
            frame = self.session.render(self.page, self.scale)
            self._preview = ImageTk.PhotoImage(frame)
            x = max(12, (self.canvas.winfo_width()-frame.width)//2)
            y = 15
            self._page_origin = (x, y)
            self.canvas.create_image(x, y, anchor='nw', image=self._preview)
            self.canvas.configure(scrollregion=(0, 0, x+frame.width+22, y+frame.height+22))
            self.page_status.configure(text=f'Страница {self.page+1}/{self.session.pages}   ·   {int(self.scale*100)}%')
        except Exception as exc:
            self.status.configure(text=f'Ошибка отображения: {exc}')

    def _point(self, event) -> tuple[float, float]:
        x = (self.canvas.canvasx(event.x) - self._page_origin[0]) / self.scale
        y = (self.canvas.canvasy(event.y) - self._page_origin[1]) / self.scale
        if self.session:
            rect = self.session.doc[self.page].rect
            x, y = max(0, min(rect.width, x)), max(0, min(rect.height, y))
        return x, y

    def _start(self, event):
        if not self.session:
            return
        self._drag_start = self._point(event)

    def _move(self, event):
        if not self.session or self._drag_start is None or self.tool.get() not in {'highlight', 'redact', 'line'}:
            return
        if self._overlay:
            self.canvas.delete(self._overlay)
        x, y = self._point(event)
        ax, ay = self._drag_start
        self._overlay = self.canvas.create_rectangle(
            self._page_origin[0]+ax*self.scale,
            self._page_origin[1]+ay*self.scale,
            self._page_origin[0]+x*self.scale,
            self._page_origin[1]+y*self.scale,
            outline='#facb67', width=2, dash=(4, 3))

    def _release(self, event):
        if not self.session or self._drag_start is None:
            return
        start = self._drag_start
        self._drag_start = None
        end = self._point(event)
        mode = self.tool.get()
        try:
            if mode == 'text':
                text = simpledialog.askstring('Добавить текст', 'Введите текст:', parent=self.root)
                if text:
                    self.session.add_text(self.page, start[0], start[1], text,
                                          fontsize=self.font_size.get(), color=self.color.get())
            elif mode == 'image':
                image = filedialog.askopenfilename(parent=self.root, title='Добавить изображение',
                                                   filetypes=[('Изображения', '*.png *.jpg *.jpeg')])
                if image:
                    x, y = start
                    self.session.add_image(self.page, fitz.Rect(x, y, x+170, y+110), image)
            elif mode in {'highlight', 'redact'}:
                rect = fitz.Rect(*start, *end).normalize()
                if mode == 'highlight':
                    self.session.highlight(self.page, rect, color=self.color.get())
                else:
                    if messagebox.askyesno('Удалить содержимое', 'Безвозвратно удалить всё внутри выделения?', parent=self.root):
                        self.session.redact(self.page, rect)
            elif mode == 'line':
                self.session.draw_line(self.page, *start, *end, color=self.color.get())
            else:
                return
            self.status.config(text='Изменения не сохранены — нажмите «Сохранить как…»')
        except Exception as exc:
            messagebox.showerror('Редактор PDF', str(exc), parent=self.root)
        finally:
            self._overlay = None
            self._show_page()

    def rotate(self):
        if self.session:
            self.session.rotate(self.page)
            self._refresh()

    def delete(self):
        if self.session:
            try:
                self.session.delete_page(self.page)
                self._refresh()
            except ConversionError as exc:
                messagebox.showwarning('Редактор', str(exc), parent=self.root)

    def move(self, delta):
        if self.session:
            self.page = self.session.move_page(self.page, delta)
            self._refresh()

    def undo(self):
        if self.session and self.session.undo():
            self._refresh()

    def redo(self):
        if self.session and self.session.redo():
            self._refresh()

    def save(self):
        if not self.session:
            return
        wanted = filedialog.asksaveasfilename(parent=self.root, title='Сохранить копию PDF',
                                              defaultextension='.pdf',
                                              initialfile=self.session.source.stem + '_edited.pdf',
                                              filetypes=[('PDF', '*.pdf')])
        if wanted:
            try:
                output = self.session.save(wanted)
                self.status.config(text=f'Сохранено: {output}')
                messagebox.showinfo('DocForge', f'Готово:\n{output}', parent=self.root)
            except Exception as exc:
                messagebox.showerror('Не удалось сохранить', str(exc), parent=self.root)

    def close(self):
        if self.session:
            self.session.close()
        self.root.destroy()


def show_pdf_editor(file: str | Path | None = None, *, content_mode: bool = False):
    root = tk.Tk()
    window = PdfEditorWindow(root, file)
    if content_mode and file:
        root.after_idle(window.edit_content)
    root.mainloop()
