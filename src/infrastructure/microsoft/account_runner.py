import asyncio
import logging
from collections.abc import Callable

from outnote import GraphError

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_graph_client_factory import IGraphClientFactory
from src.application.abstractions.i_token_rotation import ITokenRotation
from src.application.services.retry_after import RetryAfter
from src.domain.errors.service_error import ServiceError
from src.infrastructure.logging_config import LoggerNames
from src.infrastructure.microsoft.graph_call_trail import GraphCallTrail


class AccountRunner(IAccountRunner):
    """Every read and write for an account goes through here: off the event loop, with the rotated token handed back and `_native` stripped."""

    log = logging.getLogger(LoggerNames.SERVICE)

    def __init__(self, clients: IGraphClientFactory, rotation: ITokenRotation):
        self._clients = clients
        self._rotation = rotation

    async def run(self, refresh_token: str, action: Callable[..., object]) -> object:
        note, broker = self._clients.build_client(refresh_token)
        trail = GraphCallTrail(note)
        try:
            data = await asyncio.to_thread(action, trail, broker)
        except ServiceError as ex:
            if ex.status == 429:
                self.log.warning("Graph throttled %s (Retry-After %s)", trail.route, (ex.headers or {}).get("Retry-After"))
            # The token may have rotated before the action refused; keep it for the caller.
            self._keep_rotated(broker, refresh_token)
            raise
        except Exception as ex:
            if "invalid_grant" in str(ex):
                raise ServiceError(401, "The Microsoft sign-in expired; reconnect the account.")
            if isinstance(ex, GraphError) and ex.status == 404:
                raise ServiceError(404, "Not found in Microsoft 365.")
            if isinstance(ex, GraphError) and ex.status == 429:
                # OutNote already waited up to about 60 s, unless the call asked it not to. The token may have rotated first; keep it for the caller.
                self.log.warning("Graph throttled %s (Retry-After %s)", trail.route, ex.retry_after)
                self._keep_rotated(broker, refresh_token)
                raise ServiceError(429, "Microsoft is throttling this account; try again later.", headers={"Retry-After": RetryAfter.header(ex.retry_after)})
            raise ServiceError(502, f"Microsoft Graph error: {ex}")
        # Hand back the rotated refresh token so the caller can persist it.
        self._keep_rotated(broker, refresh_token)
        return self.strip_native(data)

    def _keep_rotated(self, broker, refresh_token: str) -> None:
        if broker.refresh_token and broker.refresh_token != refresh_token:
            self._rotation.record(broker.refresh_token)

    @classmethod
    def strip_native(cls, value):
        """Removes OutNote's `_native` copies (the raw Teams answer, with raw ids) from a result, in place, at any depth."""
        if isinstance(value, dict):
            value.pop("_native", None)
            for item in value.values():
                cls.strip_native(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                cls.strip_native(item)
        return value
