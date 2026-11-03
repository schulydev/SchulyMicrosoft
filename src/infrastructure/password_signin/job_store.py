import asyncio
import hashlib
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from entrance import Secret
from pydantic import SecretStr

from src.application.abstractions.i_sign_in_store import ISignInStore
from src.application.options.password_sign_in_options import PasswordSignInOptions
from src.domain.errors.rate_limited import RateLimited
from src.infrastructure.password_signin.rate_limiter import RateLimiter
from src.infrastructure.password_signin.sign_in_job import SignInJob


class JobStore(ISignInStore):
    """In-memory jobs plus the rate limits. One instance per process."""

    def __init__(self, options: PasswordSignInOptions):
        self._options = options
        self._jobs: dict[str, SignInJob] = {}
        self._by_owner: dict[str, str] = {}
        self._lock = threading.Lock()
        self._starts = RateLimiter()
        self._failures = RateLimiter()
        self._otp_hits = RateLimiter()
        self._waiters = ThreadPoolExecutor(max_workers=options.max_jobs + 20, thread_name_prefix="pwd-wait")

    @staticmethod
    def _hash(*parts: str) -> str:
        return hashlib.sha256("\x00".join(p.strip().lower() for p in parts).encode()).hexdigest()

    def start(self, user_id: str, username: str, password: SecretStr) -> SignInJob:
        user = self._hash(user_id)
        account = self._hash(user_id, username)
        if not self._starts.allow(user, self._options.client_limit, 60):
            raise RateLimited("Too many sign-in attempts.")
        if self._failures.count(account, 600) >= self._options.account_limit:
            raise RateLimited("Too many failed attempts for this account. Try again later.")
        job = SignInJob(secrets.token_urlsafe(24), user, account, self._failures, self._otp_hits, self._options)
        with self._lock:
            self._prune()
            if len(self._jobs) >= self._options.max_jobs:
                raise RateLimited("Too many sign-ins in progress.")
            job.replaces = self._by_owner.get(account)
            self._jobs[job.id] = job
        threading.Thread(target=job.run, args=(username.strip(), Secret(password.get_secret_value())), name=f"pwd-signin-{job.id[:6]}", daemon=True).start()
        return job

    async def wait_settled(self, job: SignInJob, after_version: int, timeout: float) -> None:
        await asyncio.get_running_loop().run_in_executor(self._waiters, job.wait_settled, after_version, timeout)

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

    def _expired(self, job: SignInJob) -> bool:
        now = time.monotonic()
        return now > job.expires or (job.done_at is not None and now - job.done_at > self._options.done_ttl)

    def _drop(self, job: SignInJob):
        job.stop()
        self._jobs.pop(job.id, None)
        if self._by_owner.get(job.acct) == job.id:
            del self._by_owner[job.acct]

    def _prune(self):
        for job in [j for j in self._jobs.values() if self._expired(j)]:
            self._drop(job)
