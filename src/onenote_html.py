"""OneNote page HTML, in both directions, and the page's ink.

Reading is the sanitising step. A page is parsed into a small tree and rebuilt from an allowlist:
nothing of the page's own markup is passed through. Scripts, styles, event attributes, forms and
every tag outside the list are dropped (the text inside an unknown tag is kept), styles keep only a
few text properties with plain values, links keep only http, https and mailto, and positioned items
(OneNote's text boxes, pictures and files) keep only a numeric left, top and width.

Pictures and attached files are OneNote resources behind the account's token. Their address is
never handed out: an `img` keeps only `data-resource` (the resource id, scoped like every other id)
and the caller fetches the bytes through the resource route. Ink, which Graph only sends as InkML
in a second multipart part, becomes inline SVG path data.

Writing (a new page, a replaced text box, appended text) goes through the same allowlist with no
styles beyond simple text formatting, and comes out as the XHTML OneNote takes.

A text box is editable only when it holds nothing but text: replacing a box with a picture, a file
or ink in it would drop them, so such a box is shown and never written over.
"""

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

TEXT_TAGS = {"p", "div", "span", "b", "strong", "i", "em", "u", "s", "strike", "del", "sub", "sup", "a", "br", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "pre", "code", "blockquote", "cite"}
VOID = {"br", "img", "hr", "meta", "link", "input", "col", "area", "base", "wbr", "source", "param", "embed"}
DROP_CONTENT = {"script", "style", "head", "title", "template", "noscript", "iframe", "frame", "frameset", "svg", "math", "canvas", "video", "audio", "form", "button", "select", "textarea", "applet", "embed", "xml"}
LINK_SCHEMES = ("http", "https", "mailto")
STYLE_PROPS = {"color", "background-color", "font-family", "font-size", "font-weight", "font-style", "text-decoration", "text-align", "vertical-align", "margin-top", "margin-bottom", "margin-left", "line-height", "border", "border-width", "border-style", "border-color", "border-collapse", "padding", "width"}
WRITE_STYLE_PROPS = {"color", "background-color", "font-weight", "font-style", "text-decoration", "text-align"}
STYLE_VALUE = re.compile(r"[#\w\s.,%'\"()+-]{1,100}")
STYLE_BLOCKED = ("url", "expression", "javascript", "image", "attr(", "var(", "env(")
NUMBER = re.compile(r"-?\d{1,6}(?:\.\d{1,3})?")
TAG_VALUE = re.compile(r"[a-z0-9:,-]{1,60}")
CONTENT_TYPE = re.compile(r"[a-z0-9][\w.+-]{0,126}/[a-z0-9][\w.+-]{0,126}")
COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
# The ids OneNote gives page elements (`div:{guid}{n}`) and its resources (`0-abc!1-def`).
SAFE_ID = re.compile(r"[A-Za-z0-9!_{}:.\-]{1,200}")
RESOURCE_PATH = re.compile(r"/onenote/resources/([A-Za-z0-9!_{}:.\-]{1,200})/(?:\$value|content)$")
GRAPH_HOST = "graph.microsoft.com"
MAX_ALT = 2000
MAX_NAME = 255
# Ink bounds: a page drawn on for a whole lesson is thousands of strokes; past these the rest is left out.
MAX_TRACES = 5000
MAX_POINTS = 400_000
PX_PER_HIMETRIC = 96.0 / 2540.0
BOX_WIDTH = 600
BOX_HEIGHT = 120


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.children: list = []


