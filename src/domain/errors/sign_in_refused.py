class SignInRefused(Exception):
    """A password sign-in the service refuses: answered as `{status: error, code, message}`, never with any input."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)
