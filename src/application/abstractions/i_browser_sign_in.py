from abc import ABC, abstractmethod


class IBrowserSignIn(ABC):
    """The browser sign-in: authorization code + PKCE on Microsoft's real page."""

    NATIVE_REDIRECT: str

    @abstractmethod
    def build_authorize_url(self) -> tuple[str, str]: ...

    @abstractmethod
    async def exchange_code(self, code: str, code_verifier: str, client=None) -> dict: ...
