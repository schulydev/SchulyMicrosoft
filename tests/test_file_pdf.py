"""Office files as PDF: drive items, chat files, mail attachments and uploaded bytes (all mocked, no network)."""

import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src import config, file_pdf, outnote_client
from src.app import app

H = {config.REFRESH_TOKEN_HEADER: "old-frt"}
PDF = b"%PDF-1.7\n" + b"x" * 300
LOCATION = "https://switzerlandwest1-mediap.svc.ms/transform/pdf?provider=spo&x=1"
SHARE = "https://school-my.sharepoint.com/personal/me/Documents/Plan.docx"


class Broker:
    def __init__(self):
        self.refresh_token = "old-frt"

    def __call__(self, client_id, scope=None):
        self.refresh_token = "rotated-frt"
        return "bearer"


class Note:
    def __init__(self, broker):
        self.broker = broker
        self.calls = []
        self.items = {"ITEM1": {"id": "ITEM1", "name": "Plan.docx", "size": 2048, "file": {}}}
        self.attachments = [{"id": "ATT1", "name": "Sheet.xlsx", "size": 10, "@odata.type": "#microsoft.graph.fileAttachment"}, {"id": "ATT2", "name": "photo.png", "size": 10}, {"id": "ATT3", "name": "Fwd", "size": 10, "@odata.type": "#microsoft.graph.itemAttachment"}]
        self.children = []
        self.location = LOCATION
        self.convert_error = None
        self.uploaded = []
        self.deleted = []

    def get(self, path, params=None, raw=False):
        self.broker("x")
        self.calls.append(("get", path))
        if path.startswith("me/drive/items/"):
            item = self.items.get(path.rsplit("/", 1)[1])
            if item is None:
                raise GraphError(404, "missing")
            return item
        if path.startswith("chats/"):
            return {"id": "m1", "body": {"content": '<attachment id="f1"></attachment>'}, "attachments": [{"id": "f1", "contentType": "reference", "name": "Plan.docx", "contentUrl": SHARE}, {"id": "f2", "contentType": "reference", "name": "x.docx", "contentUrl": "https://evil.test/x.docx"}]}
        if path.startswith("shares/"):
            return {"id": "SPITEM", "name": "Plan.docx", "size": 4096, "file": {}, "parentReference": {"driveId": "b!DRIVE"}}
        raise GraphError(404, "missing")

    def list(self, path, params=None, limit=None):
        self.calls.append(("list", path))
        if path.endswith("/attachments"):
            return self.attachments
        if file_pdf.TEMP_FOLDER in path:
            return self.children
        return []

    def download_attachment(self, message_id, attachment_id):
        return b"PK\x03\x04 xlsx bytes"

    def converted_url(self, item_id, fmt, drive_id=None):
        self.calls.append(("convert", item_id, fmt, drive_id))
        if self.convert_error:
            raise self.convert_error
        return self.location

    def upload(self, data, dest_path, conflict="replace", app_folder=False):
        self.uploaded.append((len(data), dest_path, conflict, app_folder))
        return {"id": "TMP!1"}

    def delete_file(self, item_id):
        self.deleted.append(item_id)


class Stream:
    def __init__(self, status=200, body=PDF):
        self.status_code = status
        self.body = body

    def iter_bytes(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i : i + size]


class Http:
    def __init__(self):
        self.answer = Stream()
        self.fetched = []

    @contextmanager
    def stream(self, method, url, **kw):
        self.fetched.append((url, kw))
        yield self.answer


@pytest.fixture
def env(monkeypatch):
    broker = Broker()
    note = Note(broker)
    http = Http()
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (note, broker))
    monkeypatch.setattr(file_pdf.entrance, "http_client", lambda: http)
    return note, http, TestClient(app)


def _secure(r):
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline; filename*=UTF-8''")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert r.content == PDF


# --- drive items ------------------------------------------------------------------
def test_drive_item_is_converted_in_place(env):
    note, http, client = env
    r = client.get("/api/files/ITEM1/pdf", headers=H)
    _secure(r)
    assert "Plan.pdf" in r.headers["content-disposition"]
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert ("convert", "ITEM1", "pdf", None) in note.calls
    # The pre-authenticated URL is fetched without following redirects and with no bearer token.
    url, kw = http.fetched[0]
    assert url == LOCATION and kw["follow_redirects"] is False and "headers" not in kw
    assert not note.uploaded


def test_drive_item_of_a_type_graph_cannot_convert_is_415(env):
    note, _, client = env
    note.items["IMG"] = {"id": "IMG", "name": "photo.png", "size": 10, "file": {}}
    assert client.get("/api/files/IMG/pdf", headers=H).status_code == 415
    assert not [c for c in note.calls if c[0] == "convert"]


