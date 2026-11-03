from src.domain.errors.service_error import ServiceError


class ConvertError(ServiceError):
    """The file can't be shown as PDF: `status` is the HTTP status to answer with (413, 415, 502)."""
