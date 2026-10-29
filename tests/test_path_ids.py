"""Ids that become upstream path segments may not carry dot segments, plain or encoded."""

import pytest
from fastapi.testclient import TestClient

from src import config, outnote_client
from src.app import app

H = {config.REFRESH_TOKEN_HEADER: "old-frt"}
BAD = ["..", ".", "a..b", "%2E%2E", "%252E%252E"]


@pytest.fixture
def calls(monkeypatch):
    seen = []

    class Note:
        def __getattr__(self, name):
            def record(*args, **kwargs):
                seen.append((name, args))
                return []
            return record

    class Broker:
        refresh_token = "old-frt"

    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (Note(), Broker()))
    return seen


@pytest.mark.parametrize("bad", BAD)
def test_the_shared_validator_refuses_dot_segments(bad):
    from fastapi import HTTPException
    from src.app import GRAPH_ID_PATTERN, _check_id
    for value in (bad, f"a/{bad}/b"):
        with pytest.raises(HTTPException):
            _check_id(value, GRAPH_ID_PATTERN, "id")


# A literal "." or ".." in a URL path is collapsed by the HTTP client before it is sent, so the routes are probed with the encoded and embedded forms.
@pytest.mark.parametrize("bad", ["a..b", "%2E%2E", "%252E%252E", "x%2F..%2Fy"])
def test_dot_ids_are_refused_on_every_path_route(calls, bad):
    client = TestClient(app)
    for url in (f"/api/chats/{bad}/messages", f"/api/chats/{bad}/photo", f"/api/mail/{bad}", f"/api/mail/m1/attachments/{bad}", f"/api/users/{bad}/photo", f"/api/chats/c1/messages/{bad}/files/a1", f"/api/chats/c1/messages/1/files/{bad}"):
        r = client.get(url, headers=H)
        assert r.status_code in (400, 404), (url, r.status_code)
    for hosted in (bad, f"a/{bad}/b"):
        assert client.get(f"/api/chats/c1/messages/1/hostedContents/{hosted}", headers=H).status_code in (400, 404)
    assert client.get("/api/mail", headers=H, params={"folder": bad}).status_code == 400
    assert client.post("/api/mail/m1/move", headers=H, json={"folder": bad}).status_code in (400, 422)
    assert calls == []


@pytest.mark.parametrize("path", ["root:/../x:", "root:/a/./b:", "items/%2E%2E", "a/../b"])
def test_file_paths_with_dot_segments_are_refused(calls, path):
    assert TestClient(app).get("/api/files", headers=H, params={"path": path}).status_code == 400
    assert calls == []


def test_ordinary_ids_still_pass(calls):
    client = TestClient(app)
    assert client.get("/api/mail", headers=H, params={"folder": "AAMkADk=-_"}).status_code == 200
    assert client.get("/api/files", headers=H, params={"path": "root:/Schule/IDPA:"}).status_code == 200
    assert client.get("/api/chats/19:ac9223@thread.v2/messages", headers=H).status_code == 200
