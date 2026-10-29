"""Folder roles, chat pictures, message media/files/cards, rich sends, meetings and GIF search (all mocked)."""

import base64
import json

import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src import account_cache, chat_html, chat_send, config, folder_roles, outnote_client, teams_chat
from src.app import app

H = {config.REFRESH_TOKEN_HEADER: "old-frt"}
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
GIF_URL = "https://media2.giphy.com/media/abc/giphy.gif"


class Broker:
    def __init__(self):
        self.refresh_token = "old-frt"
        self.redeems = []

    def __call__(self, client_id, scope=None):
        self.redeems.append((client_id, scope))
        self.refresh_token = "rotated-frt"
        return "bearer"


class Note:
    def __init__(self):
        self.calls = []
        self.messages = []
        self.members = [{"userId": "me-id", "email": "me@school.ch"}, {"userId": "u2", "email": "bo@school.ch", "displayName": "Bo"}]

    def mail_folders(self, include_children=False):
        return [{"id": "F-IN", "displayName": "Posteingang", "parentFolderId": "ROOT"}, {"id": "F-SUB", "displayName": "Kurs", "parentFolderId": "F-IN"}, {"id": "F-RSS", "displayName": "RSS-Feeds", "parentFolderId": "ROOT"}]

    def batch(self, requests):
        self.calls.append(("batch", requests))
        out = []
        for r in requests:
            if r.startswith("me/mailFolders/inbox"):
                out.append({"id": "F-IN"})
            elif r.startswith("shares/"):
                out.append({"size": 1234, "file": {"mimeType": "video/webm"}})
            else:
                out.append(GraphError(404, "not found"))
        return out

    def list(self, path, params=None, limit=None):
        self.calls.append(("list", path))
        if path.endswith("/members"):
            return self.members
        if path == "me/chats":
            return [{"id": "19:g@thread.v2", "chatType": "group"}, {"id": "19:o@unq.gbl.spaces", "chatType": "oneOnOne"}]
        return self.messages

    def get(self, path, params=None, raw=False):
        self.calls.append(("get", path, raw))
        if path == "me":
            return {"id": "me-id", "mail": "me@school.ch"}
        if "hostedContents" in path:
            return self.hosted
        raise GraphError(404, "missing")

    def put(self, path, data, content_type=None):
        self.calls.append(("put", path, len(data), content_type))
        return {"id": "ITEM", "name": "clip.webm", "eTag": '"{6D8D2C5C-1111-2222-3333-444455556666},1"', "webUrl": "https://x-my.sharepoint.com/clip.webm"}

    def post(self, path, body=None):
        self.calls.append(("post", path, body))
        if path == "me/events":
            return {"id": "EV", "subject": body["subject"], "start": body["start"], "end": body["end"], "webLink": "https://outlook/ev", "onlineMeeting": {"joinUrl": "https://teams/join"}}
        if path.endswith("/invite"):
            return {"value": []}
        return {"id": "new", "importance": body.get("importance", "normal"), "body": body["body"], "attachments": body.get("attachments", [])}


@pytest.fixture
def env(monkeypatch):
    note, broker = Note(), Broker()

    def build(frt):
        broker.refresh_token = "rotated-frt"  # the broker rotates during the read
        return note, broker

    monkeypatch.setattr(outnote_client, "build_client", build)
    return note, broker


# --- part 1: well-known folder roles ------------------------------------------
def test_folders_carry_well_known_names_and_cache_the_roles(env):
    note, broker = env
    client = TestClient(app)
    tree = client.get("/api/mail/folders", headers=H).json()
    inbox = next(f for f in tree if f["id"] == "F-IN")
    assert inbox["wellKnownName"] == "inbox"
    assert inbox["childFolders"][0]["wellKnownName"] is None
    assert next(f for f in tree if f["id"] == "F-RSS")["wellKnownName"] is None
    batches = [c for c in note.calls if c[0] == "batch"]
    assert len(batches) == 1 and len(batches[0][1]) == len(folder_roles.WELL_KNOWN_NAMES)
    client.get("/api/mail/folders", headers=H)
    assert len([c for c in note.calls if c[0] == "batch"]) == 1  # cached for the account


