from src.domain.errors.service_error import ServiceError


class SendError(ServiceError):
    """A chat message that can't be sent: `status` is the HTTP status to answer with."""
