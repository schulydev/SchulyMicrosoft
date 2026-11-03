from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.domain.errors.service_error import ServiceError
from src.domain.errors.sign_in_refused import SignInRefused


class ExceptionHandlingExtensions:
    """The one place that turns exceptions into responses, like `AddSchulyExceptionHandling`."""

    @classmethod
    def use_schuly_exception_handling(cls, app: FastAPI) -> None:
        app.add_exception_handler(ServiceError, cls._service_error)
        app.add_exception_handler(SignInRefused, cls._sign_in_refused)
        app.add_exception_handler(RequestValidationError, cls._validation_error)

    @staticmethod
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @staticmethod
    async def _sign_in_refused(_: Request, exc: SignInRefused) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"status": "error", "code": exc.code, "message": exc.message})

    @staticmethod
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default 422 echoes the rejected input; for the password routes that would be the password.
        if request.url.path.startswith("/api/auth/password"):
            details = [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
            return JSONResponse(status_code=422, content={"status": "error", "code": "invalid_request", "message": "The request is invalid.", "detail": details})
        if request.url.path in ("/api/search", "/api/files/search"):
            # The rejected input would be the search query.
            return JSONResponse(status_code=422, content={"detail": [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]})
        return await request_validation_exception_handler(request, exc)
