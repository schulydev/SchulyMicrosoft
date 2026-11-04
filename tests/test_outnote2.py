"""OutNote / Entrance 2.0: downloads, throttling, `_native`, client reuse and mail fields. A real server on localhost stands in for Microsoft; no outside network, no real token."""

import base64
import http.server
import io
import json
import threading

import entrance
import pytest
from entrance import _foci
from fastapi.testclient import TestClient
from outnote import GraphError, OutNote
from outnote._native import message_from_native

from tests.services import AccountRunner, FileFetchError, ResourceTooLarge, Upload, _BrokerCache, chat_send, config, http_clients, onenote, outnote_client, profile, teams_files
from src.api.app import app
from src.domain.errors.service_error import ServiceError

from tests.conftest import REAL_FETCH

H = {config.REFRESH_TOKEN_HEADER: "frt-1"}
CHUNK = 64 * 1024
ANYWHERE = lambda url: True  # noqa: E731


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, status=200, body=b"", **headers):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k.replace("_", "-"), v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self):
        srv = self.server
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        srv.seen.append({"method": self.command, "path": self.path, "headers": self.headers, "body": body})
        if self.path.startswith("/slow"):
            # Half the file, then nothing until the client proves it has that half.
            self.send_response(200)
            self.send_header("Content-Length", str(2 * CHUNK))
            self.end_headers()
            self.wfile.write(b"a" * CHUNK)
            self.wfile.flush()
            srv.got_first.wait(10)
            srv.sent_rest_after_first = srv.got_first.is_set()
            self.wfile.write(b"b" * CHUNK)
        elif self.path.startswith("/big"):
            self._reply(200, b"x" * (3 * CHUNK))
        elif self.path.startswith("/cookie"):
            self._reply(200, b"ok", Set_Cookie="FedAuth=account-a; Path=/")
        elif self.path.startswith("/redirect"):
            self._reply(302, Location=f"http://127.0.0.1:{srv.server_address[1]}/landed")
        elif self.path.startswith("/throttled"):
            self._reply(429, b'{"error":{"message":"slow down"}}', Retry_After="120")
        elif self.path.startswith("/me-429"):
            self._reply(429, b"", Retry_After="21")
        elif self.command == "PUT":
            self._reply(201, b'{"id":"BIG"}')
        else:
            self._reply(200, json.dumps({"data": []}).encode())

    do_GET = do_POST = do_PUT = do_DELETE = _handle

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    srv.seen = []
    srv.got_first = threading.Event()
    srv.sent_rest_after_first = False
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.got_first.set()
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def fresh_download_client(monkeypatch):
    monkeypatch.setattr(http_clients, "_download_client", None)
    yield
    client = http_clients._download_client
    if client is not None:
        client.close()


# --- entrance's client ---------------------------------------------------------------------------


def test_entrance_client_has_no_stream_and_no_get_so_nothing_here_may_use_them():
    client = entrance.http_client()
    assert not hasattr(client, "stream") and not hasattr(client, "get") and not hasattr(client, "put") and not hasattr(client, "delete")


def test_entrance_http_error_is_a_tuple_and_profile_catches_it_for_real(monkeypatch, server):
    assert isinstance(entrance.HTTPError, tuple)
    token = "a." + base64.urlsafe_b64encode(json.dumps({"oid": "oid-1", "name": "Alex"}).encode()).decode().rstrip("=") + ".c"
    broker = lambda *a: token
    monkeypatch.setattr(profile, "ME_URL", "http://127.0.0.1:9/nothing-listens-here")
    assert REAL_FETCH(None, broker)[0]["id"] == "oid-1"
    monkeypatch.setattr(profile, "ME_URL", server.url + "/me-429")
    me, ttl = REAL_FETCH(None, broker)
    assert me["id"] == "oid-1" and ttl == profile.CLAIMS_TTL


def test_an_upload_session_goes_through_the_real_client(server):
    size = chat_send.SIMPLE_UPLOAD_MAX + 7

    class N:
        def post(self, path, body=None):
            return {"uploadUrl": server.url + "/session"}

    assert chat_send.upload_file(N(), Upload("big.mp4", io.BytesIO(b"x" * size), size, "video/mp4")) == {"id": "BIG"}
    puts = [s for s in server.seen if s["method"] == "PUT"]
    assert [len(p["body"]) for p in puts] == [chat_send.UPLOAD_CHUNK, size - chat_send.UPLOAD_CHUNK]
    assert puts[1]["headers"]["Content-Range"] == f"bytes {chat_send.UPLOAD_CHUNK}-{size - 1}/{size}"
    assert not any(p["headers"].get("Authorization") for p in puts)


