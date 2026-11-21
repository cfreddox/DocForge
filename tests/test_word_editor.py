"""Regression: PDF contents are edited via a DOCX copy, never overlaid."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

import fitz
import pytest
from docx import Document
from PIL import Image

from docforge.word_workflow import make_editable_copy, export_edited_pdf
from docforge.core import ConversionError


@pytest.fixture
def pdf(tmp_path):
    src=tmp_path/'project.pdf'
    with fitz.open() as d:
        p=d.new_page()
        p.insert_text((55,80),'ORIGINAL CHAPTER')
        p.insert_text((55,130),'This text will be changed.')
        second=d.new_page()
        second.insert_text((55,90),'SECOND PAGE')
        d.save(src)
    return src


def test_edit_real_contents_pdf_docx_pdf(pdf):
    editable=make_editable_copy(pdf,use_layout_converter=False)
    assert editable != pdf and editable.suffix == '.docx'
    doc=Document(editable)
    assert any('ORIGINAL CHAPTER' in p.text for p in doc.paragraphs)
    for para in doc.paragraphs:
        for run in para.runs:
            if 'ORIGINAL CHAPTER' in run.text:
                run.text=run.text.replace('ORIGINAL CHAPTER','EDITED CHAPTER')
    doc.add_heading('NEW CHAPTER',level=2)
    table=doc.add_table(rows=2,cols=2)
    table.cell(0,0).text='Name'
    table.cell(1,0).text='Value'
    doc.save(editable)
    edited=export_edited_pdf(editable)
    with fitz.open(edited) as result:
        all_text='\n'.join(page.get_text() for page in result)
        assert 'EDITED CHAPTER' in all_text
        assert 'ORIGINAL CHAPTER' not in all_text
        assert 'NEW CHAPTER' in all_text
        assert 'Name' in all_text
    with fitz.open(pdf) as original:
        assert 'ORIGINAL CHAPTER' in original[0].get_text()
    assert editable.exists()
    assert edited != pdf


def test_unique_working_copies_and_output(pdf):
    first=make_editable_copy(pdf,use_layout_converter=False)
    second=make_editable_copy(pdf,use_layout_converter=False)
    assert first != second
    out1=export_edited_pdf(first)
    out2=export_edited_pdf(first)
    assert out1 != out2
    assert out1.exists() and out2.exists()


def test_pdf_with_image_keeps_picture_in_docx(tmp_path):
    picture=tmp_path/'photo.png'
    Image.new('RGB',(160,75),'purple').save(picture)
    pdf=tmp_path/'picture.pdf'
    with fitz.open() as d:
        p=d.new_page()
        p.insert_text((50,55),'PAGE WITH PICTURE')
        p.insert_image(fitz.Rect(70,80,250,170),filename=str(picture))
        d.save(pdf)
    edited=make_editable_copy(pdf,use_layout_converter=False)
    doc=Document(edited)
    assert doc.inline_shapes, 'PDF image must be extracted as a real DOCX drawing'


def test_invalid_source_and_destination(tmp_path):
    with pytest.raises(ConversionError):
        make_editable_copy(tmp_path/'missing.pdf')
    invalid=tmp_path/'fake.docx'
    invalid.write_text('wrong')
    with pytest.raises(ConversionError):
        export_edited_pdf(invalid.with_suffix('.pdf'))


def test_word_ui_edits_text_table_image_and_exports(pdf,tmp_path):
    import shutil
    if not shutil.which('xvfb-run'):
        pytest.skip('No virtual display')
    code=r'''
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from docx import Document
import fitz
from docforge.word_ui import WordEditorFrame
messagebox.showinfo=lambda *a,**kw: None
messagebox.showerror=lambda *a,**kw: (_ for _ in ()).throw(AssertionError(a))
root=tk.Tk();root.geometry('1200x780')
w=WordEditorFrame(root,Path(r"""%s"""))
w.pack(fill='both',expand=True)
root.update()
assert 'ORIGINAL CHAPTER' in w.text.get('1.0','end')
s=w.text.get('1.0','end-1c')
w.text.delete('1.0','end')
w.text.insert('1.0',s.replace('ORIGINAL CHAPTER','REPLACED CONTENT'))
w.text.insert('end-1c','\n| Value | Result |\n')
file=w.save_docx();assert file and file.is_file()
doc=Document(file)
assert any('REPLACED CONTENT' in p.text for p in doc.paragraphs)
assert len(doc.tables)>=1
assert not any('ORIGINAL CHAPTER' in p.text for p in doc.paragraphs)
out=w.export_pdf();assert out and out.is_file()
with fitz.open(out) as pdf:
 text='\n'.join(p.get_text() for p in pdf)
 assert 'REPLACED CONTENT' in text
 assert 'ORIGINAL CHAPTER' not in text
root.destroy()
'''
    env=os.environ.copy()
    env['XDG_CONFIG_HOME']=str(tmp_path/'cfg')
    result=subprocess.run(['xvfb-run','-a',sys.executable,'-c',code % pdf],
                          capture_output=True,text=True,timeout=90,env=env)
    assert result.returncode==0,result.stderr


def test_pdf_editor_has_content_mode(pdf,tmp_path):
    import shutil
    if not shutil.which('xvfb-run'):
        pytest.skip('No virtual display')
    code=r'''
import tkinter as tk
from docforge.pdf_editor import PdfEditorWindow
root=tk.Tk()
app=PdfEditorWindow(root,r"""%s""")
app.edit_content()
assert app._word_mode and app.word_editor is not None
assert app.word_editor.working.exists()
app.pdf_mode()
assert not app._word_mode
root.destroy()
'''
    env=os.environ.copy();env['XDG_CONFIG_HOME']=str(tmp_path/'cfg')
    proc=subprocess.run(['xvfb-run','-a',sys.executable,'-c',code % pdf],
                        capture_output=True,text=True,timeout=60,env=env)
    assert proc.returncode==0,proc.stderr


def test_regular_pdf_to_docx_uses_editable_pipeline(pdf):
    from docforge.core import convert
    dest=convert(pdf,'docx')
    assert dest.suffix=='.docx'
    doc=Document(dest)
    assert 'ORIGINAL CHAPTER' in '\n'.join(p.text for p in doc.paragraphs)


def test_writer_changes_not_overwritten_on_pdf_export(pdf,tmp_path):
    import shutil
    if not shutil.which('xvfb-run'):
        pytest.skip('No virtual display')
    script=r'''
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from docx import Document
import fitz
from docforge.word_ui import WordEditorFrame
messagebox.showinfo=lambda *a,**k:None
messagebox.showerror=lambda *a,**k: (_ for _ in ()).throw(AssertionError(a))
root=tk.Tk();w=WordEditorFrame(root, Path(r"""%s"""));w.pack();root.update()
external=Document(w.working)
external.add_paragraph('CHANGED IN WRITER')
external.save(w.working)
assert w.modified is False
out=w.export_pdf()
assert out is not None
with fitz.open(out) as pdf:
 assert any('CHANGED IN WRITER' in p.get_text() for p in pdf)
root.destroy()
'''
    env=os.environ.copy();env['XDG_CONFIG_HOME']=str(tmp_path/'cfg')
    proc=subprocess.run(['xvfb-run','-a',sys.executable,'-c',script % pdf],
                        capture_output=True,text=True,timeout=45,env=env)
    assert proc.returncode==0,proc.stderr


def test_word_ui_keeps_embedded_image_on_save(tmp_path):
    import shutil
    if not shutil.which('xvfb-run'):
        pytest.skip('No virtual display')
    source=tmp_path/'with-photo.pdf'
    image=tmp_path/'image.png'
    Image.new('RGB',(130,100),'green').save(image)
    with fitz.open() as doc:
        page=doc.new_page()
        page.insert_text((50,50),'PHOTO TEST')
        page.insert_image(fitz.Rect(60,85,200,190),filename=str(image))
        doc.save(source)
    code=r'''
import tkinter as tk
from pathlib import Path
from docx import Document
from docforge.word_ui import WordEditorFrame
root=tk.Tk();w=WordEditorFrame(root,Path(r"""%s"""));w.pack();root.update()
assert len(w._images)==1, w._images
p=w.save_docx();assert p
assert len(Document(p).inline_shapes)>=1
root.destroy()
'''
    env=os.environ.copy();env['XDG_CONFIG_HOME']=str(tmp_path/'cfg')
    p=subprocess.run(['xvfb-run','-a',sys.executable,'-c',code % source],
                     capture_output=True,text=True,timeout=45,env=env)
    assert p.returncode==0,p.stderr


def test_scripted_actual_text_replacement(pdf):
    args=[sys.executable,'-m','docforge','edit-script',str(pdf),
          '--replace','ORIGINAL CHAPTER','--with','SCRIPT EDITED']
    p=subprocess.run(args,capture_output=True,text=True,timeout=45)
    assert p.returncode==0,p.stderr
    output=Path(p.stdout.strip())
    with fitz.open(output) as document:
        assert 'SCRIPT EDITED' in document[0].get_text()
        assert 'ORIGINAL CHAPTER' not in document[0].get_text()
    with fitz.open(pdf) as original:
        assert 'ORIGINAL CHAPTER' in original[0].get_text()
