"""Chat message HTML: a strict allowlist sanitizer for what the composer sends, and the media and
file references pulled out of what Graph returns.

Sending: only formatting tags survive, with no attributes except `a[href]` (http, https, mailto),
`at[id]` for a mention the request declares, and `img[src]` pointing at one of the request's own
inline images (`../hostedContents/{n}/$value`). Everything else is dropped (the text inside an
unknown tag is kept and escaped; script/style/template contents are dropped whole).
"""

import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED = {"b", "strong", "i", "em", "u", "s", "strike", "br", "p", "div", "span", "ul", "ol", "li", "a", "code", "pre", "blockquote"}
VOID = {"br"}
DROP_CONTENT = {"script", "style", "template", "noscript", "iframe", "object", "embed", "svg", "math", "head", "title", "textarea", "select"}
LINK_SCHEMES = ("http", "https", "mailto")
HOSTED_SRC = re.compile(r"\.\./hostedContents/(\d{1,2})/\$value")


class _Sanitizer(HTMLParser):
    def __init__(self, mention_ids: set[int], image_ids: set[int]):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skip = 0
        self.mention_ids = mention_ids
        self.image_ids = image_ids
        self.used_mentions: set[int] = set()
        self.used_images: set[int] = set()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip:
            return
        attrs = dict(attrs)
        if tag == "a":
            href = _safe_href(attrs.get("href"))
            self.out.append(f'<a href="{html.escape(href, quote=True)}">' if href else "<a>")
            self.open.append(tag)
        elif tag == "at":
            mid = _int(attrs.get("id"))
            if mid is not None and mid in self.mention_ids:
                self.out.append(f'<at id="{mid}">')
                self.used_mentions.add(mid)
                self.open.append(tag)
        elif tag == "img":
            m = HOSTED_SRC.fullmatch(attrs.get("src") or "")
            if m and int(m.group(1)) in self.image_ids:
                n = int(m.group(1))
                self.out.append(f'<img src="../hostedContents/{n}/$value">')
                self.used_images.add(n)
        elif tag in VOID:
            self.out.append(f"<{tag}>")
        elif tag in ALLOWED:
            self.out.append(f"<{tag}>")
            self.open.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag in VOID or tag not in self.open:
            return
        # Close everything opened after it too, so the output always nests.
        while self.open:
            top = self.open.pop()
            self.out.append(f"</{top}>")
            if top == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        self.close()
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def _int(value):
    return int(value) if isinstance(value, str) and value.isdigit() and len(value) <= 2 else None


def _safe_href(value) -> str | None:
    value = (value or "").strip()
    if not value or any(ord(ch) < 32 for ch in value):
        return None
    parts = urlsplit(value)
    if parts.scheme.lower() not in LINK_SCHEMES:
        return None
    if parts.scheme.lower() != "mailto" and not parts.netloc:
        return None
    return value


def sanitize(content: str, mention_ids: set[int] = frozenset(), image_ids: set[int] = frozenset()) -> tuple[str, set[int], set[int]]:
    """(clean HTML, mention ids it references, inline image ids it references)."""
    parser = _Sanitizer(set(mention_ids), set(image_ids))
    parser.feed(content)
    return parser.result(), parser.used_mentions, parser.used_images


def text_to_html(text: str) -> str:
    return html.escape(text, quote=False).replace("\r\n", "\n").replace("\n", "<br>")


# --- what Graph returns ------------------------------------------------------
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_HOSTED = re.compile(r"/chats/[^/]+/messages/[^/]+/hostedContents/([^/?#]+)/\$value")
GIF_HOSTS = (".giphy.com", ".tenor.com", ".tenor.googleapis.com")
GIPHY_ITEMTYPE = "http://schema.skype.com/Giphy"
CARD_PREFIX = "application/vnd.microsoft.card."
MAX_CARD_CHARS = 64 * 1024


def _attrs(tag: str) -> dict[str, str]:
    return {m.group(1).lower(): html.unescape(m.group(2) if m.group(2) is not None else m.group(3)) for m in _ATTR.finditer(tag)}


def _size(value) -> int | None:
    try:
        n = round(float(value))
    except (TypeError, ValueError):
        return None
    return n if 0 < n <= 4096 else None


def is_gif_host(url: str) -> bool:
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host.endswith(h) or host == h[1:] for h in GIF_HOSTS)


def media(message: dict) -> list[dict]:
    """Images the body shows, in order: [{kind, url, hostedContentId, alt, width, height}].

    kind "hosted": a pasted image held by Graph; `url` is the src exactly as it appears in the body and
    `hostedContentId` the id for the hosted-content proxy. kind "gif": a Giphy/Tenor GIF; `url` is the
    public media URL (only those hosts pass). Other images (emoji, external) are left out."""
    content = (message.get("body") or {}).get("content") or ""
    out, seen = [], set()
    for tag in _IMG_TAG.findall(content):
        a = _attrs(tag)
        src = a.get("src") or ""
        if src in seen:
            continue
        hosted = _HOSTED.search(src)
        if hosted:
            item = {"kind": "hosted", "url": src, "hostedContentId": hosted.group(1)}
        elif is_gif_host(src):
            item = {"kind": "gif", "url": src, "hostedContentId": None}
        else:
            continue
        seen.add(src)
        item.update({"alt": (a.get("alt") or "")[:300] or None, "width": _size(a.get("width")), "height": _size(a.get("height"))})
        out.append(item)
    return out


def reference_files(message: dict) -> list[dict]:
    """Files shared into the chat (reference attachments): [{id, name, contentUrl}] (type and size are filled in separately)."""
    out = []
    for a in message.get("attachments") or []:
        if a.get("contentType") == "reference" and a.get("contentUrl"):
            out.append({"id": a.get("id"), "name": a.get("name"), "contentUrl": a.get("contentUrl")})
    return out


def cards(message: dict) -> list[dict]:
    """Card attachments (adaptive cards, polls, sticker apps, link previews): [{id, contentType, teamsAppId, name, content, sticker}].

    `content` is the parsed card JSON for a read-only render (null when it isn't JSON or is too large);
    `sticker` is {url, alt} when the card is a single image (sticker apps send those), else null."""
    out = []
    for a in message.get("attachments") or []:
        ctype = a.get("contentType") or ""
        if not ctype.startswith(CARD_PREFIX):
            continue
        raw = a.get("content")
        parsed = None
        if isinstance(raw, str) and len(raw) <= MAX_CARD_CHARS:
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
        elif isinstance(raw, dict):
            parsed = raw
        out.append({"id": a.get("id"), "contentType": ctype, "teamsAppId": a.get("teamsAppId"), "name": a.get("name"), "content": parsed, "sticker": _sticker(parsed)})
    return out


def _sticker(card) -> dict | None:
    if not isinstance(card, dict) or card.get("type") != "AdaptiveCard":
        return None
    body = card.get("body")
    if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], dict) or body[0].get("type") != "Image":
        return None
    url = body[0].get("url")
    if not isinstance(url, str) or urlsplit(url).scheme != "https":
        return None
    return {"url": url, "alt": body[0].get("altText")}


def gif_html(url: str, alt: str | None, width: int | None, height: int | None) -> str:
    """The markup Teams itself sends for a GIF picked from its GIF tab."""
    size = "".join(f' {k}="{v}"' for k, v in (("width", width), ("height", height)) if v)
    return f'<img alt="{html.escape(alt or "GIF", quote=True)}"{size} src="{html.escape(url, quote=True)}" itemtype="{GIPHY_ITEMTYPE}" style="height:auto; margin-top:4px; max-width:100%">'
