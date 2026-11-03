import logging
import time

from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients


class WarmUpTracker:
    """The startup warm-up and what the readiness probe reads from it."""

    READY_GRACE = 15.0
    log = logging.getLogger("schuly.microsoft")

    def __init__(self, http: IMicrosoftHttpClients):
        self._http = http
        self.started = time.monotonic()
        self.done = False

    def begin(self) -> None:
        self.started = time.monotonic()
        self.done = False

    def is_ready(self) -> bool:
        return self.done or time.monotonic() - self.started >= self.READY_GRACE

    async def warm_up(self) -> None:
        started = time.monotonic()
        try:
            await self._http.warm_up()
        except Exception as ex:
            self.log.warning("Warm-up failed after %.0f ms: %s", (time.monotonic() - started) * 1000, ex)
        else:
            self.log.info("Warm-up finished in %.0f ms", (time.monotonic() - started) * 1000)
        finally:
            self.done = True
