"""Teams emojis, custom emojis, the emoji catalogue, and file thumbnails (all mocked)."""

import json

import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src import chat_html, chat_send, config, emojis, file_thumbs, outnote_client, teams_chat
from src.app import app
from tests.test_teams_extras import Broker, Note

H = {config.REFRESH_TOKEN_HEADER: "old-frt"}
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 20
HUNDRED = '<p><emoji id="1f4af_hundredpointssymbol" alt="\U0001F4AF" title=""></emoji></p>'
SHAREPOINT = "https://x-my.sharepoint.com/a.docx"


def metadata():
    return {"categories": [
        {"id": "c1", "title": "Smileys", "emoticons": [
            {"id": "1f4af_hundredpointssymbol", "description": "Hundred points", "shortcuts": ["(hundredpoints)"], "unicode": "\U0001F4AF", "etag": "v11", "diverse": False, "animation": {"fps": 24, "framesCount": 48, "firstFrame": 1}, "keywords": ["100"]},
            {"id": "laugh", "description": "Laugh", "shortcuts": ["(laugh)", ":D"], "unicode": "\U0001F606", "etag": "v47", "diverse": False, "animation": {"fps": 24, "framesCount": 51, "firstFrame": 19}, "keywords": []},
            {"id": "yes", "description": "Yes", "shortcuts": ["(y)"], "unicode": "\U0001F44D", "etag": "v70", "diverse": True, "animation": {"fps": 24, "framesCount": 51, "firstFrame": 1}, "keywords": []},
            {"id": "salute", "description": "Salute", "shortcuts": [], "unicode": "\U0001FAE1", "etag": "v3", "diverse": False, "animation": {"fps": 24, "framesCount": 1, "firstFrame": 1}, "keywords": []},
            {"id": "../evil", "description": "x", "shortcuts": [], "unicode": "x", "animation": {}},
        ]},
    ]}


class Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.content = json.dumps(body).encode() if body is not None else text.encode()
        self.text = text

    def json(self):
        return self._body


class Cdn:
    def __init__(self):
        self.urls = []
        self.missing = set()
        self.fail = False

    def get(self, url, headers=None, timeout=None, follow_redirects=None):
        self.urls.append(url)
        if self.fail:
            return Resp(500)
        if url.rsplit("/", 1)[-1] in self.missing:
            return Resp(404, text="<Error/>")
        return Resp(200, metadata())


@pytest.fixture
def cdn(monkeypatch):
    fake = Cdn()
    emojis.clear_cache()
    monkeypatch.setattr(emojis, "http_client", lambda: fake)
    monkeypatch.setattr(emojis, "_discover_version", lambda: None)
    yield fake
    emojis.clear_cache()


@pytest.fixture
def account(monkeypatch):
    note, broker = Note(), Broker()
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (note, broker))
    return note, broker


# --- parsing the markup Graph returns ----------------------------------------------------
def test_the_real_graph_markup_becomes_a_keyed_placeholder_and_an_entry(cdn):
    content, found = emojis.message_emojis(HUNDRED, emojis.catalogue("default"))
    assert content == '<p><emoji key="e0" alt="\U0001F4AF"></emoji></p>'
    assert found == [{"key": "e0", "id": "1f4af_hundredpointssymbol", "alt": "\U0001F4AF", "title": "Hundred points", "kind": "teams", "documentId": None, "animated": True,
                      "staticUrl": f"{emojis.ASSET_BASE}/1f4af_hundredpointssymbol/default/50_f.png?v=v11",
                      "animatedUrl": f"{emojis.ASSET_BASE}/1f4af_hundredpointssymbol/default/50_anim_f.png?v=v11",
                      "frames": 48, "frameMs": 41.67, "firstFrame": 1, "size": 50}]


def test_emoji_beside_text_is_30_and_repeats_share_one_entry(cdn):
    content, found = emojis.message_emojis('<p>hi <emoji id="laugh" alt="x" title="Lach"></emoji> <emoji id="laugh" alt="x"></emoji><emoji id="salute" alt="s"></emoji></p>', emojis.catalogue("default"))
    assert content.count('key="e0"') == 2 and content.count('key="e1"') == 1
    assert [(e["id"], e["size"]) for e in found] == [("laugh", 30), ("salute", 30)]
    assert found[0]["title"] == "Lach" and found[0]["frames"] == 51
    salute = found[1]
    assert salute["animated"] is False and salute["animatedUrl"] is None and salute["frames"] == 1 and salute["frameMs"] is None


