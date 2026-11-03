from abc import ABC, abstractmethod


class ITokenRotation(ABC):
    """Where the rotated refresh token goes so that the current response carries it."""

    @abstractmethod
    def record(self, refresh_token: str) -> None: ...
