"""Chat message HTML: a strict allowlist sanitizer for what the composer sends, and the media and
file references pulled out of what Graph returns.

Sending: only formatting tags survive, with no attributes except `a[href]` (http, https, mailto),
`at[id]` for a mention the request declares, `img[src]` pointing at one of the request's own
inline images (`../hostedContents/{n}/$value`), and `emoji[id]` for an id in the Teams emoji catalogue, rewritten to exactly
what Teams sends (`<emoji id="..." alt="..." title="..."></emoji>`, alt and title taken from the catalogue, never from the
request). Everything else is dropped (the text inside an
unknown tag is kept and escaped; script/style/template contents are dropped whole).
"""

import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


class _Sanitizer(HTMLParser):
    def __init__(self, mention_ids: set[int], image_ids: set[int], emoji_lookup=None):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skip = 0
        self.mention_ids = mention_ids
        self.image_ids = image_ids
        self.used_mentions: set[int] = set()
        self.used_images: set[int] = set()
        self.emoji_lookup = emoji_lookup
        self.emoji_count = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ChatHtmlSanitizer.DROP_CONTENT:
            self.skip += 1
            return
        if self.skip:
            return
        attrs = dict(attrs)
        if tag == "a":
            href = ChatHtmlSanitizer._safe_href(attrs.get("href"))
            self.out.append(f'<a href="{html.escape(href, quote=True)}">' if href else "<a>")
            self.open.append(tag)
        elif tag == "at":
            mid = ChatHtmlSanitizer._int(attrs.get("id"))
            if mid is not None and mid in self.mention_ids:
                self.out.append(f'<at id="{mid}">')
                self.used_mentions.add(mid)
                self.open.append(tag)
        elif tag == "emoji":
            ref = attrs.get("id")
            found = self.emoji_lookup(ref) if self.emoji_lookup and isinstance(ref, str) and self.emoji_count < ChatHtmlSanitizer.MAX_EMOJIS else None
            if found:
                alt, title = found
                self.out.append(f'<emoji id="{ref}" alt="{html.escape(alt, quote=True)}" title="{html.escape(title, quote=True)}"></emoji>')
                self.emoji_count += 1
        elif tag == "img":
            m = ChatHtmlSanitizer.HOSTED_SRC.fullmatch(attrs.get("src") or "")
            if m and int(m.group(1)) in self.image_ids:
                n = int(m.group(1))
                self.out.append(f'<img src="../hostedContents/{n}/$value">')
                self.used_images.add(n)
        elif tag in ChatHtmlSanitizer.VOID:
            self.out.append(f"<{tag}>")
        elif tag in ChatHtmlSanitizer.ALLOWED:
            self.out.append(f"<{tag}>")
            self.open.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ChatHtmlSanitizer.DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag in ChatHtmlSanitizer.VOID or tag not in self.open:
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


