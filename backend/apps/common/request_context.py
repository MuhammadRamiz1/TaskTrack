"""Per-request metadata (request id, IP, user agent, impersonator) available to services
and the audit log without passing the request object through every layer."""

import contextvars
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class RequestMeta:
    request_id: str = ""
    ip: str | None = None
    user_agent: str = ""
    impersonator_id: str | None = None


_meta: contextvars.ContextVar[RequestMeta] = contextvars.ContextVar(
    "request_meta",
    default=RequestMeta(),  # noqa: B039 - frozen dataclass, immutable
)


def get() -> RequestMeta:
    return _meta.get()


def set(meta: RequestMeta) -> contextvars.Token:  # noqa: A001
    return _meta.set(meta)


def reset(token: contextvars.Token) -> None:
    _meta.reset(token)


def update(**changes) -> None:
    _meta.set(replace(_meta.get(), **changes))


def client_ip(request) -> str | None:
    """REMOTE_ADDR, or the first X-Forwarded-For hop when behind a trusted proxy."""
    from django.conf import settings

    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
