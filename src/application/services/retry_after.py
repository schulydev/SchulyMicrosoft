import math


class RetryAfter:
    """Whole seconds for a Retry-After header."""

    DEFAULT_RETRY_AFTER = 30  # seconds, for a throttled call that named no wait

    @classmethod
    def header(cls, seconds: float | None) -> str:
        """Graph's value when it gave one."""
        return str(max(1, math.ceil(seconds))) if seconds else str(cls.DEFAULT_RETRY_AFTER)