def test_a_failed_upload_deletes_the_session_through_the_real_client(server, monkeypatch):
    size = chat_send.SIMPLE_UPLOAD_MAX + 7

    class N:
        def post(self, path, body=None):
            return {"uploadUrl": server.url + "/session"}

    real = entrance.http_client().request

    def failing(method, url, **kw):
        if method == "PUT":
            raise RuntimeError("boom")
        return real(method, url, **kw)

    client = type("C", (), {"request": staticmethod(failing)})()
    monkeypatch.setattr(chat_send, "http_client", lambda: client)
    with pytest.raises(RuntimeError):
        chat_send.upload_file(N(), Upload("big.mp4", io.BytesIO(b"x" * size), size, "video/mp4"))
    assert [s["method"] for s in server.seen] == ["DELETE"]


# --- downloads -----------------------------------------------------------------------------------


def test_a_download_streams_chunk_by_chunk_instead_of_loading_the_file(server, fresh_download_client):
    stream = http_clients.open_download(server.url + "/slow", 10 * CHUNK, ANYWHERE, "video/mp4", "a.mp4").chunks
    first = next(stream)  # the server holds the rest back until this arrives: a buffering client would hang here
    assert first and set(first) == {ord("a")} and len(first) <= CHUNK
    server.got_first.set()
    rest = b"".join(stream)
    assert server.sent_rest_after_first and len(first) + len(rest) == 2 * CHUNK


def test_a_download_past_its_cap_is_refused_before_any_byte(server, fresh_download_client):
    with pytest.raises(ServiceError) as big:
        http_clients.open_download(server.url + "/big", CHUNK, ANYWHERE, "video/mp4", "a.mp4")
    assert big.value.status == 413


def test_fetch_bytes_refuses_past_its_cap_and_does_not_follow_redirects(server, fresh_download_client, monkeypatch):
    monkeypatch.setattr(teams_files, "is_download_url", lambda url: True)
    with pytest.raises(FileFetchError) as big:
        teams_files.fetch_bytes(server.url + "/big", CHUNK)
    assert big.value.status == 413
    with pytest.raises(FileFetchError) as moved:
        teams_files.fetch_bytes(server.url + "/redirect", CHUNK)
    assert moved.value.status == 502
    assert not any(s["path"] == "/landed" for s in server.seen)


def test_a_download_redirect_must_pass_the_host_check_again(server, fresh_download_client):
    with pytest.raises(ServiceError) as refused:
        http_clients.open_download(server.url + "/redirect", CHUNK, lambda url: "/landed" not in url, "video/mp4", "a.mp4")
    assert refused.value.status == 502
    assert not any(s["path"] == "/landed" for s in server.seen)


def test_the_shared_download_client_keeps_no_cookies_between_accounts(server, fresh_download_client):
    list(http_clients.open_download(server.url + "/cookie", CHUNK, ANYWHERE, "video/mp4", "a.mp4").chunks)
    list(http_clients.open_download(server.url + "/cookie", CHUNK, ANYWHERE, "video/mp4", "a.mp4").chunks)
    assert not any(s["headers"].get("Cookie") for s in server.seen)
    assert http_clients.download_client() is http_clients.download_client()


def test_the_onenote_resource_stays_capped_with_the_real_stream(server, fresh_download_client, monkeypatch):
    monkeypatch.setattr(onenote, "GRAPH", server.url + "/big")
    with pytest.raises(ResourceTooLarge):
        onenote.resource(lambda client: "bearer", "1-res", CHUNK)
    assert server.seen[0]["headers"]["Authorization"] == "Bearer bearer"


# --- throttling ----------------------------------------------------------------------------------


class Rotating:
    def __init__(self, token="frt-1"):
        self.refresh_token = token


def route_with(monkeypatch, note, broker):
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (note, broker))
    return TestClient(app)


class Throttled:
    def __init__(self, retry_after):
        self.retry_after = retry_after

    def mark_chat_read(self, chat_id):
        raise GraphError(429, "throttled", retry_after=self.retry_after)


@pytest.mark.parametrize("retry_after,header", [(12.5, "13"), (120, "120"), (0.2, "1"), (None, "30")])
def test_throttling_answers_429_with_retry_after(monkeypatch, retry_after, header):
    r = route_with(monkeypatch, Throttled(retry_after), Rotating()).post("/api/chats/c1/read", headers=H)
    assert r.status_code == 429 and r.headers["Retry-After"] == header
    assert config.REFRESH_TOKEN_HEADER not in r.headers


