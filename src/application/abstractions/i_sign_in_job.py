from abc import ABC, abstractmethod


class ISignInJob(ABC):
    """Progress of one password sign-in. Holds no password."""

    id: str
    account: object | None

    @abstractmethod
    def snapshot(self) -> dict: ...

    @abstractmethod
    def request_method(self, method: str) -> str: ...

    @abstractmethod
    def submit_code(self, code: str) -> bool: ...
