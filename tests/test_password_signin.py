"""Password sign-in: start / method / otp / poll / cancel, with Entrance's Microsoft sign-in scripted
(no network). The scripted sign-in drives the job through the same MfaPrompt hooks Entrance uses."""

import json
import logging
import threading
import time

import entrance
import pytest
from entrance import MfaCancelled, MfaSwitch, PushEvent
from fastapi.testclient import TestClient

from src import outnote_client, password_signin
from src.app import app

PASSWORD = "Tr0ub4dor&3-never-leak-me"
USER = "alex@school.ch"
BOTH = ["push", "otp"]


class FakeNote:
    def me(self):
        return {"id": "user-1", "mail": USER, "displayName": "Alex Muster"}


class FakeBroker:
    def __init__(self, refresh_token="frt-new"):
        self.refresh_token = refresh_token


KEY = "test-service-key"
UID = "schuly-user-1"
HEADERS = {"X-Schuly-Service-Key": KEY, "X-Schuly-User-Id": UID}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("SCHULY_SERVICE_KEY", KEY)
    password_signin.store.clear()
    monkeypatch.setattr(outnote_client, "build_client", lambda frt: (FakeNote(), FakeBroker(frt)))
    yield
    password_signin.store.clear()


@pytest.fixture
def api():
    return TestClient(app, headers=HEADERS)


def scripted(monkeypatch, script):
    """Replace Entrance's sign-in: the password is 'submitted' (taken from the Secret), then `script(prompt)` plays Microsoft."""

    def login(username, secret, **kw):
        assert kw["cookies"] is None and kw["frt_store"] is None  # nothing persisted
        submitted = secret.take()
        assert submitted == PASSWORD
        del submitted
        return script(kw["mfa"])

    monkeypatch.setattr(password_signin.entrance, "foci_login", login)


def drive(prompt, offered, push=None, code=None, wrong=0):
    """Mirror of Entrance's interactive loop: choose -> push/otp, switch, retry."""
    while True:
        method = prompt.choose(list(offered))
        try:
            if method == "push":
                push(prompt)
                return FakeBroker()
            for attempt in range(1, 4):
                given = prompt.otp(attempt)
                if given == code:
                    return FakeBroker()
            raise entrance.OtpRejected("rejected", attempts=3)
        except MfaSwitch:
            continue
        except (entrance.PushError, entrance.OtpRejected) as ex:
            if not prompt.retry(ex):
                raise


def push_wait(approve, deny=None, number="42"):
    def push(prompt):
        prompt.on_push(PushEvent(entrance.NUMBER_MATCHING, number=number, expires_in=120))
        while True:
            if prompt.cancelled():
                raise MfaCancelled("cancelled")
            if prompt.should_switch():
                raise MfaSwitch()
            if deny is not None and deny.is_set():
                raise entrance.PushError("denied", state="denied")
            if approve.is_set():
                prompt.on_push(PushEvent(entrance.APPROVED))
                return
            time.sleep(0.01)

    return push


def start(api, username=USER, password=PASSWORD):
    return api.post("/api/auth/password/start", json={"username": username, "password": password})


def until(api, sign_in_id, status, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = api.get(f"/api/auth/password/{sign_in_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.02)
    raise AssertionError(f"never reached {status}; last: {body}")


# --- outcomes --------------------------------------------------------------------------------
def test_no_mfa_completes_straight_after_the_password(api, monkeypatch):
    scripted(monkeypatch, lambda prompt: FakeBroker())
    r = start(api)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete" and body["refresh_token"] == "frt-new"
    assert body["account"] == {"id": "user-1", "email": USER, "name": "Alex Muster"}
    assert body["sign_in_id"]


def test_push_approve(api, monkeypatch):
    approve = threading.Event()
    scripted(monkeypatch, lambda p: drive(p, BOTH, push=push_wait(approve)))
    body = start(api).json()
    assert body["status"] == "mfa_required" and body["methods"] == BOTH
    sid = body["sign_in_id"]

    pushed = api.post(f"/api/auth/password/{sid}/method", json={"method": "push"}).json()
    assert pushed["status"] == "push_pending" and pushed["number"] == "42"
    assert 0 < pushed["expires_in"] <= 120

    assert api.get(f"/api/auth/password/{sid}").json()["status"] == "push_pending"
    approve.set()
    done = until(api, sid, "complete")
    assert done["refresh_token"] == "frt-new" and done["account"]["email"] == USER


def test_only_offered_methods_are_listed_and_others_refused(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, ["otp"], code="123456"))
    body = start(api).json()
    assert body["methods"] == ["otp"]
    r = api.post(f"/api/auth/password/{body['sign_in_id']}/method", json={"method": "push"})
    assert r.status_code == 409 and r.json()["code"] == "method_unavailable"


def test_push_denied_then_try_again(api, monkeypatch):
    deny, approve = threading.Event(), threading.Event()
    rounds = []

    def push(prompt):
        rounds.append(1)
        (push_wait(approve, deny) if len(rounds) == 1 else push_wait(approve))(prompt)

    scripted(monkeypatch, lambda p: drive(p, BOTH, push=push))
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "push"})
    deny.set()
    denied = until(api, sid, "denied")
    assert denied["methods"] == BOTH
    again = api.post(f"/api/auth/password/{sid}/method", json={"method": "push"}).json()
    assert again["status"] == "push_pending"
    approve.set()
    assert until(api, sid, "complete")["refresh_token"] == "frt-new"


