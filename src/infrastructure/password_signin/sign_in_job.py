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

import logging
import threading
import time

import entrance
from entrance import MfaCancelled, MfaPrompt, MfaSwitch, Secret

from src.application.abstractions.i_sign_in_job import ISignInJob
from src.application.options.password_sign_in_options import PasswordSignInOptions
from src.domain.sign_in.sign_in_state import SignInState
from src.infrastructure.logging_config import LoggerNames
from src.infrastructure.password_signin.rate_limiter import RateLimiter


class SignInJob(MfaPrompt, ISignInJob):
    """Progress of one sign-in, and the `MfaPrompt` Entrance calls back into. Holds no password."""

    OTP_ATTEMPTS = entrance.OTP_ATTEMPTS
    MESSAGES = {
        "invalid_credentials": "Wrong email or password.",
        "unsupported": "This Microsoft account can't be signed in with a password here.",
        "blocked": "Microsoft blocked this sign-in because of a security policy.",
        "failed": "The Microsoft sign-in failed.",
        "otp_exhausted": "Too many wrong codes. Start the sign-in again later.",
    }
    log = logging.getLogger(LoggerNames.PASSWORD_SIGN_IN)

    def __init__(self, job_id: str, user: str, account: str, failures: RateLimiter, otp_hits: RateLimiter, options: PasswordSignInOptions):
        self.id = job_id
        self.user = user  # hash of the Schuly user id that started the job; only that user may touch it
        self.acct = account  # hash of (Schuly user, Microsoft account name)
        self.replaces: str | None = None  # this user's earlier job for the same account, replaced once the password passed
        self._failures = failures
        self._otp_hits = otp_hits
        self._options = options
        self.otp_used = 0
        self._budget_out = False
        self.expires = time.monotonic() + options.job_ttl
        self.done_at: float | None = None
        self.cond = threading.Condition()
        self.state = SignInState.WORKING
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

    @classmethod
    def failure_for(cls, ex: BaseException) -> tuple[str, str]:
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
        return code, cls.MESSAGES[code]

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
            while not (self.version > after_version and self.state not in SignInState.TRANSIENT):
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self.cond.wait(timeout=left)
            return True

    def snapshot(self) -> dict:
        """Everything a response needs, taken under the lock. Never contains the password."""
        with self.cond:
            snap = {"state": self.state, "version": self.version, "methods": list(self.methods), "notice": self.notice}
            if self.state == SignInState.PUSH_PENDING:
                snap["number"] = self.number
                snap["expires_in"] = max(0, int(self.push_deadline - time.monotonic()))
            if self.state in (SignInState.OTP_REQUIRED, SignInState.MFA_REQUIRED) or self.otp_invalid:
                snap["attempts_left"] = self.attempts_left
                snap["otp_invalid"] = self.otp_invalid
            if self.state == SignInState.COMPLETE:
                snap["refresh_token"] = self.refresh_token
            if self.state == SignInState.ERROR:
                snap["code"], snap["message"] = self.error_code, self.error_message
            return snap

    # -- actions from the HTTP side --------------------------------------------------------------
    def request_method(self, method: str) -> str:
        """Ask for a method. Returns "ok", "same" (already on it), "unavailable" (not offered) or "invalid_state"."""
        with self.cond:
            if method not in self.methods:
                return "unavailable"
            if self.state in SignInState.CHOOSABLE or (self.state == SignInState.PUSH_PENDING and method == "otp") or (self.state == SignInState.OTP_REQUIRED and method == "push"):
                self.requested = method
                self.cond.notify_all()
                return "ok"
            if (self.state == SignInState.PUSH_PENDING and method == "push") or (self.state == SignInState.OTP_REQUIRED and method == "otp"):
                return "same"  # already on that method
            return "invalid_state"

    def submit_code(self, code: str) -> bool:
        with self.cond:
            if self.state != SignInState.OTP_REQUIRED or self.code is not None:
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
                state = notice if notice in (SignInState.DENIED, SignInState.TIMED_OUT) else SignInState.MFA_REQUIRED
                self._set(state, notice=notice, number=None)
                self._wait(lambda: self.requested in self.methods)
            method, self.requested = self.requested, None
            self._set(SignInState.STARTING_PUSH if method == "push" else SignInState.STARTING_OTP, notice=None, otp_invalid=False)
            return method

    def on_push(self, event):
        if event.state == entrance.NUMBER_MATCHING:
            with self.cond:
                self._set(SignInState.PUSH_PENDING, number=event.number, push_deadline=time.monotonic() + (event.expires_in or self._options.push_timeout))
        elif event.state == entrance.APPROVED:
            with self.cond:
                self._set(SignInState.VERIFYING)

    def should_switch(self):
        return self.requested is not None

    def cancelled(self):
        return self._dead()

    def otp(self, attempt):
        with self.cond:
            if self.otp_used >= self._options.otp_job_budget or self._otp_hits.count(self.acct, 3600) >= self._options.otp_account_budget:
                self._budget_out = True
                raise entrance.OtpRejected("authenticator code budget spent", attempts=self.otp_used)
            self.attempts_left = min(self.OTP_ATTEMPTS - attempt + 1, self._options.otp_job_budget - self.otp_used)
            self._set(SignInState.OTP_REQUIRED, otp_invalid=attempt > 1)
            self._wait(lambda: self.code is not None or self.requested is not None)
            if self.code is None:
                raise MfaSwitch()
            code, self.code = self.code, None
            self.otp_used += 1
            self._otp_hits.add(self.acct)
            self._set(SignInState.VERIFYING)
            return code

    def retry(self, error):
        if isinstance(error, entrance.PushError) and error.state in (SignInState.DENIED, SignInState.TIMED_OUT):
            self._retry_notice = error.state
            return True
        if isinstance(error, entrance.OtpRejected):
            if self._budget_out or self.otp_used >= self._options.otp_job_budget:
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
            broker = entrance.foci_login(username, secret, cookies=None, frt_store=None, mfa=self, push_timeout=self._options.push_timeout, push_interval=self._options.push_interval)
            with self.cond:
                self.done_at = time.monotonic()
                self._set(SignInState.COMPLETE, refresh_token=broker.refresh_token)
        except MfaCancelled:
            self.log.info("password sign-in %s cancelled", self.id)
        except BaseException as ex:  # noqa: BLE001 - the worker must always end in a terminal state
            code, message = self.failure_for(ex)
            if code == "invalid_credentials":
                self._failures.add(self.acct)  # only failed password attempts count against the limiter
            self.log.warning("password sign-in %s ended: %s (%s)", self.id, code, type(ex).__name__)
            with self.cond:
                self.done_at = time.monotonic()
                self._set(SignInState.ERROR, error_code=code, error_message=message)
        finally:
            secret.take()  # no-op once submitted; guarantees nothing outlives the call
