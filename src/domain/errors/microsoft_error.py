from src.domain.errors.service_error import ServiceError


class MicrosoftError(ServiceError):
    """Microsoft's sign-in endpoint answered with an error; a 502 for the caller."""

    def __init__(self, error: str, description: str = ""):
        self.error = error
        super().__init__(502, f"{error}: {description}" if description else error)
