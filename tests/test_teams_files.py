"""Team files, drive routes, channel messages and the file-text routes (mocked Graph, no network)."""

from contextlib import contextmanager
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from outnote import C_SITES, GraphError

from src import config, file_text, outnote_client, teams_files
from src.app import app
from tests.test_file_text import docx_bytes

H = {config.REFRESH_TOKEN_HEADER: "old-frt"}
TEAM = "11111111-2222-3333-4444-555555555555"
CHANNEL = "19:abcDEF123_-@thread.tacv2"
DRIVE = "b!DRIVE-1_x"
DL = "https://school.sharepoint.com/dl/abc"


class Broker:
    refresh_token = "old-frt"

    def __call__(self, client_id, scope=None):
        self.refresh_token = "rotated-frt"
        return "bearer"


class Note:
    def __init__(self, broker):
        self.broker = broker
        self.calls = []
        self.item = {"id": "IT1", "name": "Plan.docx", "size": 100, "file": {"mimeType": "application/octet-stream"}, "@microsoft.graph.downloadUrl": DL}

    def get(self, path, params=None, raw=False, client=None):
        self.broker("x")
        path = unquote(path)
        self.calls.append(("get", path, client))
        if path == f"groups/{TEAM}/drive":
            return {"id": DRIVE}
        if path == f"drives/{DRIVE}/root":
            return {"id": "ROOT", "name": "root"}
        if path == f"teams/{TEAM}/channels/{CHANNEL}/filesFolder":
            return {"id": "CH", "name": "Deutsch", "parentReference": {"driveId": DRIVE}}
        if ":/" in path:
            if "Missing" in path:
                raise GraphError(404, "no")
            return {"id": "SUB", "name": path.rsplit("/", 1)[1], "folder": {}}
        if path.startswith("me/drive/items/") or path.startswith("drives/"):
            return dict(self.item)
        raise GraphError(404, "missing " + path)

    def list(self, path, params=None, limit=None, client=None):
        self.broker("x")
        self.calls.append(("list", path, client))
        if path == "me/joinedTeams":
            return [{"id": TEAM, "displayName": "BM23d", "description": "d", "x": 1}]
        if path.endswith("/channels"):
            return [{"id": CHANNEL, "displayName": "Deutsch", "membershipType": "standard", "description": None}]
        if path.endswith("/children"):
            return [{"id": "F1", "name": "a.docx", "file": {}}]
        if path == "me/drive/sharedWithMe":
            return [{"remoteItem": {"id": "R1", "name": "s.xlsx", "size": 5, "file": {}, "webUrl": "https://x", "parentReference": {"driveId": "b!OTHER"}, "shared": {"sharedBy": {"user": {"displayName": "Ann", "email": "a@x.ch"}}, "sharedDateTime": "2026-01-01T00:00:00Z"}}}, {"id": "nodrive"}]
        if path == "me/drive/recent":
            return [{"id": "O1", "name": "mine.docx", "file": {}, "parentReference": {"driveId": "b!ME"}, "lastModifiedBy": {"user": {"displayName": "Me", "email": "me@x.ch", "id": "u"}}}]
        if path.endswith("/messages"):
            return [
                {"id": "100", "messageType": "message", "createdDateTime": "2026-01-01T00:00:00Z", "from": {"user": {"displayName": "A", "id": "u1"}}, "body": {"contentType": "html", "content": "<p>Hi <at>Bob</at></p>"}, "attachments": [{"name": "f.pdf", "contentType": "reference", "contentUrl": "https://s/f.pdf"}], "subject": None},
                {"id": "200", "messageType": "message", "createdDateTime": "2026-02-01T00:00:00Z", "body": {"contentType": "text", "content": "x" * 5000}},
                {"id": "300", "messageType": "systemEventMessage", "createdDateTime": "2026-03-01T00:00:00Z", "body": {"content": ""}},
                {"id": "400", "messageType": "message", "deletedDateTime": "2026-03-01T00:00:00Z", "body": {"content": "gone"}},
            ]
        if path.endswith("/replies"):
            return [{"id": "2", "replyToId": "1", "messageType": "message", "createdDateTime": "2026-01-02T00:00:00Z", "body": {"contentType": "text", "content": "b"}}, {"id": "1x", "replyToId": "1", "messageType": "message", "createdDateTime": "2026-01-01T00:00:00Z", "body": {"contentType": "text", "content": "a"}}]
        return []


class Stream:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        pass

    def iter_bytes(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i : i + size]


class Http:
    def __init__(self):
        self.body = b""
        self.fetched = []

    @contextmanager
    def stream(self, method, url, **kw):
        self.fetched.append((url, kw))
        yield Stream(self.body)


@pytest.fixture
def env(monkeypatch):
    broker = Broker()
    note = Note(broker)
    http = Http()
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (note, broker))
    monkeypatch.setattr(teams_files.entrance, "http_client", lambda: http)
    monkeypatch.setattr(outnote_client.entrance, "http_client", lambda: http)
    return note, http, TestClient(app)


