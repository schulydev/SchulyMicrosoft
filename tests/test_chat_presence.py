import pytest
from fastapi.testclient import TestClient
from outnote import GraphError

from src.api.app import app
from tests.services import config, outnote_client

H = {config.REFRESH_TOKEN_HEADER: "frt-1"}
CHAT = "19:o@unq.gbl.spaces"


class Broker:
    refresh_token = "frt-1"

    def __call__(self, *args):
        return "token"


class Note:
    def __init__(self):
        self.chat = {"chatType": "oneOnOne", "members": [{"userId": "me-id"}, {"userId": "bo"}]}
        self.asked = []
        self.chat_reads = 0
        self.refusal = None

    def me(self):
        return {"id": "me-id"}

    def get(self, path, params=None, retry=True):
        assert path == f"chats/{CHAT}" and params == {"$expand": "members"} and retry is False
        self.chat_reads += 1
        return self.chat

    def presences(self, ids):
        self.asked.append(ids)
        if self.refusal:
            raise GraphError(self.refusal, "no")
        return [{"id": ids[0], "availability": "Busy", "activity": "InACall"}]


@pytest.fixture
def note(monkeypatch):
    n, broker = Note(), Broker()
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (n, broker))
    return n


def _get():
    return TestClient(app).get(f"/api/chats/{CHAT}/presence", headers=H)


def test_a_one_on_one_chat_answers_the_other_persons_status_and_caches_it(note):
    assert _get().json() == {"availability": "Busy", "activity": "InACall"}
    _get()
    assert note.asked == [["bo"]] and note.chat_reads == 1


@pytest.mark.parametrize("chat", [
    {"chatType": "group", "members": [{"userId": "me-id"}, {"userId": "bo"}]},
    {"chatType": "oneOnOne", "members": [{"userId": "me-id"}]},
    {"chatType": "oneOnOne", "members": [{"userId": "me-id"}, {"userId": "bo"}, {"userId": "al"}]},
])
def test_any_other_chat_asks_for_nobody(note, chat):
    note.chat = chat
    assert _get().json() == {"availability": None, "activity": None}
    assert note.asked == []


@pytest.mark.parametrize("status", [403, 429])
def test_a_refusal_means_no_status_rather_than_an_error(note, status):
    note.refusal = status
    r = _get()
    assert r.status_code == 200 and r.json() == {"availability": None, "activity": None}
    _get()
    assert len(note.asked) == 1  # not asked again right away


def test_a_bad_chat_id_is_refused(note):
    assert TestClient(app).get("/api/chats/not%20a%20chat/presence", headers=H).status_code in (400, 404, 422)
    assert note.asked == []