def test_failed_role_lookup_still_lists_folders_and_is_not_cached(env, monkeypatch):
    note, broker = env
    monkeypatch.setattr(note, "batch", lambda requests: (_ for _ in ()).throw(GraphError(503, "busy")))
    tree = TestClient(app).get("/api/mail/folders", headers=H).json()
    assert all(f["wellKnownName"] is None for f in tree)
    assert folder_roles.cached(broker) is None


# --- part 2: chat pictures ----------------------------------------------------
class FakeResponse:
    def __init__(self, status, body=None, content=b""):
        self.status_code = status
        self._body = body
        self.content = content

    def json(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self, *a):
        yield self.content


class FakeHttp:
    def __init__(self, picture="URL@https://ch-prod.asyncgw.teams.microsoft.com/v1/objects/0-x/views/avatar_fullsize"):
        self.calls = []
        self.picture = picture

    def post(self, url, headers=None, content=None, timeout=None):
        self.calls.append(("post", url))
        return FakeResponse(200, {"tokens": {"skypeToken": "skype", "expiresIn": 4000}, "regionGtms": {"chatService": "https://ch.ng.msg.teams.microsoft.com"}})

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("get", url, headers))
        if "unknown" in url:
            return FakeResponse(404)
        return FakeResponse(200, {"threadProperties": {"picture": self.picture} if self.picture else {}})

    def stream(self, method, url, headers=None, timeout=None, follow_redirects=None):
        self.calls.append(("stream", url, headers))
        return FakeResponse(200, content=PNG)


@pytest.fixture
def http(monkeypatch):
    fake = FakeHttp()
    monkeypatch.setattr(teams_chat, "http_client", lambda: fake)
    return fake


def test_chat_photo_streams_the_group_picture_with_the_skype_token(env, http):
    note, broker = env
    r = TestClient(app).get("/api/chats/19:g@thread.v2/photo", headers=H)
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert broker.redeems == [(teams_chat.TEAMS_CLIENT, teams_chat.SPACES_SCOPE)]
    stream = next(c for c in http.calls if c[0] == "stream")
    assert stream[2] == {"Authorization": "skype_token skype"}


def test_chat_photo_is_404_without_a_custom_picture(env, http):
    http.picture = None
    assert TestClient(app).get("/api/chats/19:g@thread.v2/photo", headers=H).status_code == 404
    assert TestClient(app).get("/api/chats/19:unknown@thread.v2/photo", headers=H).status_code == 404


def test_picture_urls_outside_microsoft_media_hosts_are_ignored(env, http):
    http.picture = "URL@https://evil.example/x.png"
    assert TestClient(app).get("/api/chats/19:g@thread.v2/photo", headers=H).status_code == 404
    assert not [c for c in http.calls if c[0] == "stream"]


def test_chat_list_flags_group_chats_with_a_picture_and_caches_lookups(env, http):
    client = TestClient(app)
    chats = client.get("/api/chats", headers=H).json()
    assert [(c["id"], c["hasImage"]) for c in chats] == [("19:g@thread.v2", True), ("19:o@unq.gbl.spaces", False)]
    lookups = len([c for c in http.calls if c[0] == "get"])
    client.get("/api/chats", headers=H)
    assert len([c for c in http.calls if c[0] == "get"]) == lookups == 1
    assert len([c for c in http.calls if c[0] == "post"]) == 1  # one skype token per account


def test_chat_list_survives_a_refused_teams_sign_in(env, monkeypatch):
    class Refusing(FakeHttp):
        def post(self, url, headers=None, content=None, timeout=None):
            return FakeResponse(401, {})

    monkeypatch.setattr(teams_chat, "http_client", lambda: Refusing())
    chats = TestClient(app).get("/api/chats", headers=H).json()
    assert [c["hasImage"] for c in chats] == [False, False]


# --- part 3: received media, files and cards -----------------------------------
HOSTED_SRC = "https://graph.microsoft.com/v1.0/chats/19:g@thread.v2/messages/171/hostedContents/aWQ9eA==/$value"


