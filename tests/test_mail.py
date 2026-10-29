"""Mail routes: success, rotated-token header, validation 4xx and the expired-sign-in 401. OutNote is mocked."""

import base64

import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src import config, outnote_client
from src.app import app

H = {config.REFRESH_TOKEN_HEADER: "old-frt"}
MID = "AAMkAGI2=-_x"
ATT = [
    {"id": "a1", "name": "Plan ü.pdf", "contentType": "application/pdf", "size": 5, "isInline": False, "contentId": None, "contentBytes": "AAAA", "@odata.type": "#microsoft.graph.fileAttachment"},
    {"id": "html", "name": "x.html", "contentType": "text/html; charset=utf-8", "size": 5, "isInline": False, "contentId": None},
    {"id": "svg", "name": "x.svg", "contentType": "image/svg+xml", "size": 5, "isInline": False, "contentId": None},
    {"id": "big", "name": "huge.bin", "contentType": "application/octet-stream", "size": 26 * 1024 * 1024, "isInline": False, "contentId": None},
    {"id": "ref", "name": "link", "contentType": None, "size": 1, "isInline": False, "contentId": None},
]


class FakeNote:
    def __init__(self, calls):
        self.calls = calls

    def _rec(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def emails(self, **kw):
        self._rec("emails", **kw)
        return []

    def mail_folders(self, include_children=False):
        self._rec("mail_folders", include_children=include_children)
        return [
            {"id": "inbox-id", "displayName": "Inbox", "parentFolderId": "root", "unreadItemCount": 2, "totalItemCount": 9, "path": "Inbox"},
            {"id": "sent-id", "displayName": "Sent", "parentFolderId": "root", "unreadItemCount": 0, "totalItemCount": 1, "path": "Sent"},
            {"id": "sub-id", "displayName": "Sub", "parentFolderId": "inbox-id", "unreadItemCount": 0, "totalItemCount": 0, "path": "Inbox/Sub"},
            {"id": "subsub-id", "displayName": "SubSub", "parentFolderId": "sub-id", "unreadItemCount": 0, "totalItemCount": 0, "path": "Inbox/Sub/SubSub"},
        ]

    def email(self, message_id):
        self._rec("email", message_id)
        return {"id": message_id, "body": {"contentType": "html", "content": "<p>hi</p>"}}

    def list(self, path, params=None, limit=None):
        self._rec("list", path)
        return ATT

    def download_attachment(self, message_id, attachment_id, dest=None):
        self._rec("download_attachment", message_id, attachment_id)
        if attachment_id == "ref":
            raise ValueError("reference attachment (a link, not a file): https://x")
        return b"%PDF-"

    def send_mail(self, **kw):
        self._rec("send_mail", **kw)

    def reply(self, message_id, comment, reply_all=False):
        self._rec("reply", message_id, comment, reply_all)

    def forward(self, message_id, to, comment=""):
        self._rec("forward", message_id, to, comment)

    def create_draft(self, **kw):
        self._rec("create_draft", **kw)
        return {"id": "draft-1", "isDraft": True}

    def send_draft(self, message_id):
        self._rec("send_draft", message_id)

    def mark_read(self, message_id, read=True):
        self._rec("mark_read", message_id, read)

    def flag(self, message_id, status="flagged"):
        self._rec("flag", message_id, status)

    def move_email(self, message_id, folder):
        self._rec("move_email", message_id, folder)
        return {"id": "moved-id"}

    def delete_email(self, message_id):
        self._rec("delete_email", message_id)


class Broker:
    refresh_token = "rotated-frt"


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (FakeNote(recorded), Broker()))
    return recorded


@pytest.fixture
def client():
    return TestClient(app)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def msg(**over):
    body = {"to": ["a@example.com"], "subject": "Hi", "body": "Hello"}
    body.update(over)
    return body


def test_mail_folder_accepts_an_id_and_rejects_bad_characters(calls, client):
    r = client.get("/api/mail", headers=H, params={"folder": "AAMk=-_"})
    assert r.status_code == 200
    assert calls[0][2]["folder"] == "AAMk%3D-_"
    assert "body" not in calls[0][2]["select"].split(",")
    assert client.get("/api/mail", headers=H, params={"folder": "a b;x"}).status_code == 400


