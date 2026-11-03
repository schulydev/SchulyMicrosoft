"""FastAPI dependencies. The composition itself lives in `src/api/extensions` and `src/api/app.py`."""

import hmac

from fastapi import Request
from mediatorx import Mediator

from src.api.http_headers import HttpHeaders
from src.application.options.service_auth_options import ServiceAuthOptions
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


def get_mediator(request: Request) -> Mediator:
    """FastAPI dependency. Returns the process-wide Mediator instance."""
    return request.app.state.services.mediator


def get_password_caller(request: Request) -> str:
    """Gate for the password routes: the shared service key plus the Schuly user id. Returns the user id."""
    expected = request.app.state.services.get(ServiceAuthOptions).service_key
    if not expected:
        raise ServiceError(503, "Password sign-in is disabled: no service key is configured.")
    given = request.headers.get(HttpHeaders.SERVICE_KEY_HEADER, "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise ServiceError(401, "Missing or invalid service key.")
    user_id = request.headers.get(HttpHeaders.USER_ID_HEADER, "")
    if not GraphIds.SCHULY_USER_ID_PATTERN.fullmatch(user_id):
        raise ServiceError(401, "Missing or invalid user id.")
    return user_id
