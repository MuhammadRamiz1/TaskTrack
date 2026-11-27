"""Domain errors and the single DRF exception handler.

Every error response has the shape::

    {"error": {"code": str, "message": str, "details": dict, "request_id": str}}
"""

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import set_rollback

from . import request_context


class DomainError(Exception):
    """Business-rule violation raised by services. Views never catch it."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "domain_error"
    message = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict | None = None,
        status_code: int | None = None,
    ):
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        if status_code:
            self.status_code = status_code
        super().__init__(self.message)


class Conflict(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class Gone(DomainError):
    status_code = status.HTTP_410_GONE
    code = "gone"


class Forbidden(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    message = "You do not have permission to perform this action."


class NotFound(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Not found."


class Unprocessable(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "unprocessable"


class InvalidInput(DomainError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "validation_error"
    message = "Invalid input."


def _payload(code: str, message: str, details: Any = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_context.get().request_id,
        }
    }


def error_response(code: str, message: str, status_code: int, details: Any = None) -> Response:
    """Build an error response without raising (used when the transaction must commit)."""
    return Response(_payload(code, message, details), status=status_code)


def _first_code(detail) -> str | None:
    if isinstance(detail, drf.ErrorDetail):
        return detail.code
    if isinstance(detail, list) and detail:
        return _first_code(detail[0])
    if isinstance(detail, dict) and detail:
        return _first_code(next(iter(detail.values())))
    return None


def exception_handler(exc, context):
    headers = {}
    if isinstance(exc, DomainError):
        set_rollback()
        return Response(_payload(exc.code, exc.message, exc.details), status=exc.status_code)

    if isinstance(exc, Http404):
        exc = drf.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf.PermissionDenied()
    elif isinstance(exc, DjangoValidationError):
        exc = drf.ValidationError(detail=exc.message_dict if hasattr(exc, "error_dict") else exc.messages)

    if not isinstance(exc, drf.APIException):
        return None  # unhandled: Django returns 500 and Sentry captures it

    set_rollback()
    if getattr(exc, "auth_header", None):
        headers["WWW-Authenticate"] = exc.auth_header
    if getattr(exc, "wait", None):
        headers["Retry-After"] = str(int(exc.wait))

    if isinstance(exc, drf.ValidationError):
        details = exc.detail if isinstance(exc.detail, dict) else {"non_field_errors": exc.detail}
        return Response(
            _payload("validation_error", "Invalid input.", details), status=exc.status_code, headers=headers
        )

    code_map = {
        drf.NotAuthenticated: "not_authenticated",
        drf.NotFound: "not_found",
        drf.MethodNotAllowed: "method_not_allowed",
        drf.Throttled: "throttled",
        drf.UnsupportedMediaType: "unsupported_media_type",
        drf.ParseError: "parse_error",
    }
    code = next((c for cls, c in code_map.items() if isinstance(exc, cls)), None)
    if code is None:
        detail_code = _first_code(exc.detail)
        code = detail_code if detail_code and detail_code not in {"invalid", "error"} else exc.default_code
    message = str(exc.detail) if not isinstance(exc.detail, (list, dict)) else exc.default_detail
    if isinstance(exc, drf.NotAuthenticated):
        exc.status_code = status.HTTP_401_UNAUTHORIZED
    return Response(_payload(code, str(message)), status=exc.status_code, headers=headers)