def test_folders_are_nested_and_rotate_the_token(calls, client):
    r = client.get("/api/mail/folders", headers=H)
    assert r.status_code == 200
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    tree = r.json()
    assert [f["id"] for f in tree] == ["inbox-id", "sent-id"]
    assert tree[0]["childFolders"][0]["id"] == "sub-id"
    assert tree[0]["childFolders"][0]["childFolders"][0]["id"] == "subsub-id"
    assert calls[0][2] == {"include_children": True}


def test_message_is_fetched_with_an_encoded_id(calls, client):
    r = client.get(f"/api/mail/{MID}", headers=H)
    assert r.status_code == 200
    assert r.json()["body"]["content"] == "<p>hi</p>"
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert calls[0][1] == ("AAMkAGI2%3D-_x",)


def test_a_bad_id_is_rejected(calls, client):
    assert client.get("/api/mail/bad%20id", headers=H).status_code == 400
    assert client.get("/api/mail/" + "a" * 513, headers=H).status_code == 400
    assert client.delete("/api/mail/a;b", headers=H).status_code == 400
    assert calls == []


def test_attachment_list_has_no_content_bytes(calls, client):
    r = client.get(f"/api/mail/{MID}/attachments", headers=H)
    assert r.status_code == 200
    first = r.json()[0]
    assert set(first) == {"id", "name", "contentType", "size", "isInline", "contentId"}
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"


def test_attachment_download_headers(calls, client):
    r = client.get(f"/api/mail/{MID}/attachments/a1", headers=H)
    assert r.status_code == 200
    assert r.content == b"%PDF-"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == "attachment; filename*=UTF-8''Plan%20%C3%BC.pdf"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"


@pytest.mark.parametrize("attachment_id,name", [("html", "x.html"), ("svg", "x.svg")])
def test_active_attachments_are_served_as_opaque_downloads(calls, client, attachment_id, name):
    r = client.get(f"/api/mail/{MID}/attachments/{attachment_id}", headers=H)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"] == f"attachment; filename*=UTF-8''{name}"
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_attachment_over_25mb_is_413_and_missing_is_404(calls, client):
    big = client.get(f"/api/mail/{MID}/attachments/big", headers=H)
    assert big.status_code == 413
    assert not any(c[0] == "download_attachment" for c in calls)
    assert big.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert client.get(f"/api/mail/{MID}/attachments/nope", headers=H).status_code == 404
    assert client.get(f"/api/mail/{MID}/attachments/ref", headers=H).status_code == 422


def test_send_passes_validated_arguments(calls, client):
    payload = msg(cc=["c@example.com"], html=True, attachments=[{"name": "../evil/na:me.txt", "contentType": "text/plain", "contentBase64": b64(b"hello")}])
    r = client.post("/api/mail/send", headers=H, json=payload)
    assert r.status_code == 204
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    kw = calls[0][2]
    assert kw["to"] == ["a@example.com"] and kw["cc"] == ["c@example.com"] and kw["bcc"] is None and kw["html"] is True
    assert kw["attachments"] == [("_evil_na_me.txt", b"hello")]


@pytest.mark.parametrize(
    "payload,status",
    [
        (msg(to=[]), 400),
        (msg(to=["not-an-address"]), 400),
        (msg(to=["a b@example.com"]), 400),
        (msg(to=[f"u{i}@example.com" for i in range(101)]), 400),
        (msg(subject="s" * 256), 400),
        (msg(body="x" * (1024 * 1024 + 1)), 413),
        (msg(attachments=[{"name": "a", "contentBase64": "***"}]), 400),
        (msg(attachments=[{"name": "a", "contentBase64": b64(b"x" * (2 * 1024 * 1024))}, {"name": "b", "contentBase64": b64(b"x" * (2 * 1024 * 1024))}]), 413),
        ({"to": ["a@example.com"]}, 422),
    ],
)
def test_send_validation(calls, client, payload, status):
    assert client.post("/api/mail/send", headers=H, json=payload).status_code == status
    assert calls == []


