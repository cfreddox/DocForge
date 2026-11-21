"""End-to-end No-LibreOffice regression fixtures with Cyrillic and local media."""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import pytest
from docx import Document
from docx.shared import Inches
from openpyxl import Workbook, load_workbook
from PIL import Image
from pptx import Presentation
from pptx.util import Inches as SlideInches

from docforge import core
from docforge.office_native import office_to_pdf, preferred_available
from docforge.word_workflow import export_edited_pdf


@pytest.fixture
def office_samples(tmp_path):
    img = tmp_path / 'скан фото.png'
    Image.new('RGB', (100, 60), '#13a6bd').save(img)
    word = Document()
    word.add_heading('Лабораторная работа', 0)
    word.add_paragraph('Русский текст и шрифты 2026. Вторая строка.')
    word.add_picture(str(img), width=Inches(1))
    t = word.add_table(rows=2, cols=2)
    t.cell(0,0).text, t.cell(0,1).text = 'Город', 'Значение'
    t.cell(1,0).text, t.cell(1,1).text = 'Самара', '15'
    path_docx = tmp_path / 'проект.docx'
    word.save(path_docx)
    prs = Presentation()
    for title in ('Обзор рынка', 'Результаты проекта'):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        shape = slide.shapes.add_textbox(SlideInches(.7), SlideInches(.7),
                                         SlideInches(6), SlideInches(1))
        shape.text = title
        slide.shapes.add_picture(str(img), SlideInches(2), SlideInches(2), width=SlideInches(2))
    path_pptx = tmp_path / 'проект.pptx'
    prs.save(path_pptx)
    workbook = Workbook()
    ws = workbook.active
    ws.title = 'Поставка'
    ws.append(['Магазин', 'Количество'])
    ws.append(['Самара', 15])
    ws.append(['Тольятти', 28])
    ws['A1'].font = __import__('openpyxl').styles.Font(bold=True)
    ws.merge_cells('A4:B4'); ws['A4'] = 'Итог'
    path_xlsx = tmp_path / 'таблица.xlsx'
    workbook.save(path_xlsx)
    path_md = tmp_path / 'отчёт.md'
    path_md.write_text('# Отчёт\n\n**Тестирование** завершено.\n\n![Фото](скан%20фото.png)\n', encoding='utf-8')
    return {'docx':path_docx,'pptx':path_pptx,'xlsx':path_xlsx,'md':path_md}


def test_no_libreoffice_dependency_or_process(office_samples):
    assert all('libreoffice' not in core.needs(s, 'pdf') for s in ('docx','pptx','xlsx','md'))
    assert 'libreoffice' not in core.doctor()
    with patch('docforge.core.run') as run_spy:
        for fmt in ('docx','pptx','xlsx'):
            source = office_samples[fmt]
            actual = core.convert(source, 'pdf')
            with fitz.open(actual) as pdf:
                assert pdf.page_count >= 1
        assert not run_spy.called, 'Office PDF path must not spawn an office executable'


def test_cyrillic_and_media_in_native_fallback(office_samples):
    for fmt, required, count in [('docx','Лабораторная работа',1),
                                  ('pptx','Обзор рынка',2),
                                  ('xlsx','Самара',1)]:
        pdf = core.convert(office_samples[fmt], 'pdf')
        with fitz.open(pdf) as doc:
            text=' '.join(page.get_text() for page in doc)
            assert required in text
            assert doc.page_count >= count
            if fmt in {'docx','pptx'}:
                assert any(page.get_images() for page in doc)


def test_markdown_embedded_picture_without_office(office_samples):
    result=core.convert(office_samples['md'], 'pdf')
    with fitz.open(result) as doc:
        assert 'Тестирование' in doc[0].get_text()
        assert doc[0].get_images()


def test_edited_docx_to_pdf_without_office(office_samples):
    docx = office_samples['docx']
    doc=Document(docx)
    doc.paragraphs[1].text = 'Текст действительно заменён'
    doc.save(docx)
    out=export_edited_pdf(docx)
    with fitz.open(out) as pdf:
        content=''.join(page.get_text() for page in pdf)
        assert 'Текст действительно заменён' in content
        assert 'Русский текст и шрифты' not in content
    assert 'Текст действительно заменён' in Document(docx).paragraphs[1].text


def test_csv_spreadsheet_roundtrip(tmp_path):
    csv_file=tmp_path/'sample.csv'
    with csv_file.open('w',newline='',encoding='utf-8') as f:
        csv.writer(f).writerows([['Город','Продажи'],['Самара',15],['Казань',42]])
    xlsx=core.convert(csv_file,'xlsx')
    assert load_workbook(xlsx).active['A2'].value == 'Самара'
    result=core.convert(xlsx,'csv')
    assert 'Самара' in result.read_text(encoding='utf-8-sig')
    pdf=core.convert(csv_file,'pdf')
    with fitz.open(pdf) as doc:
        assert 'Казань' in doc[0].get_text()


def test_legacy_file_formats_are_not_misrepresented():
    assert core.SUPPORTED['doc'] == ()
    assert core.SUPPORTED['ppt'] == ()
    assert core.SUPPORTED['xls'] == ()
    assert core.SUPPORTED['odp'] == ()


def test_preferred_adapter_mock_path(tmp_path, monkeypatch):
    src=tmp_path/'demo.docx'
    Document().save(src)
    out=tmp_path/'demo.pdf'
    dummy=fitz.open()
    dummy.new_page()
    pdf_bytes=dummy.tobytes()
    dummy.close()
    class Engine:
        @staticmethod
        def convert_path(path, options):
            assert Path(path)==src
            return SimpleNamespace(pdf=pdf_bytes, warnings=[])
        @staticmethod
        def ConvertOptions(**kwargs):
            assert kwargs.get('include_warnings') is True
            return kwargs
    module = __import__('types').ModuleType('office2pdf')
    module.convert_path = Engine.convert_path
    module.ConvertOptions = Engine.ConvertOptions
    monkeypatch.setitem(sys.modules, 'office2pdf', module)
    with patch('docforge.office_native.preferred_available',return_value=True):
        assert office_to_pdf(src,out,strict=True)=='office2pdf'
    with fitz.open(out) as doc: assert doc.page_count==1


def test_installer_and_bundles_need_no_libreoffice():
    root=Path(__file__).resolve().parents[1]
    script=(root/'windows/install.ps1').read_text(encoding='ascii')
    assert 'download.documentfoundation.org' not in script
    assert 'msiexec' not in script.lower()
    assert 'OfficeMsi' not in script
    assert 'office2pdf' in script
    if (root/'install.sh').exists():
        assert 'libreoffice ' not in (root/'install.sh').read_text().lower()
    if (root/'requirements.txt').exists():
        assert 'office2pdf-python' in (root/'requirements.txt').read_text()
    assert 'office2pdf-python' in (root/'windows/requirements-windows.txt').read_text()


def test_odt_rtf_text_export_is_not_routed_to_office_suite(tmp_path):
    import subprocess
    md=tmp_path/'simple.md'
    md.write_text('# Заголовок\n\nТекст в документе.\n',encoding='utf-8')
    for fmt in ('odt','rtf'):
        office=tmp_path/f'source.{fmt}'
        subprocess.run(['pandoc',str(md),'-o',str(office)],check=True)
        pdf=core.convert(office,'pdf')
        with fitz.open(pdf) as book:
            assert 'Заголовок' in book[0].get_text()