def test_push_timeout(api, monkeypatch):
    def push(prompt):
        prompt.on_push(PushEvent(entrance.NUMBER_MATCHING, number="7", expires_in=1))
        raise entrance.PushError("timed out", state="timed_out")

    scripted(monkeypatch, lambda p: drive(p, BOTH, push=push))
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "push"})
    assert until(api, sid, "timed_out")["methods"] == BOTH


def test_otp_ok(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, BOTH, code="654321"))
    sid = start(api).json()["sign_in_id"]
    r = api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"}).json()
    assert r["status"] == "otp_required" and r["attempts_left"] == 3
    done = api.post(f"/api/auth/password/{sid}/otp", json={"code": "654321"}).json()
    assert done["status"] == "complete" and done["refresh_token"] == "frt-new"


def test_otp_wrong_then_ok(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, BOTH, code="654321"))
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"})
    bad = api.post(f"/api/auth/password/{sid}/otp", json={"code": "111111"}).json()
    assert bad["status"] == "otp_invalid" and bad["attempts_left"] == 2
    good = api.post(f"/api/auth/password/{sid}/otp", json={"code": "654 321"}).json()
    assert good["status"] == "complete"


def test_otp_attempts_exhausted_returns_to_method_choice(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, BOTH, code="654321"))
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"})
    left = []
    for guess in ("111111", "222222", "333333"):
        r = api.post(f"/api/auth/password/{sid}/otp", json={"code": guess}).json()
        assert r["status"] == "otp_invalid"
        left.append(r["attempts_left"])
    assert left == [2, 1, 0]
    state = api.get(f"/api/auth/password/{sid}").json()
    assert state["status"] == "otp_invalid" and state["methods"] == BOTH
    again = api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"}).json()
    assert again["status"] == "otp_required" and again["attempts_left"] == 2  # job budget: 5 - 3


def test_switch_push_to_otp_and_back(api, monkeypatch):
    approve = threading.Event()
    scripted(monkeypatch, lambda p: drive(p, BOTH, push=push_wait(approve), code="654321"))
    sid = start(api).json()["sign_in_id"]
    assert api.post(f"/api/auth/password/{sid}/method", json={"method": "push"}).json()["status"] == "push_pending"
    switched = api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"}).json()
    assert switched["status"] == "otp_required"
    back = api.post(f"/api/auth/password/{sid}/method", json={"method": "push"}).json()
    assert back["status"] == "push_pending" and back["number"] == "42"
    approve.set()
    assert until(api, sid, "complete")


def test_method_to_the_current_method_is_a_no_op(api, monkeypatch):
    approve = threading.Event()
    scripted(monkeypatch, lambda p: drive(p, BOTH, push=push_wait(approve)))
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "push"})
    assert api.post(f"/api/auth/password/{sid}/method", json={"method": "push"}).json()["status"] == "push_pending"
    approve.set()


