"""OneNote: ids, the page sanitizer, ink, and the routes over a fake Graph."""

import json

import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src import config, onenote, onenote_html, outnote_client
from src.account_cache import AccountCache
from src.app import app

GROUP = "3f2a9c10-1111-4222-8333-944455556666"
H = {config.REFRESH_TOKEN_HEADER: "old-frt"}
RES = "https://graph.microsoft.com/v1.0/groups('x')/onenote/resources/{}/$value"

PAGE = f"""<html lang="de-CH"><head><title>Week one</title><style>body{{background:url(https://evil.test/x)}}</style></head>
<body data-absolute-enabled="true" style="font-family:Calibri;font-size:11pt">
<img id="img:{{1}}" alt="Blockzeiten" width="793.5" height="1122.5" src="{RES.format('0-small!1-a')}" data-fullres-src="{RES.format('0-full!1-a')}" data-fullres-src-type="image/png" style="position:absolute;left:24px;top:91px" />
<div id="div:{{A}}{{1}}" style="position:absolute;left:48px;top:120px;width:624px">
<h1 onclick="steal()">Week <i>one</i></h1>
<p style="color:#c00;background-image:url(https://evil.test/t);font-weight:bold">Read the <b>brief</b> and <a href="https://example.test/x" onclick="steal()">the link</a>.<script>alert(1)</script></p>
<p><a href="javascript:alert(1)">bad link</a></p>
<p data-tag="to-do:completed">done</p>
<table><tr><th colspan="2">a</th><td rowspan="x">b</td></tr></table>
</div>
<div id="div:{{B}}{{2}}" style="position:absolute;left:700px;top:10px;width:200px"><p>with file</p>
<object data-attachment="Aufgabe.pdf" type="application/pdf" data="{RES.format('0-doc!1-a')}"/></div>
<div id="div:{{C}}{{3}}" style="position:absolute;left:5px;top:600px"><p>Nur Text</p></div>
<img src="https://evil.test/onenote/resources/0-x!1-a/$value" />
<iframe src="https://evil.test"></iframe>
</body></html>"""


# --- ids -------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1-5bb0ce61-ea45-401f-91f1-1aabe0e5a031", "0-abc!1-def", f"{GROUP}@1-abc!2-def", "div:{a}{1}"])
def test_ids_that_are_accepted(value):
    assert onenote.is_id(value)


@pytest.mark.parametrize("value", ["", "a/b", "..", "a..b", "x@1-abc", f"{GROUP}@{GROUP}@1-a", f"{GROUP}@", "1-a?x=1", "1-a%2F", "a" * 301, "1 a"])
def test_ids_that_are_refused(value):
    assert not onenote.is_id(value)


def test_a_scoped_id_names_the_team_root():
    group, graph_id = onenote.parse_id(f"{GROUP.upper()}@1-abc")
    assert (group, graph_id) == (GROUP, "1-abc")
    assert onenote.root(group) == f"groups/{GROUP}/onenote"
    assert onenote.root(None) == "me/onenote"


# --- sanitizer -------------------------------------------------------------------------------


def test_a_page_becomes_safe_markup_with_places_kept():
    page = onenote_html.render_page(PAGE, None, GROUP)
    out = page["html"]
    assert page["title"] == "Week one"
    for forbidden in ("alert", "onclick", "steal", "javascript", "<script", "<style", "evil.test", "url(", "graph.microsoft.com", "<iframe", "<object", "src="):
        assert forbidden not in out, forbidden
    assert 'href="https://example.test/x"' in out and 'rel="noopener noreferrer"' in out
    assert "bad link" in out
    assert "color:#c00" in out and "font-weight:bold" in out
    assert 'data-tag="to-do:completed"' in out
    assert 'colspan="2"' in out and "rowspan" not in out
    assert f'data-resource="{GROUP}@0-full!1-a"' in out
    assert 'style="position:absolute;left:24px;top:91px"' in out
    assert 'style="position:absolute;left:48px;top:120px;width:624px"' in out
    assert page["width"] >= 793 and page["height"] >= 1122