def test_a_429_keeps_a_token_that_rotated_first(monkeypatch):
    r = route_with(monkeypatch, Throttled(5), Rotating("frt-2")).post("/api/chats/c1/read", headers=H)
    assert r.status_code == 429 and r.headers[config.REFRESH_TOKEN_HEADER] == "frt-2"


def test_other_graph_errors_stay_502(monkeypatch):
    class Failing:
        def mark_chat_read(self, chat_id):
            raise GraphError(503, "down", retry_after=2)

    r = route_with(monkeypatch, Failing(), Rotating()).post("/api/chats/c1/read", headers=H)
    assert r.status_code == 502 and "Retry-After" not in r.headers


def test_real_outnote_gives_up_on_a_long_wait_and_the_route_says_429(monkeypatch, server):
    note = OutNote("static-token", base=server.url + "/throttled")
    r = route_with(monkeypatch, note, Rotating()).get("/api/calendar", headers=H)
    assert r.status_code == 429 and r.headers["Retry-After"] == "120"
    assert len(server.seen) == 1  # 120 s is past OutNote's budget, so it did not sit and wait


def test_a_refused_content_redirect_is_not_read_as_no_link():
    class Note:
        def get(self, path):
            return {}

        def redirect(self, path):
            raise GraphError(429, "throttled", retry_after=9)

    with pytest.raises(GraphError) as ex:
        teams_files.download_url(Note(), "me/drive/items/I", {})
    assert ex.value.status == 429


# --- what Graph can't serve (OutNote 2.0.1's cases, on our own helper) ------------------------------
DRIVE_URL = "/api/drives/d1/items/i1"
CHAT_URL = "/api/chats/c1/messages/1/files/a1"
CONTENT_URL = "https://x.sharepoint.com/f.docx"


class ServeNote:
    """A file with no link anywhere, whose `/content` answers `status`; or a folder."""

    def __init__(self, status=None, folder=False):
        self.status, self.folder = status, folder
        self.select = []

    def chat_message(self, chat_id, message_id):
        return self.get(f"chats/{chat_id}/messages/{message_id}")

    def list(self, path, params=None, limit=None, retry=True):
        return [{"id": "1", "attachments": [{"id": "a1", "name": "f.docx", "contentType": "reference", "contentUrl": CONTENT_URL}]}]

    def get(self, path, params=None, retry=True):
        self.select.append((params or {}).get("$select") or path.partition("$select=")[2] or "the whole item")
        if "/messages/" in path:
            return {"attachments": [{"id": "a1", "name": "f.docx", "contentType": "reference", "contentUrl": CONTENT_URL}]}
        if self.folder:
            return {"id": "i1", "name": "dir", "folder": {}}
        return {"id": "i1", "name": "f.docx", "size": 1, "file": {}}

    def redirect(self, path):
        raise GraphError(self.status, "refused")


@pytest.mark.parametrize("url", [DRIVE_URL + "/content", DRIVE_URL + "/text", CHAT_URL])
@pytest.mark.parametrize("status,expected", [(403, 403), (404, 404), (406, 415), (415, 415), (429, 429), (500, 502)])
def test_all_three_download_routes_give_graphs_refusal_its_own_status(monkeypatch, url, status, expected):
    r = route_with(monkeypatch, ServeNote(status), Rotating()).get(url, headers=H)
    assert r.status_code == expected


@pytest.mark.parametrize("url", [DRIVE_URL + "/content", DRIVE_URL + "/text", CHAT_URL])
def test_a_folder_says_it_is_a_folder_on_all_three_download_routes(monkeypatch, url):
    note = ServeNote(folder=True)
    r = route_with(monkeypatch, note, Rotating()).get(url, headers=H)
    assert r.status_code == 404 and "folder" in r.json()["detail"]
    assert any("folder" in s or s == "the whole item" for s in note.select)


def test_the_fallback_link_still_gets_the_host_check(monkeypatch):
    class Elsewhere(ServeNote):
        def redirect(self, path):
            return "https://evil.example/f.docx"

    client = route_with(monkeypatch, Elsewhere(), Rotating())
    assert client.get(DRIVE_URL + "/content", headers=H).status_code == 502
    assert client.get(DRIVE_URL + "/text", headers=H).status_code == 502


def test_a_throttled_photo_passes_graphs_wait_on(monkeypatch):
    class Note:
        def get(self, path, raw=False):
            raise GraphError(429, "throttled", retry_after=44)

    broker = Rotating()
    r = route_with(monkeypatch, Note(), broker).get("/api/people/photo", headers=H, params={"email": "a@school.ch"})
    assert r.status_code == 429 and r.headers["Retry-After"] == "44"