@pytest.mark.parametrize(
    "error, code",
    [
        (entrance.InvalidCredentials("Wrong username or password"), "invalid_credentials"),
        (entrance.FederatedAccount(redirect_url="https://adfs.school.ch/adfs"), "unsupported"),
        (entrance.UnsupportedMfa("only sms", offered=["OneWaySMS"]), "unsupported"),
        (entrance.Blocked("blocked", code="53003"), "blocked"),
        (entrance.LoginFailed("Stuck on a page"), "failed"),
        (entrance.TokenError("invalid_grant", "x"), "failed"),
    ],
)
def test_failures_map_to_stable_codes(api, monkeypatch, error, code):
    def fail(prompt):
        raise error

    scripted(monkeypatch, fail)
    body = start(api).json()
    assert body["status"] == "error" and body["code"] == code
    assert body["message"] == password_signin.MESSAGES[code]
    assert "refresh_token" not in body


def test_failure_after_choosing_a_method(api, monkeypatch):
    def script(prompt):
        prompt.choose(BOTH)
        raise entrance.Blocked("policy", code="53003")

    scripted(monkeypatch, script)
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "push"})
    assert until(api, sid, "error")["code"] == "blocked"


# --- jobs ----------------------------------------------------------------------------------------
def test_unknown_id_is_404(api):
    for r in (
        api.get("/api/auth/password/nope"),
        api.post("/api/auth/password/nope/method", json={"method": "push"}),
        api.post("/api/auth/password/nope/otp", json={"code": "123456"}),
    ):
        assert r.status_code == 404 and r.json()["status"] == "error" and r.json()["code"] == "not_found"
    assert api.delete("/api/auth/password/nope").status_code == 204


def test_expired_job_is_gone(api, monkeypatch):
    approve = threading.Event()
    scripted(monkeypatch, lambda p: drive(p, BOTH, push=push_wait(approve)))
    sid = start(api).json()["sign_in_id"]
    job = password_signin.store.get(sid, UID)
    job.expires = time.monotonic() - 1
    assert api.get(f"/api/auth/password/{sid}").status_code == 404
    assert len(password_signin.store) == 0


def test_sweeper_drops_expired_and_stale_finished_jobs(api, monkeypatch):
    scripted(monkeypatch, lambda p: FakeBroker())
    sid = start(api).json()["sign_in_id"]
    assert len(password_signin.store) == 1
    password_signin.store.get(sid, UID).done_at = time.monotonic() - password_signin.DONE_TTL - 1
    password_signin.store.sweep()
    assert len(password_signin.store) == 0


def test_ttl_is_capped_at_ten_minutes():
    assert password_signin.JOB_TTL <= 600


def test_delete_cancels_the_worker(api, monkeypatch):
    ended = threading.Event()

    def script(prompt):
        try:
            return drive(prompt, BOTH, push=push_wait(threading.Event()))
        except MfaCancelled:
            ended.set()
            raise

    scripted(monkeypatch, script)
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "push"})
    assert api.delete(f"/api/auth/password/{sid}").status_code == 204
    assert ended.wait(5)
    assert api.get(f"/api/auth/password/{sid}").status_code == 404


def test_cancel_while_waiting_for_the_method_choice(api, monkeypatch):
    ended = threading.Event()

    def script(prompt):
        try:
            return drive(prompt, BOTH)
        except MfaCancelled:
            ended.set()
            raise

    scripted(monkeypatch, script)
    sid = start(api).json()["sign_in_id"]
    api.delete(f"/api/auth/password/{sid}")
    assert ended.wait(5)


def test_a_new_sign_in_for_the_same_account_replaces_the_old_one(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, BOTH))
    first = start(api).json()["sign_in_id"]
    second = start(api).json()["sign_in_id"]
    assert first != second
    assert api.get(f"/api/auth/password/{first}").status_code == 404
    assert api.get(f"/api/auth/password/{second}").status_code == 200


def test_otp_before_asking_is_a_conflict(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, BOTH))
    sid = start(api).json()["sign_in_id"]
    r = api.post(f"/api/auth/password/{sid}/otp", json={"code": "123456"})
    assert r.status_code == 409 and r.json()["code"] == "invalid_state"


def test_malformed_code_is_rejected(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, BOTH, code="123456"))
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"})
    assert api.post(f"/api/auth/password/{sid}/otp", json={"code": "abcdef"}).status_code == 422


# --- rate limits -------------------------------------------------------------------------------------
def test_per_client_rate_limit(api, monkeypatch):
    monkeypatch.setattr(password_signin, "CLIENT_LIMIT", 2)
    scripted(monkeypatch, lambda p: FakeBroker())
    assert start(api, username="a@school.ch").status_code == 200
    assert start(api, username="b@school.ch").status_code == 200
    r = start(api, username="c@school.ch")
    assert r.status_code == 429 and r.json()["code"] == "rate_limited" and r.json()["status"] == "error"