def test_drive_item_over_100_mb_is_413(env):
    note, _, client = env
    note.items["BIG"] = {"id": "BIG", "name": "big.pptx", "size": 101 * 1024 * 1024, "file": {}}
    assert client.get("/api/files/BIG/pdf", headers=H).status_code == 413


def test_graph_refusing_the_conversion_is_415(env):
    note, _, client = env
    note.convert_error = GraphError(406, "not acceptable")
    assert client.get("/api/files/ITEM1/pdf", headers=H).status_code == 415


def test_a_folder_or_missing_item_is_404(env):
    note, _, client = env
    note.items["DIR"] = {"id": "DIR", "name": "Folder.docx", "folder": {}}
    assert client.get("/api/files/DIR/pdf", headers=H).status_code == 404
    assert client.get("/api/files/NOPE/pdf", headers=H).status_code == 404


@pytest.mark.parametrize("location", ["http://switzerlandwest1-mediap.svc.ms/x", "https://evil.test/x.pdf", "https://mediap.svc.ms.evil.test/x", "https://user:pw@switzerlandwest1-mediap.svc.ms/x", "https://switzerlandwest1-mediap.svc.ms:8443/x", "https://evil-svc.ms/x"])
def test_only_the_conversion_hosts_are_fetched(env, location):
    note, http, client = env
    note.location = location
    assert client.get("/api/files/ITEM1/pdf", headers=H).status_code == 502
    assert not http.fetched


def test_host_allowlist():
    assert file_pdf.is_converted_url(LOCATION)
    assert file_pdf.is_converted_url("https://eu-1-mediap.svc.ms/transform/pdf")
    assert file_pdf.is_converted_url("https://school-my.sharepoint.com/_layouts/15/download.aspx")
    assert not file_pdf.is_converted_url("https://svc.ms/x")
    assert not file_pdf.is_converted_url("https://x.svc.ms/x")
    assert not file_pdf.is_converted_url("https://sharepoint.com.evil.test/x")
    assert not file_pdf.is_converted_url("https://a b-mediap.svc.ms/x")


def test_an_answer_that_is_not_a_pdf_is_refused(env):
    _, http, client = env
    http.answer = Stream(body=b"<html><script>alert(1)</script></html>")
    r = client.get("/api/files/ITEM1/pdf", headers=H)
    assert r.status_code == 502 and b"script" not in r.content


def test_a_failed_upstream_fetch_is_502(env):
    _, http, client = env
    http.answer = Stream(status=403)
    assert client.get("/api/files/ITEM1/pdf", headers=H).status_code == 502


def test_an_oversized_pdf_is_413(env, monkeypatch):
    monkeypatch.setattr(file_pdf, "MAX_PDF_BYTES", 100)
    _, _, client = env
    assert client.get("/api/files/ITEM1/pdf", headers=H).status_code == 413


@pytest.mark.parametrize("bad", ["a..b", "%2E%2E", "x%2F..%2Fy"])
def test_dot_segment_ids_are_refused(env, bad):
    note, _, client = env
    assert client.get(f"/api/files/{bad}/pdf", headers=H).status_code in (400, 404)
    assert client.get(f"/api/chats/19:a@thread.v2/messages/{bad}/files/f1/pdf", headers=H).status_code in (400, 404)
    assert client.get(f"/api/mail/{bad}/attachments/ATT1/pdf", headers=H).status_code in (400, 404)
    assert not [c for c in note.calls if c[0] == "convert"]


# --- chat files ---------------------------------------------------------------------
def test_chat_file_is_converted_where_it_lives(env):
    note, _, client = env
    r = client.get("/api/chats/19:a@thread.v2/messages/m1/files/f1/pdf", headers=H)
    _secure(r)
    share = [c for c in note.calls if c[0] == "get" and c[1].startswith("shares/")][0][1]
    assert share.startswith("shares/u!" + base64.urlsafe_b64encode(SHARE.encode()).decode().rstrip("="))
    assert ("convert", "SPITEM", "pdf", "b%21DRIVE") in note.calls


def test_chat_file_outside_sharepoint_is_refused(env):
    note, _, client = env
    assert client.get("/api/chats/19:a@thread.v2/messages/m1/files/f2/pdf", headers=H).status_code == 415
    assert not [c for c in note.calls if c[1:2] and str(c[1]).startswith("shares/")]
    assert client.get("/api/chats/19:a@thread.v2/messages/m1/files/nope/pdf", headers=H).status_code == 404


# --- mail attachments (temporary upload) ---------------------------------------------
def test_mail_attachment_goes_through_a_temporary_file_that_is_deleted(env):
    note, _, client = env
    r = client.get("/api/mail/MSG1/attachments/ATT1/pdf", headers=H)
    _secure(r)
    assert "Sheet.pdf" in r.headers["content-disposition"]
    size, path, conflict, app_folder = note.uploaded[0]
    assert app_folder is True and conflict == "fail"
    assert path.startswith(file_pdf.TEMP_FOLDER + "/") and path.endswith(".xlsx") and "Sheet" not in path
    assert ("convert", "TMP%211", "pdf", None) in note.calls
    assert note.deleted == ["TMP%211"]


