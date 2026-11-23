"""Shared fixtures.

* Every test runs as the runtime database role (``SET LOCAL ROLE tasktrack_app``), so
  Postgres RLS is enforced exactly as in production.
* Test setup runs in PLATFORM context; each API request resets to the context its
  token proves, and the middleware restores the test's context afterwards.
* ``AuditCheckingClient`` asserts that every successful mutating request wrote at least
  one audit entry, and records which mutating routes were exercised; a full run fails
  if any mutating route was never exercised.
"""

import os

import pytest
from django.conf import settings
from django.db import connection
from django.urls import get_resolver, resolve
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.common import tenancy
from tests import factories as f

PLATFORM = tenancy.TenantState(tenancy.Mode.PLATFORM)

#: Mutating routes that legitimately may change nothing (and so write no audit entry).
AUDIT_EXEMPT = {
    ("auth-password-forgot", "POST"),  # unknown/inactive email: nothing happens (no enumeration)
    ("auth-logout", "POST"),  # no or invalid cookie: nothing to revoke
    ("auth-refresh", "POST"),  # rotation is bookkeeping; reuse detection is audited separately
    ("hr-employee-import-preview", "POST"),  # read-only check of an uploaded sheet
}
SKIP_COVERAGE = {"schema", "docs", "redoc"}

_exercised: set[tuple[str, str]] = set()


class AuditCheckingClient(APIClient):
    def generic(self, method, path, *args, **kwargs):
        mutating = method.upper() not in {"GET", "HEAD", "OPTIONS"}
        before = AuditLog.objects.count() if mutating else 0
        response = super().generic(method, path, *args, **kwargs)
        if mutating and 200 <= response.status_code < 300:
            name = resolve(path.split("?")[0]).url_name
            _exercised.add((name, method.upper()))
            if (name, method.upper()) not in AUDIT_EXEMPT:
                assert AuditLog.objects.count() > before, f"{method} {path} succeeded without an audit entry"
        return response


@pytest.fixture(autouse=True)
def _runtime_role(db):
    with connection.cursor() as cursor:
        cursor.execute(f'SET LOCAL ROLE "{settings.DB_APP_ROLE}"')
    tenancy.set_python_state(PLATFORM)
    tenancy.apply_db(PLATFORM)
    yield
    tenancy.set_python_state(tenancy.NO_CONTEXT)


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()


@pytest.fixture
def anon():
    return f.client_for(None)


@pytest.fixture
def company_a():
    return f.CompanyFactory(name="Acme", slug="acme")


@pytest.fixture
def company_b():
    return f.CompanyFactory(name="Globex", slug="globex")


@pytest.fixture
def super_admin():
    return f.make_user(None, email="root@platform.test")


@pytest.fixture
def mailbox(django_capture_on_commit_callbacks):
    """Use as ``with mailbox(): ...`` to run on_commit callbacks (emails) in tests."""
    from django.core import mail

    def run():
        return django_capture_on_commit_callbacks(execute=True)

    run.outbox = mail.outbox
    return run


def _mutating_routes() -> set[tuple[str, str]]:
    routes = set()

    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns, prefix + str(p.pattern))
                continue
            view = getattr(p.callback, "view_class", None)
            if view is None or p.name in SKIP_COVERAGE or not (prefix + str(p.pattern)).startswith("api/v1/"):
                continue
            for method in ("post", "put", "patch", "delete"):
                if hasattr(view, method):
                    routes.add((p.name, method.upper()))

    walk(get_resolver().url_patterns)
    return routes


def pytest_sessionfinish(session, exitstatus):
    full_run = (
        not session.config.option.keyword
        and not session.config.option.markexpr
        and all(os.path.basename(str(a).rstrip("/\\")) == "tests" for a in session.config.args)
    )
    if not full_run or exitstatus != 0 or os.environ.get("PYTEST_XDIST_WORKER"):
        return
    routes = _mutating_routes()
    missing = sorted(routes - _exercised)
    print(
        f"\nAudit coverage: {len(routes) - len(missing)}/{len(routes)} mutating routes exercised with an audit check."
    )
    if missing:
        print("\nMutating endpoints never exercised by a successful test (audit coverage):")
        for name, method in missing:
            print(f"  {method} {name}")
        session.exitstatus = 1


from tests.conftest_world import world  # noqa: E402, F401 - shared fixture