def test_only_failed_attempts_count_against_the_account_limit(api, monkeypatch):
    monkeypatch.setattr(password_signin, "ACCOUNT_LIMIT", 2)
    scripted(monkeypatch, lambda p: FakeBroker())
    for _ in range(4):  # successes never count
        assert start(api).json()["status"] == "complete"

    def wrong(prompt):
        raise entrance.InvalidCredentials("no")

    scripted(monkeypatch, wrong)
    assert start(api).json()["code"] == "invalid_credentials"
    assert start(api).json()["code"] == "invalid_credentials"
    r = start(api)
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"
    assert start(api, username="other@school.ch").status_code == 200


def test_a_third_party_cannot_lock_a_victim_out(api, monkeypatch):
    monkeypatch.setattr(password_signin, "ACCOUNT_LIMIT", 2)

    def wrong(prompt):
        raise entrance.InvalidCredentials("no")

    scripted(monkeypatch, wrong)
    attacker = TestClient(app, headers={**HEADERS, "X-Schuly-User-Id": "attacker"})
    for _ in range(2):
        assert start(attacker).json()["code"] == "invalid_credentials"
    assert start(attacker).status_code == 429
    scripted(monkeypatch, lambda p: FakeBroker())
    assert start(api).json()["status"] == "complete"  # the victim has their own, untouched limit


def test_max_concurrent_jobs(api, monkeypatch):
    monkeypatch.setattr(password_signin, "MAX_JOBS", 1)
    scripted(monkeypatch, lambda p: drive(p, BOTH))
    assert start(api, username="a@school.ch").json()["status"] == "mfa_required"
    r = start(api, username="b@school.ch")
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"


def test_service_runs_a_single_uvicorn_process():
    import pathlib

    text = (pathlib.Path(__file__).parent.parent / "asgi.py").read_text()
    assert "workers=1" in text


# --- the password never sticks around -------------------------------------------------------------------
def reaches(obj, needle, seen=None, depth=0):
    """Does `needle` appear anywhere inside obj (recursing through containers and object attributes)?"""
    seen = set() if seen is None else seen
    if id(obj) in seen or depth > 12:
        return False
    seen.add(id(obj))
    if isinstance(obj, str):
        return needle in obj
    if isinstance(obj, (bytes, bytearray)):
        return needle.encode() in obj
    if isinstance(obj, dict):
        return any(reaches(k, needle, seen, depth + 1) or reaches(v, needle, seen, depth + 1) for k, v in obj.items())
    if isinstance(obj, (list, tuple, set, frozenset)):
        return any(reaches(v, needle, seen, depth + 1) for v in obj)
    if isinstance(obj, (threading.Condition, threading.Lock, threading.Event, int, float, bool, type(None))):
        return False
    attrs = dict(getattr(obj, "__dict__", {}))
    for cls in type(obj).__mro__:
        for slot in getattr(cls, "__slots__", ()):
            if hasattr(obj, slot):
                attrs[slot] = getattr(obj, slot)
    return any(reaches(v, needle, seen, depth + 1) for v in attrs.values())


def test_password_is_not_in_the_job_store_at_any_stage(api, monkeypatch):
    approve = threading.Event()
    scripted(monkeypatch, lambda p: drive(p, BOTH, push=push_wait(approve)))
    sid = start(api).json()["sign_in_id"]
    assert not reaches(password_signin.store, PASSWORD)
    api.post(f"/api/auth/password/{sid}/method", json={"method": "push"})
    assert not reaches(password_signin.store, PASSWORD)
    approve.set()
    until(api, sid, "complete")
    assert not reaches(password_signin.store, PASSWORD)
    assert not reaches(password_signin.store._jobs[sid], PASSWORD)


def test_reaches_helper_actually_finds_strings():
    class Holder:
        def __init__(self):
            self.inner = {"x": [PASSWORD]}

    assert reaches(Holder(), PASSWORD)


