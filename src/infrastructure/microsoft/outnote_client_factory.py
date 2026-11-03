from outnote import OutNote

from src.application.abstractions.i_graph_client_factory import IGraphClientFactory
from src.infrastructure.microsoft.broker_cache import BrokerCache
from src.infrastructure.microsoft.shared_broker import SharedBroker


class OutNoteClientFactory(IGraphClientFactory):
    """OutNote clients over the per-token brokers, the one place that holds them."""

    def __init__(self):
        self._brokers = BrokerCache()

    def build_client(self, refresh_token: str) -> tuple[OutNote, SharedBroker]:
        """An OutNote client over a shared per-token broker; read `broker.refresh_token` after use for the (possibly rotated) value."""
        broker = self._brokers.get(refresh_token)
        return broker.note, broker