class _Tree(HTMLParser):
    """A forgiving tree builder: OneNote's markup is regular, and anything that is not is closed where it can be."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag.lower(), {k.lower(): (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if node.tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag.lower(), {k.lower(): (v or "") for k, v in attrs}))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _parse(markup: str) -> _Node:
    tree = _Tree()
    tree.feed(markup)
    tree.close()
    return tree.root


def _find(node: _Node, tag: str) -> _Node | None:
    for child in node.children:
        if isinstance(child, _Node):
            if child.tag == tag:
                return child
            found = _find(child, tag)
            if found is not None:
                return found
    return None


def _text(node: _Node) -> str:
    return "".join(c if isinstance(c, str) else _text(c) for c in node.children)


def safe_href(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value or len(value) > 2000 or any(ord(ch) < 32 for ch in value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in LINK_SCHEMES or (scheme != "mailto" and not parts.netloc):
        return None
    return value


def _style(value: str | None, allowed: set[str]) -> str:
    out = []
    for rule in (value or "").split(";"):
        name, sep, val = rule.partition(":")
        name, val = name.strip().lower(), val.strip()
        if not sep or name not in allowed or not STYLE_VALUE.fullmatch(val) or any(b in val.lower() for b in STYLE_BLOCKED):
            continue
        out.append(f"{name}:{val}")
    return ";".join(out)


def _length(style: str | None, prop: str) -> float | None:
    """A number of CSS px out of `left:48px;top:12pt` (a pt value is scaled)."""
    for rule in (style or "").split(";"):
        name, sep, val = rule.partition(":")
        if sep and name.strip().lower() == prop:
            val = val.strip().lower()
            unit = "pt" if val.endswith("pt") else ""
            number = val.removesuffix("px").removesuffix("pt").strip()
            if NUMBER.fullmatch(number):
                px = float(number) * (96.0 / 72.0 if unit == "pt" else 1.0)
                return round(px, 1)
    return None


def _attr_number(value: str | None) -> float | None:
    value = (value or "").strip().removesuffix("px")
    return round(float(value), 1) if NUMBER.fullmatch(value) else None


def _num(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def scoped(scope: str | None, graph_id: str) -> str:
    """An id handed out: bare for the person's own OneNote, `<group>@<id>` for a team's."""
    return f"{scope}@{graph_id}" if scope else graph_id


def resource_id(url: str | None) -> str | None:
    """The resource id in a Graph resource address, accepted only from Graph's own https host."""
    if not url or len(url) > 2000:
        return None
    try:
        parts = urlsplit(html.unescape(url))
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or (parts.hostname or "").lower() != GRAPH_HOST or port not in (None, 443) or parts.username or parts.password:
        return None
    match = RESOURCE_PATH.search(parts.path)
    return match.group(1) if match and SAFE_ID.fullmatch(match.group(1)) else None


def element_id(node: _Node) -> str | None:
    """The id a PATCH can target: the one OneNote generated (`includeIDs=true`)."""
    for name in ("id", "data-id"):
        value = node.attrs.get(name)
        if value and SAFE_ID.fullmatch(value):
            return value
    return None


def text_only(node: _Node) -> bool:
    return all(isinstance(c, str) or (c.tag in TEXT_TAGS and text_only(c)) for c in node.children)


