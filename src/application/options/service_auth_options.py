import os


class ServiceAuthOptions:
    """The password routes take a Microsoft password, so only the Schuly plugin may call them. It sends the shared secret and the signed-in Schuly user's id. With no key configured the routes answer 503 (never open)."""

    SERVICE_KEY_ENV = "SCHULY_SERVICE_KEY"

    @property
    def service_key(self) -> str:
        return os.getenv(self.SERVICE_KEY_ENV, "")
