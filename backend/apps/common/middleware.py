import time
import uuid

import structlog
from django.db import connection

from . import request_context, tenancy

logger = structlog.get_logger("tasktrack.request")


class RequestContextMiddleware:
    """Assigns a request id, binds log context, and isolates tenant state per request.

    The tenant ContextVar is reset to NONE for the request and restored afterwards,
    so state can never leak between requests served by the same thread.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if 8 <= len(incoming) <= 64 and incoming.isascii() else uuid.uuid4().hex
        request.request_id = request_id
        meta_token = request_context.set(
            request_context.RequestMeta(
                request_id=request_id,
                ip=request_context.client_ip(request),
                user_agent=request.headers.get("User-Agent", "")[:255],
            )
        )
        previous_state = tenancy.current()
        tenancy.set_python_state(tenancy.NO_CONTEXT)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, method=request.method, path=request.path)
        started = time.monotonic()
        try:
            response = self.get_response(request)
        finally:
            tenancy.set_python_state(previous_state)
            # Only matters when an outer transaction wraps the request (tests).
            if (
                previous_state.mode != tenancy.Mode.NONE
                and connection.in_atomic_block
                and not connection.needs_rollback
            ):
                tenancy.apply_db(previous_state)
            request_context.reset(meta_token)
        response["X-Request-ID"] = request_id
        logger.info(
            "request.finished", status=response.status_code, duration_ms=round((time.monotonic() - started) * 1000, 1)
        )
        structlog.contextvars.clear_contextvars()
        return response