def test_messages_carry_media_files_and_cards(env):
    note, _ = env
    sticker = {"type": "AdaptiveCard", "body": [{"type": "Image", "url": "https://stickers.newfuture.cc/stickers/a/cat.gif", "altText": "cat"}]}
    note.messages = [{
        "id": "171",
        "body": {"contentType": "html", "content": f'<p><img src="{HOSTED_SRC}" width="393.7" alt="Bild"><img alt="Cat GIF" src="{GIF_URL}" itemtype="http://schema.skype.com/Giphy"><img src="https://evil.example/a.png"></p>'},
        "attachments": [
            {"id": "a1", "contentType": "reference", "contentUrl": "https://x-my.sharepoint.com/clip.webm", "name": "clip.webm"},
            {"id": "c1", "contentType": "application/vnd.microsoft.card.adaptive", "teamsAppId": "app", "content": json.dumps(sticker)},
        ],
    }]
    m = TestClient(app).get("/api/chats/19:g@thread.v2/messages", headers=H).json()[0]
    assert m["media"] == [
        {"kind": "hosted", "url": None, "hostedContentId": "aWQ9eA==", "alt": "Bild", "width": 394, "height": None},
        {"kind": "gif", "url": GIF_URL, "hostedContentId": None, "alt": "Cat GIF", "width": None, "height": None},
    ]
    assert m["files"] == [{"id": "a1", "name": "clip.webm", "contentUrl": "https://x-my.sharepoint.com/clip.webm", "contentType": "video/webm", "size": 1234, "kind": "video", "hasThumbnail": True, "webUrl": "https://x-my.sharepoint.com/clip.webm"}]
    assert m["cards"][0]["content"] == sticker
    assert m["cards"][0]["sticker"] == {"url": "https://stickers.newfuture.cc/stickers/a/cat.gif", "alt": "cat"}
    assert m["importance"] == "normal"


def test_hosted_content_proxy_serves_only_images(env):
    note, _ = env
    note.hosted = PNG
    r = TestClient(app).get("/api/chats/19:g@thread.v2/messages/171/hostedContents/aWQ9eA==", headers=H)
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    note.hosted = b"<html><script>alert(1)</script>"
    assert TestClient(app).get("/api/chats/19:g@thread.v2/messages/171/hostedContents/aWQ9eA==", headers=H).status_code == 415
    assert TestClient(app).get("/api/chats/19:g@thread.v2/messages/1;x/hostedContents/a", headers=H).status_code == 400


# --- composer: sanitizing and sending -----------------------------------------
def test_sanitizer_keeps_only_the_allowlist():
    dirty = '<p style="color:red" onclick="x()">Hi <b>there</b><script>bad()</script><a href="javascript:alert(1)">j</a> <a href="https://schuly.dev" target="_blank">ok</a> <a href="mailto:a@b.ch">m</a><img src="https://evil/x" onerror="x()"><iframe>z</iframe><table><tr><td>cell</td></tr></table> <at id="0">Bo</at><at id="7">Nobody</at></p>'
    clean, mentions, images = chat_html.sanitize(dirty, {0}, set())
    assert clean == '<p>Hi <b>there</b><a>j</a> <a href="https://schuly.dev">ok</a> <a href="mailto:a@b.ch">m</a>cell <at id="0">Bo</at>Nobody</p>'
    assert mentions == {0} and images == set()


def test_html_send_with_mention_importance_and_gif(env):
    note, _ = env
    body = {"content": '<p>Hi <at id="0">Bo</at> <u>now</u></p>', "contentType": "html", "importance": "urgent",
            "mentions": [{"id": 0, "mentionText": "Bo", "mentioned": {"user": {"id": "u2", "displayName": "Bo"}}}, {"id": 1, "mentionText": "Unused", "mentioned": {"user": {"id": "u3"}}}],
            "gif": {"url": GIF_URL, "alt": "Cat", "width": 200, "height": 150}}
    r = TestClient(app).post("/api/chats/19:g@thread.v2/messages", headers=H, json=body)
    assert r.status_code == 200
    sent = next(c for c in note.calls if c[0] == "post")[2]
    assert sent["importance"] == "urgent"
    assert sent["mentions"] == [{"id": 0, "mentionText": "Bo", "mentioned": {"user": {"id": "u2", "displayName": "Bo", "userIdentityType": "aadUser"}}}]
    assert sent["body"]["content"].startswith('<p>Hi <at id="0">Bo</at> <u>now</u></p><img alt="Cat" width="200" height="150" src="' + GIF_URL + '" itemtype="http://schema.skype.com/Giphy"')
    assert r.json()["media"][0]["kind"] == "gif"


