"""Teams emojis (the animated "personal expressions") and tenant custom emojis.

Teams emoji
-----------
Graph returns a Teams emoji in a chat message body as `<emoji id="1f4af_hundredpointssymbol" alt="..." title="..."></emoji>`
(some clients send `<img itemtype="http://schema.skype.com/Emoji" itemid="...">`; both are read). The picture
is served by Teams' public CDN, per emoji id and size:

    {ASSET_BASE}/{id}/default/{size}_f.png          still (size x size)
    {ASSET_BASE}/{id}/default/{size}_anim_f.png     vertical sprite strip, `frames` square frames, played at 24 fps
    ...  _f_s{tone+1}.png                           skin tone variants (`{id}-tone{1..5}` in markup)

Sizes: 20, 30, 40, 50, 60, 100. The catalogue (categories, ids, shortcuts, unicode, localized titles, frame counts) is
the JSON Teams loads itself: `{METADATA_BASE}/{version}/{locale}.json`, falling back to `default.json`. It is public,
so no token is involved; it is cached here for 24 hours per locale.

Custom emoji
------------
A tenant's own emoji live in the Teams media service (AMS) and need the skype token, so they are never linked
directly: a message carries `kind: "custom"` and a `documentId`, and the image comes from the proxy route.
The tenant's custom emoji list is a Graph beta API (`TeamworkCustomEmoji.Read`) that the first-party clients
used here are not granted, so the catalogue carries `custom: []`.
"""

import html
import re
import threading
import time
from urllib.parse import urlsplit
from entrance import http_client

from src.application.abstractions.i_emoji_catalogue import IEmojiCatalogue
from src.application.options.emoji_options import EmojiOptions
from src.domain.chat.catalogue import Catalogue
from src.domain.chat.emoji_assets import EmojiAssets
from src.domain.errors.emoji_error import EmojiError