class _Render:
    def __init__(self, scope: str | None, write: bool = False):
        self.scope = scope
        self.write = write
        self.resources: dict[str, dict] = {}

    def children(self, node: _Node) -> str:
        return "".join(self.node(c) for c in node.children)

    def node(self, node) -> str:
        if isinstance(node, str):
            return html.escape(node, quote=False)
        tag = node.tag
        if tag in DROP_CONTENT:
            return ""
        if tag == "img":
            return "" if self.write else self.image(node, positioned=False)
        if tag == "object":
            return "" if self.write else self.file(node, positioned=False)
        if tag not in TEXT_TAGS:
            return self.children(node)
        if tag == "br":
            return "<br/>" if self.write else "<br>"
        attrs = []
        if tag == "a":
            href = safe_href(node.attrs.get("href"))
            if href:
                attrs.append(f'href="{html.escape(href, quote=True)}"')
                if not self.write:
                    attrs.append('rel="noopener noreferrer"')
        if tag in ("td", "th"):
            for name in ("colspan", "rowspan"):
                value = node.attrs.get(name, "")
                if value.isdigit() and 1 <= int(value) <= 100:
                    attrs.append(f'{name}="{int(value)}"')
        tag_value = node.attrs.get("data-tag", "").lower()
        if tag_value and TAG_VALUE.fullmatch(tag_value) and tag in ("p", "li", "span", "div", "h1", "h2", "h3", "h4", "h5", "h6"):
            attrs.append(f'data-tag="{tag_value}"')
        style = _style(node.attrs.get("style"), WRITE_STYLE_PROPS if self.write else STYLE_PROPS)
        if style:
            attrs.append(f'style="{html.escape(style, quote=True)}"')
        head = f"<{tag} {' '.join(attrs)}>" if attrs else f"<{tag}>"
        return f"{head}{self.children(node)}</{tag}>"

    def _position(self, node: _Node, positioned: bool, width: float | None = None) -> str:
        if not positioned:
            return ""
        style = node.attrs.get("style")
        left, top = _length(style, "left") or 0.0, _length(style, "top") or 0.0
        parts = [f"position:absolute;left:{_num(left)}px;top:{_num(top)}px"]
        if width is not None:
            parts.append(f"width:{_num(width)}px")
        return f' style="{";".join(parts)}"'

    def image(self, node: _Node, positioned: bool) -> str:
        rid = resource_id(node.attrs.get("data-fullres-src")) or resource_id(node.attrs.get("src"))
        if rid is None:
            return ""
        sid = scoped(self.scope, rid)
        kind = (node.attrs.get("data-fullres-src-type") or node.attrs.get("data-src-type") or "").lower()
        self.resources.setdefault(sid, {"id": sid, "kind": "image", "name": None, "contentType": kind if CONTENT_TYPE.fullmatch(kind) else None})
        alt = (node.attrs.get("alt") or "")[:MAX_ALT]
        width, height = _attr_number(node.attrs.get("width")), _attr_number(node.attrs.get("height"))
        size = (f' width="{_num(width)}"' if width else "") + (f' height="{_num(height)}"' if height else "")
        return f'<img data-resource="{html.escape(sid, quote=True)}" alt="{html.escape(alt, quote=True)}"{size}{self._position(node, positioned)}>'

    def file(self, node: _Node, positioned: bool) -> str:
        rid = resource_id(node.attrs.get("data"))
        if rid is None:
            return ""
        sid = scoped(self.scope, rid)
        name = re.sub(r"[\x00-\x1f\x7f]", "", node.attrs.get("data-attachment") or "")[:MAX_NAME] or "file"
        kind = (node.attrs.get("type") or "").lower()
        self.resources.setdefault(sid, {"id": sid, "kind": "file", "name": name, "contentType": kind if CONTENT_TYPE.fullmatch(kind) else None})
        return f'<span class="on-file" data-resource="{html.escape(sid, quote=True)}"{self._position(node, positioned)}>{html.escape(name)}</span>'


def split_parts(body: str) -> tuple[str, str | None]:
    """The HTML and the InkML of an answer. With `includeInkML` Graph answers multipart, the HTML first; without, the HTML alone."""
    first = body.split("\n", 1)[0].strip()
    if not first.startswith("--") or len(first) < 3:
        return body, None
    page = ink = None
    for part in body.split(first):
        head, sep, rest = part.partition("\r\n\r\n")
        if not sep:
            head, sep, rest = part.partition("\n\n")
        if not sep:
            continue
        head = head.lower()
        if "text/html" in head and page is None:
            page = rest.strip().removesuffix("--").strip()
        elif "inkml" in head and ink is None:
            ink = rest.strip().removesuffix("--").strip()
    return page if page is not None else body, ink


def has_ink(page: str) -> bool:
    """OneNote only marks ink in the HTML; the strokes come with `includeInkML`."""
    return "InkNode is not supported" in page