def test_send_rejects_gifs_from_other_hosts_and_bad_importance(env):
    client = TestClient(app)
    assert client.post("/api/chats/c1/messages", headers=H, json={"content": "x", "gif": {"url": "https://evil.example/a.gif"}}).status_code == 400
    assert client.post("/api/chats/c1/messages", headers=H, json={"content": "x", "importance": "loud"}).status_code == 400
    assert client.post("/api/chats/c1/messages", headers=H, json={"content": "x", "contentType": "markdown"}).status_code == 400


def test_multipart_send_inlines_images_and_shares_files(env):
    note, _ = env
    files = [("images", ("dot.png", PNG, "image/png")), ("files", ("clip.webm", b"webm-bytes", "video/webm"))]
    data = {"content": 'Look <img src="../hostedContents/1/$value">', "contentType": "html"}
    r = TestClient(app).post("/api/chats/19:g@thread.v2/messages", headers=H, data=data, files=files)
    assert r.status_code == 200, r.text
    put = next(c for c in note.calls if c[0] == "put")
    assert put[1] == "me/drive/root:/Microsoft%20Teams%20Chat%20Files/clip.webm:/content?@microsoft.graph.conflictBehavior=rename"
    assert put[3] == "video/webm"
    invite = next(c for c in note.calls if c[0] == "post" and c[1].endswith("/invite"))
    assert invite[2] == {"recipients": [{"objectId": "u2"}], "roles": ["read"], "requireSignIn": True, "sendInvitation": False}
    sent = [c for c in note.calls if c[0] == "post" and c[1].endswith("/messages")][0][2]
    assert sent["hostedContents"] == [{"@microsoft.graph.temporaryId": "1", "contentBytes": base64.b64encode(PNG).decode(), "contentType": "image/png"}]
    assert sent["attachments"] == [{"id": "6d8d2c5c-1111-2222-3333-444455556666", "contentType": "reference", "contentUrl": "https://x-my.sharepoint.com/clip.webm", "name": "clip.webm"}]
    assert sent["body"]["content"] == 'Look <img src="../hostedContents/1/$value"><attachment id="6d8d2c5c-1111-2222-3333-444455556666"></attachment>'


def test_multipart_send_refuses_non_image_inline_parts(env):
    r = TestClient(app).post("/api/chats/c1/messages", headers=H, data={"content": "x"}, files=[("images", ("a.png", b"<svg onload=x>", "image/png"))])
    assert r.status_code == 415


def test_large_files_go_through_an_upload_session_in_320k_multiples(monkeypatch):
    class Http:
        def __init__(self):
            self.puts = []

        def put(self, url, content=None, headers=None, timeout=None):
            self.puts.append((len(content), headers["Content-Range"]))
            done = sum(n for n, _ in self.puts) == size
            return FakeResponse(201 if done else 202, {"id": "BIG"} if done else {})

    import io
    size = 5 * 1024 * 1024 + 7
    http = Http()
    monkeypatch.setattr(chat_send, "http_client", lambda: http)

    class N:
        def post(self, path, body=None):
            assert path.endswith(":/createUploadSession")
            return {"uploadUrl": "https://upload.example/session"}

    item = chat_send.upload_file(N(), chat_send.Upload("big.mp4", io.BytesIO(b"x" * size), size, "video/mp4"))
    assert item == {"id": "BIG"}
    assert all(n % (320 * 1024) == 0 for n, _ in http.puts[:-1])
    assert http.puts[-1][1] == f"bytes {chat_send.UPLOAD_CHUNK}-{size - 1}/{size}"


def test_files_over_100_mb_are_refused():
    import io
    with pytest.raises(chat_send.SendError) as ex:
        chat_send.validate(chat_send.OutgoingMessage(content="x", files=[chat_send.Upload("a", io.BytesIO(), chat_send.MAX_FILE_BYTES + 1)]))
    assert ex.value.status == 413


