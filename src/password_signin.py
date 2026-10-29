"""Microsoft password sign-in with an interactive second factor, as short-lived in-memory jobs.

The ONE place in this service that receives a Microsoft password. It is handed to Entrance once,
on a worker thread, wrapped in a one-shot `entrance.Secret`; Entrance posts it to Microsoft and
drops it. It is never stored, cached, logged or returned, and never lives on a job: a job only holds
progress (state, methods, the push number, the result). Jobs are in memory only, so the service must
run as ONE process (see asgi.py) - a second worker would not know a job started on the first.

Entrance runs the sign-in on the worker thread and calls back into the job (an `MfaPrompt`) when
Microsoft asks for MFA; the job blocks there on a condition until the HTTP side supplies the choice
or the code.
"""

import hashlib
import logging
import os
import secrets
import threading
import time
from collections import deque

import entrance
from entrance import MfaCancelled, MfaPrompt, MfaSwitch, Secret

log = logging.getLogger("schuly.microsoft.password")

JOB_TTL = int(os.getenv("PASSWORD_SIGNIN_TTL", "600"))  # hard cap per job, seconds (<= 10 min)
JOB_TTL = min(JOB_TTL, 600)
DONE_TTL = 120  # a finished job stays readable this long (a lost response can be re-read)
MAX_JOBS = int(os.getenv("PASSWORD_SIGNIN_MAX_JOBS", "100"))
CLIENT_LIMIT = int(os.getenv("PASSWORD_SIGNIN_CLIENT_LIMIT", "30"))  # starts per Schuly user per minute
ACCOUNT_LIMIT = int(os.getenv("PASSWORD_SIGNIN_ACCOUNT_LIMIT", "6"))  # FAILED password attempts per (Schuly user, account) per 10 minutes
OTP_JOB_BUDGET = 5  # authenticator codes tried per job, however often the method is re-chosen
OTP_ACCOUNT_BUDGET = 10  # codes per (Schuly user, account) per hour, across jobs
PUSH_TIMEOUT = 120
PUSH_INTERVAL = 1.5
OTP_ATTEMPTS = entrance.OTP_ATTEMPTS

# States. Transient ones mean "the worker is busy"; everything else is a place the caller can act on.
WORKING, STARTING_PUSH, STARTING_OTP, VERIFYING = "working", "starting_push", "starting_otp", "verifying"
MFA_REQUIRED, PUSH_PENDING, OTP_REQUIRED = "mfa_required", "push_pending", "otp_required"
DENIED, TIMED_OUT, COMPLETE, ERROR = "denied", "timed_out", "complete", "error"
TRANSIENT = {WORKING, STARTING_PUSH, STARTING_OTP, VERIFYING}
CHOOSABLE = {MFA_REQUIRED, DENIED, TIMED_OUT}  # states where /method picks a (new) method

MESSAGES = {
    "invalid_credentials": "Wrong email or password.",
    "unsupported": "This Microsoft account can't be signed in with a password here.",
    "blocked": "Microsoft blocked this sign-in because of a security policy.",
    "failed": "The Microsoft sign-in failed.",
    "otp_exhausted": "Too many wrong codes. Start the sign-in again later.",
}


class RateLimited(Exception):
    """Too many sign-in attempts (per client or per account) or too many jobs in progress."""


class RateLimiter:
    """Sliding-window counter keyed by an opaque string (never the raw account name)."""

    def __init__(self):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def add(self, key: str):
        with self._lock:
            self._hits.setdefault(key, deque()).append(time.monotonic())

    def count(self, key: str, window: float) -> int:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            while hits and now - hits[0] > window:
                hits.popleft()
            return len(hits)

    def sweep(self, window: float = 600):
        now = time.monotonic()
        with self._lock:
            for key in [k for k, h in self._hits.items() if not h or now - h[-1] > window]:
                del self._hits[key]


def failure_for(ex: BaseException) -> tuple[str, str]:
    """Map a sign-in exception to a stable (code, message). Only the exception TYPE decides; the
    exception text is never copied into a response."""
    if isinstance(ex, entrance.InvalidCredentials):
        code = "invalid_credentials"
    elif isinstance(ex, entrance.OtpRejected):
        code = "otp_exhausted"
    elif isinstance(ex, entrance.Unsupported):
        code = "unsupported"
    elif isinstance(ex, entrance.Blocked):
        code = "blocked"
    else:
        code = "failed"
    return code, MESSAGES[code]


