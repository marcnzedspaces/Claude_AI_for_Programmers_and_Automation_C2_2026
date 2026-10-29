import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
)
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.logging import log_event
from app.schemas.error import (
    ErrorDetail,
    ErrorResponse,
    ValidationIssue,
)
from app.services.claude_service import (
    ClaudeConfigurationError,
    ClaudeResponseError,
)


# Every request gets an ID in request_id_middleware. Reuse it so logs, error bodies and headers all match.
# The fallback only matters if the middleware did not run.
def _request_id(request: Request) -> str:
    return getattr(
        request.state,
        "request_id",
        f"req_{uuid4().hex}",
    )


# One function builds every error reply, so all errors share the same JSON shape (ErrorResponse)
# and are logged the same way.
def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[ValidationIssue] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)

    response_headers = dict(headers or {})
    # Clients can quote this ID when they report a problem.
    response_headers["X-Request-ID"] = request_id

    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=request_id,
            details=details or [],
        )
    )

    log_event(
        "request_error",
        # 5xx means our fault (ERROR); 4xx means the caller's request was wrong (WARNING).
        level=(
            logging.ERROR
            if status_code >= 500
            else logging.WARNING
        ),
        request_id=request_id,
        status_code=status_code,
        error_code=code,
    )

    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=response_headers,
    )


# Middleware wraps every request: it runs before the route (to create the request ID)
# and after it (to log how long the request took).
async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = f"req_{uuid4().hex}"
    # request.state holds data for this one request, so error handlers can read the ID later.
    request.state.request_id = request_id
    started = perf_counter()

    # call_next runs the route (and any later middleware) and gives back its response.
    response = await call_next(request)
    latency_ms = int(
        (perf_counter() - started) * 1000
    )
    response.headers["X-Request-ID"] = request_id

    log_event(
        "http_request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=latency_ms,
    )

    return response


# 422: FastAPI/Pydantic rejected the request data (for example ?limit=500).
# Each problem is turned into a ValidationIssue so the client knows which field to fix.
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [
        ValidationIssue(
            # error["loc"] is a path such as ("query", "limit"); join it into "query.limit".
            location=".".join(
                str(part)
                for part in error.get("loc", ())
            )
            or "request",
            message=str(
                error.get(
                    "msg",
                    "Invalid request value.",
                )
            ),
            error_type=str(
                error.get(
                    "type",
                    "validation_error",
                )
            ),
        )
        for error in exc.errors()
    ]

    return _error_response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        details=details,
    )


# Handles HTTPException, such as the 404 raised by a route.
# The status code is mapped to a stable, machine-readable error code.
async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    codes = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
    }

    message = (
        exc.detail
        if isinstance(exc.detail, str)
        else "Request failed."
    )

    return _error_response(
        request,
        status_code=exc.status_code,
        code=codes.get(
            exc.status_code,
            "HTTP_ERROR",
        ),
        message=message,
        headers=exc.headers,
    )


# The claude_* handlers below turn Anthropic API failures into clean 5xx replies.
# The raw exception text is never sent to the client because it could reveal internal details.
async def claude_timeout_handler(
    request: Request,
    exc: APITimeoutError,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=504,
        code="AI_TIMEOUT",
        message="The AI service timed out.",
    )


async def claude_rate_limit_handler(
    request: Request,
    exc: RateLimitError,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=503,
        code="AI_RATE_LIMITED",
        message="The AI service is temporarily busy.",
    )


async def claude_connection_handler(
    request: Request,
    exc: APIConnectionError,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=503,
        code="AI_UNAVAILABLE",
        message="The AI service is temporarily unavailable.",
    )


async def claude_status_handler(
    request: Request,
    exc: APIStatusError,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=502,
        code="AI_SERVICE_ERROR",
        message="The AI service returned an upstream error.",
    )


async def claude_response_handler(
    request: Request,
    exc: ClaudeResponseError,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=502,
        code="AI_INVALID_RESPONSE",
        message="The AI service returned an unusable response.",
    )


async def claude_configuration_handler(
    request: Request,
    exc: ClaudeConfigurationError,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=503,
        code="AI_UNAVAILABLE",
        message="The AI service is unavailable.",
    )


# Any MongoDB failure becomes a 503; the client never sees driver details.
async def database_exception_handler(
    request: Request,
    exc: PyMongoError,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=503,
        code="DATABASE_UNAVAILABLE",
        message="The database is temporarily unavailable.",
    )


# Last resort for any bug we did not anticipate: a generic 500 with no internals.
async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected server error occurred.",
    )


# Called once from main.py. FastAPI picks the handler that matches the exception's class,
# so the specific handlers win over the generic Exception one.
def register_exception_handlers(
    app: FastAPI,
) -> None:
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )
    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )
    app.add_exception_handler(
        APITimeoutError,
        claude_timeout_handler,
    )
    app.add_exception_handler(
        RateLimitError,
        claude_rate_limit_handler,
    )
    app.add_exception_handler(
        APIConnectionError,
        claude_connection_handler,
    )
    app.add_exception_handler(
        APIStatusError,
        claude_status_handler,
    )
    app.add_exception_handler(
        ClaudeResponseError,
        claude_response_handler,
    )
    app.add_exception_handler(
        ClaudeConfigurationError,
        claude_configuration_handler,
    )
    app.add_exception_handler(
        PyMongoError,
        database_exception_handler,
    )
    app.add_exception_handler(
        Exception,
        unexpected_exception_handler,
    )
