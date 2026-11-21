"""Windows XLSX native font fallback regression tests."""
from pathlib import Path

import pymupdf
import pytest
from openpyxl import Workbook

from docforge import office_native


def workbook(tmp_path):
    path = tmp_path / 'sample.xlsx'
    book = Workbook()
    book.active.append(['Native XLSX sample', 2026])
    book.save(path)
    return path


def pdf_with_text(path: Path, text: str):
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((60, 60), text)
    pdf.save(path)
    pdf.close()


def test_native_missing_xlsx_unicode_uses_verified_fallback(tmp_path, monkeypatch):
    source = workbook(tmp_path)
    target = tmp_path / 'out.pdf'
    monkeypatch.setattr(office_native, 'preferred_available', lambda: True)
    monkeypatch.setattr(office_native, '_office2pdf', lambda src, dst: pdf_with_text(dst, 'unmapped text'))
    result = office_native.office_to_pdf(source, target)
    assert result == 'simplified-verified'
    with pymupdf.open(target) as pdf:
        assert 'Native XLSX sample' in ''.join(page.get_text() for page in pdf)


def test_good_native_xlsx_is_not_replaced(tmp_path, monkeypatch):
    source = workbook(tmp_path)
    target = tmp_path / 'out.pdf'
    monkeypatch.setattr(office_native, 'preferred_available', lambda: True)
    monkeypatch.setattr(office_native, '_office2pdf', lambda src, dst: pdf_with_text(dst, 'Native XLSX sample'))
    def forbidden(*args):
        raise AssertionError('fallback not expected')
    monkeypatch.setattr(office_native, '_fallback_xlsx', forbidden)
    assert office_native.office_to_pdf(source, target) == 'office2pdf'


def test_healthcheck_produces_searchable_xlsx_with_fallback(tmp_path, monkeypatch):
    source = workbook(tmp_path)
    result = tmp_path / 'out.pdf'
    monkeypatch.setattr(office_native, 'preferred_available', lambda: False)
    assert office_native.office_to_pdf(source, result) == 'simplified'
    assert office_native._xlsx_text_check(source, result)