class SignInJob(MfaPrompt):
    """Progress of one sign-in, and the `MfaPrompt` Entrance calls back into. Holds no password."""

    def __init__(self, job_id: str, user: str, account: str, failures: "RateLimiter", otp_hits: "RateLimiter"):
        self.id = job_id
        self.user = user  # hash of the Schuly user id that started the job; only that user may touch it
        self.acct = account  # hash of (Schuly user, Microsoft account name)
        self.replaces: str | None = None  # this user's earlier job for the same account, replaced once the password passed
        self._failures = failures
        self._otp_hits = otp_hits
        self.otp_used = 0
        self._budget_out = False
        self.expires = time.monotonic() + JOB_TTL
        self.done_at: float | None = None
        self.cond = threading.Condition()
        self.state = WORKING
        self.version = 0
        self.methods: list[str] = []
        self.notice: str | None = None
        self.number: str | None = None
        self.push_deadline = 0.0
        self.attempts_left = 0
        self.otp_invalid = False
        self.requested: str | None = None
        self.code: str | None = None  # a one-time authenticator code, taken (cleared) by the worker
        self.refresh_token: str | None = None
        self.account = None
        self.error_code: str | None = None
        self.error_message: str | None = None
        self.cancel = False
        self._retry_notice: str | None = None

    # -- state ---------------------------------------------------------------------------------
    def _set(self, state: str, **fields):
        """Move to a state (caller holds `cond`) and wake every waiter."""
        self.state = state
        self.version += 1
        for key, value in fields.items():
            setattr(self, key, value)
        self.cond.notify_all()

    def _dead(self) -> bool:
        return self.cancel or time.monotonic() > self.expires

    def _wait(self, predicate):
        """Block (holding `cond`) until `predicate()` or the job is cancelled / expired."""
        while not predicate():
            if self._dead():
                raise MfaCancelled("Sign-in cancelled")
            self.cond.wait(timeout=max(0.05, min(1.0, self.expires - time.monotonic())))

    def stop(self):
        with self.cond:
            self.cancel = True
            self.cond.notify_all()

    def wait_settled(self, after_version: int, timeout: float) -> bool:
        """Wait (from the HTTP side) until a non-transient state newer than `after_version`."""
        deadline = time.monotonic() + timeout
        with self.cond:
            while not (self.version > after_version and self.state not in TRANSIENT):
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self.cond.wait(timeout=left)
            return True

    def snapshot(self) -> dict:
        """Everything a response needs, taken under the lock. Never contains the password."""
        with self.cond:
            snap = {"state": self.state, "version": self.version, "methods": list(self.methods), "notice": self.notice}
            if self.state == PUSH_PENDING:
                snap["number"] = self.number
                snap["expires_in"] = max(0, int(self.push_deadline - time.monotonic()))
            if self.state in (OTP_REQUIRED, MFA_REQUIRED) or self.otp_invalid:
                snap["attempts_left"] = self.attempts_left
                snap["otp_invalid"] = self.otp_invalid
            if self.state == COMPLETE:
                snap["refresh_token"] = self.refresh_token
            if self.state == ERROR:
                snap["code"], snap["message"] = self.error_code, self.error_message
            return snap

    # -- actions from the HTTP side --------------------------------------------------------------
    def request_method(self, method: str) -> str:
        """Ask for a method. Returns "ok", "same" (already on it), "unavailable" (not offered) or "invalid_state"."""
        with self.cond:
            if method not in self.methods:
                return "unavailable"
            if self.state in CHOOSABLE or (self.state == PUSH_PENDING and method == "otp") or (self.state == OTP_REQUIRED and method == "push"):
                self.requested = method
                self.cond.notify_all()
                return "ok"
            if (self.state == PUSH_PENDING and method == "push") or (self.state == OTP_REQUIRED and method == "otp"):
                return "same"  # already on that method
            return "invalid_state"

    def submit_code(self, code: str) -> bool:
        with self.cond:
            if self.state != OTP_REQUIRED or self.code is not None:
                return False
            self.code = code
            self.cond.notify_all()
            return True

    # -- MfaPrompt (called by Entrance on the worker thread) -------------------------------------
    def choose(self, methods):
        with self.cond:
            self.methods = list(methods)
            if self.requested not in methods:
                notice, self._retry_notice = self._retry_notice, None
                state = notice if notice in (DENIED, TIMED_OUT) else MFA_REQUIRED
                self._set(state, notice=notice, number=None)
                self._wait(lambda: self.requested in self.methods)
            method, self.requested = self.requested, None
            self._set(STARTING_PUSH if method == "push" else STARTING_OTP, notice=None, otp_invalid=False)
            return method

    def on_push(self, event):
        if event.state == entrance.NUMBER_MATCHING:
            with self.cond:
                self._set(PUSH_PENDING, number=event.number, push_deadline=time.monotonic() + (event.expires_in or PUSH_TIMEOUT))
        elif event.state == entrance.APPROVED:
            with self.cond:
                self._set(VERIFYING)

    def should_switch(self):
        return self.requested is not None

    def cancelled(self):
        return self._dead()

    def otp(self, attempt):
        with self.cond:
            if self.otp_used >= OTP_JOB_BUDGET or self._otp_hits.count(self.acct, 3600) >= OTP_ACCOUNT_BUDGET:
                self._budget_out = True
                raise entrance.OtpRejected("authenticator code budget spent", attempts=self.otp_used)
            self.attempts_left = min(OTP_ATTEMPTS - attempt + 1, OTP_JOB_BUDGET - self.otp_used)
            self._set(OTP_REQUIRED, otp_invalid=attempt > 1)
            self._wait(lambda: self.code is not None or self.requested is not None)
            if self.code is None:
                raise MfaSwitch()
            code, self.code = self.code, None
            self.otp_used += 1
            self._otp_hits.add(self.acct)
            self._set(VERIFYING)
            return code

    def retry(self, error):
        if isinstance(error, entrance.PushError) and error.state in (DENIED, TIMED_OUT):
            self._retry_notice = error.state
            return True
        if isinstance(error, entrance.OtpRejected):
            if self._budget_out or self.otp_used >= OTP_JOB_BUDGET:
                return False  # terminal: a fresh sign-in is required
            with self.cond:
                self.attempts_left = 0
                self.otp_invalid = True
            self._retry_notice = "otp_exhausted"
            return True
        return False

    # -- the worker --------------------------------------------------------------------------------
    def run(self, username: str, secret: Secret):
        try:
            broker = entrance.foci_login(username, secret, cookies=None, frt_store=None, mfa=self, push_timeout=PUSH_TIMEOUT, push_interval=PUSH_INTERVAL)
            with self.cond:
                self.done_at = time.monotonic()
                self._set(COMPLETE, refresh_token=broker.refresh_token)
        except MfaCancelled:
            log.info("password sign-in %s cancelled", self.id)
        except BaseException as ex:  # noqa: BLE001 - the worker must always end in a terminal state
            code, message = failure_for(ex)
            if code == "invalid_credentials":
                self._failures.add(self.acct)  # only failed password attempts count against the limiter
            log.warning("password sign-in %s ended: %s (%s)", self.id, code, type(ex).__name__)
            with self.cond:
                self.done_at = time.monotonic()
                self._set(ERROR, error_code=code, error_message=message)
        finally:
            secret.take()  # no-op once submitted; guarantees nothing outlives the call


