from src.domain.errors.service_error import ServiceError


class TextError(ServiceError):
    """The file can't be read as text: `status` is the HTTP status to answer with (413, 415, 422)."""
