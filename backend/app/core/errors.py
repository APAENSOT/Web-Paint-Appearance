"""One error shape, everywhere.

`docs/03-SECURITY.md` section 7 and `docs/tasks/T03-api-contract.md` item 4
fix the body of every failure at exactly four keys:

    { "statusCode", "error", "message", "correlationId" }

The handlers below cover the three ways a FastAPI application otherwise
produces a *different* shape: `HTTPException` (`{"detail": ...}`), request
validation (`{"detail": [...]}`), and an unhandled exception (a stack trace
in the response when the server is in debug). No stack trace reaches a
client; it goes to the log, tagged with the same correlation id the client
was given, so a user can quote four characters and an engineer can find the
request.
"""

from __future__ import annotations

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import correlation_id_of

log = logging.getLogger("app.error")


def error_body(status_code: int, message: str, correlation_id: str, error: str | None = None) -> dict:
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:  # pragma: no cover - non-standard status
        phrase = "Error"
    return {
        "statusCode": status_code,
        "error": error or phrase,
        "message": message,
        "correlationId": correlation_id,
    }


def error_response(status_code: int, message: str, request: Request, error: str | None = None) -> JSONResponse:
    cid = correlation_id_of(request)
    return JSONResponse(
        status_code=status_code,
        content=error_body(status_code, message, cid, error),
        headers={"X-Correlation-ID": cid},
    )


class ServiceUnavailable(Exception):
    """A dependency the route needs is not usable.

    Raised instead of letting a driver error escape, so a misconfigured or
    unreachable database produces the documented error shape and a 503
    rather than a 500 with a connection string in it.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        response = error_response(exc.status_code, detail, request)
        # 401 must say how to authenticate, or a browser client cannot.
        for key, value in (getattr(exc, "headers", None) or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors():
            location = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            parts.append(f"{location or 'request'}: {err.get('msg', 'invalid')}")
        return error_response(422, "; ".join(parts) or "Request validation failed", request)

    @app.exception_handler(ServiceUnavailable)
    async def _unavailable(request: Request, exc: ServiceUnavailable) -> JSONResponse:
        cid = correlation_id_of(request)
        log.error("dependency unavailable", extra={"correlation_id": cid, "detail": exc.message})
        return error_response(503, exc.message, request)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        cid = correlation_id_of(request)
        log.exception("unhandled exception", extra={"correlation_id": cid})
        return error_response(
            500,
            "Internal server error. Quote the correlationId when reporting this.",
            request,
        )