@pytest.mark.parametrize("fail_with", [None, "wrong", "leaky"])
def test_password_never_in_logs_or_responses(api, monkeypatch, caplog, fail_with):
    caplog.set_level(logging.DEBUG)
    seen = []

    def script(prompt):
        if fail_with == "wrong":
            raise entrance.InvalidCredentials("Wrong username or password")
        if fail_with == "leaky":  # even an exception that carries the password must not surface it
            raise entrance.LoginFailed(f"boom {PASSWORD}")
        return drive(prompt, BOTH, code="123456")

    scripted(monkeypatch, script)
    r = start(api)
    seen.append(r.text)
    if fail_with is None:
        sid = r.json()["sign_in_id"]
        seen.append(api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"}).text)
        seen.append(api.post(f"/api/auth/password/{sid}/otp", json={"code": "000000"}).text)
        seen.append(api.post(f"/api/auth/password/{sid}/otp", json={"code": "123456"}).text)
        seen.append(api.get(f"/api/auth/password/{sid}").text)
    for text in seen:
        assert PASSWORD not in text
    assert PASSWORD not in caplog.text
    assert not reaches(password_signin.store, PASSWORD)


def test_validation_errors_do_not_echo_the_password(api):
    r = api.post("/api/auth/password/start", json={"password": PASSWORD})  # username missing
    assert r.status_code == 422 and PASSWORD not in r.text
    assert r.json()["code"] == "invalid_request"
    r = api.post("/api/auth/password/start", json={"username": "x", "password": PASSWORD})  # username too short
    assert r.status_code == 422 and PASSWORD not in r.text
    r = api.post("/api/auth/password/start", content=b"{" + PASSWORD.encode(), headers={"content-type": "application/json"})
    assert r.status_code == 422 and PASSWORD not in r.text


def test_other_routes_keep_the_default_validation_body(api):
    r = api.post("/api/auth/browser/complete", json={})
    assert r.status_code == 422 and "detail" in r.json()


def test_password_model_never_reprs_the_password():
    from src.models import PasswordStartRequest

    model = PasswordStartRequest(username=USER, password=PASSWORD)
    assert PASSWORD not in repr(model) and PASSWORD not in model.model_dump_json()


def test_secret_is_spent_after_submit(api, monkeypatch):
    spent = []

    def login(username, secret, **kw):
        secret.take()
        spent.append(secret)
        return FakeBroker()

    monkeypatch.setattr(password_signin.entrance, "foci_login", login)
    assert start(api).json()["status"] == "complete"
    assert spent and not spent[0] and PASSWORD not in repr(spent[0])


# --- with the real Entrance underneath ---------------------------------------------------------------------
CALLBACK_CODE = "REAL-CODE"
MS = "https://login.microsoftonline.com/common"


class _Resp:
    def __init__(self, status=200, text="", headers=None, data=None, url=MS + "/authorize"):
        self.status_code, self.text, self.headers, self.url, self._data = status, text, headers or {}, url, data

    def json(self):
        return self._data


def _page(**cfg):
    base = {"sFT": "ft", "sCtx": "ctx", "canary": "can", "urlPost": MS + "/login"}
    base.update(cfg)
    return _Resp(text="<script>$Config=" + json.dumps(base) + ";</script>")


class _MsSession:
    """Just enough of Microsoft: credentials page, MFA page offering both methods, SAS, callback."""

    gate = threading.Event()  # the user taps the number once the test sets this
    good_code = "123456"

    def __init__(self, *a, **k):
        self.headers = {}
        self.cookies = type("J", (), {"jar": [], "set": lambda *a, **k: None})()
        self.polls = 0

    def get(self, url, **kw):
        return _page(urlGetCredentialType=MS + "/GetCredentialType")

    def post(self, url, json=None, data=None, headers=None, allow_redirects=None):
        if url.endswith("GetCredentialType"):
            return _Resp(data={"Credentials": {}, "IfExistsResult": 0})
        if url.endswith("/login"):
            ids = [{"authMethodId": "PhoneAppNotification"}, {"authMethodId": "PhoneAppOTP"}]
            return _page(urlPost=MS + "/ProcessAuth", urlBeginAuth=MS + "/SAS/BeginAuth", urlEndAuth=MS + "/SAS/EndAuth", arrUserProofs=ids)
        if url.endswith("BeginAuth"):
            if json["AuthMethodId"] == "PhoneAppNotification":
                return _Resp(data={"Success": True, "Entropy": 55, "SessionId": "S", "Ctx": "c", "FlowToken": "f"})
            return _Resp(data={"Success": True, "SessionId": "S", "Ctx": "c", "FlowToken": "f"})
        if url.endswith("EndAuth"):
            if json["AuthMethodId"] == "PhoneAppNotification":
                self.polls += 1
                if self.polls < 3 or not self.gate.is_set():
                    return _Resp(data={"Success": False, "Retry": True, "ResultValue": "AuthenticationPending"})
                return _Resp(data={"Success": True, "Ctx": "c", "FlowToken": "f"})
            ok = json["AdditionalAuthData"] == self.good_code
            return _Resp(data={"Success": ok, "ResultValue": "Success" if ok else "OathCodeIncorrect", "Ctx": "c", "FlowToken": "f"})
        if url.endswith("ProcessAuth"):
            return _Resp(302, headers={"location": f"https://login.microsoftonline.com/common/oauth2/nativeclient?code={CALLBACK_CODE}&state=" + self.state})
        raise AssertionError(url)

    state = ""


@pytest.fixture
def real_entrance(monkeypatch):
    import entrance._client as ec
    import entrance._foci as ef
    import entrance._push as ep

    class Session(_MsSession):
        def get(self, url, **kw):
            _MsSession.state = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))["state"]
            return super().get(url, **kw)

    monkeypatch.setattr(ec.requests, "Session", Session)
    _MsSession.gate = threading.Event()
    real_sleep = time.sleep
    monkeypatch.setattr(ep.time, "sleep", lambda s: real_sleep(0.005))
    monkeypatch.setattr(password_signin, "PUSH_INTERVAL", 0)
    monkeypatch.setattr(ef, "_post_token", lambda url, data: {"refresh_token": "real-frt", "access_token": "at"})


