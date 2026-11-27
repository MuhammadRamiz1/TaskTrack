"""Structured JSON logging with PII/secret redaction. Imported by LOGGING (no Django imports)."""

import structlog

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "token",
        "access",
        "refresh",
        "secret",
        "authorization",
        "cookie",
        "email",
        "otp",
        "code",
        "totp",
        "recovery_code",
        "mfa_token",
    }
)
REDACTED = "[redacted]"


def redact(_, __, event_dict):
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
    return event_dict


FOREIGN_PRE_CHAIN = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    redact,
]

FORMATTER_PROCESSORS = [
    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
    structlog.processors.format_exc_info,
    structlog.processors.JSONRenderer(),
]

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


def sentry_before_send(event, hint):
    request = event.get("request") or {}
    request.pop("data", None)
    request.pop("cookies", None)
    headers = request.get("headers") or {}
    for header in list(headers):
        if header.lower() in {"authorization", "cookie", "x-csrftoken"}:
            headers[header] = REDACTED
    event.pop("user", None)
    return event