def test_unknown_catalogue_still_gives_a_still_picture():
    content, found = emojis.message_emojis('<p><emoji id="newone" alt="N"></emoji></p>', None)
    assert found[0]["animated"] is False and found[0]["staticUrl"].startswith(emojis.ASSET_BASE + "/newone/default/50_f.png")


def test_skin_tone_ids_use_the_s_suffix(cdn):
    _, found = emojis.message_emojis('<p>a <emoji id="yes-tone3" alt="y"></emoji></p>', emojis.catalogue("default"))
    assert found[0]["staticUrl"].startswith(f"{emojis.ASSET_BASE}/yes/default/30_f_s4.png") and "_anim_f_s4.png" in found[0]["animatedUrl"]


@pytest.mark.parametrize("bad", ["../x", "a/b", "A B", "x" * 80, "", "laugh-tone9", "a.b"])
def test_invalid_ids_become_alt_text_and_no_entry(cdn, bad):
    content, found = emojis.message_emojis(f'<p><emoji id="{bad}" alt="&lt;b&gt;"></emoji></p>', emojis.catalogue("default"))
    assert found == [] and "<emoji" not in content


def test_the_img_form_is_read_too(cdn):
    html = '<p><readonly contenteditable="false" itemtype="http://schema.skype.com/Emoji"><img itemtype="http://schema.skype.com/Emoji" itemid="laugh" src="https://statics.teams.cdn.office.net/x.png" alt="L"></readonly> hi</p>'
    content, found = emojis.message_emojis(html, emojis.catalogue("default"))
    assert found[0]["id"] == "laugh" and found[0]["kind"] == "teams" and "<img" not in content and "<readonly" not in content


def test_custom_emoji_has_a_document_id_and_never_a_raw_url():
    html = '<p>x <emoji id="party;0-weu-d1-abc123" alt="party"></emoji> <img itemtype="http://schema.skype.com/CustomEmoji" itemid="wow" alt="wow" src="https://ch-prod.asyncgw.teams.microsoft.com/v1/objects/0-weu-d2-def456/views/imgt2_anim"></p>'
    content, found = emojis.message_emojis(html, None)
    assert [(e["kind"], e["documentId"], e["staticUrl"], e["animatedUrl"]) for e in found] == [("custom", "0-weu-d1-abc123", None, None), ("custom", "0-weu-d2-def456", None, None)]
    assert "asyncgw" not in content


def test_custom_emoji_from_other_hosts_or_bad_ids_is_dropped():
    html = '<p><img itemtype="http://schema.skype.com/CustomEmoji" itemid="x" alt="x" src="https://evil.example/v1/objects/abc/views/imgt2_anim"><emoji id="a;../b" alt="y"></emoji></p>'
    content, found = emojis.message_emojis(html, None)
    assert found == [] and "evil" not in content


def test_messages_route_carries_emojis_and_rewrites_the_body(cdn, account):
    note, _ = account
    note.messages = [{"id": "1", "body": {"contentType": "html", "content": HUNDRED}}, {"id": "2", "body": {"contentType": "html", "content": "<p>plain</p>"}}]
    first, second = TestClient(app).get("/api/chats/19:g@thread.v2/messages", headers=H).json()
    assert first["emojis"][0]["id"] == "1f4af_hundredpointssymbol" and "key=" in first["body"]["content"]
    assert second["emojis"] == [] and second["body"]["content"] == "<p>plain</p>"