def test_valid_path_rules():
    assert teams_files.valid_path("") == [] and teams_files.valid_path(None) == []
    assert teams_files.valid_path("/Deutsch/Prüfungen/") == ["Deutsch", "Prüfungen"]
    for bad in ["..", "a/../b", "./a", "a/.", "a%2Eb", "a\\b", "a:b", "a#b", "a?b", "a\x01b", "x" * 401, "a.."]:
        with pytest.raises(ValueError):
            teams_files.valid_path(bad)


def test_download_url_allowlist():
    assert teams_files.is_download_url("https://school-my.sharepoint.com/x")
    for bad in ["http://a.sharepoint.com/x", "https://sharepoint.com.evil.test/x", "https://evilsharepoint.com/x", "https://a.sharepoint.com@evil.test/x", "https://a.sharepoint.com:8443/x", "https://onedrive.live.com/x", "https://x.svc.ms/y", None]:
        assert not teams_files.is_download_url(bad)


def test_teams_and_channels_are_cached_and_trimmed(env):
    note, _, client = env
    r = client.get("/api/teams", headers=H)
    assert r.json() == [{"id": TEAM, "displayName": "BM23d", "description": "d"}]
    assert r.headers["cache-control"] == "no-store" and r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    client.get("/api/teams", headers=H)
    assert [c for c in note.calls if c[1] == "me/joinedTeams"] == [("list", "me/joinedTeams", None)]
    assert client.get(f"/api/teams/{TEAM}/channels", headers=H).json()[0]["displayName"] == "Deutsch"


def test_team_library_root_resolves_drive_with_sites_client(env):
    note, _, client = env
    r = client.get(f"/api/teams/{TEAM}/files", headers=H)
    body = r.json()
    assert body["driveId"] == DRIVE and body["folder"] == {"id": "ROOT", "name": "root", "path": ""}
    assert body["items"][0]["parentReference"]["driveId"] == DRIVE
    assert ("get", f"groups/{TEAM}/drive", C_SITES) in note.calls
    client.get(f"/api/teams/{TEAM}/files", headers=H)
    assert len([c for c in note.calls if c[1] == f"groups/{TEAM}/drive"]) == 1


