class RateLimited(Exception):
    """Too many sign-in attempts (per client or per account) or too many jobs in progress."""