class EmojiCatalogue(IEmojiCatalogue):
    """Teams' public emoji catalogue (cached 24 hours), message emoji parsing and the send allowlist."""

    CDN_HOSTS = frozenset({"statics.teams.cdn.office.net", "teams.public.onecdn.static.microsoft"})
    ASSET_BASE = EmojiAssets.ASSET_BASE
    METADATA_BASE = "https://statics.teams.cdn.office.net/evergreen-assets/personal-expressions/v1/metadata"
    TEAMS_PAGE = "https://teams.microsoft.com/v2/"
    SIZES = EmojiAssets.SIZES
    INLINE_SIZE = 30
    BIG_SIZE = 50  # a message that is only emoji
    FPS = EmojiAssets.FPS
    CATALOGUE_TTL = 24 * 3600
    MAX_LOCALES = 24
    MAX_METADATA_BYTES = 4 * 1024 * 1024
    MAX_PAGE_BYTES = 2 * 1024 * 1024
    FETCH_TIMEOUT = 8.0
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    EMOJI_ID = re.compile(r"[a-z0-9_]{1,64}")
    EMOJI_REF = re.compile(r"([a-z0-9_]{1,64})(?:-tone([1-5]))?")
    LOCALE = re.compile(r"[a-z]{2,3}(?:-[a-z0-9]{2,8}){0,2}")
    DOCUMENT_ID = re.compile(r"[A-Za-z0-9_-]{1,120}")
    SHORTCUT = re.compile(r"[a-z0-9_-]{1,50}")
    AMS_PATH = re.compile(r"/v1/objects/([A-Za-z0-9_-]{1,120})/views/")
    AMS_SUFFIXES = (".asyncgw.teams.microsoft.com", ".asm.skype.com")
    MAX_ALT = 40
    MAX_TITLE = 100
    _EMOJI_TAG = re.compile(r"<emoji\b([^>]*)>(?:\s*</emoji>)?", re.IGNORECASE)
    _EMOJI_IMG = re.compile(r"<img\b[^>]*\bitemtype\s*=\s*[\"']http://schema\.skype\.com/(?:Custom)?Emoji[\"'][^>]*>", re.IGNORECASE)
    _EMOJI_ANY = re.compile(_EMOJI_TAG.pattern + "|" + _EMOJI_IMG.pattern, re.IGNORECASE)
    _READONLY = re.compile(r"<readonly\b[^>]*>\s*(<img\b[^>]*>)\s*</readonly>", re.IGNORECASE)
    _ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
    _TAG = re.compile(r"<[^>]*>")
    _EMOJI_OUT = re.compile(r"<emoji\b[^>]*>(?:[^<]*</emoji>)?")
    http_client = staticmethod(http_client)
    _clock = staticmethod(time.monotonic)

    def __init__(self, options: EmojiOptions):
        self._cache: dict[str, tuple[float, Catalogue]] = {}
        self._lock = threading.Lock()
        self._version = {"value": options.version}

    def asset_url(self, emoji_id: str, size: int, animated: bool, tone: int = 0, etag: str | None = None) -> str:
        suffix = f"_s{tone + 1}" if tone else ""
        query = f"?v={etag}" if etag and re.fullmatch(r"[A-Za-z0-9._-]{1,20}", etag) else ""
        return f"{self.ASSET_BASE}/{emoji_id}/default/{size}{'_anim' if animated else ''}_f{suffix}.png{query}"

    def is_cdn_url(self, url: str) -> bool:
        try:
            parts = urlsplit(url or "")
            port = parts.port
        except ValueError:
            return False
        return parts.scheme == "https" and port in (None, 443) and not parts.username and not parts.password and (parts.hostname or "").lower() in self.CDN_HOSTS

    def parse_ref(self, value) -> tuple[str, int] | None:
        """(base id, skin tone 0-5) for a Teams emoji id such as `laugh` or `yes-tone3`, else None."""
        m = self.EMOJI_REF.fullmatch(value) if isinstance(value, str) else None
        return (m.group(1), int(m.group(2) or 0)) if m else None

    def normalize_locale(self, value: str | None) -> str | None:
        """`default` or a lowercase locale such as `de-de`; None when it is not shaped like one."""
        value = (value or "").strip().lower().replace("_", "-")
        if value in ("", "default"):
            return "default"
        return value if self.LOCALE.fullmatch(value) else None

    def _json(self, url: str):
        r = self.http_client().request("GET", url, timeout=self.FETCH_TIMEOUT)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise EmojiError(502, f"Teams emoji metadata {r.status_code}")
        if len(r.content) > self.MAX_METADATA_BYTES:
            raise EmojiError(502, "Teams emoji metadata is too large")
        try:
            return r.json()
        except ValueError:
            raise EmojiError(502, "Teams emoji metadata is not JSON") from None

    def _discover_version(self) -> str | None:
        """The asset version Teams' own web client is currently using (its config bundle names it), or None."""
        try:
            page = self.http_client().request("GET", self.TEAMS_PAGE, headers={"User-Agent": self.UA}, timeout=self.FETCH_TIMEOUT, follow_redirects=True)
            if page.status_code != 200 or len(page.content) > self.MAX_PAGE_BYTES:
                return None
            m = re.search(r"//([\w.-]+)/teams-modular-packages/hashed-assets/(config-prod-[0-9a-f]+\.js)", page.text)
            if not m or m.group(1).lower() not in self.CDN_HOSTS:
                return None
            bundle = self.http_client().request("GET", f"https://{m.group(1).lower()}/teams-modular-packages/hashed-assets/{m.group(2)}", timeout=self.FETCH_TIMEOUT, follow_redirects=True)
            if bundle.status_code != 200 or len(bundle.content) > 8 * self.MAX_PAGE_BYTES:
                return None
            v = re.search(r'emoticonAssetVersion:\[\{value:"([0-9a-f]{32})"', bundle.text)
            return v.group(1) if v else None
        except Exception:
            return None

    def _candidates(self, locale: str) -> list[str]:
        names = [locale]
        if locale != "default" and "-" not in locale:
            names.append(f"{locale}-{locale}")
        if locale != "default":
            names.append("default")
        return names

    def _fetch(self, locale: str) -> Catalogue:
        for attempt in range(2):
            version = self._version["value"]
            for name in self._candidates(locale):
                raw = self._json(f"{self.METADATA_BASE}/{version}/{name}.json")
                if isinstance(raw, dict) and isinstance(raw.get("categories"), list):
                    return self._build(raw, name, version)
            found = self._discover_version() if attempt == 0 else None
            if not found or found == version:
                break
            self._version["value"] = found
        raise EmojiError(502, "The Teams emoji catalogue is unavailable")

    def _strings(self, values, count: int, length: int) -> list[str]:
        return [v[:length] for v in (values or [])[:count] if isinstance(v, str)] if isinstance(values, list) else []

    def _item(self, e) -> dict | None:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not self.EMOJI_ID.fullmatch(e["id"]):
            return None
        anim = e.get("animation") if isinstance(e.get("animation"), dict) else {}
        frames = anim.get("framesCount") if isinstance(anim.get("framesCount"), int) and 0 < anim.get("framesCount") <= 1000 else 1
        fps = anim.get("fps") if isinstance(anim.get("fps"), (int, float)) and 0 < anim.get("fps") <= 120 else self.FPS
        first = anim.get("firstFrame") if isinstance(anim.get("firstFrame"), int) and 1 <= anim.get("firstFrame") <= frames else 1
        etag = e.get("etag") if isinstance(e.get("etag"), str) else None
        animated = frames > 1
        return {
            "id": e["id"],
            "shortcuts": self._strings(e.get("shortcuts"), 20, 40),
            "unicode": str(e.get("unicode") or "")[:32],
            "title": str(e.get("description") or "")[:self.MAX_TITLE],
            "keywords": self._strings(e.get("keywords"), 30, 30),
            "diverse": bool(e.get("diverse")),
            "animated": animated,
            "staticUrl": self.asset_url(e["id"], self.INLINE_SIZE, False, 0, etag),
            "animatedUrl": self.asset_url(e["id"], self.INLINE_SIZE, True, 0, etag) if animated else None,
            "frames": frames,
            "frameMs": round(1000 / fps, 2) if animated else None,
            "firstFrame": first,
            "etag": etag,
        }

    def _build(self, raw: dict, locale: str, version: str) -> Catalogue:
        cat = Catalogue(locale, version)
        for c in raw["categories"]:
            if not isinstance(c, dict):
                continue
            items = []
            for e in c.get("emoticons") or []:
                item = self._item(e)
                if item and item["id"] not in cat.by_id:
                    items.append(item)
                    cat.by_id[item["id"]] = item
            cat.categories.append({"id": str(c.get("id") or "")[:100], "title": str(c.get("title") or "")[:100], "emojis": items})
        if not cat.by_id:
            raise EmojiError(502, "The Teams emoji catalogue is empty")
        return cat

    def catalogue(self, locale: str = "default") -> Catalogue:
        """The catalogue for `locale` (already normalized), cached 24 hours; concurrent misses fetch once."""
        hit = self._cache.get(locale)
        if hit and hit[0] > self._clock():
            return hit[1]
        with self._lock:
            hit = self._cache.get(locale)
            if hit and hit[0] > self._clock():
                return hit[1]
            cat = self._fetch(locale)
            self._cache.pop(locale, None)
            self._cache[locale] = (self._clock() + self.CATALOGUE_TTL, cat)
            while len(self._cache) > self.MAX_LOCALES:
                del self._cache[next(iter(self._cache))]
            return cat

    def cached_catalogue(self, locale: str = "default") -> Catalogue | None:
        hit = self._cache.get(locale)
        return hit[1] if hit and hit[0] > self._clock() else None

    def clear_cache(self):
        with self._lock:
            self._cache.clear()

    def for_send(self, ref) -> tuple[str, str] | None:
        """(alt, title) for an emoji id the catalogue knows (skin tones only on diverse ones), else None. Raises EmojiError if the catalogue can't be loaded."""
        parsed = self.parse_ref(ref)
        if not parsed:
            return None
        item = self.catalogue("default").by_id.get(parsed[0])
        if not item or (parsed[1] and not item["diverse"]):
            return None
        return item["unicode"], item["title"]

    def _attrs(self, tag: str) -> dict[str, str]:
        return {m.group(1).lower(): html.unescape(m.group(2) if m.group(2) is not None else m.group(3)) for m in self._ATTR.finditer(tag)}

    def _custom_document(self, emoji_id: str, src: str) -> tuple[str, str] | None:
        """(shortcut, document id) of a custom emoji: its id is `shortcut;documentId`, or the AMS object in its picture URL."""
        shortcut = ""
        if ";" in emoji_id:
            shortcut, _, doc = emoji_id.partition(";")
            if self.DOCUMENT_ID.fullmatch(doc) and ".." not in doc:
                return (shortcut if self.SHORTCUT.fullmatch(shortcut) else "", doc)
            return None
        try:
            parts = urlsplit(src or "")
            host = (parts.hostname or "").lower()
        except ValueError:
            return None
        m = self.AMS_PATH.search(parts.path or "")
        if m and parts.scheme == "https" and any(host.endswith(s) for s in self.AMS_SUFFIXES) and ".." not in m.group(1):
            return (emoji_id if self.SHORTCUT.fullmatch(emoji_id or "") else "", m.group(1))
        return None

    def message_emojis(self, content: str, cat: Catalogue | None = None) -> tuple[str, list[dict]]:
        """(content with each emoji turned into `<emoji key="e0" alt="...">...</emoji>` (the alt as text, so clients that strip the tag still show the emoji), the emoji list).

        Entries are `{key, id, alt, title, kind: "teams"|"custom", animated, staticUrl, animatedUrl, frames, frameMs, size, firstFrame, documentId}`;
        one entry per distinct emoji, however often it repeats. `size` is the sprite width to use: 50 for a message that is only emoji, else 30.
        Anything that looks like an emoji but is neither a valid Teams id nor a custom one is replaced by its alt text."""
        if not content or "emoji" not in content.lower():
            return content, []
        content = self._READONLY.sub(lambda m: m.group(1), content)
        entries: dict[tuple[str, str], dict] = {}

        def replace(match):
            tag = match.group(0)
            a = self._attrs(tag)
            raw_id = (a.get("id") if tag[:2].lower() == "<e" else a.get("itemid")) or ""
            alt = (a.get("alt") or "")[:self.MAX_ALT]
            title = (a.get("title") or "")[:self.MAX_TITLE]
            custom = "customemoji" in a.get("itemtype", "").lower() or ";" in raw_id
            if custom:
                found = self._custom_document(raw_id, a.get("src") or "")
                if not found:
                    return html.escape(alt, quote=False)
                shortcut, doc = found
                key = ("custom", doc)
                if key not in entries:
                    entries[key] = {"key": f"e{len(entries)}", "id": raw_id[:200] or doc, "alt": alt or shortcut, "title": title or shortcut, "kind": "custom", "animated": True, "staticUrl": None, "animatedUrl": None, "frames": None, "frameMs": None, "firstFrame": None, "documentId": doc}
            else:
                parsed = self.parse_ref(raw_id)
                if not parsed:
                    return html.escape(alt, quote=False)
                base, tone = parsed
                key = ("teams", raw_id)
                if key not in entries:
                    item = cat.by_id.get(base) if cat else None
                    entries[key] = {"key": f"e{len(entries)}", "id": raw_id, "alt": alt or (item or {}).get("unicode") or "", "title": title or (item or {}).get("title") or "", "kind": "teams", "item": item, "base": base, "tone": tone, "documentId": None}
            e = entries[key]
            return f'<emoji key="{e["key"]}" alt="{html.escape(e["alt"], quote=True)}">{html.escape(e["alt"])}</emoji>'

        content = self._EMOJI_ANY.sub(replace, content)
        if not entries:
            return content, []
        lowered = content.lower()
        bare = html.unescape(self._TAG.sub("", self._EMOJI_OUT.sub("", content))).replace(chr(160), "")
        only_emoji = "<img" not in lowered and "<attachment" not in lowered and not bare.strip()
        size = self.BIG_SIZE if only_emoji else self.INLINE_SIZE
        out = []
        for e in entries.values():
            if e["kind"] == "teams":
                item, base, tone = e.pop("item"), e.pop("base"), e.pop("tone")
                animated = bool(item and item["animated"]) and not (item["diverse"] is False and tone)
                etag = item["etag"] if item else None
                e.update({"animated": animated, "staticUrl": self.asset_url(base, size, False, tone, etag), "animatedUrl": self.asset_url(base, size, True, tone, etag) if animated else None, "frames": item["frames"] if animated else 1, "frameMs": item["frameMs"] if animated else None, "firstFrame": item["firstFrame"] if animated else 1})
            e["size"] = size
            out.append(e)
        return content, out
