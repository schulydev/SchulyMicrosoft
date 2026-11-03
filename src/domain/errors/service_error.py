class ServiceError(Exception):
    """A request the service refuses: `status_code` and `detail` are what the caller reads. One exception handler answers every one of them."""

    def __init__(self, status_code: int, detail: str, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.detail = detail
        self.headers = headers
        super().__init__(detail)

    @property
    def status(self) -> int:
        return self.status_code
