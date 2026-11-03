import asyncio

from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.abstractions.i_sign_in_store import ISignInStore
from src.application.services.warm_up_tracker import WarmUpTracker


class ApplicationLifetime:
    """What runs for as long as the process does: the warm-up, the sign-in sweeper, and the shutdown."""

    SWEEP_EVERY = 15

    def __init__(self, tracker: WarmUpTracker, store: ISignInStore, http: IMicrosoftHttpClients):
        self._tracker = tracker
        self._store = store
        self._http = http
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        # Pre-open the TLS connections to Microsoft in the background: the first call after a cold start otherwise pays DNS, TCP and TLS (and any dead-address timeout) itself.
        self._tracker.begin()
        self._tasks = [asyncio.create_task(self._tracker.warm_up()), asyncio.create_task(self._sweep_sign_ins())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        self._store.clear()
        await self._http.close_shared_client()

    async def _sweep_sign_ins(self) -> None:
        """Drop expired password sign-in jobs (and stale rate-limit windows) every few seconds."""
        while True:
            await asyncio.sleep(self.SWEEP_EVERY)
            self._store.sweep()
