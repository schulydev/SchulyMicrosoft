import os
from dataclasses import dataclass


@dataclass
class PasswordSignInOptions:
    """Limits of the in-memory password sign-in jobs."""

    job_ttl: int  # hard cap per job, seconds (<= 10 min)
    max_jobs: int
    client_limit: int  # starts per Schuly user per minute
    account_limit: int  # FAILED password attempts per (Schuly user, account) per 10 minutes
    done_ttl: int = 120  # a finished job stays readable this long (a lost response can be re-read)
    otp_job_budget: int = 5  # authenticator codes tried per job, however often the method is re-chosen
    otp_account_budget: int = 10  # codes per (Schuly user, account) per hour, across jobs
    push_timeout: int = 120
    push_interval: float = 1.5

    @classmethod
    def from_environment(cls) -> "PasswordSignInOptions":
        return cls(job_ttl=min(int(os.getenv("PASSWORD_SIGNIN_TTL", "600")), 600), max_jobs=int(os.getenv("PASSWORD_SIGNIN_MAX_JOBS", "100")), client_limit=int(os.getenv("PASSWORD_SIGNIN_CLIENT_LIMIT", "30")), account_limit=int(os.getenv("PASSWORD_SIGNIN_ACCOUNT_LIMIT", "6")))