def test_resources_are_listed_by_scoped_id_and_only_from_graphs_host():
    page = onenote_html.render_page(PAGE, None, GROUP)
    assert page["resources"] == [
        {"id": f"{GROUP}@0-full!1-a", "kind": "image", "name": None, "contentType": "image/png"},
        {"id": f"{GROUP}@0-doc!1-a", "kind": "file", "name": "Aufgabe.pdf", "contentType": "application/pdf"},
    ]
    assert onenote_html.resource_id("https://graph.microsoft.com.evil.test/v1.0/me/onenote/resources/0-a/$value") is None
    assert onenote_html.resource_id("http://graph.microsoft.com/v1.0/me/onenote/resources/0-a/$value") is None
    assert onenote_html.resource_id("https://user@graph.microsoft.com/v1.0/me/onenote/resources/0-a/$value") is None
    assert onenote_html.resource_id("https://graph.microsoft.com/v1.0/me/onenote/resources/0-a/$value") == "0-a"


def test_only_a_box_of_plain_text_is_editable():
    outlines = {o["id"]: o for o in onenote_html.render_page(PAGE)["outlines"]}
    # The first box had a script, the second holds a file: both are shown and never written over.
    assert outlines["div:{A}{1}"]["editable"] is False
    assert outlines["div:{B}{2}"]["editable"] is False
    assert outlines["div:{C}{3}"]["editable"] is True
    assert outlines["div:{C}{3}"]["html"].strip() == "<p>Nur Text</p>"
    assert 'data-outline="div:{C}{3}" data-editable="true"' in onenote_html.render_page(PAGE)["html"]
    assert onenote_html.outline_style(PAGE, "div:{C}{3}") == "position:absolute;left:5px;top:600px"
    assert onenote_html.outline_style(PAGE, "div:{B}{2}") is None
    assert onenote_html.outline_style(PAGE, "div:{Z}{9}") is None


def test_what_is_written_is_cut_down_to_text_formatting():
    out = onenote_html.sanitize_for_write('<p style="color:red;position:absolute;left:0">Hi <b>there</b><br><img src="x"><script>x()</script><a href="javascript:x">j</a><a href="https://a.test">a</a></p><ul><li>one</li></ul><foo>kept</foo>')
    assert out == '<p style="color:red">Hi <b>there</b><br/><a>j</a><a href="https://a.test">a</a></p><ul><li>one</li></ul>kept'
    assert onenote_html.new_page("A <b>", None) == "<!DOCTYPE html><html><head><title>A &lt;b&gt;</title></head><body></body></html>"


INK = """<?xml version="1.0" encoding="utf-8"?>
<inkml:ink xmlns:inkml="http://www.w3.org/2003/InkML"><inkml:definitions>
<inkml:brush xml:id="{b}{1}"><inkml:brushProperty name="width" value="100" units="himetric" /><inkml:brushProperty name="color" value="#E71225" /><inkml:brushProperty name="transparency" value="0" /></inkml:brush>
<inkml:brush xml:id="{b}{2}"><inkml:brushProperty name="color" value="javascript:x" /><inkml:brushProperty name="rasterOp" value="maskPen" /><inkml:brushProperty name="transparency" value="127" /></inkml:brush>
</inkml:definitions><inkml:traceGroup>
<inkml:trace xml:id="t1" contextRef="#c" brushRef="#{b}{1}">0 0 10, 2540 0 10, '0 '2540 10</inkml:trace>
<inkml:trace xml:id="t2" contextRef="#c" brushRef="#{b}{2}">0 1270 5</inkml:trace>
<inkml:trace brushRef="#nope">1 1</inkml:trace>
</inkml:traceGroup></inkml:ink>"""


def test_ink_becomes_svg_paths_in_page_pixels():
    svg, width, height = onenote_html.ink_svg(INK)
    assert 'd="M0.0 0.0l0.1 0L96.0 0.0L96.0 96.0"' in svg
    assert 'stroke="#E71225"' in svg and 'stroke-width="3.8"' in svg
    # A colour that is not a colour is not carried; a highlighter is see-through.
    assert "javascript" not in svg and 'stroke="#333333"' in svg and "mix-blend-mode:multiply" in svg
    assert (width, height) == (104.0, 104.0)
    assert onenote_html.ink_svg("<inkml:ink/>") is None


