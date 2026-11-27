"""Tenant context: one source of truth for the Python layer and the Postgres RLS layer.

Every database access runs in exactly one mode:

* TENANT   - one company. TenantManager filters by company_id and RLS allows
             only rows whose company_id equals ``app.company_id``.
* PLATFORM - super admin endpoints and platform jobs. RLS allows all rows.
* AUTH     - pre-authentication lookups (login by email, token by hash). RLS allows
             SELECT on account tables only; writes must switch to TENANT/PLATFORM.
* NONE     - default. TenantManager raises and RLS returns no rows (fail closed).

The Postgres settings are set with ``set_config(..., is_local => true)``, so they last
until the end of the current transaction and are safe with pooled connections.
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

from django.db import connection, transaction


class Mode(StrEnum):
    NONE = "none"
    TENANT = "tenant"
    PLATFORM = "platform"
    AUTH = "auth"


@dataclass(frozen=True, slots=True)
class TenantState:
    mode: Mode = Mode.NONE
    company_id: uuid.UUID | None = None


NO_CONTEXT = TenantState()
_state: contextvars.ContextVar[TenantState] = contextvars.ContextVar("tenant_state", default=NO_CONTEXT)


class TenantContextMissing(RuntimeError):
    """A tenant-owned table was queried outside any tenant context."""


def current() -> TenantState:
    return _state.get()


def current_company_id() -> uuid.UUID | None:
    state = _state.get()
    return state.company_id if state.mode == Mode.TENANT else None


def apply_db(state: TenantState) -> None:
    """Write ``state`` into the Postgres transaction settings read by RLS policies."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.company_id', %s, true),"
            " set_config('app.platform', %s, true),"
            " set_config('app.auth_lookup', %s, true)",
            [
                str(state.company_id) if state.mode == Mode.TENANT else "",
                "on" if state.mode == Mode.PLATFORM else "",
                "on" if state.mode == Mode.AUTH else "",
            ],
        )


def _db_usable() -> bool:
    return connection.in_atomic_block and not connection.needs_rollback


def activate(state: TenantState) -> None:
    """Switch the context for the rest of the current request/transaction.

    Used by authentication, which runs inside the request transaction
    (ATOMIC_REQUESTS). RequestContextMiddleware restores the previous state.
    """
    _state.set(state)
    if _db_usable():
        apply_db(state)


def set_python_state(state: TenantState) -> None:
    _state.set(state)


@contextmanager
def _scoped(state: TenantState) -> Iterator[None]:
    previous = _state.get()
    token = _state.set(state)
    try:
        with transaction.atomic():
            apply_db(state)
            yield
    finally:
        _state.reset(token)
        # The savepoint was released (settings persist) or rolled back (settings
        # reverted). Re-apply the outer state when the outer transaction continues.
        if _db_usable():
            apply_db(previous)


def tenant_context(company_id: uuid.UUID | str) -> contextmanager:
    if not company_id:
        raise ValueError("tenant_context requires a company id")
    return _scoped(TenantState(Mode.TENANT, uuid.UUID(str(company_id))))


def platform_context() -> contextmanager:
    return _scoped(TenantState(Mode.PLATFORM))


def auth_lookup_context() -> contextmanager:
    return _scoped(TenantState(Mode.AUTH))


def context_for_company(company_id: uuid.UUID | None) -> contextmanager:
    """Tenant context for a company user, platform context for a super admin (no company)."""
    return tenant_context(company_id) if company_id else platform_context()


def state_for_company(company_id: uuid.UUID | None) -> TenantState:
    return TenantState(Mode.TENANT, company_id) if company_id else TenantState(Mode.PLATFORM)
