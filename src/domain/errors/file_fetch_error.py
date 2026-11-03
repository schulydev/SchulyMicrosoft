from src.domain.errors.service_error import ServiceError


class FileFetchError(ServiceError):
    """A download that can't be served: `status` is the HTTP status to answer with."""