# --- native --------------------------------------------------------------------------------------


def test_native_copies_never_reach_a_response(monkeypatch):
    raw = {"id": "1", "from": "https://x/contacts/8:orgid:RAW-OID", "messagetype": "Text", "content": "hi", "conversationid": "19:raw@thread.v2", "originalarrivaltime": "2026-01-01T00:00:00.000Z"}

    class Note:
        def list(self, path, params=None, limit=None):
            return [message_from_native(raw, "c1"), {"id": "2", "nested": [{"_native": {"secret": "RAW-OID"}, "keep": 1}]}]

        def batch(self, requests):
            return []

    r = route_with(monkeypatch, Note(), Rotating()).get("/api/chats/c1/messages", headers=H)
    assert r.status_code == 200 and "_native" not in r.text
    assert r.json()[1]["nested"] == [{"keep": 1}]


def test_strip_native_walks_tuples_and_leaves_other_values_alone():
    item, data = {"_native": 1, "a": 2}, b"bytes"
    assert AccountRunner.strip_native((item, data)) == ({"a": 2}, b"bytes")
    assert AccountRunner.strip_native(None) is None


# --- client reuse --------------------------------------------------------------------------------


def test_one_outnote_client_per_account_kept_across_rotation(monkeypatch):
    monkeypatch.setattr(outnote_client, "_brokers", _BrokerCache())
    rotated = iter(["frt-a2"])
    monkeypatch.setattr(_foci, "_post_token", lambda url, data: {"access_token": "at", "refresh_token": next(rotated, data["refresh_token"]), "expires_in": 3600})
    note_a, broker_a = outnote_client.build_client("frt-a1")
    assert outnote_client.build_client("frt-a1")[0] is note_a
    note_b, broker_b = outnote_client.build_client("frt-b1")
    assert note_b is not note_a and broker_b is not broker_a and note_b._ids is not note_a._ids
    broker_a("client")  # rotates
    assert broker_a.refresh_token == "frt-a2"
    assert outnote_client.build_client("frt-a2") == (note_a, broker_a)
    assert note_a._tp is broker_a and note_b._tp is broker_b


# --- mail list -----------------------------------------------------------------------------------


def test_the_mail_list_keeps_recipients_and_no_body_through_real_outnote(monkeypatch):
    note = OutNote("static-token")
    seen = {}
    monkeypatch.setattr(note, "list", lambda path, params, limit=None: seen.update(path=path, **params) or [])
    r = route_with(monkeypatch, note, Rotating()).get("/api/mail", headers=H)
    assert r.status_code == 200
    fields = seen["$select"].split(",")
    assert {"toRecipients", "from", "bodyPreview", "flag", "isRead", "hasAttachments", "receivedDateTime", "subject"} <= set(fields)
    assert "body" not in fields


# --- batch ---------------------------------------------------------------------------------------


GROUPS = ["3f2a9c10-1111-4222-8333-94445555666" + str(i) for i in range(3)]
BOOK = {"id": "1-b", "displayName": "Book"}


class BatchNote:
    def __init__(self, answers=None, error=None):
        self.answers, self.error = answers, error
        self.lists = []

    def batch(self, requests, client=None):
        assert client == onenote.C_ONENOTE and all("$select=" in r for r in requests)
        if self.error:
            raise self.error
        return self.answers

    def list(self, path, params=None, limit=None, client=None):
        self.lists.append(path)
        return [BOOK]


JOINED = [{"id": g, "name": g} for g in GROUPS]


def test_team_notebooks_come_from_one_batch():
    note = BatchNote([{"value": [BOOK]}, GraphError(403, "no"), {"value": []}])
    assert onenote._team_pages(note, JOINED) == [[BOOK], [], []]


def test_a_team_with_more_pages_or_no_answer_is_asked_on_its_own():
    note = BatchNote([{"value": [BOOK], "@odata.nextLink": "https://next"}, None, {"value": []}])
    assert onenote._team_pages(note, JOINED) == [None, None, []]


@pytest.mark.parametrize("error", [GraphError(400, "batch refused"), OSError("down")])
def test_a_failed_batch_falls_back_to_one_list_per_team(error):
    assert onenote._team_pages(BatchNote(error=error), JOINED) == [None, None, None]


def test_a_throttled_batch_is_raised_instead_of_waiting_again_per_team():
    with pytest.raises(GraphError):
        onenote._team_pages(BatchNote(error=GraphError(429, "throttled", retry_after=9)), JOINED)