def test_the_multipart_answer_is_split_into_html_and_ink():
    body = "--abc\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><body><!-- InkNode is not supported --></body></html>\r\n--abc\r\nContent-Type: application/inkml+xml\r\n\r\n<inkml:ink/>\r\n--abc--\r\n"
    page, ink = onenote_html.split_parts(body)
    assert page.startswith("<html>") and onenote_html.has_ink(page) and ink == "<inkml:ink/>"
    assert onenote_html.split_parts("<html/>") == ("<html/>", None)


# --- routes over a fake Graph ----------------------------------------------------------------


class FakeNote:
    def __init__(self):
        self.calls = []
        self.patched = None
        self.posted = None
        self.deleted = None
        self.role = "Owner"
        self.filter_fails = False
        self.content = PAGE

    def list(self, path, params=None, limit=None, client=None, **_):
        self.calls.append(("list", path, params))
        if path == "me/joinedTeams":
            return [{"id": GROUP, "displayName": "Class 3a"}, {"id": "not-a-guid", "displayName": "x"}]
        if path == "me/onenote/notebooks":
            return [{"id": "1-nb", "displayName": "Mine", "userRole": "Owner", "isDefault": True, "links": {"oneNoteWebUrl": {"href": "https://onenote.test/nb"}}}]
        if path == f"groups/{GROUP}/onenote/notebooks":
            return [{"id": "1-class", "displayName": "Class notebook", "userRole": "Reader", "links": {"oneNoteWebUrl": {"href": "javascript:x"}}}]
        if path == f"groups/{GROUP}/onenote/sections":
            return [
                {"id": "1-s1", "displayName": "Welcome", "parentNotebook": {"id": "1-class"}, "parentSectionGroup": None},
                {"id": "1-s2", "displayName": "Week 1", "parentNotebook": {"id": "1-class"}, "parentSectionGroup": {"id": "1-g2"}},
                {"id": "1-other", "displayName": "Elsewhere", "parentNotebook": {"id": "1-zzz"}, "parentSectionGroup": None},
            ]
        if path == f"groups/{GROUP}/onenote/sectionGroups":
            return [
                {"id": "1-g1", "displayName": "Students", "parentNotebook": {"id": "1-class"}, "parentSectionGroup": None},
                {"id": "1-g2", "displayName": "Alex", "parentNotebook": {"id": "1-class"}, "parentSectionGroup": {"id": "1-g1"}},
            ]
        if path == "me/onenote/sections":
            return [{"id": "1-ms", "displayName": "Notes", "parentNotebook": {"id": "1-nb"}, "parentSectionGroup": {"id": "1-pg"}}]
        if path == "me/onenote/sectionGroups":
            raise AssertionError("the personal collection of all groups is not asked")
        if path == "me/onenote/notebooks/1-nb/sectionGroups":
            return [{"id": "1-pg", "displayName": "School"}]
        if path == "me/onenote/sectionGroups/1-pg/sectionGroups":
            return []
        if path.endswith("/pages") and "$filter" in (params or {}):
            if self.filter_fails:
                raise GraphError(400, "The number of maximum sections is exceeded for this request.")
            return [{"id": "1-p1", "title": "Week plan", "parentSection": {"id": "1-s2", "displayName": "Week 1"}, "parentNotebook": {"id": "1-class", "displayName": "Class notebook"}}, {"id": "1-p9", "title": "Plan", "parentNotebook": {"id": "1-other"}}]
        if path.endswith("/sections/1-s1/pages"):
            return [{"id": "1-p5", "title": "Planning"}, {"id": "1-p6", "title": "Other"}]
        if path == "me/onenote/sections/1-ms/pages":
            return [{"id": "1-mp", "title": "My plan"}]
        if path.endswith("/sections/1-s2/pages"):
            return [{"id": "1-p7", "title": "Lesson plan"}]
        raise AssertionError(path)

    def get(self, path, params=None, raw=False, client=None, **_):
        self.calls.append(("get", path, params))
        if path.endswith("/content"):
            if params.get("includeInkML"):
                return f"--b1\r\nContent-Type: text/html\r\n\r\n{self.content}\r\n--b1\r\nContent-Type: application/inkml+xml\r\n\r\n{INK}\r\n--b1--"
            return self.content
        if "/pages/" in path:
            return {"id": "1-p1", "title": "Week one", "links": {"oneNoteWebUrl": {"href": "https://onenote.test/p"}}, "parentSection": {"id": "1-s2", "displayName": "Week 1"}, "parentNotebook": {"id": "1-class", "displayName": "Class notebook", "userRole": self.role}}
        if path.endswith("/pages"):
            return {"value": [{"id": "1-p1", "title": "A", "level": 0, "order": 0}, {"id": "1-p2", "title": "", "level": 1, "order": 1}], "@odata.nextLink": "https://graph.microsoft.com/next"}
        raise AssertionError(path)

    def post(self, path, body=None, client=None, content_type=None, **_):
        self.posted = (path, body, content_type)
        return {"id": "1-new", "title": "Fresh", "links": {"oneNoteWebUrl": {"href": "https://onenote.test/new"}}}

    def patch(self, path, body, client=None, **_):
        self.patched = (path, body)

    def delete(self, path, client=None, **_):
        self.deleted = path


