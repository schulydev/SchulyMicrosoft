from abc import ABC, abstractmethod


class IAccountBroker(ABC):
    """An account's token broker. Calling it mints an access token, which may rotate `refresh_token`."""

    refresh_token: str | None

    @abstractmethod
    def __call__(self, client_id, scope="https://graph.microsoft.com/.default"): ...