def test_real_entrance_push(api, real_entrance):
    body = start(api).json()
    assert body["status"] == "mfa_required" and body["methods"] == BOTH
    sid = body["sign_in_id"]
    pushed = api.post(f"/api/auth/password/{sid}/method", json={"method": "push"}).json()
    assert pushed["status"] == "push_pending" and pushed["number"] == "55"
    _MsSession.gate.set()
    done = until(api, sid, "complete")
    assert done["refresh_token"] == "real-frt" and done["account"]["email"] == USER
    assert not reaches(password_signin.store, PASSWORD)


def test_real_entrance_otp_wrong_then_ok(api, real_entrance):
    sid = start(api).json()["sign_in_id"]
    assert api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"}).json()["status"] == "otp_required"
    bad = api.post(f"/api/auth/password/{sid}/otp", json={"code": "000000"}).json()
    assert bad["status"] == "otp_invalid" and bad["attempts_left"] == 2
    assert api.post(f"/api/auth/password/{sid}/otp", json={"code": "123456"}).json()["status"] == "complete"


def test_real_entrance_switch_push_to_otp(api, real_entrance):
    sid = start(api).json()["sign_in_id"]
    assert api.post(f"/api/auth/password/{sid}/method", json={"method": "push"}).json()["status"] == "push_pending"
    assert api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"}).json()["status"] == "otp_required"
    assert api.post(f"/api/auth/password/{sid}/otp", json={"code": "123456"}).json()["status"] == "complete"


# --- who may call, and whose job it is -------------------------------------------------------------------
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Schuly-Service-Key": "wrong", "X-Schuly-User-Id": UID}, {"X-Schuly-Service-Key": KEY}, {"X-Schuly-Service-Key": KEY, "X-Schuly-User-Id": "bad id!"}],
)
def test_password_routes_need_the_service_key_and_a_user_id(monkeypatch, headers):
    scripted(monkeypatch, lambda p: pytest.fail("must not run"))
    bare = TestClient(app)
    body = {"username": USER, "password": PASSWORD}
    assert bare.post("/api/auth/password/start", json=body, headers=headers).status_code == 401
    assert bare.get("/api/auth/password/x", headers=headers).status_code == 401
    assert bare.delete("/api/auth/password/x", headers=headers).status_code == 401
    assert bare.post("/api/auth/password/x/method", json={"method": "push"}, headers=headers).status_code == 401
    assert bare.post("/api/auth/password/x/otp", json={"code": "123456"}, headers=headers).status_code == 401
    assert len(password_signin.store) == 0


def test_routes_are_disabled_when_no_service_key_is_configured(monkeypatch):
    monkeypatch.delenv("SCHULY_SERVICE_KEY")
    r = TestClient(app).post("/api/auth/password/start", json={"username": USER, "password": PASSWORD}, headers={"X-Schuly-Service-Key": "", "X-Schuly-User-Id": UID})
    assert r.status_code == 503 and PASSWORD not in r.text
    assert TestClient(app).get("/api/auth/password/x", headers=HEADERS).status_code == 503