class FakeBroker:
    def __init__(self):
        self.refresh_token = "old-frt"
        self.cache = AccountCache()


@pytest.fixture
def graph(monkeypatch):
    note, broker = FakeNote(), FakeBroker()

    def build(frt):
        broker.refresh_token = "rotated-frt"
        return note, broker

    monkeypatch.setattr(outnote_client, "build_client", build)
    return note


def client():
    return TestClient(app)


def test_notebooks_are_the_persons_own_then_each_teams(graph):
    r = client().get("/api/onenote/notebooks", headers=H)
    assert r.status_code == 200 and r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    mine, team = r.json()
    assert mine["id"] == "1-nb" and mine["source"] == {"kind": "personal", "id": None, "name": None} and mine["writable"] and mine["webUrl"] == "https://onenote.test/nb"
    assert team["id"] == f"{GROUP}@1-class" and team["source"] == {"kind": "team", "id": GROUP, "name": "Class 3a"}
    assert team["writable"] is False and team["webUrl"] is None
    # Kept a short while: a second list asks Graph nothing.
    before = len(graph.calls)
    client().get("/api/onenote/notebooks", headers=H)
    assert len(graph.calls) == before


def test_the_section_tree_nests_groups_and_keeps_only_the_notebooks_own(graph):
    r = client().get(f"/api/onenote/notebooks/{GROUP}@1-class/sections", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["notebookId"] == f"{GROUP}@1-class"
    welcome, students = body["children"]
    assert (welcome["kind"], welcome["displayName"], welcome["id"]) == ("section", "Welcome", f"{GROUP}@1-s1")
    assert students["kind"] == "group" and students["children"][0]["displayName"] == "Alex"
    assert students["children"][0]["children"][0]["id"] == f"{GROUP}@1-s2"
    assert "Elsewhere" not in json.dumps(body)


def test_pages_are_paged_with_select_and_levels(graph):
    r = client().get(f"/api/onenote/sections/{GROUP}@1-s2/pages", headers=H, params={"top": 2, "skip": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["nextSkip"] == 6
    assert [(p["id"], p["level"]) for p in body["items"]] == [(f"{GROUP}@1-p1", 0), (f"{GROUP}@1-p2", 1)]
    kind, path, params = graph.calls[-1]
    assert path == f"groups/{GROUP}/onenote/sections/1-s2/pages" and params["$top"] == 2 and params["$skip"] == 4 and params["pagelevel"] == "true" and "$select" in params
    assert client().get("/api/onenote/sections/x/pages", headers=H, params={"top": 101}).status_code == 422


def test_a_page_comes_sanitized_with_resources_outlines_and_ink(graph):
    graph.content = PAGE.replace("<p>Nur Text</p>", "<p>Nur Text</p><!-- InkNode is not supported -->")
    r = client().get(f"/api/onenote/pages/{GROUP}@1-p1", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Week one" and body["writable"] is True and body["webUrl"] == "https://onenote.test/p"
    assert body["section"] == {"id": f"{GROUP}@1-s2", "displayName": "Week 1"}
    assert body["hasInk"] is True and '<svg class="on-ink"' in body["html"]
    assert len(body["resources"]) == 2 and len(body["outlines"]) == 3
    assert "alert" not in body["html"]


@pytest.mark.parametrize("path", ["/api/onenote/pages/..", "/api/onenote/pages/a..b", "/api/onenote/pages/not-a-guid@1-a", "/api/onenote/notebooks/a%2Fb/sections", "/api/onenote/resources/x@y"])
def test_bad_ids_are_refused_before_graph(graph, path):
    r = client().get(path, headers=H)
    assert r.status_code in (400, 404)
    assert graph.calls == []


def test_an_update_sends_title_outline_and_append_commands(graph):
    r = client().patch(f"/api/onenote/pages/{GROUP}@1-p1", headers=H, json={"title": "New <title>", "outlines": [{"id": "div:{C}{3}", "html": "<p>Neu <b>fett</b><script>x</script></p>"}], "append": "<p>More</p>"})
    assert r.status_code == 200
    path, commands = graph.patched
    assert path == f"groups/{GROUP}/onenote/pages/1-p1/content"
    assert commands == [
        {"target": "title", "action": "replace", "content": "New &lt;title&gt;"},
        {"target": "div:{C}{3}", "action": "replace", "content": '<div style="position:absolute;left:5px;top:600px"><p>Neu <b>fett</b></p></div>'},
        {"target": "body", "action": "append", "content": "<div><p>More</p></div>"},
    ]
    assert r.json()["id"] == f"{GROUP}@1-p1"


def test_a_box_with_more_than_text_is_never_written_over(graph):
    r = client().patch(f"/api/onenote/pages/{GROUP}@1-p1", headers=H, json={"outlines": [{"id": "div:{B}{2}", "html": "<p>x</p>"}]})
    assert r.status_code == 400 and graph.patched is None
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"


def test_a_read_only_notebook_refuses_writes(graph):
    graph.role = "Reader"
    r = client().patch(f"/api/onenote/pages/{GROUP}@1-p1", headers=H, json={"title": "x"})
    assert r.status_code == 403 and graph.patched is None


def test_update_bodies_are_capped(graph):
    r = client().patch(f"/api/onenote/pages/{GROUP}@1-p1", headers=H, json={"append": "x" * (1024 * 1024 + 1)})
    assert r.status_code == 413
    r = client().patch(f"/api/onenote/pages/{GROUP}@1-p1", headers=H, json={"outlines": [{"id": "div:{C}{3}", "html": "x"}] * 51})
    assert r.status_code == 422
    r = client().patch(f"/api/onenote/pages/{GROUP}@1-p1", headers=H, json={"outlines": [{"id": "../x", "html": "x"}]})
    assert r.status_code == 400


def test_create_posts_xhtml_and_delete_deletes(graph):
    r = client().post(f"/api/onenote/sections/{GROUP}@1-s2/pages", headers=H, json={"title": "Fresh", "html": "<p>Hi<img src=x onerror=y></p>"})
    assert r.status_code == 201
    assert r.json()["id"] == f"{GROUP}@1-new" and r.json()["sectionId"] == f"{GROUP}@1-s2"
    path, body, content_type = graph.posted
    assert path == f"groups/{GROUP}/onenote/sections/1-s2/pages" and content_type == "application/xhtml+xml"
    assert body == "<!DOCTYPE html><html><head><title>Fresh</title></head><body><div><p>Hi</p></div></body></html>"
    r = client().delete(f"/api/onenote/pages/{GROUP}@1-p1", headers=H)
    assert r.status_code == 204 and graph.deleted == f"groups/{GROUP}/onenote/pages/1-p1"
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt"
    assert client().post(f"/api/onenote/sections/{GROUP}@1-s2/pages", headers=H, json={"title": ""}).status_code == 422


def test_search_filters_titles_in_one_notebook(graph):
    r = client().get("/api/onenote/search", headers=H, params={"q": "pl'an", "notebook": f"{GROUP}@1-class"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"items": [{"id": f"{GROUP}@1-p1", "title": "Week plan", "lastModifiedDateTime": None, "webUrl": None, "section": {"id": f"{GROUP}@1-s2", "displayName": "Week 1"}, "notebook": {"id": f"{GROUP}@1-class", "displayName": "Class notebook"}}], "partial": False}
    params = next(p for k, path, p in graph.calls if "$filter" in (p or {}))
    assert params["$filter"] == "contains(tolower(title),'pl''an')"


def test_search_walks_the_sections_of_a_notebook_too_big_for_the_filter(graph):
    graph.filter_fails = True
    r = client().get("/api/onenote/search", headers=H, params={"q": "plan", "notebook": f"{GROUP}@1-class"})
    assert r.status_code == 200
    body = r.json()
    assert [h["title"] for h in body["items"]] == ["Planning", "Lesson plan"] or [h["title"] for h in body["items"]] == ["Lesson plan", "Planning"]
    assert body["items"][0]["notebook"]["displayName"] == "Class notebook" and body["partial"] is False


def test_search_everywhere_marks_a_team_it_could_not_search(graph):
    graph.filter_fails = True
    r = client().get("/api/onenote/search", headers=H, params={"q": "plan"})
    body = r.json()
    # The person's own sections are walked instead; the class notebook is left for a notebook-scoped search.
    assert r.status_code == 200 and [h["title"] for h in body["items"]] == ["My plan"] and body["partial"] is True
    assert body["items"][0]["notebook"] == {"id": "1-nb", "displayName": "Mine"}
    assert client().get("/api/onenote/search", headers=H, params={"q": "   "}).status_code == 400


def test_resources_serve_only_images_inline_and_files_as_downloads(graph, monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    monkeypatch.setattr(onenote, "resource", lambda broker, rid, limit: png if "img" in rid else b"%PDF-1.7")
    r = client().get(f"/api/onenote/resources/{GROUP}@0-img!1-a", headers=H)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.headers["cache-control"] == "no-store"
    assert r.headers[config.REFRESH_TOKEN_HEADER] == "rotated-frt" and r.headers["x-content-type-options"] == "nosniff"
    r = client().get(f"/api/onenote/resources/{GROUP}@0-doc!1-a", headers=H)
    assert r.status_code == 415
    r = client().get(f"/api/onenote/resources/{GROUP}@0-doc!1-a", headers=H, params={"kind": "file", "name": "Auf/gabe.pdf"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"] == "attachment; filename*=UTF-8''Auf_gabe.pdf" and "sandbox" in r.headers["content-security-policy"]
    assert client().get(f"/api/onenote/resources/{GROUP}@0-doc!1-a", headers=H, params={"kind": "html"}).status_code == 400


def test_an_oversized_resource_is_refused(graph, monkeypatch):
    def too_big(broker, rid, limit):
        raise onenote.ResourceTooLarge()

    monkeypatch.setattr(onenote, "resource", too_big)
    assert client().get("/api/onenote/resources/0-a", headers=H).status_code == 413


def test_onenote_refusals_keep_their_meaning(graph, monkeypatch):
    def refuse(note, section, top, skip):
        raise GraphError(422, "Sync of this section is not supported.")

    monkeypatch.setattr(onenote, "pages", refuse)
    r = client().get("/api/onenote/sections/1-s/pages", headers=H)
    assert r.status_code == 422 and "Sync of this section" in r.json()["detail"]


def test_a_write_drops_the_kept_lists(graph):
    client().get("/api/onenote/notebooks", headers=H)
    client().delete("/api/onenote/pages/1-p1", headers=H)
    before = len(graph.calls)
    client().get("/api/onenote/notebooks", headers=H)
    assert len(graph.calls) > before


def test_a_personal_notebooks_groups_are_walked_not_listed_whole(graph):
    r = client().get("/api/onenote/notebooks/1-nb/sections", headers=H)
    assert r.status_code == 200
    (school,) = r.json()["children"]
    assert school["kind"] == "group" and school["children"][0]["id"] == "1-ms"