# --- meetings and GIFs ----------------------------------------------------------
def test_meeting_invites_the_chat_members_and_returns_the_join_url(env):
    note, _ = env
    r = TestClient(app).post("/api/chats/19:g@thread.v2/meeting", headers=H, json={"subject": "IDPA", "start": "2026-11-02T14:00:00+01:00", "end": "2026-11-02T15:00:00+01:00"})
    assert r.status_code == 201
    assert r.json()["joinUrl"] == "https://teams/join"
    event = next(c for c in note.calls if c[1] == "me/events")[2]
    assert event["isOnlineMeeting"] and event["onlineMeetingProvider"] == "teamsForBusiness"
    assert event["start"] == {"dateTime": "2026-11-02T13:00:00", "timeZone": "UTC"}
    assert [a["emailAddress"]["address"] for a in event["attendees"]] == ["bo@school.ch"]


def test_gif_search_needs_a_giphy_key(env, monkeypatch):
    monkeypatch.delenv("GIPHY_API_KEY", raising=False)
    r = TestClient(app).get("/api/gifs/search", headers=H, params={"q": "cat"})
    assert r.status_code == 503


def test_gif_search_needs_a_microsoft_sign_in(env, monkeypatch):
    monkeypatch.setenv("GIPHY_API_KEY", "k")
    client = TestClient(app)
    assert client.get("/api/gifs/search", params={"q": "cat"}).status_code == 422
    assert client.get("/api/gifs/trending").status_code == 422
    assert client.get("/api/gifs/trending", headers={config.REFRESH_TOKEN_HEADER: "has spaces in it"}).status_code == 401


def test_gif_search_is_rate_limited_per_account(env, monkeypatch):
    from src import gifs
    monkeypatch.setenv("GIPHY_API_KEY", "k")
    monkeypatch.setattr(gifs, "_search", lambda key, query, limit: [])
    client = TestClient(app)
    codes = [client.get("/api/gifs/search", headers=H, params={"q": f"q{i}"}).status_code for i in range(gifs.RATE_PER_MINUTE + 1)]
    assert codes[:-1] == [200] * gifs.RATE_PER_MINUTE and codes[-1] == 429


def test_gif_search_returns_only_giphy_urls(env, monkeypatch):
    from src import gifs
    calls = []

    class Http:
        def get(self, url, params=None, timeout=None):
            calls.append(url)
            assert url.endswith("/search") and params["q"] == "cat"
            return FakeResponse(200, {"data": [{"id": "g1", "title": "Cat", "images": {"downsized_medium": {"url": GIF_URL + "?cid=1", "width": "200", "height": "150"}, "fixed_width_small": {"url": GIF_URL}}}, {"id": "bad", "images": {"original": {"url": "https://evil.example/x.gif"}}}]})

    monkeypatch.setenv("GIPHY_API_KEY", "k")
    monkeypatch.setattr(gifs, "http_client", lambda: Http())
    gifs._results.set(("cat", 5), None, 0)
    r = TestClient(app).get("/api/gifs/search", headers=H, params={"q": "cat", "limit": 5})
    assert r.json() == [{"id": "g1", "title": "Cat", "url": GIF_URL, "previewUrl": GIF_URL, "width": 200, "height": 150}]
    TestClient(app).get("/api/gifs/search", headers=H, params={"q": "Cat", "limit": 5})
    assert len(calls) == 1  # cached by (query, limit)