# --- the catalogue --------------------------------------------------------------------------
def test_catalogue_is_cached_24h_per_locale_and_falls_back(cdn, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(emojis, "_clock", lambda: clock[0])
    cdn.missing = {"de-de.json"}
    client = TestClient(app)
    r = client.get("/api/emojis/catalogue?locale=de_DE")
    assert r.status_code == 200 and r.json()["locale"] == "default"
    assert r.headers["cache-control"] == "public, max-age=3600" and config.REFRESH_TOKEN_HEADER not in r.headers
    body = r.json()
    assert body["sizes"] == [20, 30, 40, 50, 60, 100] and body["fps"] == 24 and body["custom"] == []
    laugh = next(e for c in body["categories"] for e in c["emojis"] if e["id"] == "laugh")
    assert laugh == {"id": "laugh", "shortcuts": ["(laugh)", ":D"], "unicode": "\U0001F606", "title": "Laugh", "keywords": [], "diverse": False, "animated": True, "staticUrl": f"{emojis.ASSET_BASE}/laugh/default/30_f.png?v=v47", "animatedUrl": f"{emojis.ASSET_BASE}/laugh/default/30_anim_f.png?v=v47", "frames": 51, "frameMs": 41.67, "firstFrame": 19, "etag": "v47"}
    assert "../evil" not in json.dumps(body)
    fetched = len(cdn.urls)
    client.get("/api/emojis/catalogue?locale=de_DE")
    assert len(cdn.urls) == fetched
    clock[0] += emojis.CATALOGUE_TTL + 1
    client.get("/api/emojis/catalogue?locale=de_DE")
    assert len(cdn.urls) > fetched


def test_catalogue_refuses_odd_locales_and_survives_cdn_errors(cdn):
    client = TestClient(app)
    assert client.get("/api/emojis/catalogue?locale=../../x").status_code == 400
    cdn.fail = True
    assert client.get("/api/emojis/catalogue").status_code == 502


def test_catalogue_rediscovers_a_rotated_asset_version(cdn, monkeypatch):
    new = "a" * 32
    monkeypatch.setattr(emojis, "_discover_version", lambda: new)
    monkeypatch.setitem(emojis._version, "value", "b" * 32)
    real = cdn.get
    cdn.get = lambda url, headers=None, timeout=None, follow_redirects=None: Resp(404, text="x") if "/" + "b" * 32 + "/" in url else real(url)
    assert emojis.catalogue("default").version == new


# --- sending ---------------------------------------------------------------------------------
def test_sanitizer_rewrites_catalogue_emoji_to_the_exact_teams_markup(cdn):
    dirty = '<p>x <emoji id="laugh" alt="evil&quot; onerror=1" title="t" onclick="x()" style="a:b">kid</emoji> <emoji id="nope" alt="n"></emoji> <emoji id="../laugh" alt="n"></emoji> <emoji alt="n"></emoji><img itemtype="http://schema.skype.com/Emoji" itemid="laugh" src="https://evil.example/x.png"></p>'
    clean, _, _ = chat_html.sanitize(dirty, set(), set(), emojis.for_send)
    assert clean == '<p>x <emoji id="laugh" alt="\U0001F606" title="Laugh"></emoji>kid   </p>'


def test_sanitizer_drops_emoji_without_a_lookup_and_caps_the_count(cdn):
    assert chat_html.sanitize('<p><emoji id="laugh"></emoji>a</p>')[0] == "<p>a</p>"
    many = '<emoji id="laugh"></emoji>' * (chat_html.MAX_EMOJIS + 5)
    assert chat_html.sanitize(many, emoji_lookup=emojis.for_send)[0].count("<emoji ") == chat_html.MAX_EMOJIS


def test_skin_tones_only_on_diverse_emoji(cdn):
    assert emojis.for_send("yes-tone2") == ("\U0001F44D", "Yes")
    assert emojis.for_send("laugh-tone2") is None and emojis.for_send("laugh-tone7") is None


def test_send_posts_teams_emoji_markup(cdn):
    msg = chat_send.OutgoingMessage(content='<p>go <emoji id="1f4af_hundredpointssymbol" alt="x"></emoji></p>', content_type="html")
    body = chat_send.payload(chat_send.validate(msg))["body"]
    assert body == {"contentType": "html", "content": '<p>go <emoji id="1f4af_hundredpointssymbol" alt="\U0001F4AF" title="Hundred points"></emoji></p>'}


def test_send_says_503_when_the_catalogue_is_unavailable(cdn):
    cdn.fail = True
    with pytest.raises(chat_send.SendError) as ex:
        chat_send.payload(chat_send.validate(chat_send.OutgoingMessage(content='<emoji id="laugh"></emoji>', content_type="html")))
    assert ex.value.status == 503


# --- custom emoji proxy --------------------------------------------------------------------------
class Stream:
    def __init__(self, status, content):
        self.status_code, self.content = status, content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self, *a):
        yield self.content