def test_temporary_file_is_deleted_when_the_conversion_fails(env):
    note, http, client = env
    http.answer = Stream(body=b"not a pdf")
    assert client.get("/api/mail/MSG1/attachments/ATT1/pdf", headers=H).status_code == 502
    assert note.deleted == ["TMP%211"]
    note.deleted.clear()
    note.convert_error = GraphError(500, "boom")
    assert client.get("/api/mail/MSG1/attachments/ATT1/pdf", headers=H).status_code == 502
    assert note.deleted == ["TMP%211"]


def test_mail_attachments_that_cannot_be_converted(env):
    note, _, client = env
    assert client.get("/api/mail/MSG1/attachments/ATT2/pdf", headers=H).status_code == 415
    assert client.get("/api/mail/MSG1/attachments/ATT3/pdf", headers=H).status_code == 415
    assert client.get("/api/mail/MSG1/attachments/NOPE/pdf", headers=H).status_code == 404
    note.attachments[0]["size"] = 26 * 1024 * 1024
    assert client.get("/api/mail/MSG1/attachments/ATT1/pdf", headers=H).status_code == 413
    assert not note.uploaded


# --- uploaded bytes -------------------------------------------------------------------
def test_convert_route_converts_the_body(env):
    note, _, client = env
    r = client.post("/api/convert/pdf?name=Zeugnis%20Q1.docx", headers={**H, "Content-Type": "application/octet-stream"}, content=b"PK\x03\x04docx")
    _secure(r)
    assert "Zeugnis%20Q1.pdf" in r.headers["content-disposition"]
    assert note.uploaded[0][0] == 8 and note.uploaded[0][1].endswith(".docx")
    assert note.deleted == ["TMP%211"]


def test_convert_route_deletes_the_temporary_file_on_failure(env):
    note, _, client = env
    note.location = "https://evil.test/x"
    assert client.post("/api/convert/pdf?name=a.pptx", headers=H, content=b"PK").status_code == 502
    assert note.deleted == ["TMP%211"]


def test_convert_route_refuses_types_and_empty_bodies(env):
    note, _, client = env
    assert client.post("/api/convert/pdf?name=page.html", headers=H, content=b"<p>").status_code == 415
    assert client.post("/api/convert/pdf?name=noext", headers=H, content=b"x").status_code == 415
    assert client.post("/api/convert/pdf?name=a.docx", headers=H, content=b"").status_code == 400
    assert client.post("/api/convert/pdf", headers=H, content=b"x").status_code == 422
    assert not note.uploaded


def test_convert_route_caps_the_declared_length(env):
    note, _, client = env
    r = client.post("/api/convert/pdf?name=a.docx", headers={**H, "Content-Length": str(106 * 1024 * 1024)}, content=b"x")
    assert r.status_code == 413
    assert not note.uploaded


def test_convert_route_counts_a_chunked_body(env, monkeypatch):
    import src.app as service

    monkeypatch.setattr(service, "MAX_SEND_BYTES", 1024)
    note, _, client = env

    def chunks():
        for _ in range(4):
            yield b"x" * 512

    r = client.post("/api/convert/pdf?name=a.docx", headers=H, content=chunks())
    assert r.status_code == 413
    assert not note.uploaded


def test_convert_route_needs_a_wellformed_token(env):
    _, _, client = env
    assert client.post("/api/convert/pdf?name=a.docx", headers={config.REFRESH_TOKEN_HEADER: "a b"}, content=b"x").status_code == 401


# --- sweep ---------------------------------------------------------------------------
def test_sweep_deletes_only_stale_files_and_is_throttled(env):
    note, _, _ = env
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    note.children = [
        {"id": "OLD", "createdDateTime": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")},
        {"id": "NEW", "createdDateTime": (now - timedelta(minutes=5)).isoformat()},
        {"id": "ODD", "createdDateTime": "yesterday"},
    ]
    broker = note.broker
    assert file_pdf.sweep(note, broker, now) == 1
    assert note.deleted == ["OLD"]
    assert file_pdf.sweep(note, broker, now) == 0
    assert note.deleted == ["OLD"]


def test_sweep_ignores_a_missing_folder(env):
    note, _, _ = env

    def missing(path, params=None, limit=None):
        raise GraphError(404, "itemNotFound")

    note.list = missing
    assert file_pdf.sweep(note, Broker()) == 0


def test_a_conversion_sweeps_first(env):
    note, _, client = env
    note.children = [{"id": "LEFT", "createdDateTime": "2020-01-01T00:00:00Z"}]
    client.post("/api/convert/pdf?name=a.docx", headers=H, content=b"PK")
    assert note.deleted == ["LEFT", "TMP%211"]