def render_page(page: str, ink: str | None = None, scope: str | None = None) -> dict:
    """A page as sanitized markup, its resources, its text boxes and the size of its canvas."""
    root = _parse(page)
    title_node = _find(root, "title")
    title = re.sub(r"\s+", " ", _text(title_node)).strip() if title_node else ""
    body = _find(root, "body") or root
    render = _Render(scope)
    parts, outlines = [], []
    width = height = 0.0
    for child in body.children:
        if isinstance(child, str):
            parts.append(render.node(child))
            continue
        style = child.attrs.get("style")
        left, top = _length(style, "left"), _length(style, "top")
        positioned = left is not None or top is not None
        if child.tag == "div":
            oid = element_id(child)
            box_width = _length(style, "width")
            inner = render.children(child)
            editable = oid is not None and text_only(child)
            attrs = (f' data-outline="{html.escape(oid, quote=True)}" data-editable="{"true" if editable else "false"}"' if oid else "") + render._position(child, positioned, box_width)
            parts.append(f"<div{attrs}>{inner}</div>")
            if oid:
                outlines.append({"id": oid, "editable": editable, "html": inner})
            if positioned:
                width = max(width, (left or 0) + (box_width or BOX_WIDTH))
                height = max(height, (top or 0) + BOX_HEIGHT)
        elif child.tag == "img":
            parts.append(render.image(child, positioned))
            if positioned:
                width = max(width, (left or 0) + (_attr_number(child.attrs.get("width")) or 0))
                height = max(height, (top or 0) + (_attr_number(child.attrs.get("height")) or 0))
        elif child.tag == "object":
            parts.append(render.file(child, positioned))
            if positioned:
                width, height = max(width, (left or 0) + 240), max(height, (top or 0) + 40)
        else:
            parts.append(render.node(child))
    strokes = ink_svg(ink) if ink else None
    if strokes:
        svg, ink_w, ink_h = strokes
        parts.append(svg)
        width, height = max(width, ink_w), max(height, ink_h)
    return {
        "title": title,
        "html": "".join(parts),
        "width": int(width + 24) if width else 0,
        "height": int(height + 24) if height else 0,
        "resources": list(render.resources.values()),
        "outlines": outlines,
        "hasInk": has_ink(page),
    }


def outline_style(page: str, outline: str) -> str | None:
    """The place of one editable text box of the current page (`position:absolute;left;top;width`), or None when it is not one."""
    body = _find(_parse(page), "body")
    for child in body.children if body else []:
        if isinstance(child, _Node) and child.tag == "div" and element_id(child) == outline:
            if not text_only(child):
                return None
            style = child.attrs.get("style")
            left, top, width = _length(style, "left"), _length(style, "top"), _length(style, "width")
            if left is None and top is None:
                return ""
            out = f"position:absolute;left:{_num(left or 0)}px;top:{_num(top or 0)}px"
            return out + (f";width:{_num(width)}px" if width else "")
    return None


def sanitize_for_write(markup: str) -> str:
    """Rich text from the editor, cut down to formatting OneNote keeps, as XHTML. No pictures, files or positions."""
    return _Render(None, write=True).children(_parse(markup or ""))


def new_page(title: str, body: str | None) -> str:
    """The XHTML document a new page is created from."""
    content = f"<div>{sanitize_for_write(body)}</div>" if body and body.strip() else ""
    return f"<!DOCTYPE html><html><head><title>{html.escape(title, quote=False)}</title></head><body>{content}</body></html>"


# --- ink -------------------------------------------------------------------------------------


