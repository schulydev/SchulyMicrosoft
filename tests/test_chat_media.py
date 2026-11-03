"""Chat images and videos: Range, content types, redirects, how few Graph calls a chat's files cost, the throttle log, and forwarded messages. A real local server stands in for SharePoint; no outside network, no real token."""

import http.server
import json
import logging
import re
import threading

import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src.api.app import app
from src.application.services.chat_html_sanitizer import ChatHtmlSanitizer
from src.application.services.content_names import ContentNames
from src.domain.files.byte_range import ByteRange
from tests.services import config, http_clients, outnote_client, teams_files

H = {config.REFRESH_TOKEN_HEADER: "frt-1"}
VIDEO = bytes(range(256)) * 400
SHARE = "https://school.sharepoint.com/personal/a/Documents/clip.mp4"
CHAT = "19:media@thread.v2"
FILE_URL = f"/api/chats/{CHAT}/messages/171/files/a1"
RAW_ID_PARTS = ("media@thread", "171", "a1", "school.sharepoint", "u!")


class Sharepoint(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        srv = self.server
        srv.seen.append({"path": self.path, "range": self.headers.get("Range"), "encoding": self.headers.get("Accept-Encoding"), "auth": self.headers.get("Authorization")})
        if self.path.startswith("/moved"):
            return self._reply(302, Location="/video")
        if self.path.startswith("/expired"):
            return self._reply(403)
        if self.path.startswith("/busy"):
            return self._reply(429, Retry_After="33")
        if self.path.startswith("/broken"):
            return self._reply(500)
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
        if not match:
            return self._reply(200, VIDEO)
        start = int(match[1])
        if start >= len(VIDEO):
            return self._reply(416, Content_Range=f"bytes */{len(VIDEO)}")
        end = min(int(match[2]) if match[2] else len(VIDEO) - 1, len(VIDEO) - 1)
        self._reply(206, VIDEO[start : end + 1], Content_Range=f"bytes {start}-{end}/{len(VIDEO)}")

    def _reply(self, status, body=b"", **headers):
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def sharepoint(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Sharepoint)
    srv.daemon_threads = True
    srv.seen = []
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(http_clients, "_download_client", None)
    monkeypatch.setattr(teams_files, "is_download_url", lambda url: url.startswith(srv.url))
    yield srv
    client = http_clients._download_client
    if client is not None:
        client.close()
    srv.shutdown()
    srv.server_close()


class Broker:
    refresh_token = "frt-1"


class Note:
    """A chat whose one message holds one video. Counts every Graph call by route."""

    def __init__(self, link=None, name="clip.mp4", mime="application/octet-stream"):
        self.calls = []
        self.link, self.name, self.mime = link, name, mime
        self.message_status = None
        self.listable = True
        self.teams_status = None
        self.teams_has_file = True

    def attachment(self):
        return {"id": "a1", "name": self.name, "contentType": "reference", "contentUrl": SHARE}

    def get(self, path, params=None, raw=False, retry=True):
        self.calls.append(path)
        if "/messages/" in path:
            if self.message_status:
                raise GraphError(self.message_status, "refused", retry_after=62)
            return {"id": "171", "attachments": [self.attachment()]}
        if path.startswith("shares/"):
            return {"id": "ITEM", "name": self.name, "size": len(VIDEO), "file": {"mimeType": self.mime}, "parentReference": {"driveId": "b!DRIVE"}, "@microsoft.graph.downloadUrl": self.link}
        if "/thumbnails/" in path:
            return b"\xff\xd8\xffthumbnail"
        raise GraphError(404, "missing")

    def list(self, path, params=None, limit=None, retry=True):
        self.calls.append(path)
        return [{"id": "171", "attachments": [self.attachment()]}] if self.listable else []

    def batch(self, requests):
        self.calls.append("$batch")
        return [{"id": "ITEM", "size": len(VIDEO), "file": {"mimeType": self.mime}, "parentReference": {"driveId": "b!DRIVE"}} for _ in requests]

    def chat_message(self, chat_id, message_id):
        self.calls.append("chat_message")
        if self.teams_status:
            raise GraphError(self.teams_status, "refused", retry_after=62)
        return {"id": message_id, "attachments": [self.attachment()] if self.teams_has_file else []}

    def single_reads(self):
        return [c for c in self.calls if "/messages/" in c and not c.endswith("/messages")]


@pytest.fixture
def chat(monkeypatch):
    def build(note):
        broker = Broker()
        monkeypatch.setattr(outnote_client, "build_client", lambda frt: (note, broker))
        return TestClient(app)

    return build


# --- Range and what a player needs ----------------------------------------------------------------


def test_a_range_request_answers_206_with_only_those_bytes(chat, sharepoint):
    client = chat(Note(sharepoint.url + "/video"))
    r = client.get(FILE_URL, headers={**H, "Range": "bytes=1000-1999"})
    assert r.status_code == 206 and r.content == VIDEO[1000:2000]
    assert r.headers["content-range"] == f"bytes 1000-1999/{len(VIDEO)}"
    assert r.headers["content-length"] == "1000" and r.headers["accept-ranges"] == "bytes"
    assert sharepoint.seen[-1]["range"] == "bytes=1000-1999"


def test_without_a_range_the_whole_file_comes_with_its_length_and_says_it_can_seek(chat, sharepoint):
    r = chat(Note(sharepoint.url + "/video")).get(FILE_URL, headers=H)
    assert r.status_code == 200 and r.content == VIDEO
    assert r.headers["content-length"] == str(len(VIDEO)) and r.headers["accept-ranges"] == "bytes"
    assert sharepoint.seen[-1]["range"] is None


def test_a_range_past_the_end_stays_416(chat, sharepoint):
    r = chat(Note(sharepoint.url + "/video")).get(FILE_URL, headers={**H, "Range": f"bytes={len(VIDEO)}-"})
    assert r.status_code == 416 and r.headers["content-range"] == f"bytes */{len(VIDEO)}"


@pytest.mark.parametrize("value", ["bytes=-500", "bytes=5-1", "bytes=0-1,5-9", "items=0-1", "bytes=0-1\r\nX: y", "x" * 200])
def test_any_other_range_is_ignored_and_never_passed_on(value):
    assert ByteRange.parse(value) is None


def test_the_bytes_are_asked_for_uncompressed_and_with_no_token(chat, sharepoint):
    chat(Note(sharepoint.url + "/video")).get(FILE_URL, headers=H)
    assert sharepoint.seen[-1]["encoding"] == "identity" and sharepoint.seen[-1]["auth"] is None


def test_seeking_costs_no_more_graph_calls(chat, sharepoint):
    note = Note(sharepoint.url + "/video")
    client = chat(note)
    client.get(FILE_URL, headers={**H, "Range": "bytes=0-99"})
    before = list(note.calls)
    for start in (1000, 5000, 50000):
        assert client.get(FILE_URL, headers={**H, "Range": f"bytes={start}-{start + 9}"}).status_code == 206
    assert note.calls == before


def test_a_file_response_still_cannot_run(chat, sharepoint):
    r = chat(Note(sharepoint.url + "/video", name="clip.html", mime="text/html")).get(FILE_URL, headers=H)
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"].startswith("attachment")


# --- content types --------------------------------------------------------------------------------


@pytest.mark.parametrize("name,mime,expected", [
    ("clip.mp4", "application/octet-stream", "video/mp4"),
    ("clip.mp4", None, "video/mp4"),
    ("clip.MOV", "", "video/quicktime"),
    ("a.jpg", "application/octet-stream", "image/jpeg"),
    ("clip.mp4", "video/mp4", "video/mp4"),
    ("clip.bin", "application/octet-stream", "application/octet-stream"),
    ("page.mp4", "text/html", "application/octet-stream"),
    ("a.svg", "application/octet-stream", "application/octet-stream"),
    ("a.html", None, "application/octet-stream"),
])
def test_the_type_served(name, mime, expected):
    assert ContentNames.media_type(name, mime) == expected


def test_an_mp4_graph_calls_generic_is_served_as_video(chat, sharepoint):
    r = chat(Note(sharepoint.url + "/video")).get(FILE_URL, headers=H)
    assert r.headers["content-type"].startswith("video/mp4")


# --- redirects, refusals and hosts -----------------------------------------------------------------


def test_a_download_link_that_redirects_is_followed(chat, sharepoint):
    r = chat(Note(sharepoint.url + "/moved")).get(FILE_URL, headers=H)
    assert r.status_code == 200 and r.content == VIDEO and [s["path"] for s in sharepoint.seen] == ["/moved", "/video"]


def test_a_redirect_to_another_host_is_refused(chat, sharepoint, monkeypatch):
    monkeypatch.setattr(teams_files, "is_download_url", lambda url: "/moved" in url)
    r = chat(Note(sharepoint.url + "/moved")).get(FILE_URL, headers=H)
    assert r.status_code == 502 and [s["path"] for s in sharepoint.seen] == ["/moved"]


def test_a_refusal_is_a_status_and_not_a_broken_200(chat, sharepoint):
    assert chat(Note(sharepoint.url + "/broken")).get(FILE_URL, headers=H).status_code == 502


def test_a_throttled_download_passes_its_wait_on(chat, sharepoint):
    r = chat(Note(sharepoint.url + "/busy")).get(FILE_URL, headers=H)
    assert r.status_code == 429 and r.headers["retry-after"] == "33"


def test_an_expired_link_is_replaced_once(chat, sharepoint):
    note = Note(sharepoint.url + "/expired")
    client = chat(note)
    client.get(FILE_URL, headers=H)  # refused twice: the kept link is dropped
    note.link = sharepoint.url + "/video"
    assert client.get(FILE_URL, headers=H).status_code == 200


@pytest.mark.parametrize("url,ok", [
    ("https://school.sharepoint.com/x", True),
    ("https://public.dm.files.1drv.com/x", True),
    ("https://evil.example/x", False),
    ("https://files.1drv.com.evil.example/x", False),
    ("https://sharepoint.com.evil.example/x", False),
    ("http://school.sharepoint.com/x", False),
    ("https://u:p@school.sharepoint.com/x", False),
    ("https://school.sharepoint.com:8443/x", False),
])
def test_the_download_host_check(url, ok):
    assert teams_files.is_download_url(url) is ok


# --- how few Graph calls a chat's files cost ------------------------------------------------------


def test_files_listed_with_their_message_never_read_the_message_again(chat, sharepoint):
    note = Note(sharepoint.url + "/video")
    client = chat(note)
    assert client.get(f"/api/chats/{CHAT}/messages", headers=H).status_code == 200
    note.message_status = note.teams_status = 429  # as measured on a real account: this read is what Graph refuses
    assert client.get(FILE_URL + "/thumbnail", headers=H).status_code == 200
    assert client.get(FILE_URL, headers=H).status_code == 200
    assert note.single_reads() == [] and "chat_message" not in note.calls


def test_thumbnail_after_the_list_needs_only_the_thumbnail_call(chat, sharepoint):
    note = Note(sharepoint.url + "/video")
    client = chat(note)
    client.get(f"/api/chats/{CHAT}/messages", headers=H)
    note.calls.clear()
    assert client.get(FILE_URL + "/thumbnail", headers=H).status_code == 200
    assert len(note.calls) == 1 and "/thumbnails/" in note.calls[0]


def test_an_unremembered_file_is_read_through_chat_message_once(chat, sharepoint):
    note = Note(sharepoint.url + "/video")
    client = chat(note)
    assert client.get(FILE_URL + "/thumbnail", headers=H).status_code == 200
    assert client.get(FILE_URL, headers=H).status_code == 200
    assert note.calls.count("chat_message") == 1 and note.single_reads() == []


def test_a_throttled_chat_message_falls_back_to_the_list(chat, sharepoint, caplog):
    note = Note(sharepoint.url + "/video")
    note.teams_status = 429
    with caplog.at_level(logging.WARNING, logger="schuly.microsoft"):
        assert chat(note).get(FILE_URL, headers=H).status_code == 200
    assert "asking the list" in caplog.text and "media@thread" not in caplog.text


def test_a_chat_message_without_the_file_falls_back_to_the_list(chat, sharepoint):
    note = Note(sharepoint.url + "/video")
    note.teams_has_file = False
    assert chat(note).get(FILE_URL, headers=H).status_code == 200
    assert f"me/chats/{CHAT}/messages" in note.calls


def test_a_file_nothing_knows_is_a_404(chat, sharepoint):
    note = Note(sharepoint.url + "/video")
    note.teams_has_file = False
    note.listable = False
    assert chat(note).get(FILE_URL, headers=H).status_code == 404


def test_a_real_refusal_of_chat_message_keeps_its_status(chat, sharepoint):
    note = Note(sharepoint.url + "/video")
    note.teams_status = 404
    assert chat(note).get(FILE_URL, headers=H).status_code == 404


def test_a_failed_file_lookup_on_the_list_is_not_asked_again_each_refresh(chat):
    class Throttled(Note):
        def batch(self, requests):
            self.calls.append("$batch")
            raise GraphError(429, "throttled", retry_after=60)

    note = Throttled()
    client = chat(note)
    for _ in range(3):
        client.get(f"/api/chats/{CHAT}/messages", headers=H)
    assert note.calls.count("$batch") == 1


# --- the throttle's real wait and the log line ------------------------------------------------------


def test_graphs_wait_comes_through_and_the_log_names_the_call_with_nothing_of_the_user(chat, sharepoint, caplog):
    class Refused(Note):
        def get(self, path, params=None, raw=False, retry=True):
            self.calls.append(path)
            raise GraphError(429, "refused", retry_after=62)

    note = Refused(sharepoint.url + "/video")
    with caplog.at_level(logging.WARNING, logger="schuly.microsoft"):
        r = chat(note).get(FILE_URL, headers=H)
    assert r.status_code == 429 and r.headers["retry-after"] == "62"
    lines = [rec.getMessage() for rec in caplog.records if "throttled" in rec.getMessage()]
    assert lines == ["Graph throttled shares/*/driveItem (Retry-After 62)"]
    for part in RAW_ID_PARTS + ("frt-1",):
        assert part not in lines[0]


def test_the_log_masks_everything_but_graph_words():
    from src.infrastructure.microsoft.graph_call_trail import GraphCallTrail

    assert GraphCallTrail.mask("shares/u!abc/driveItem?$select=name") == "shares/*/driveItem"
    assert GraphCallTrail.mask("drives/b!x/items/01A/thumbnails/0/medium/content") == "drives/*/items/*/thumbnails/*/medium/content"
    assert GraphCallTrail.mask("users/kid@school.ch/photos/64x64/$value") == "users/*/photos/*/$value"


# --- forwarded messages and replies ---------------------------------------------------------------


def forwarded(content):
    return {"id": "m1", "body": {"contentType": "html", "content": '<attachment id="f1"></attachment>'}, "attachments": [{"id": "f1", "contentType": "forwardedMessageReference", "name": None, "contentUrl": None, "content": content}]}


def test_a_forward_becomes_a_quote_with_its_sender_time_and_content():
    content = json.dumps({"originalSender": {"user": {"id": "RAW-USER", "displayName": "Kylian B."}}, "originalSentDateTime": "2026-11-02T10:00:00Z", "originalMessageContent": "<p>hello</p>", "originalMessageId": "RAW-MSG"})
    [quote] = ChatHtmlSanitizer.quotes(forwarded(content))
    assert quote == {"kind": "forward", "senderName": "Kylian B.", "sentAt": "2026-11-02T10:00:00Z", "content": "<p>hello</p>", "contentType": "html"}
    assert "RAW" not in json.dumps(quote)


def test_a_reply_quote_reads_the_documented_preview():
    message = {"attachments": [{"id": "1", "contentType": "messageReference", "content": json.dumps({"messageId": "1", "messagePreview": "see you", "messageSender": {"user": {"displayName": "Ana"}}})}]}
    assert ChatHtmlSanitizer.quotes(message) == [{"kind": "reply", "senderName": "Ana", "sentAt": None, "content": "see you", "contentType": "text"}]


@pytest.mark.parametrize("content", [None, "not json", "[1]", json.dumps({"somethingNew": "x"})])
def test_a_quote_of_an_unknown_shape_is_still_a_quote_and_not_a_crash(content):
    [quote] = ChatHtmlSanitizer.quotes(forwarded(content))
    assert quote["kind"] == "forward" and quote["content"] is None


def test_the_list_carries_quotes_with_their_emojis_and_asks_for_no_file(chat, caplog):
    class ForwardNote(Note):
        def list(self, path, params=None, limit=None, retry=True):
            self.calls.append(path)
            return [forwarded(json.dumps({"originalMessageContent": '<p><emoji id="smile" alt="x" title="Smile"></emoji></p>', "originalSender": {"user": {"displayName": "Kylian B."}}})), forwarded(json.dumps({"somethingNew": "secret text"}))]

    note = ForwardNote()
    with caplog.at_level(logging.WARNING, logger="schuly.microsoft"):
        body = chat(note).get(f"/api/chats/{CHAT}/messages", headers=H).json()
    quote = body[0]["quotes"][0]
    assert quote["senderName"] == "Kylian B." and "<emoji" in quote["content"] and quote["emojis"][0]["key"] == "e0"
    assert body[0]["attachments"][0]["content"] is None
    assert body[0]["files"] == [] and "$batch" not in note.calls and not [c for c in note.calls if c.startswith("shares/")]
    # The unknown shape names its fields so the real one can be read, and never its content.
    assert "somethingNew" in caplog.text and "secret text" not in caplog.text
