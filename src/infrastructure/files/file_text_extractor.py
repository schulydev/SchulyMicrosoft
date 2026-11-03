"""Plain text out of documents, spreadsheets, presentations, PDFs and text files (the FileText answer).

Office and PDF libraries are imported lazily. Untrusted bytes are checked before they reach an OOXML library: the source is capped,
the zip's declared uncompressed size is summed (zipfile never reads past a member's declared size) and a member with an absurd
compression ratio or an XML part declaring entities is refused. Nothing here logs content; it runs in the worker thread.
"""

import csv
import io
import posixpath
import zipfile
from datetime import date, datetime, time

from src.application.abstractions.i_file_text_extractor import IFileTextExtractor
from src.domain.errors.text_error import TextError
from src.domain.files.file_text_limits import FileTextLimits


class FileTextExtractor(IFileTextExtractor):
    """Plain text out of documents, spreadsheets, presentations, PDFs and text files."""

    MAX_SOURCE_BYTES = FileTextLimits.MAX_SOURCE_BYTES
    MAX_UNCOMPRESSED = 200 * 1024 * 1024
    MAX_ZIP_MEMBERS = 10000
    MAX_RATIO = 250
    RATIO_FROM = 4 * 1024 * 1024
    DEFAULT_CHARS = FileTextLimits.DEFAULT_CHARS
    MAX_CHARS = FileTextLimits.MAX_CHARS
    TEXT_CAP = 2_000_000
    MAX_PDF_PAGES = 300
    MAX_SLIDES = 500
    DEFAULT_ROWS = FileTextLimits.DEFAULT_ROWS
    MAX_ROWS = FileTextLimits.MAX_ROWS
    MAX_ROW_OFFSET = FileTextLimits.MAX_ROW_OFFSET
    PEEK_ROWS = 10000
    DOCUMENT = {"docx"}
    SPREADSHEET = {"xlsx", "xlsm"}
    PRESENTATION = {"pptx"}
    PDF = {"pdf"}
    TEXT = {"txt", "md", "markdown", "csv", "tsv", "json", "xml", "html", "htm", "ics", "log", "yaml", "yml", "ini", "cfg", "conf", "toml", "tex", "sql", "css", "js", "ts", "py", "java", "cs", "c", "cpp", "h", "sh", "ps1", "rb", "go", "rs", "php", "kt", "swift", "dart", "lua", "vcf", "srt"}
    LEGACY = {"doc", "xls", "ppt", "odt", "ods", "odp", "rtf"}
    UNSUPPORTED = FileTextLimits.UNSUPPORTED

    def extension(self, name) -> str:
        return posixpath.splitext(name or "")[1].lstrip(".").lower() if isinstance(name, str) else ""

    def kind_of(self, name) -> str | None:
        """document | spreadsheet | presentation | pdf | text | legacy (convert to PDF first), or None when the type can't be read."""
        ext = self.extension(name)
        for kind, exts in (("document", self.DOCUMENT), ("spreadsheet", self.SPREADSHEET), ("presentation", self.PRESENTATION), ("pdf", self.PDF), ("text", self.TEXT), ("legacy", self.LEGACY)):
            if ext in exts:
                return kind
        return None

    def extract(self, name: str, data: bytes, offset: int = 0, max_chars: int = DEFAULT_CHARS, sheet: str | None = None, row_offset: int = 0, max_rows: int = DEFAULT_ROWS, notes: list[str] | None = None) -> dict:
        """The FileText answer for `data`. Legacy formats must be converted to PDF by the caller (`extract` then gets the PDF, name ending in .pdf)."""
        kind = self.kind_of(name)
        if kind is None or kind == "legacy":
            raise TextError(415, self.UNSUPPORTED)
        if len(data) > self.MAX_SOURCE_BYTES:
            raise TextError(413, "The file is larger than 25 MB.")
        max_chars = max(1, min(max_chars, self.MAX_CHARS))
        offset = max(0, offset)
        notes = list(notes or [])
        result = {"name": name, "kind": kind}
        try:
            if kind == "spreadsheet":
                self._zip_guard(data)
                text, extra = self._spreadsheet(data, sheet, max(0, min(row_offset, self.MAX_ROW_OFFSET)), max(1, min(max_rows, self.MAX_ROWS)), notes)
            elif kind == "document":
                self._zip_guard(data)
                text, extra = self._document(data, notes), {}
            elif kind == "presentation":
                self._zip_guard(data)
                text, extra = self._presentation(data, notes, result), {}
            elif kind == "pdf":
                text, extra = self._pdf(data, notes, result), {}
            else:
                text, extra = self._plain(name, data, notes), {}
        except TextError:
            raise
        except Exception:
            raise TextError(422, "The file could not be read.")
        capped = len(text) > self.TEXT_CAP
        if capped:
            text = text[:self.TEXT_CAP]
            notes.append(f"Only the first {self.TEXT_CAP} characters are counted.")
        page = text[offset : offset + max_chars]
        end = offset + len(page)
        more = end < len(text)
        result.update({"text": page, "offset": offset, "nextOffset": end if more else None, "totalChars": len(text), "truncated": more or capped or extra.pop("limited", False), "notes": notes})
        result.update(extra)
        return result

    def _zip_guard(self, data: bytes):
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise TextError(422, "The file is damaged or not an Office document.")
        with archive:
            members = archive.infolist()
            if len(members) > self.MAX_ZIP_MEMBERS:
                raise TextError(413, "The file contains too many parts.")
            total = 0
            for m in members:
                total += m.file_size
                if m.file_size >= self.RATIO_FROM and m.file_size > self.MAX_RATIO * max(m.compress_size, 1):
                    raise TextError(413, "The file is compressed suspiciously well and is refused.")
            if total > self.MAX_UNCOMPRESSED:
                raise TextError(413, "The file unpacks to more than 200 MB.")
            for m in members:
                if m.filename.lower().endswith((".xml", ".rels")) and m.file_size:
                    with archive.open(m) as part:
                        head = part.read(4096).upper()
                    if b"<!ENTITY" in head or b"<!DOCTYPE" in head and b"[" in head:
                        raise TextError(422, "The file contains XML entity declarations and is refused.")

    def _cell(self, text) -> str:
        return " ".join(str(text).split()).replace("|", "\\|")

    def _document(self, data: bytes, notes: list[str]) -> str:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = Document(io.BytesIO(data))
        out, size = [], 0
        for child in doc.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                para = Paragraph(child, doc)
                text = para.text
                if not text.strip():
                    out.append("")
                    continue
                style = (para.style.name if para.style is not None else "") or ""
                if style == "Title":
                    text = "# " + text
                elif style.startswith("Heading "):
                    level = style[8:]
                    text = "#" * (int(level) if level.isdigit() and 1 <= int(level) <= 6 else 1) + " " + text
                out.append(text)
                size += len(text)
            elif tag == "tbl":
                for row in Table(child, doc).rows:
                    seen, cells = set(), []
                    for cell in row.cells:
                        if id(cell._tc) in seen:
                            continue
                        seen.add(id(cell._tc))
                        cells.append(self._cell(cell.text))
                    line = "| " + " | ".join(cells) + " |"
                    out.append(line)
                    size += len(line)
            if size > self.TEXT_CAP:
                notes.append("The document is longer than the reader's limit; the rest is left out.")
                break
        return self._squeeze("\n".join(out))

    def _squeeze(self, text: str) -> str:
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text.strip()

    def _value(self, v) -> str:
        if v is None:
            return ""
        if isinstance(v, (datetime, date, time)):
            return v.isoformat()
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        return str(v)

    def _spreadsheet(self, data: bytes, sheet: str | None, row_offset: int, max_rows: int, notes: list[str]):
        import defusedxml  # noqa: F401  (openpyxl parses with defusedxml when it is installed)
        from itertools import islice

        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            sheets = [{"name": ws.title, "rows": int(ws.max_row or 0), "columns": int(ws.max_column or 0)} for ws in wb.worksheets]
            if not sheets:
                raise TextError(422, "The workbook has no sheets.")
            name = sheet if sheet is not None else sheets[0]["name"]
            if name not in wb.sheetnames:
                raise TextError(404, "Sheet not found.")
            ws = wb[name]
            rows = ws.iter_rows(values_only=True)
            for _ in islice(rows, row_offset):
                pass
            page = [list(r) for r in islice(rows, max_rows)]
            more = False
            for peeked in islice(rows, self.PEEK_ROWS):
                if any(v is not None and v != "" for v in peeked):
                    more = True
                    break
            while page and all(v is None or v == "" for v in page[-1]):
                page.pop()
            width = max((max((i + 1 for i, v in enumerate(r) if v is not None and v != ""), default=0) for r in page), default=0)
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            for r in page:
                writer.writerow([self._value(v) for v in (r + [None] * width)[:width]])
            count = len(page)
            if more:
                notes.append(f"Only rows {row_offset + 1} to {row_offset + count} of sheet {name} are included; continue with rowOffset={row_offset + count}.")
            extra = {"sheets": sheets, "sheet": name, "rowOffset": row_offset, "rowCount": count, "nextRowOffset": row_offset + count if more else None, "limited": more}
            return buf.getvalue(), extra
        finally:
            wb.close()

    def _shape_text(self, shape, out: list[str]):
        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            text = shape.text_frame.text.strip()
            if text:
                out.append(text)
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                out.append("| " + " | ".join(self._cell(c.text) for c in row.cells) + " |")
        if shape.shape_type == 6:  # group
            for inner in shape.shapes:
                self._shape_text(inner, out)

    def _presentation(self, data: bytes, notes: list[str], result: dict) -> str:
        from pptx import Presentation

        prs = Presentation(io.BytesIO(data))
        slides = list(prs.slides)
        result["pages"] = len(slides)
        out, size = [], 0
        for number, slide in enumerate(slides, 1):
            if number > self.MAX_SLIDES:
                notes.append(f"Only the first {self.MAX_SLIDES} slides are included.")
                break
            lines = [f"--- Slide {number} ---"]
            for shape in slide.shapes:
                self._shape_text(shape, lines)
            if slide.has_notes_slide:
                spoken = slide.notes_slide.notes_text_frame.text.strip() if slide.notes_slide.notes_text_frame is not None else ""
                if spoken:
                    lines.append("Notes: " + spoken)
            block = "\n".join(lines)
            out.append(block)
            size += len(block)
            if size > self.TEXT_CAP:
                notes.append("The presentation is longer than the reader's limit; the rest is left out.")
                break
        return "\n\n".join(out)

    def _pdf(self, data: bytes, notes: list[str], result: dict) -> str:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:
                ok = 0
            if not ok:
                raise TextError(422, "The PDF is password protected.")
        total = len(reader.pages)
        result["pages"] = total
        out, size = [], 0
        for number, page in enumerate(reader.pages, 1):
            if number > self.MAX_PDF_PAGES:
                notes.append(f"Only the first {self.MAX_PDF_PAGES} pages are included.")
                break
            out.append(f"--- Page {number} ---\n{(page.extract_text() or '').strip()}")
            size += len(out[-1])
            if size > self.TEXT_CAP:
                notes.append("The PDF is longer than the reader's limit; the rest is left out.")
                break
        return "\n\n".join(out)

    def decode(self, data: bytes) -> str:
        if data.startswith(b"\xef\xbb\xbf"):
            return data[3:].decode("utf-8", "replace")
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16", "replace")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")

    def _plain(self, name: str, data: bytes, notes: list[str]) -> str:
        text = self.decode(data)
        if self.extension(name) in ("html", "htm"):
            from outnote import html_to_text

            return html_to_text(text)
        return text.replace("\r\n", "\n").replace("\r", "\n")