class JobStore:
    """In-memory jobs plus the rate limits. One instance per process."""

    def __init__(self):
        self._jobs: dict[str, SignInJob] = {}
        self._by_owner: dict[str, str] = {}
        self._lock = threading.Lock()
        self._starts = RateLimiter()
        self._failures = RateLimiter()
        self._otp_hits = RateLimiter()

    @staticmethod
    def _hash(*parts: str) -> str:
        return hashlib.sha256("\x00".join(p.strip().lower() for p in parts).encode()).hexdigest()

    def start(self, user_id: str, username: str, secret: Secret) -> SignInJob:
        user = self._hash(user_id)
        account = self._hash(user_id, username)
        if not self._starts.allow(user, CLIENT_LIMIT, 60):
            raise RateLimited("Too many sign-in attempts.")
        if self._failures.count(account, 600) >= ACCOUNT_LIMIT:
            raise RateLimited("Too many failed attempts for this account. Try again later.")
        job = SignInJob(secrets.token_urlsafe(24), user, account, self._failures, self._otp_hits)
        with self._lock:
            self._prune()
            if len(self._jobs) >= MAX_JOBS:
                raise RateLimited("Too many sign-ins in progress.")
            job.replaces = self._by_owner.get(account)
            self._jobs[job.id] = job
        threading.Thread(target=job.run, args=(username.strip(), secret), name=f"pwd-signin-{job.id[:6]}", daemon=True).start()
        return job

    def promote(self, job: SignInJob):
        """The password passed: this job becomes the user's current one for the account and replaces their earlier one."""
        with self._lock:
            if job.id not in self._jobs:
                return
            previous = self._jobs.get(job.replaces or "")
            if previous is not None and previous.user == job.user:
                self._drop(previous)
            self._by_owner[job.acct] = job.id

    def get(self, job_id: str, user_id: str) -> SignInJob | None:
        """The job, only for the Schuly user that started it (anyone else gets None, like an unknown id)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.user != self._hash(user_id):
                return None
            if self._expired(job):
                self._drop(job)
                return None
            return job

    def remove(self, job_id: str, user_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.user == self._hash(user_id):
                self._drop(job)

    def sweep(self):
        with self._lock:
            self._prune()
        self._starts.sweep(60)
        self._failures.sweep(600)
        self._otp_hits.sweep(3600)

    def clear(self):
        with self._lock:
            for job in self._jobs.values():
                job.stop()
            self._jobs.clear()
            self._by_owner.clear()
        self._starts = RateLimiter()
        self._failures = RateLimiter()
        self._otp_hits = RateLimiter()

    def __len__(self):
        return len(self._jobs)

    @staticmethod
    def _expired(job: SignInJob) -> bool:
        now = time.monotonic()
        return now > job.expires or (job.done_at is not None and now - job.done_at > DONE_TTL)

    def _drop(self, job: SignInJob):
        job.stop()
        self._jobs.pop(job.id, None)
        if self._by_owner.get(job.acct) == job.id:
            del self._by_owner[job.acct]

    def _prune(self):
        for job in [j for j in self._jobs.values() if self._expired(j)]:
            self._drop(job)


store = JobStore()