def test_channel_folder_and_subpath(env):
    note, _, client = env
    r = client.get(f"/api/teams/{TEAM}/files", params={"channel_id": CHANNEL, "path": "Prüfungen/2026"}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["driveId"] == DRIVE and body["folder"] == {"id": "SUB", "name": "2026", "path": "Prüfungen/2026"}
    assert any(c[1].startswith(f"drives/{DRIVE}/items/CH:/Pr") for c in note.calls)
    assert client.get(f"/api/teams/{TEAM}/files", params={"channel_id": CHANNEL, "path": "Missing"}, headers=H).status_code == 404


@pytest.mark.parametrize("url", [
    "/api/teams/not-a-team/channels",
    f"/api/teams/{TEAM}/files?channel_id=bad",
    f"/api/teams/{TEAM}/files?path=../x",
    f"/api/teams/{TEAM}/files?path=a%252Fb",
    f"/api/teams/{TEAM}/files?path=a%3Ab",
    f"/api/teams/{TEAM}/channels/{CHANNEL}/messages/12a/replies",
    f"/api/teams/{TEAM}/channels/19:..@thread.tacv2/messages",
    "/api/drives/b!x%2F..%2Fy/items/IT1",
    "/api/drives/..%2F/items/IT1",
    f"/api/drives/{DRIVE}/items/..",
    f"/api/drives/{DRIVE}/items/a..b/children",
])
def test_bad_ids_are_400(env, url):
    note, _, client = env
    r = client.get(url, headers=H)
    assert r.status_code in (400, 404), url
    assert not note.calls


def test_drive_item_and_children_carry_drive_id(env):
    _, _, client = env
    item = client.get(f"/api/drives/{DRIVE}/items/IT1", headers=H).json()
    assert item["parentReference"]["driveId"] == DRIVE and item["id"] == "IT1"
    assert client.get(f"/api/drives/{DRIVE}/items/IT1/children", headers=H).json()[0]["parentReference"]["driveId"] == DRIVE


def test_content_streams_with_secure_headers(env):
    note, http, client = env
    http.body = b"PK\x03\x04data"
    r = client.get(f"/api/drives/{DRIVE}/items/IT1/content", headers=H)
    assert r.status_code == 200 and r.content == http.body
    assert r.headers["content-disposition"].startswith("attachment; filename*=UTF-8''Plan.docx")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert http.fetched[0][0] == DL and http.fetched[0][1]["follow_redirects"] is False


def test_content_refuses_foreign_hosts_folders_and_big_files(env):
    note, http, client = env
    note.item["@microsoft.graph.downloadUrl"] = "https://evil.test/x"
    assert client.get(f"/api/drives/{DRIVE}/items/IT1/content", headers=H).status_code == 502
    assert not http.fetched
    note.item = {"id": "F", "name": "dir", "folder": {}}
    assert client.get(f"/api/drives/{DRIVE}/items/F/content", headers=H).status_code == 404
    note.item = {"id": "B", "name": "big.bin", "size": 101 * 1024 * 1024, "file": {}, "@microsoft.graph.downloadUrl": DL}
    assert client.get(f"/api/drives/{DRIVE}/items/B/content", headers=H).status_code == 413


def test_shared_and_recent_are_flattened(env):
    _, _, client = env
    shared = client.get("/api/files/shared", headers=H).json()
    assert shared == [{"id": "R1", "name": "s.xlsx", "size": 5, "webUrl": "https://x", "lastModifiedDateTime": None, "parentReference": {"driveId": "b!OTHER"}, "file": {}, "shared": {"sharedBy": {"displayName": "Ann", "email": "a@x.ch"}, "sharedDateTime": "2026-01-01T00:00:00Z"}}]
    recent = client.get("/api/files/recent", headers=H).json()
    assert recent[0]["parentReference"]["driveId"] == "b!ME" and recent[0]["lastModifiedBy"]["user"]["email"] == "me@x.ch"


def test_channel_messages_are_normalized(env):
    _, _, client = env
    r = client.get(f"/api/teams/{TEAM}/channels/{CHANNEL}/messages", headers=H)
    assert r.status_code == 200, r.text
    msgs = r.json()
    assert [m["id"] for m in msgs] == ["200", "100"]  # newest first; system and deleted dropped
    assert len(msgs[0]["text"]) == 4000
    assert msgs[1]["text"] == "Hi Bob" and msgs[1]["from"] == {"displayName": "A", "id": "u1"}
    assert msgs[1]["attachments"] == [{"name": "f.pdf", "contentType": "reference", "webUrl": "https://s/f.pdf"}]
    assert msgs[1]["replyCount"] is None and msgs[1]["messageType"] == "message"
    replies = client.get(f"/api/teams/{TEAM}/channels/{CHANNEL}/messages/100/replies", headers=H).json()
    assert [m["id"] for m in replies] == ["1x", "2"] and replies[0]["replyToId"] == "1"


def test_text_route_reads_a_drive_docx(env):
    note, http, client = env
    http.body = docx_bytes()
    r = client.get(f"/api/drives/{DRIVE}/items/IT1/text", params={"max_chars": 20}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "document" and body["name"] == "Plan.docx" and len(body["text"]) == 20 and body["nextOffset"] == 20
    assert r.headers["cache-control"] == "no-store"
    own = client.get("/api/files/IT1/text", headers=H)
    assert own.status_code == 200 and ("get", "me/drive/items/IT1", None) in note.calls


def test_text_route_415_413_and_bad_params(env):
    note, http, client = env
    note.item = {"id": "I", "name": "pic.png", "size": 5, "file": {}, "@microsoft.graph.downloadUrl": DL}
    r = client.get(f"/api/drives/{DRIVE}/items/I/text", headers=H)
    assert r.status_code == 415 and r.json() == {"detail": "This file type cannot be read as text."}
    note.item = {"id": "I", "name": "big.docx", "size": 26 * 1024 * 1024, "file": {}, "@microsoft.graph.downloadUrl": DL}
    assert client.get(f"/api/drives/{DRIVE}/items/I/text", headers=H).status_code == 413
    assert client.get(f"/api/drives/{DRIVE}/items/I/text?max_chars=100001", headers=H).status_code == 422
    assert client.get(f"/api/drives/{DRIVE}/items/I/text?max_rows=2001", headers=H).status_code == 422


def test_text_route_converts_legacy_through_pdf(env, monkeypatch):
    note, http, client = env
    from tests.test_file_text import pdf_bytes
    import io
    from src import file_pdf

    note.item = {"id": "I", "name": "old.doc", "size": 5, "file": {}}
    monkeypatch.setattr(file_pdf, "drive_item_pdf", lambda n, item_id, drive_id=None: io.BytesIO(pdf_bytes(1)))
    r = client.get(f"/api/drives/{DRIVE}/items/I/text", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "pdf" and "Page text 1" in body["text"] and body["name"] == "old.doc" and any("PDF" in n for n in body["notes"])


def test_convert_text_raw_bytes(env):
    _, _, client = env
    r = client.post("/api/convert/text?name=Plan.docx", content=docx_bytes(), headers=H)
    assert r.status_code == 200 and r.json()["text"].startswith("# Title one")
    assert r.headers["cache-control"] == "no-store"
    assert client.post("/api/convert/text?name=x.exe", content=b"x", headers=H).status_code == 415
    assert client.post("/api/convert/text?name=x.txt", content=b"", headers=H).status_code == 400
    assert client.post("/api/convert/text?name=x.docx", content=b"junk", headers=H).status_code == 422


def test_convert_text_body_cap(env, monkeypatch):
    _, _, client = env
    import src.app as app_module

    monkeypatch.setattr(app_module, "MAX_TEXT_SOURCE_BYTES", 100)
    assert client.post("/api/convert/text?name=x.txt", content=b"a" * 101, headers=H).status_code == 413
    assert client.post("/api/convert/text?name=x.txt", content=b"a" * 100, headers=H).json()["text"] == "a" * 100