class AmsHttp:
    def __init__(self):
        self.content, self.calls = PNG, []

    def post(self, url, headers=None, content=None, timeout=None):
        return Resp(200, {"tokens": {"skypeToken": "skype", "expiresIn": 4000}, "regionGtms": {"chatService": "https://ch.ng.msg.teams.microsoft.com", "amsV2": "https://ch-prod.asyncgw.teams.microsoft.com"}})

    def stream(self, method, url, headers=None, timeout=None, follow_redirects=None):
        self.calls.append((url, headers))
        return Stream(200, self.content)


@pytest.fixture
def ams(account, monkeypatch):
    fake = AmsHttp()
    monkeypatch.setattr(teams_chat, "http_client", lambda: fake)
    return fake


def test_custom_emoji_is_fetched_with_the_skype_token_and_never_cacheable(ams):
    r = TestClient(app).get("/api/emojis/custom/0-weu-d1-abc123?animated=false", headers=H)
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store" and r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    url, headers = ams.calls[0]
    assert url == "https://ch-prod.asyncgw.teams.microsoft.com/v1/objects/0-weu-d1-abc123/views/img_thumb_tiny" and headers == {"Authorization": "skype_token skype"}
    TestClient(app).get("/api/emojis/custom/0-weu-d1-abc123", headers=H)
    assert ams.calls[1][0].endswith("/views/imgt2_anim")


def test_custom_emoji_refuses_bad_ids_and_non_images(ams):
    client = TestClient(app)
    assert client.get("/api/emojis/custom/a..b", headers=H).status_code == 400
    ams.content = b"<html>"
    assert client.get("/api/emojis/custom/abc", headers=H).status_code == 404


def test_media_hosts_are_exact_microsoft_https_hosts():
    assert teams_chat._media_host("https://evil.example") is None
    assert teams_chat._media_host("http://x.asyncgw.teams.microsoft.com") is None
    assert teams_chat._media_host("https://x.asyncgw.teams.microsoft.com:444") is None
    assert teams_chat._media_host("https://ch-prod.asyncgw.teams.microsoft.com/v1") == "https://ch-prod.asyncgw.teams.microsoft.com"


# --- file kinds and thumbnails -----------------------------------------------------------------------
@pytest.mark.parametrize("name,mime,kind", [("a.DOCX", None, "word"), ("a.xlsx", None, "excel"), ("a.pptx", None, "powerpoint"), ("a.pdf", None, "pdf"), ("a.one", None, "onenote"), ("a.png", None, "image"), ("a.mp4", None, "video"), ("a.mp3", None, "audio"), ("a.zip", None, "archive"), ("a.py", None, "code"), ("a.txt", None, "text"), ("noext", "image/webp", "image"), ("noext", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "word"), ("a.drawio", "application/octet-stream", "other"), (None, None, "other")])
def test_file_kinds(name, mime, kind):
    assert file_thumbs.file_kind(name, mime) == kind


@pytest.mark.parametrize("url,ok", [
    ("https://contoso-my.sharepoint.com/personal/a/b.docx", True), ("https://onedrive.live.com/x", True), ("https://1drv.ms/w/s!abc", True),
    ("http://contoso.sharepoint.com/x", False), ("https://sharepoint.com/x", False), ("https://evilsharepoint.com/x", False), ("https://contoso.sharepoint.com.evil.example/x", False),
    ("https://user@contoso.sharepoint.com/x", False), ("https://contoso.sharepoint.com:8443/x", False), ("https://evil.example/?u=https://x.sharepoint.com", False), ("javascript:alert(1)", False), ("", False), (None, False),
])
def test_only_sharepoint_and_onedrive_hosts_are_share_urls(url, ok):
    assert file_thumbs.is_share_url(url) is ok


