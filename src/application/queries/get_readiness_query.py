from dataclasses import dataclass

from mediatorx import IQuery, IQueryHandler

from src.application.services.warm_up_tracker import WarmUpTracker


@dataclass
class GetReadinessQuery(IQuery[bool]):
    """Whether the startup warm-up finished or its grace period passed."""

    pass


class GetReadinessHandler(IQueryHandler[GetReadinessQuery, bool]):
    def __init__(self, tracker: WarmUpTracker):
        self._tracker = tracker

    async def handle(self, query: GetReadinessQuery) -> bool:
        return self._tracker.is_ready()
