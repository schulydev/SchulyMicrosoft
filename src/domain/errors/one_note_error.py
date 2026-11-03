from src.domain.errors.service_error import ServiceError


class OneNoteError(ServiceError):
    """A refusal OneNote gives as such: `status` is the HTTP status to answer with."""
