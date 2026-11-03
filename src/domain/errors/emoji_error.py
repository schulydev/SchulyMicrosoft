from src.domain.errors.service_error import ServiceError


class EmojiError(ServiceError):
    """The Teams emoji catalogue can't be loaded."""