def test_message_files_carry_kind_thumbnail_flag_and_web_url(cdn, account):
    note, _ = account
    note.messages = [{"id": "1", "body": {"content": "x"}, "attachments": [
        {"id": "a1", "contentType": "reference", "contentUrl": SHAREPOINT, "name": "a.docx"},
        {"id": "a2", "contentType": "reference", "contentUrl": "https://elsewhere.example/a.docx", "name": "a.docx"}]}]
    files = TestClient(app).get("/api/chats/19:g@thread.v2/messages", headers=H).json()[0]["files"]
    assert [(f["kind"], f["hasThumbnail"], f["webUrl"]) for f in files] == [("word", True, SHAREPOINT), ("word", False, None)]


class ThumbNote:
    def __init__(self):
        self.calls, self.thumb, self.file = [], JPEG, True

    def get(self, path, params=None, raw=False):
        self.calls.append(path)
        if path.startswith("me/chats") or "/messages/" in path:
            return {"id": "m1", "attachments": [{"id": "a1", "contentType": "reference", "contentUrl": SHAREPOINT, "name": "a.docx"}, {"id": "a2", "contentType": "reference", "contentUrl": "https://evil.example/a.docx", "name": "b.docx"}]}
        if path.startswith("shares/"):
            return {"id": "01ABC!x_y", "parentReference": {"driveId": "b!drive-1"}, "file": {} if self.file else None, "size": 5}
        if "/thumbnails/" in path:
            if self.thumb is None:
                raise GraphError(404, "no thumbnail")
            return self.thumb
        raise GraphError(404, "missing")


@pytest.fixture
def thumbs(monkeypatch):
    note, broker = ThumbNote(), Broker()
    broker.redeems = []
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (setattr(broker, "refresh_token", "rotated-frt") or note, broker))
    return note


def test_chat_thumbnail_resolves_once_per_hour_and_never_caches_the_response(thumbs):
    client = TestClient(app)
    r = client.get("/api/chats/19:g@thread.v2/messages/171/files/a1/thumbnail?size=large", headers=H)
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "no-store" and r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert "drives/b%21drive-1/items/01ABC%21x_y/thumbnails/0/large/content" in thumbs.calls
    client.get("/api/chats/19:g@thread.v2/messages/171/files/a1/thumbnail", headers=H)
    assert len([c for c in thumbs.calls if c.startswith("shares/")]) == 1
    assert thumbs.calls[-1].endswith("/thumbnails/0/medium/content")


def test_thumbnail_404s_without_a_thumbnail_a_non_image_or_a_foreign_host(thumbs):
    client = TestClient(app)
    url = "/api/chats/19:g@thread.v2/messages/171/files/%s/thumbnail"
    thumbs.thumb = None
    assert client.get(url % "a1", headers=H).status_code == 404
    thumbs.thumb = b"<html>not an image</html>"
    assert client.get(url % "a1", headers=H).status_code == 404
    thumbs.thumb = PNG
    assert client.get(url % "a2", headers=H).status_code == 404
    assert not [c for c in thumbs.calls if "evil" in c]
    assert client.get(url % "missing", headers=H).status_code == 404


def test_thumbnail_validates_size_and_ids(thumbs):
    client = TestClient(app)
    assert client.get("/api/chats/19:g@thread.v2/messages/171/files/a1/thumbnail?size=huge", headers=H).status_code == 400
    assert client.get("/api/chats/19:g@thread.v2/messages/171/files/a..1/thumbnail", headers=H).status_code == 400
    assert client.get("/api/chats/a..b/messages/171/files/a1/thumbnail", headers=H).status_code == 400


def test_drive_item_thumbnail(thumbs):
    client = TestClient(app)
    r = client.get("/api/files/01ABC!x_y/thumbnail?size=small", headers=H)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert thumbs.calls[-1] == "me/drive/items/01ABC%21x_y/thumbnails/0/small/content"
    assert client.get("/api/files/a..b/thumbnail", headers=H).status_code == 400
    thumbs.thumb = None
    assert client.get("/api/files/abc/thumbnail", headers=H).status_code == 404


def test_folders_have_no_thumbnail(thumbs):
    thumbs.file = False
    assert TestClient(app).get("/api/chats/19:g@thread.v2/messages/171/files/a1/thumbnail", headers=H).status_code == 404
