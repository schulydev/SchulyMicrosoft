"""Text extraction from documents, sheets, slides, PDFs and text (built in memory, no network)."""

import io
import zipfile
from datetime import date

import pytest

from src import file_text


def docx_bytes():
    from docx import Document

    d = Document()
    d.add_heading("Title one", 1)
    d.add_paragraph("Hello world")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "a", "b|x", "c", "d"
    d.add_heading("Sub", 2)
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def xlsx_bytes(rows=5):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["name", "when", "n"])
    ws.append(["x", date(2026, 1, 2), 3.5])
    for i in range(rows):
        ws.append([f"r{i}", None, i])
    ws.append([None, None, None])
    wb.create_sheet("Other").append(["only"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def pptx_bytes():
    from pptx import Presentation

    p = Presentation()
    s = p.slides.add_slide(p.slide_layouts[1])
    s.shapes.title.text = "Slide title"
    s.placeholders[1].text = "Body text"
    s.notes_slide.notes_text_frame.text = "speaker words"
    p.slides.add_slide(p.slide_layouts[5]).shapes.title.text = "Second"
    out = io.BytesIO()
    p.save(out)
    return out.getvalue()


def pdf_bytes(pages=2):
    # A hand-written PDF with real text objects.
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(pages))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>")
    for i in range(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents {4 + i * 2} 0 R /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>")
        stream = f"BT /F1 12 Tf 10 100 Td (Page text {i + 1}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_docx_headings_paragraphs_and_tables_in_order():
    r = file_text.extract("Plan.docx", docx_bytes())
    assert r["kind"] == "document"
    assert r["text"].splitlines()[0] == "# Title one"
    assert "Hello world" in r["text"] and "| a | b\\|x |" in r["text"] and "## Sub" in r["text"]
    assert r["text"].index("Hello") < r["text"].index("| a |") < r["text"].index("## Sub")
    assert r["offset"] == 0 and r["nextOffset"] is None and r["truncated"] is False and r["notes"] == []


def test_paging_by_characters():
    r = file_text.extract("Plan.docx", docx_bytes(), offset=0, max_chars=10)
    assert len(r["text"]) == 10 and r["nextOffset"] == 10 and r["truncated"] is True
    r2 = file_text.extract("Plan.docx", docx_bytes(), offset=r["nextOffset"], max_chars=100000)
    assert r2["nextOffset"] is None and r2["totalChars"] == r["totalChars"]
    assert r["text"] + r2["text"] == file_text.extract("Plan.docx", docx_bytes())["text"]


def test_xlsx_rows_dates_sheets_and_paging():
    r = file_text.extract("Sheet.xlsx", xlsx_bytes(rows=5))
    assert r["kind"] == "spreadsheet" and r["sheet"] == "Data"
    lines = r["text"].splitlines()
    assert lines[0] == "name,when,n" and lines[1].startswith("x,2026-01-02") and len(lines) == 7  # trailing empty row trimmed
    assert [s["name"] for s in r["sheets"]] == ["Data", "Other"]
    assert r["rowOffset"] == 0 and r["rowCount"] == 7 and r["nextRowOffset"] is None
    page = file_text.extract("Sheet.xlsx", xlsx_bytes(rows=5), max_rows=3)
    assert page["rowCount"] == 3 and page["nextRowOffset"] == 3 and page["truncated"] is True and page["notes"]
    nxt = file_text.extract("Sheet.xlsx", xlsx_bytes(rows=5), row_offset=3, max_rows=100)
    assert nxt["text"].splitlines()[0] == "r1,,1" and nxt["nextRowOffset"] is None
    other = file_text.extract("Sheet.xlsx", xlsx_bytes(), sheet="Other")
    assert other["text"] == "only\n" and other["sheet"] == "Other"
    with pytest.raises(file_text.TextError) as ex:
        file_text.extract("Sheet.xlsx", xlsx_bytes(), sheet="Nope")
    assert ex.value.status == 404


def test_row_caps_are_clamped():
    r = file_text.extract("Sheet.xlsx", xlsx_bytes(rows=3), max_rows=10**9)
    assert r["rowCount"] == 5


def test_pptx_slides_and_notes():
    r = file_text.extract("Deck.pptx", pptx_bytes())
    assert r["kind"] == "presentation" and r["pages"] == 2
    assert "--- Slide 1 ---" in r["text"] and "Slide title" in r["text"] and "Body text" in r["text"] and "Notes: speaker words" in r["text"] and "--- Slide 2 ---" in r["text"]


def test_pdf_pages_and_cap(monkeypatch):
    r = file_text.extract("a.pdf", pdf_bytes(2))
    assert r["kind"] == "pdf" and r["pages"] == 2 and "--- Page 1 ---" in r["text"] and "Page text 2" in r["text"]
    monkeypatch.setattr(file_text, "MAX_PDF_PAGES", 1)
    capped = file_text.extract("a.pdf", pdf_bytes(2))
    assert "Page text 2" not in capped["text"] and capped["pages"] == 2 and capped["notes"]


def test_text_decoding_and_html():
    assert file_text.extract("a.txt", b"\xef\xbb\xbfhi\r\nthere")["text"] == "hi\nthere"
    assert file_text.extract("a.csv", "caf\xe9".encode("latin-1"))["text"] == "caf\xe9"
    assert file_text.extract("a.txt", "zü".encode("utf-16"))["text"] == "zü"
    html = file_text.extract("a.html", b"<html><body><p>Hello <b>you</b></p></body></html>")
    assert html["kind"] == "text" and html["text"] == "Hello you"


def test_unknown_and_legacy_types_are_415():
    for name in ("a.exe", "a.png", "noext"):
        with pytest.raises(file_text.TextError) as ex:
            file_text.extract(name, b"x")
        assert ex.value.status == 415 and str(ex.value) == "This file type cannot be read as text."
    assert file_text.kind_of("old.doc") == "legacy" and file_text.kind_of("a.ODS") == "legacy"
    with pytest.raises(file_text.TextError) as ex:
        file_text.extract("old.doc", b"x")
    assert ex.value.status == 415


def test_source_cap_is_413(monkeypatch):
    monkeypatch.setattr(file_text, "MAX_SOURCE_BYTES", 10)
    with pytest.raises(file_text.TextError) as ex:
        file_text.extract("a.txt", b"x" * 11)
    assert ex.value.status == 413


def test_damaged_office_file_is_422():
    with pytest.raises(file_text.TextError) as ex:
        file_text.extract("a.docx", b"not a zip")
    assert ex.value.status == 422


def _zip(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return out.getvalue()


def test_zip_bomb_guards(monkeypatch):
    monkeypatch.setattr(file_text, "MAX_UNCOMPRESSED", 1000)
    with pytest.raises(file_text.TextError) as ex:
        file_text.extract("a.xlsx", _zip({"a.xml": b"0" * 5000}))
    assert ex.value.status == 413
    monkeypatch.setattr(file_text, "MAX_UNCOMPRESSED", 200 * 1024 * 1024)
    monkeypatch.setattr(file_text, "RATIO_FROM", 1000)
    with pytest.raises(file_text.TextError) as ex:
        file_text.extract("a.docx", _zip({"word/document.xml": b"0" * 100000}))
    assert ex.value.status == 413


def test_xml_entity_declarations_are_refused():
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "boom">]><x>&a;</x>'
    with pytest.raises(file_text.TextError) as ex:
        file_text.extract("a.pptx", _zip({"ppt/presentation.xml": evil}))
    assert ex.value.status == 422