def test_reply_and_forward(calls, client):
    assert client.post(f"/api/mail/{MID}/reply", headers=H, json={"comment": "ok", "replyAll": True}).status_code == 204
    assert calls[0] == ("reply", ("AAMkAGI2%3D-_x", "ok", True), {})
    r = client.post(f"/api/mail/{MID}/forward", headers=H, json={"to": ["b@example.com"]})
    assert r.status_code == 204
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert calls[1][1] == ("AAMkAGI2%3D-_x", ["b@example.com"], "")
    assert client.post(f"/api/mail/{MID}/forward", headers=H, json={"to": []}).status_code == 400
    assert client.post(f"/api/mail/{MID}/forward", headers=H, json={"to": ["nope"]}).status_code == 400
    assert client.post(f"/api/mail/{MID}/reply", headers=H, json={}).status_code == 422


def test_drafts_create_and_send(calls, client):
    r = client.post("/api/mail/drafts", headers=H, json=msg())
    assert r.status_code == 201 and r.json()["id"] == "draft-1"
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert client.post("/api/mail/drafts", headers=H, json=msg(to=[])).status_code == 400
    s = client.post("/api/mail/drafts/d%3D1/send", headers=H)
    assert s.status_code == 204
    assert s.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert calls[-1] == ("send_draft", ("d%3D1",), {})


def test_read_flag_move_delete(calls, client):
    r = client.post(f"/api/mail/{MID}/read", headers=H, json={"read": True})
    assert r.status_code == 200 and r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert calls[0][1] == ("AAMkAGI2%3D-_x", True)
    assert client.post(f"/api/mail/{MID}/flag", headers=H, json={"status": "complete"}).status_code == 200
    assert calls[1][1] == ("AAMkAGI2%3D-_x", "complete")
    assert client.post(f"/api/mail/{MID}/flag", headers=H, json={"status": "bogus"}).status_code == 422
    m = client.post(f"/api/mail/{MID}/move", headers=H, json={"folder": "archive"})
    assert m.status_code == 200 and m.json() == {"id": "moved-id"}
    assert client.post(f"/api/mail/{MID}/move", headers=H, json={"folder": "bad folder"}).status_code == 400
    d = client.delete(f"/api/mail/{MID}", headers=H)
    assert d.status_code == 204 and d.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert calls[-1][0] == "delete_email"


def test_fixed_paths_are_not_read_as_message_ids(calls, client):
    client.get("/api/mail/folders", headers=H)
    assert calls[0][0] == "mail_folders"


def test_a_missing_token_is_rejected(client):
    assert client.get("/api/mail/folders").status_code == 422
    assert client.post("/api/mail/send", json=msg()).status_code == 422


@pytest.mark.parametrize(
    "method,path,json",
    [
        ("get", "/api/mail/folders", None),
        ("get", f"/api/mail/{MID}", None),
        ("get", f"/api/mail/{MID}/attachments/a1", None),
        ("post", "/api/mail/send", msg()),
        ("post", "/api/mail/drafts", msg()),
        ("post", f"/api/mail/{MID}/reply", {"comment": "x"}),
        ("post", f"/api/mail/{MID}/read", {"read": False}),
        ("delete", f"/api/mail/{MID}", None),
    ],
)
def test_an_expired_token_maps_to_401(monkeypatch, client, method, path, json):
    class Dead:
        def __getattr__(self, name):
            def boom(*a, **k):
                raise RuntimeError("AADSTS700082 invalid_grant: expired")
            return boom

    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (Dead(), Broker()))
    r = getattr(client, method)(path, headers=H, **({"json": json} if json is not None else {}))
    assert r.status_code == 401


def test_graph_404_maps_to_404_and_other_errors_to_502(monkeypatch, client):
    class Note:
        def email(self, message_id):
            raise GraphError(404, "gone")

        def mail_folders(self, include_children=False):
            raise GraphError(500, "boom")

    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (Note(), Broker()))
    assert client.get(f"/api/mail/{MID}", headers=H).status_code == 404
    assert client.get("/api/mail/folders", headers=H).status_code == 502


def test_mail_list_skip_pages_with_skip_param_and_rejects_search(calls, client):
    r = client.get("/api/mail", headers=H, params={"folder": "inbox", "top": 25, "skip": 50, "unread": "true"})
    assert r.status_code == 200
    assert ("list", ("me/mailFolders/inbox/messages",), {}) in calls or any(c[0] == "list" and c[1][0] == "me/mailFolders/inbox/messages" for c in calls)
    assert client.get("/api/mail", headers=H, params={"skip": 5, "search": "x"}).status_code == 400