def test_another_user_cannot_read_drive_or_cancel_a_job(api, monkeypatch):
    approve = threading.Event()
    scripted(monkeypatch, lambda p: drive(p, BOTH, push=push_wait(approve), code="123456"))
    sid = start(api).json()["sign_in_id"]
    other = TestClient(app, headers={**HEADERS, "X-Schuly-User-Id": "someone-else"})
    assert other.get(f"/api/auth/password/{sid}").status_code == 404
    assert other.post(f"/api/auth/password/{sid}/method", json={"method": "push"}).status_code == 404
    assert other.post(f"/api/auth/password/{sid}/otp", json={"code": "123456"}).status_code == 404
    assert other.delete(f"/api/auth/password/{sid}").status_code == 204
    assert api.get(f"/api/auth/password/{sid}").json()["status"] == "mfa_required"  # still alive and untouched


def test_starting_the_same_account_as_another_user_does_not_cancel_the_first_job(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, BOTH))
    first = start(api).json()["sign_in_id"]
    other = TestClient(app, headers={**HEADERS, "X-Schuly-User-Id": "someone-else"})
    second = start(other).json()["sign_in_id"]
    assert api.get(f"/api/auth/password/{first}").status_code == 200
    assert other.get(f"/api/auth/password/{second}").status_code == 200


def test_own_earlier_job_is_replaced_only_after_the_password_passed(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, BOTH))
    first = start(api).json()["sign_in_id"]

    def wrong(prompt):
        raise entrance.InvalidCredentials("no")

    scripted(monkeypatch, wrong)
    assert start(api).json()["code"] == "invalid_credentials"
    assert api.get(f"/api/auth/password/{first}").status_code == 200  # a failed attempt must not kill it
    scripted(monkeypatch, lambda p: drive(p, BOTH))
    third = start(api).json()["sign_in_id"]
    assert api.get(f"/api/auth/password/{first}").status_code == 404
    assert api.get(f"/api/auth/password/{third}").status_code == 200


# --- authenticator code budget -----------------------------------------------------------------------------
def wrong_codes(api, sid, n):
    return [api.post(f"/api/auth/password/{sid}/otp", json={"code": f"11111{i}"}).json() for i in range(n)]


def test_otp_budget_per_job_cannot_be_reset_by_rechoosing(api, monkeypatch):
    scripted(monkeypatch, lambda p: drive(p, BOTH, code="654321"))
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"})
    assert [r["status"] for r in wrong_codes(api, sid, 3)] == ["otp_invalid"] * 3  # first round of 3 spent
    assert api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"}).json()["attempts_left"] == 2
    first = api.post(f"/api/auth/password/{sid}/otp", json={"code": "222221"}).json()
    last = api.post(f"/api/auth/password/{sid}/otp", json={"code": "222222"}).json()
    assert first["status"] == "otp_invalid" and first["attempts_left"] == 1
    assert last["status"] == "error" and last["code"] == "otp_exhausted"
    assert api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"}).status_code == 409


def test_otp_budget_per_account_holds_across_jobs(api, monkeypatch):
    monkeypatch.setattr(password_signin, "OTP_ACCOUNT_BUDGET", 4)
    scripted(monkeypatch, lambda p: drive(p, BOTH, code="654321"))
    sid = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid}/method", json={"method": "otp"})
    wrong_codes(api, sid, 3)  # 3 of the 4 hourly codes
    sid2 = start(api).json()["sign_in_id"]
    api.post(f"/api/auth/password/{sid2}/method", json={"method": "otp"})
    first = api.post(f"/api/auth/password/{sid2}/otp", json={"code": "333331"}).json()  # the 4th
    assert first["status"] == "error" and first["code"] == "otp_exhausted"  # the 4th wrong code spends the hourly budget
    sid3 = start(api).json()["sign_in_id"]  # budget gone: a fresh job is refused codes at once
    api.post(f"/api/auth/password/{sid3}/method", json={"method": "otp"})
    assert until(api, sid3, "error")["code"] == "otp_exhausted"
    other = TestClient(app, headers={**HEADERS, "X-Schuly-User-Id": "someone-else"})
    sid4 = start(other).json()["sign_in_id"]
    assert other.post(f"/api/auth/password/{sid4}/method", json={"method": "otp"}).json()["status"] == "otp_required"
