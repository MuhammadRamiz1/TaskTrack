"""Writing audit entries. Call ``record()`` inside the same transaction as the change."""

import datetime
import decimal
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from apps.common import request_context, tenancy

from .models import AuditLog

SENSITIVE_FIELDS = frozenset(
    {"password", "token_hash", "code_hash", "totp_secret_enc", "refresh_jti", "secret", "token"}
)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (uuid.UUID, decimal.Decimal)):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): ("[redacted]" if k in SENSITIVE_FIELDS else _jsonable(v)) for k, v in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "pk"):
        return str(value.pk)
    return str(value)


def snapshot(instance, fields: Iterable[str]) -> dict:
    """Plain dict of ``fields`` from a model instance (FKs as ids)."""
    data = {}
    for name in fields:
        field = instance._meta.get_field(name)
        data[name] = _jsonable(getattr(instance, field.attname))
    return data


def diff(old: dict, new: dict) -> tuple[dict, dict]:
    """Only the keys whose values changed."""
    changed = [k for k in new if old.get(k) != new.get(k)]
    return {k: old.get(k) for k in changed}, {k: new.get(k) for k in changed}


def record(
    *,
    actor,
    action: str,
    entity=None,
    entity_type: str = "",
    entity_id: Any = "",
    old_value: Any = None,
    new_value: Any = None,
    company_id: uuid.UUID | None = None,
) -> AuditLog:
    """Append one audit entry.

    ``company_id`` defaults to the entity's company, then the actor's company, then
    the active tenant. Platform actions on a company pass that company's id so the
    company's own audit log shows them.
    """
    if entity is not None:
        entity_type = entity_type or entity._meta.model_name
        entity_id = entity_id or entity.pk
        if company_id is None:
            company_id = getattr(entity, "company_id", None) if entity._meta.model_name != "company" else entity.pk
    if company_id is None and actor is not None:
        company_id = getattr(actor, "company_id", None)
    if company_id is None:
        company_id = tenancy.current_company_id()

    meta = request_context.get()
    return AuditLog.objects.create(
        company_id=company_id,
        actor_id=getattr(actor, "pk", None),
        actor_email=getattr(actor, "email", "") or "",
        impersonator_id=meta.impersonator_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id or ""),
        old_value=_jsonable(old_value),
        new_value=_jsonable(new_value),
        ip=meta.ip,
        user_agent=meta.user_agent,
        request_id=meta.request_id,
    )