def test_account_cache_expires_and_is_bounded(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(account_cache.time, "monotonic", lambda: clock[0])
    cache = account_cache.AccountCache(max_items=2)
    cache.set("a", 1, 10)
    assert cache.get("a") == 1
    clock[0] += 11
    assert cache.get("a") is None
    for k in "bcd":
        cache.set(k, k, 100)
    assert cache.get("b") is None and cache.get("d") == "d"


def test_no_response_carrying_a_token_is_cacheable(env, http, monkeypatch):
    """Every route that can hand back a rotated refresh token must forbid storing the response."""
    from src import gifs
    note, _ = env
    monkeypatch.setenv("GIPHY_API_KEY", "k")
    monkeypatch.setattr(gifs, "_search", lambda key, query, limit: [])
    monkeypatch.setattr(note, "get", lambda path, params=None, raw=False: PNG if raw == "bytes" else {"id": "me-id"})
    client = TestClient(app)
    responses = [
        client.get("/api/chats/19:g@thread.v2/photo", headers=H),
        client.get("/api/chats/19:g@thread.v2/messages/171/hostedContents/aWQ9eA==", headers=H),
        client.get("/api/people/photo", headers=H, params={"email": "ana@school.ch"}),
        client.get("/api/users/u1/photo", headers=H),
        client.get("/api/gifs/trending", headers=H),
        client.get("/api/chats", headers=H),
    ]
    for r in responses:
        assert r.status_code == 200, r.url
        assert config.REFRESH_TOKEN_HEADER in r.headers, r.url
        cache_control = r.headers.get("cache-control", "")
        assert "max-age" not in cache_control and "public" not in cache_control and "private" not in cache_control, r.url
        assert cache_control == "no-store" or r.headers["content-type"].startswith("application/json"), r.url


@pytest.mark.parametrize("src", [
    "https://evil.com/v1.0/chats/x/messages/y/hostedContents/z/$value",
    "https://graph.microsoft.com.evil.com/v1.0/chats/x/messages/y/hostedContents/z/$value",
    "http://graph.microsoft.com/v1.0/chats/x/messages/y/hostedContents/z/$value",
    "https://graph.microsoft.com:8443/v1.0/chats/x/messages/y/hostedContents/z/$value",
    "https://user@graph.microsoft.com/v1.0/chats/x/messages/y/hostedContents/z/$value",
    "https://graph.microsoft.com/v2.0/chats/x/messages/y/hostedContents/z/$value",
    "https://graph.microsoft.com/v1.0/evil/v1.0/chats/x/messages/y/hostedContents/z/$value",
    "https://evil.com/x?u=https://graph.microsoft.com/v1.0/chats/x/messages/y/hostedContents/z/$value",
])
def test_hosted_media_needs_exactly_a_graph_url(src):
    assert chat_html.media({"body": {"content": f'<img src="{src}">'}}) == []


def test_hosted_media_accepts_v1_and_beta_and_returns_no_raw_src():
    for version in ("v1.0", "beta"):
        src = f"https://graph.microsoft.com/{version}/chats/19:a/messages/1/hostedContents/aWQ9eA==/$value"
        assert chat_html.media({"body": {"content": f'<img src="{src}">'}}) == [{"kind": "hosted", "url": None, "hostedContentId": "aWQ9eA==", "alt": None, "width": None, "height": None}]


@pytest.mark.parametrize("url", ["https://media2.giphy.com.evil.com/a.gif", "https://evilgiphy.com/a.gif", "https://evil.com/media2.giphy.com/a.gif", "http://media2.giphy.com/a.gif", "https://x.media2.giphy.com/a.gif", "https://media2.giphy.com:444/a.gif"])
def test_gif_hosts_are_exact_and_https(url):
    assert not chat_html.is_gif_host(url)
    assert chat_html.media({"body": {"content": f'<img src="{url}">'}}) == []
    card = {"type": "AdaptiveCard", "body": [{"type": "Image", "url": url}]}
    assert chat_html.cards({"attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": json.dumps(card)}]})[0]["sticker"] is None


def test_oversized_sends_are_refused_before_parsing(env):
    client = TestClient(app)
    r = client.post("/api/chats/c1/messages", headers={**H, "Content-Length": str(200 * 1024 * 1024), "Content-Type": "multipart/form-data; boundary=x"}, content=b"--x--")
    assert r.status_code == 413
    big = b"--x\r\nContent-Disposition: form-data; name=\"files\"; filename=\"a.bin\"\r\n\r\n" + b"0" * (300 * 1024) + b"\r\n--x--\r\n"
    import src.app as app_module
    old = app_module.MAX_SEND_BYTES
    app_module.MAX_SEND_BYTES = 100 * 1024
    try:
        def chunks():
            for i in range(0, len(big), 64 * 1024):
                yield big[i:i + 64 * 1024]
        r = client.post("/api/chats/c1/messages", headers={**H, "Content-Type": "multipart/form-data; boundary=x"}, content=chunks())
        assert r.status_code == 413
    finally:
        app_module.MAX_SEND_BYTES = old
    assert client.post("/api/chats/c1/messages", headers={config.REFRESH_TOKEN_HEADER: "bad token with spaces"}, json={"content": "x"}).status_code == 401