class _Ink(HTMLParser):
    """InkML read as tags: brushes with their properties, and traces with the brush they use. Parsed as markup, never as XML (no entities, no DTD)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.brushes: dict[str, dict] = {}
        self.brush: dict | None = None
        self.traces: list[tuple[str, list[str]]] = []
        self.trace: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = {k.lower(): v or "" for k, v in attrs}
        if tag == "inkml:brush":
            self.brush = {"color": "#333333", "width": 50.0, "opacity": 1.0, "highlight": False}
            self.brushes[attrs.get("xml:id", "")] = self.brush
        elif tag == "inkml:brushproperty" and self.brush is not None:
            name, value = attrs.get("name", "").lower(), attrs.get("value", "")
            if name == "color" and COLOR.fullmatch(value):
                self.brush["color"] = value
            elif name == "width" and NUMBER.fullmatch(value):
                self.brush["width"] = float(value)
            elif name == "transparency" and NUMBER.fullmatch(value):
                self.brush["opacity"] = min(1.0, max(0.05, 1.0 - float(value) / 255.0))
            elif name == "rasterop":
                self.brush["highlight"] = value.lower() == "maskpen"
        elif tag == "inkml:trace" and len(self.traces) < MAX_TRACES:
            self.trace = (attrs.get("brushref", "").lstrip("#"), [])
            self.traces.append(self.trace)

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == "inkml:brush":
            self.brush = None
        elif tag == "inkml:trace":
            self.trace = None

    def handle_data(self, data):
        if self.trace is not None:
            self.trace[1].append(data)


def _points(trace: str, budget: int) -> list[tuple[float, float]]:
    """The points of one trace (`x y f, x y f`), where a value may carry `'` (first difference) or `"` (second difference)."""
    out, value, speed = [], [0.0, 0.0], [0.0, 0.0]
    for sample in trace.split(","):
        if len(out) >= budget:
            break
        for channel, token in enumerate(sample.split()[:2]):
            kind = 1 if token.startswith("'") else 2 if token.startswith('"') else 0
            token = token.lstrip("'\"")
            try:
                number = float(token)
            except ValueError:
                continue
            if kind == 0:
                value[channel], speed[channel] = number, 0.0
            elif kind == 1:
                speed[channel] = number
                value[channel] += number
            else:
                speed[channel] += number
                value[channel] += speed[channel]
        out.append((value[0] * PX_PER_HIMETRIC, value[1] * PX_PER_HIMETRIC))
    return out


def ink_svg(xml: str) -> tuple[str, float, float] | None:
    """The strokes as one SVG of paths in page pixels, with its width and height; None when there are none."""
    reader = _Ink()
    try:
        reader.feed(xml)
        reader.close()
    except Exception:
        return None
    paths: dict[str, list[str]] = {}
    right = bottom = 0.0
    budget = MAX_POINTS
    for brush_id, chunks in reader.traces:
        if brush_id not in reader.brushes or budget <= 0:
            continue
        points = _points("".join(chunks), budget)
        budget -= len(points)
        d, last = [], None
        for x, y in points:
            if last and abs(x - last[0]) < 0.4 and abs(y - last[1]) < 0.4:
                continue
            d.append(f"{'L' if d else 'M'}{x:.1f} {y:.1f}" + ("" if d else "l0.1 0"))
            last = (x, y)
            right, bottom = max(right, x), max(bottom, y)
        if d:
            paths.setdefault(brush_id, []).append("".join(d))
    if not paths:
        return None
    width, height = round(right + 8), round(bottom + 8)
    out = [f'<svg class="on-ink" aria-hidden="true" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="position:absolute;left:0px;top:0px">']
    for brush_id, ds in paths.items():
        brush = reader.brushes[brush_id]
        stroke = max(0.5, round(brush["width"] * PX_PER_HIMETRIC, 1))
        opacity = round(min(brush["opacity"], 0.5) if brush["highlight"] else brush["opacity"], 2)
        blend = ' style="mix-blend-mode:multiply"' if brush["highlight"] else ""
        out.append(f'<path fill="none" stroke-linecap="round" stroke-linejoin="round" stroke="{brush["color"]}" stroke-width="{_num(stroke)}" opacity="{_num(opacity)}"{blend} d="{" ".join(ds)}"/>')
    out.append("</svg>")
    return "".join(out), float(width), float(height)


def plain_text(markup: str) -> str:
    """Visible text of sanitized markup (search snippets, tests)."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()
