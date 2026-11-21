"""Word-style *content* editor for a DOCX working copy of a PDF.

Unlike PDF annotations, every edit changes document text and is compiled to
DOCX/PDF.  The separate working copy can also be edited in Редактор DOCX
for complex layouts not representable by the lightweight built-in editor.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import Table
from PIL import Image, ImageTk

from .core import ConversionError
from .word_workflow import make_editable_copy, export_edited_pdf, open_in_word_processor

BG = '#16253b'
PANEL = '#243851'
INSET = '#365373'
FG = '#f5f8ff'
MUTED = '#c8d9ef'
ACCENT = '#69a5ff'


def _hex_rgb(value: str) -> RGBColor:
    value = value.lstrip('#')
    return RGBColor(*(int(value[p:p+2], 16) for p in (0, 2, 4)))


class WordEditorFrame(tk.Frame):
    """Rich text, document structure and DOCX/PDF export with live styling."""

    def __init__(self, parent, pdf: str | Path, *, existing_docx: Path | None = None):
        super().__init__(parent, bg=BG)
        self.source = Path(pdf).resolve()
        self.working = existing_docx or make_editable_copy(self.source)
        self._images: dict[str, tuple[bytes, str]] = {}
        self._image_refs: list[ImageTk.PhotoImage] = []
        self.modified = False
        self._known_mtime = None
        self.font_family = tk.StringVar(value='DejaVu Sans')
        self.font_size = tk.StringVar(value='12')
        self.para_style = tk.StringVar(value='Обычный текст')
        self.font_color = tk.StringVar(value='#172b49')
        self._build()
        self._load_docx()

    def _button(self, parent, text, command, *, primary=False, width=None):
        btn = tk.Button(parent, text=text, command=command,
                        bg=ACCENT if primary else INSET,
                        fg='#0b203f' if primary else FG,
                        activebackground='#9fc8ff' if primary else '#405d83',
                        activeforeground='#0b203f' if primary else FG,
                        borderwidth=0, relief='flat', padx=8, pady=7,
                        cursor='hand2', font=('DejaVu Sans', 9, 'bold' if primary else 'normal'))
        if width:
            btn.configure(width=width)
        btn.pack(side='left', padx=(0, 5))
        return btn

    def _build(self):
        self.configure(bg=BG)
        nav = tk.Frame(self, bg=BG)
        nav.pack(fill='x', padx=7, pady=(0, 7))
        tk.Label(nav, text='Редактирование содержимого  /  DOCX', font=('DejaVu Sans', 12, 'bold'),
                 bg=BG, fg=FG).pack(side='left')
        self._button(nav, 'Сохранить DOCX', self.save_docx, primary=True)
        self._button(nav, 'Экспорт PDF', self.export_pdf, primary=True)
        self._button(nav, 'Открыть DOCX во внешнем редакторе', self.open_writer)
        self._button(nav, 'Обновить из DOCX', self.reload_from_disk)

        tabs = tk.Frame(self, bg=PANEL)
        tabs.pack(fill='x', padx=5)
        tk.Label(tabs, text='ГЛАВНАЯ    ВСТАВКА    МАКЕТ    ПРАВКА', bg=PANEL, fg=FG,
                 font=('DejaVu Sans', 9, 'bold'), pady=5).pack(anchor='w', padx=13)
        ribbon = tk.Frame(self, bg=PANEL)
        ribbon.pack(fill='x', padx=5, pady=(0, 5))
        self._button(ribbon, 'Ж', lambda: self._style('bold'))
        self._button(ribbon, 'К', lambda: self._style('italic'))
        self._button(ribbon, 'Ч̲', lambda: self._style('underline'))
        fam = ttk.Combobox(ribbon, width=13, textvariable=self.font_family,
                           values=['DejaVu Sans','Liberation Sans','Liberation Serif','Arial','Times New Roman'],
                           state='readonly')
        fam.pack(side='left', padx=(5, 3))
        fam.bind('<<ComboboxSelected>>', lambda _: self._style('family-' + self.font_family.get()))
        size = ttk.Combobox(ribbon, width=4, textvariable=self.font_size,
                            values=['9','10','11','12','14','16','18','20','24','28','36'], state='readonly')
        size.pack(side='left', padx=(0, 8))
        size.bind('<<ComboboxSelected>>', lambda _: self._style('size-' + self.font_size.get()))
        style = ttk.Combobox(ribbon, width=18, textvariable=self.para_style,
                             values=['Обычный текст','Заголовок 1','Заголовок 2','Заголовок 3'], state='readonly')
        style.pack(side='left', padx=(0, 5))
        style.bind('<<ComboboxSelected>>', lambda _: self._paragraph_style())
        self._button(ribbon, '• Список', lambda: self._prefix_lines('• '))
        self._button(ribbon, '1. Список', lambda: self._prefix_lines('1. '))
        self._button(ribbon, '↶', self.undo)
        self._button(ribbon, '↷', self.redo)
        inserts = tk.Frame(self, bg=PANEL)
        inserts.pack(fill='x', padx=5, pady=(0, 5))
        for text, callback in [
            ('Выравн.: слева', lambda: self._style('align-left')),
            ('По центру', lambda: self._style('align-center')),
            ('Справа', lambda: self._style('align-right')),
            ('Таблица', self.insert_table),
            ('Изображение', self.insert_image),
            ('Разрыв страницы', self.page_break),
            ('Найти / заменить', self.find_replace),
        ]:
            self._button(inserts, text, callback)

        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=5, pady=(2, 4))
        left = tk.Frame(body, bg=PANEL, width=154)
        left.pack(side='left', fill='y', padx=(0, 8))
        left.pack_propagate(False)
        tk.Label(left, text='ДОКУМЕНТ', font=('DejaVu Sans', 10,'bold'),
                 bg=PANEL, fg=FG, pady=13).pack(anchor='w', padx=12)
        self._info_label = tk.Label(left, text=f'Исходный PDF:\n{self.source.name}\n\nРабочая копия:\n{self.working.name}',
                                    bg=PANEL, fg=MUTED, justify='left', wraplength=139,
                                    font=('DejaVu Sans', 9))
        self._info_label.pack(anchor='w', padx=12, pady=5)
        tk.Label(left, text='Редактируется текст DOCX.\nСохранённый PDF\nсоздаётся заново.',
                 bg=PANEL, fg=MUTED, wraplength=136, justify='left').pack(anchor='w', padx=12, pady=15)
        self._button(left, 'Внешний DOCX-редактор', self.open_writer)
        right = tk.Frame(body, bg=PANEL, width=184)
        right.pack(side='right', fill='y', padx=(8, 0))
        right.pack_propagate(False)
        tk.Label(right,text='СВОЙСТВА ТЕКСТА', bg=PANEL,fg=FG,
                 font=('DejaVu Sans',10,'bold')).pack(anchor='w', padx=10, pady=(12, 15))
        tk.Label(right,text='Цвет текста',bg=PANEL,fg=MUTED).pack(anchor='w',padx=10)
        colors = tk.Frame(right, bg=PANEL)
        colors.pack(anchor='w',padx=10,pady=7)
        for c in ['#172b49','#2468c8','#d83a61','#21986d','#9a50bf']:
            tk.Button(colors,width=2,bg=c,relief='flat',bd=0,
                      command=lambda x=c:self._style('color-'+x)).pack(side='left',padx=2)
        tk.Label(right,text='Изменение содержания\nобновляет DOCX,\nа не исходный PDF.',bg=PANEL,
                 fg=MUTED,justify='left',wraplength=165).pack(anchor='w', padx=10,pady=(20,5))
        center = tk.Frame(body, bg='#39465d')
        center.pack(side='left', fill='both', expand=True)
        self.text = tk.Text(center, bg='#fffefd', fg='#1d2e4b', insertbackground='#1c4aa5',
                            selectbackground='#b5d2ff', selectforeground='#142c57',
                            wrap='word', undo=True, autoseparators=True, maxundo=120,
                            padx=44, pady=35, relief='flat', bd=0,
                            font=('DejaVu Sans',12), spacing1=3, spacing3=5)
        yscroll = tk.Scrollbar(center, command=self.text.yview)
        yscroll.pack(side='right', fill='y')
        self.text.pack(side='left', fill='both', expand=True, padx=20, pady=10)
        self.text.configure(yscrollcommand=yscroll.set)
        self.text.bind('<<Modified>>', self._on_modified)
        self.text.bind('<Control-b>', lambda e: (self._style('bold'),'break')[1])
        self.text.bind('<Control-i>', lambda e: (self._style('italic'),'break')[1])
        self.text.bind('<Control-u>', lambda e: (self._style('underline'),'break')[1])
        self.text.bind('<Control-s>', lambda e: (self.save_docx(),'break')[1])
        self.text.bind('<Control-f>', lambda e: (self.find_replace(),'break')[1])
        for tag in ('bold','italic','underline'):
            cfg = {'underline':True} if tag == 'underline' else {
                'font':('DejaVu Sans',12, tag)}
            self.text.tag_configure(tag, **cfg)
        for level, size in [('heading1',20),('heading2',16),('heading3',14)]:
            self.text.tag_configure(level,font=('DejaVu Sans',size,'bold'),foreground='#204f98',spacing1=11)
        for align, anchor in [('align-left','left'),('align-center','center'),('align-right','right')]:
            self.text.tag_configure(align, justify=anchor)
        for sz in [9,10,11,12,14,16,18,20,24,28,36]:
            self.text.tag_configure('size-'+str(sz),font=('DejaVu Sans',sz))
        for family in ['DejaVu Sans','Liberation Sans','Liberation Serif','Arial','Times New Roman']:
            self.text.tag_configure('family-'+family,font=(family,12))

        self.status = tk.Label(self,text='Готово к редактированию',bg=BG,fg=MUTED,
                               font=('DejaVu Sans',9),anchor='w')
        self.status.pack(fill='x',padx=11,pady=(2,4))

    def _on_modified(self, event):
        if self.text.edit_modified():
            self.modified = True
            self.text.edit_modified(False)

    def _load_docx(self):
        document = Document(self.working)
        self.text.delete('1.0','end')
        self._image_refs.clear()
        self._images.clear()
        for item in document.iter_inner_content():
            if isinstance(item, Table):
                for row in item.rows:
                    line = '| ' + ' | '.join(cell.text.replace('\n',' ') for cell in row.cells) + ' |\n'
                    self.text.insert('end', line)
                self.text.insert('end','\n')
                continue
            if not isinstance(item, Paragraph):
                continue
            start = self.text.index('end-1c')
            for run in item.runs:
                if run.text:
                    styles = []
                    if run.bold: styles.append('bold')
                    if run.italic: styles.append('italic')
                    if run.underline: styles.append('underline')
                    # Keep original Word soft line breaks distinct from paragraph boundaries.
                    if '\n' in run.text or '\v' in run.text:
                        styles.append('soft-break')
                    self.text.insert('end-1c',run.text.replace('\v', '\n'),tuple(styles))
                for blip in run._element.xpath('.//a:blip'):
                    rid = blip.get(qn('r:embed'))
                    if rid and rid in item.part.related_parts:
                        part = item.part.related_parts[rid]
                        self._insert_image_data(part.blob, part.content_type, at='end-1c')
            end = self.text.index('end-1c')
            style = item.style.name if item.style is not None else ''
            if style.startswith('Heading'):
                level = style.rsplit(' ',1)[-1]
                if level in ('1','2','3'):
                    self.text.tag_add('heading'+level,start,end)
            if item.alignment == WD_ALIGN_PARAGRAPH.CENTER:
                self.text.tag_add('align-center',start,end)
            elif item.alignment == WD_ALIGN_PARAGRAPH.RIGHT:
                self.text.tag_add('align-right',start,end)
            self.text.insert('end-1c','\n')
        self.text.edit_reset()
        self.modified=False
        self.text.edit_modified(False)
        self._known_mtime = self.working.stat().st_mtime_ns

    def reload_from_disk(self):
        if self.modified and not messagebox.askyesno('DocForge',
                'Есть несохранённые изменения. Загрузить DOCX с диска и потерять их?',parent=self):
            return
        self._load_docx()
        self.status.config(text='Содержимое обновлено из DOCX')

    def _insert_image_data(self, data: bytes, content_type: str = 'image/png', *, at: str = 'insert'):
        try:
            with Image.open(BytesIO(data)) as im:
                img = im.convert('RGBA')
                img.thumbnail((410, 280), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
            self._image_refs.append(photo)
            name = self.text.image_create(at,image=photo,padx=3,pady=5)
            self._images[name] = (data,content_type)
            return name
        except (OSError, ValueError):
            return None

    def _style(self, tag: str):
        if not self.text.tag_cget(tag,'font') and tag.startswith('color-'):
            self.text.tag_configure(tag,foreground=tag[6:])
        try:
            start = self.text.index('sel.first')
            end = self.text.index('sel.last')
        except tk.TclError:
            start = self.text.index('insert linestart')
            end = self.text.index('insert lineend')
        if tag in self.text.tag_names(start):
            self.text.tag_remove(tag,start,end)
        else:
            self.text.tag_add(tag,start,end)
        self.modified=True
        self.text.focus_set()

    def _paragraph_style(self):
        tags={'Заголовок 1':'heading1','Заголовок 2':'heading2','Заголовок 3':'heading3'}
        selection = self.para_style.get()
        for tag in ('heading1','heading2','heading3'):
            start=self.text.index('insert linestart')
            end=self.text.index('insert lineend')
            self.text.tag_remove(tag,start,end)
        if selection in tags:
            self._style(tags[selection])
        self.modified=True

    def _prefix_lines(self, prefix: str):
        try:
            start = self.text.index('sel.first linestart')
            end = self.text.index('sel.last lineend')
        except tk.TclError:
            start = self.text.index('insert linestart')
            end = self.text.index('insert lineend')
        count = int(self.text.count(start,end,'lines')[0])+1
        line = start
        for n in range(count):
            if self.text.compare(line,'>=','end-1c'):
                break
            if self.text.get(line,self.text.index(f'{line} lineend')).strip():
                pre = f'{n+1}. ' if prefix.startswith('1.') else prefix
                self.text.insert(line,pre)
            line = self.text.index(f'{line} +1line linestart')
        self.modified=True

    def insert_image(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('Изображение','*.png *.jpg *.jpeg *.webp')])
        if path:
            data=Path(path).read_bytes()
            if self._insert_image_data(data):
                self.modified=True

    def insert_table(self):
        columns=simpledialog.askinteger('Таблица','Количество столбцов (2–8)',initialvalue=3,minvalue=2,maxvalue=8,parent=self)
        if columns is None: return
        rows=simpledialog.askinteger('Таблица','Количество строк (1–30)',initialvalue=3,minvalue=1,maxvalue=30,parent=self)
        if rows is None: return
        lines=[]
        for r in range(rows):
            lines.append('| ' + ' | '.join(f'Ячейка {r+1}.{c+1}' for c in range(columns)) + ' |')
        self.text.insert('insert','\n'+'\n'.join(lines)+'\n')
        self.modified=True

    def page_break(self):
        self.text.insert('insert','\n\f\n')
        self.modified=True

    def find_replace(self):
        find=simpledialog.askstring('Найти','Какой текст найти?',parent=self)
        if not find: return
        repl=simpledialog.askstring('Заменить',f'Заменить «{find}» на:',parent=self)
        if repl is None: return
        value=self.text.get('1.0','end-1c')
        count=value.count(find)
        if count:
            self.text.delete('1.0','end')
            self.text.insert('1.0',value.replace(find,repl))
            self.modified=True
        self.status.config(text=f'Заменено: {count}. При замене всего текста стили выделения сбрасываются.')

    def undo(self):
        try:self.text.edit_undo()
        except tk.TclError:pass
    def redo(self):
        try:self.text.edit_redo()
        except tk.TclError:pass

    def _to_document(self) -> Document:
        """Save text/tags and embedded images to a genuine DOCX structure."""
        document=Document()
        # Keep page dimensions/margins from the generated working copy.
        original=Document(self.working)
        if original.sections:
            src, dst=original.sections[0], document.sections[0]
            for k in ('page_width','page_height','top_margin','bottom_margin','left_margin','right_margin'):
                setattr(dst,k,getattr(src,k))
        paragraph = document.add_paragraph()
        # Tk's explicit line boundaries must not acquire Word's default after-spacing.
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.space_before = Pt(0)
        tag_stack: set[str] = set()
        buffer = ''
        current_runs: list[tuple[str,set[str]]] = []

        def push_text(chunk: str):
            if not chunk:return
            run=paragraph.add_run(chunk)
            run.bold = 'bold' in tag_stack
            run.italic = 'italic' in tag_stack
            run.underline = 'underline' in tag_stack
            for tag in tag_stack:
                if tag.startswith('size-'):
                    try:run.font.size=Pt(int(tag[5:]))
                    except (ValueError,TypeError):pass
                if tag.startswith('family-'):run.font.name=tag[7:]
                if tag.startswith('color-'):run.font.color.rgb=_hex_rgb(tag[6:])

        line_number=1
        def finish():
            nonlocal paragraph, line_number
            line_tags = set(self.text.tag_names(f'{line_number}.0')) | tag_stack
            for tag,level in (('heading1','Heading 1'),('heading2','Heading 2'),('heading3','Heading 3')):
                if tag in line_tags:
                    paragraph.style=level
                    break
            if 'align-center' in line_tags:
                paragraph.alignment=WD_ALIGN_PARAGRAPH.CENTER
            elif 'align-right' in line_tags:
                paragraph.alignment=WD_ALIGN_PARAGRAPH.RIGHT
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.space_before = Pt(0)
            line_number += 1

        # text.dump preserves selected character styles and embedded images.
        tokens = self.text.dump('1.0','end-1c',text=True,tag=True,image=True)
        for kind,value,index in tokens:
            if kind == 'tagon':
                tag_stack.add(value)
            elif kind == 'tagoff':
                tag_stack.discard(value)
            elif kind == 'image':
                record=self._images.get(value)
                if record:
                    try:paragraph.add_run().add_picture(BytesIO(record[0]),width=Inches(4.5))
                    except (ValueError,OSError):pass
            elif kind == 'text':
                pieces=value.split('\n')
                for n,piece in enumerate(pieces):
                    if '\f' in piece:
                        before, *after=piece.split('\f')
                        if before:push_text(before)
                        for remaining in after:
                            document.add_page_break()
                            if remaining:push_text(remaining)
                    else:push_text(piece)
                    if n < len(pieces)-1:
                        if 'soft-break' in tag_stack:
                            paragraph.add_run().add_break()
                            line_number += 1
                        else:
                            finish()
        # Remove only final empty paragraph (keep user blank lines).
        if paragraph.text == '' and not paragraph._p.xpath('.//a:blip'):
            document._element.body.remove(paragraph._p)
        # Convert adjacent | a | b | rows into one actual multirow Word table.
        pending=[]
        def flush_table():
            if not pending:
                return
            first = pending[0]
            records=[[v.strip() for v in p.text.strip().strip('|').split('|')] for p in pending]
            count=max(len(r) for r in records)
            table=document.add_table(rows=len(records),cols=count)
            table.style='Table Grid'
            for row, values in zip(table.rows, records):
                for cell,value in zip(row.cells,values):
                    cell.text=value
            first._p.addprevious(table._tbl)
            for p in pending:
                if p._p.getparent() is not None:
                    p._p.getparent().remove(p._p)
            pending.clear()
        for item in list(document.paragraphs):
            text=item.text.strip()
            if text.startswith('|') and text.endswith('|') and len(text.strip('|').split('|'))>1:
                pending.append(item)
            else:
                flush_table()
        flush_table()
        return document

    def save_docx(self) -> Path | None:
        try:
            if (self._known_mtime is not None and self.working.stat().st_mtime_ns != self._known_mtime):
                raise ConversionError('DOCX изменён внешним редактором. Нажмите «Обновить из DOCX» перед сохранением из DocForge.')
            document=self._to_document()
            document.save(self.working)
            self._known_mtime=self.working.stat().st_mtime_ns
            self.modified=False
            self.status.config(text=f'Сохранена редактируемая копия: {self.working.name}')
            return self.working
        except Exception as exc:
            messagebox.showerror('DocForge · DOCX',str(exc),parent=self)
            return None

    def export_pdf(self) -> Path | None:
        # An externally edited DOCX is authoritative until reloaded. Do not
        # silently overwrite Writer's changes from the stale in-app document.
        changed_outside = (self._known_mtime is not None and
                           self.working.stat().st_mtime_ns != self._known_mtime)
        if changed_outside and self.modified:
            messagebox.showerror('DOCX изменён вне DocForge',
                'Содержимое изменено одновременно во внешнем редакторе и DocForge. Обновите редактор из DOCX или сохраните правки в другой файл.',parent=self)
            return None
        if (not changed_outside) and self.modified and self.save_docx() is None:
            return None
        try:
            path=export_edited_pdf(self.working)
            self.status.config(text=f'Новый PDF: {path.name}')
            messagebox.showinfo('DocForge · Готово', f'Создан новый PDF:\n{path}\n\nИсходный документ сохранён.',parent=self)
            return path
        except Exception as exc:
            messagebox.showerror('Не удалось экспортировать PDF',str(exc),parent=self)
            return None

    def open_writer(self):
        if self.modified and self.save_docx() is None:return
        try:
            open_in_word_processor(self.working)
            messagebox.showinfo('DocForge · DOCX',
                'После редактирования во внешней программе сохраните DOCX.\n'
                'Затем используйте «Экспорт PDF» в DocForge.\n\n'
                'Если продолжите редактировать в DocForge, откройте редактор заново, чтобы обновить содержимое.',
                parent=self)
        except Exception as exc:
            messagebox.showerror('Редактор DOCX',str(exc),parent=self)