class ChatHtmlSanitizer:
    """The chat composer's HTML allowlist and the media, files and cards inside a Graph chat message."""

    ALLOWED = {"b", "strong", "i", "em", "u", "s", "strike", "br", "p", "div", "span", "ul", "ol", "li", "a", "code", "pre", "blockquote"}
    VOID = {"br"}
    DROP_CONTENT = {"script", "style", "template", "noscript", "iframe", "object", "embed", "svg", "math", "head", "title", "textarea", "select"}
    LINK_SCHEMES = ("http", "https", "mailto")
    MAX_EMOJIS = 100
    HOSTED_SRC = re.compile(r"\.\./hostedContents/(\d{1,2})/\$value")
    _IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
    _ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
    _HOSTED_PATH = re.compile(r"/(?:v1\.0|beta)/chats/[^/]+/messages/[^/]+/hostedContents/([^/?#]+)/\$value")
    GRAPH_HOST = "graph.microsoft.com"
    # Exact hosts only (no suffix matching): Giphy's and Tenor's media CDNs, and the sticker hosts seen in received sticker cards.
    GIF_HOSTS = frozenset({"media.giphy.com", "media0.giphy.com", "media1.giphy.com", "media2.giphy.com", "media3.giphy.com", "media4.giphy.com", "i.giphy.com", "media.tenor.com", "media1.tenor.com", "c.tenor.com"})
    STICKER_HOSTS = frozenset({"stickers.newfuture.cc"})
    GIPHY_ITEMTYPE = "http://schema.skype.com/Giphy"
    QUOTE_KINDS = {"forwardedMessageReference": "forward", "messageReference": "reply"}
    QUOTE_SENDER_NAME_FIELDS = ("originalSenderDisplayName", "senderDisplayName", "messageSenderDisplayName")
    QUOTE_SENDER_FIELDS = ("originalSender", "messageSender", "sender", "from")
    QUOTE_TIME_FIELDS = ("originalSentDateTime", "originalCreatedDateTime", "originalMessageDateTime", "originalMessageTime", "sentDateTime", "createdDateTime", "originalArrivalTime")
    QUOTE_BODY_FIELDS = ("originalMessageContent", "originalContent", "originalMessage", "messageContent", "content", "body", "originalMessagePreview", "messagePreview", "preview")
    MAX_QUOTE_FIELD_CHARS = 300
    CARD_PREFIX = "application/vnd.microsoft.card."
    MAX_CARD_CHARS = 64 * 1024

    @staticmethod
    def _int(value):
        return int(value) if isinstance(value, str) and value.isdigit() and len(value) <= 2 else None

    @staticmethod
    def _safe_href(value) -> str | None:
        value = (value or "").strip()
        if not value or any(ord(ch) < 32 for ch in value):
            return None
        parts = urlsplit(value)
        if parts.scheme.lower() not in ChatHtmlSanitizer.LINK_SCHEMES:
            return None
        if parts.scheme.lower() != "mailto" and not parts.netloc:
            return None
        return value

    @staticmethod
    def sanitize(content: str, mention_ids: set[int] = frozenset(), image_ids: set[int] = frozenset(), emoji_lookup=None) -> tuple[str, set[int], set[int]]:
        """(clean HTML, mention ids it references, inline image ids it references). `emoji_lookup(id)` returns (alt, title) for a catalogue emoji id, else None."""
        parser = _Sanitizer(set(mention_ids), set(image_ids), emoji_lookup)
        parser.feed(content)
        return parser.result(), parser.used_mentions, parser.used_images

    @staticmethod
    def text_to_html(text: str) -> str:
        return html.escape(text, quote=False).replace("\r\n", "\n").replace("\n", "<br>")

    @staticmethod
    def _attrs(tag: str) -> dict[str, str]:
        return {m.group(1).lower(): html.unescape(m.group(2) if m.group(2) is not None else m.group(3)) for m in ChatHtmlSanitizer._ATTR.finditer(tag)}

    @staticmethod
    def _size(value) -> int | None:
        try:
            n = round(float(value))
        except (TypeError, ValueError):
            return None
        return n if 0 < n <= 4096 else None

    @staticmethod
    def _https_host(url: str, hosts: frozenset) -> bool:
        try:
            parts = urlsplit(url or "")
            port = parts.port
        except ValueError:
            return False
        return parts.scheme == "https" and port in (None, 443) and not parts.username and not parts.password and (parts.hostname or "").lower() in hosts

    @staticmethod
    def is_gif_host(url: str) -> bool:
        return ChatHtmlSanitizer._https_host(url, ChatHtmlSanitizer.GIF_HOSTS)

    @staticmethod
    def hosted_content_id(src: str) -> str | None:
        """The hosted-content id when `src` is exactly a Graph hosted-content URL, else None."""
        if not ChatHtmlSanitizer._https_host(src, frozenset({ChatHtmlSanitizer.GRAPH_HOST})):
            return None
        m = ChatHtmlSanitizer._HOSTED_PATH.fullmatch(urlsplit(src).path)
        return m.group(1) if m else None

    @staticmethod
    def media(message: dict) -> list[dict]:
        """Images the body shows, in order: [{kind, url, hostedContentId, alt, width, height}].

        kind "hosted": a pasted image held by Graph; `url` is null and `hostedContentId` is the id the web
        passes to the plugin's media proxy. kind "gif": a Giphy/Tenor GIF; `url` is the public media URL
        (exact allowlisted hosts, https only). Other images (emoji, external) are left out."""
        content = (message.get("body") or {}).get("content") or ""
        out, seen = [], set()
        for tag in ChatHtmlSanitizer._IMG_TAG.findall(content):
            a = ChatHtmlSanitizer._attrs(tag)
            src = a.get("src") or ""
            if src in seen:
                continue
            hosted = ChatHtmlSanitizer.hosted_content_id(src)
            if hosted:
                item = {"kind": "hosted", "url": None, "hostedContentId": hosted}
            elif ChatHtmlSanitizer.is_gif_host(src):
                item = {"kind": "gif", "url": src, "hostedContentId": None}
            else:
                continue
            seen.add(src)
            item.update({"alt": (a.get("alt") or "")[:300] or None, "width": ChatHtmlSanitizer._size(a.get("width")), "height": ChatHtmlSanitizer._size(a.get("height"))})
            out.append(item)
        return out

    @staticmethod
    def reference_files(message: dict) -> list[dict]:
        """Files shared into the chat (reference attachments): [{id, name, contentUrl}] (type and size are filled in separately)."""
        out = []
        for a in message.get("attachments") or []:
            if a.get("contentType") == "reference" and a.get("contentUrl"):
                out.append({"id": a.get("id"), "name": a.get("name"), "contentUrl": a.get("contentUrl")})
        return out

    @staticmethod
    def quotes(message: dict) -> list[dict]:
        """Forwarded messages and replies, which arrive as attachments: [{kind: "forward"|"reply", senderName, sentAt, content, contentType}], with no ids.

        Graph documents only that a forward's `content` holds "the original message context", so several names are read. `content` goes to the client's message sanitizer like a message body."""
        out = []
        for a in message.get("attachments") or []:
            kind = ChatHtmlSanitizer.QUOTE_KINDS.get(a.get("contentType"))
            if kind is None:
                continue
            raw = a.get("content")
            parsed = raw if isinstance(raw, dict) else None
            if isinstance(raw, str) and len(raw) <= ChatHtmlSanitizer.MAX_CARD_CHARS:
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = None
            if not isinstance(parsed, dict):
                parsed = {}
            content, content_type = ChatHtmlSanitizer._quote_content(parsed)
            quote = {"kind": kind, "senderName": ChatHtmlSanitizer._quote_sender(parsed), "sentAt": ChatHtmlSanitizer._first_text(parsed, ChatHtmlSanitizer.QUOTE_TIME_FIELDS), "content": content, "contentType": content_type}
            if content is None and parsed:
                quote["unread"] = sorted(k for k in parsed if isinstance(k, str) and k.isalnum())[:30]
            out.append(quote)
        return out

    @staticmethod
    def _first_text(values: dict, names: tuple[str, ...]) -> str | None:
        return next((v[:ChatHtmlSanitizer.MAX_QUOTE_FIELD_CHARS] for v in (values.get(n) for n in names) if isinstance(v, str) and v.strip()), None)

    @staticmethod
    def _quote_sender(values: dict) -> str | None:
        name = ChatHtmlSanitizer._first_text(values, ChatHtmlSanitizer.QUOTE_SENDER_NAME_FIELDS)
        if name:
            return name
        for field_name in ChatHtmlSanitizer.QUOTE_SENDER_FIELDS:
            sender = values.get(field_name)
            if isinstance(sender, str) and sender.strip():
                return sender[:ChatHtmlSanitizer.MAX_QUOTE_FIELD_CHARS]
            if isinstance(sender, dict):
                for who in (sender.get("user"), sender.get("application"), sender):
                    name = ChatHtmlSanitizer._first_text(who, ("displayName",)) if isinstance(who, dict) else None
                    if name:
                        return name
        return None

    @staticmethod
    def _quote_content(values: dict) -> tuple[str | None, str]:
        for name in ChatHtmlSanitizer.QUOTE_BODY_FIELDS:
            body = values.get(name)
            if isinstance(body, dict):
                kind, body = str(body.get("contentType") or "").lower(), body.get("content")
            else:
                kind = str(values.get(name + "Type") or values.get("contentType") or "").lower()
            if isinstance(body, str) and body.strip():
                is_html = kind == "html" or (kind != "text" and "<" in body and ">" in body)
                return body[:ChatHtmlSanitizer.MAX_CARD_CHARS], "html" if is_html else "text"
        return None, "text"

    @staticmethod
    def cards(message: dict) -> list[dict]:
        """Card attachments (adaptive cards, polls, sticker apps, link previews): [{id, contentType, teamsAppId, name, content, sticker}].

        `content` is the parsed card JSON for a read-only render (null when it isn't JSON or is too large);
        `sticker` is {url, alt} when the card is a single image (sticker apps send those), else null."""
        out = []
        for a in message.get("attachments") or []:
            ctype = a.get("contentType") or ""
            if not ctype.startswith(ChatHtmlSanitizer.CARD_PREFIX):
                continue
            raw = a.get("content")
            parsed = None
            if isinstance(raw, str) and len(raw) <= ChatHtmlSanitizer.MAX_CARD_CHARS:
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = None
            elif isinstance(raw, dict):
                parsed = raw
            out.append({"id": a.get("id"), "contentType": ctype, "teamsAppId": a.get("teamsAppId"), "name": a.get("name"), "content": parsed, "sticker": ChatHtmlSanitizer._sticker(parsed)})
        return out

    @staticmethod
    def _sticker(card) -> dict | None:
        if not isinstance(card, dict) or card.get("type") != "AdaptiveCard":
            return None
        body = card.get("body")
        if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], dict) or body[0].get("type") != "Image":
            return None
        url = body[0].get("url")
        if not isinstance(url, str) or not (ChatHtmlSanitizer._https_host(url, ChatHtmlSanitizer.STICKER_HOSTS) or ChatHtmlSanitizer.is_gif_host(url)):
            return None
        return {"url": url, "alt": body[0].get("altText")}

    @staticmethod
    def gif_html(url: str, alt: str | None, width: int | None, height: int | None) -> str:
        """The markup Teams itself sends for a GIF picked from its GIF tab."""
        size = "".join(f' {k}="{v}"' for k, v in (("width", width), ("height", height)) if v)
        return f'<img alt="{html.escape(alt or "GIF", quote=True)}"{size} src="{html.escape(url, quote=True)}" itemtype="{ChatHtmlSanitizer.GIPHY_ITEMTYPE}" style="height:auto; margin-top:4px; max-width:100%">'
