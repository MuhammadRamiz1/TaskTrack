"""Postgres Row-Level Security: the second line of tenant isolation, tested directly."""

import pytest
from django.apps import apps
from django.db import DatabaseError, connection, transaction

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.common import tenancy
from apps.common.models import TenantModel
from tests import factories as f

EXTRA_RLS_TABLES = {  # tenant tables that are not TenantModel subclasses
    "companies_company",
    "accounts_user",
    "accounts_passwordresettoken",
    "accounts_usersession",
    "accounts_recoverycode",
    "rbac_role",
    "rbac_rolepermission",
    "audit_auditlog",
}


def _rows(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


def test_every_tenant_table_has_rls_and_policy():
    tables = {m._meta.db_table for m in apps.get_models() if issubclass(m, TenantModel)} | EXTRA_RLS_TABLES
    rows = dict(_rows("SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY(%s)", [list(tables)]))
    policies = {r[0] for r in _rows("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")}
    assert set(rows) == tables
    assert all(rows.values()), {t for t, on in rows.items() if not on}
    assert tables <= policies


def test_runtime_role_cannot_bypass_rls():
    assert _rows("SELECT current_user")[0][0] == "tasktrack_app"
    assert _rows("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")[0] == (False, False)


def test_no_context_sees_no_rows(company_a):
    f.make_user(company_a)
    tenancy.apply_db(tenancy.NO_CONTEXT)
    assert _rows("SELECT count(*) FROM accounts_user")[0][0] == 0
    assert _rows("SELECT count(*) FROM rbac_userrole")[0][0] == 0
    assert _rows("SELECT count(*) FROM companies_company")[0][0] == 0


def test_tenant_context_sees_only_own_company(company_a, company_b):
    a_user, b_user = f.make_user(company_a), f.make_user(company_b)
    with tenancy.tenant_context(company_a.pk):
        ids = {r[0] for r in _rows("SELECT id FROM accounts_user")}
        companies = {r[0] for r in _rows("SELECT id FROM companies_company")}
    assert a_user.pk in ids and b_user.pk not in ids
    assert companies == {company_a.pk}


def test_cross_tenant_insert_and_update_are_rejected(company_a, company_b):
    b_user = f.make_user(company_b)
    with tenancy.tenant_context(company_a.pk):
        with pytest.raises(DatabaseError), transaction.atomic():
            _rows(
                "INSERT INTO accounts_invitetoken (id, created_at, updated_at, company_id, user_id, token_hash,"
                " expires_at, send_count) VALUES (gen_random_uuid(), now(), now(), %s, %s, 'x', now(), 1)",
                [company_b.pk, b_user.pk],
            )
        with connection.cursor() as cursor:
            cursor.execute("UPDATE accounts_user SET first_name = 'pwned' WHERE id = %s", [b_user.pk])
            assert cursor.rowcount == 0
    b_user.refresh_from_db()
    assert b_user.first_name != "pwned"


def test_auth_lookup_is_read_only(company_a):
    user = f.make_user(company_a)
    with tenancy.auth_lookup_context():
        assert _rows("SELECT count(*) FROM accounts_user WHERE id = %s", [user.pk])[0][0] == 1
        assert _rows("SELECT count(*) FROM rbac_userrole")[0][0] == 0  # not an account table
        with connection.cursor() as cursor:
            cursor.execute("UPDATE accounts_user SET first_name = 'x' WHERE id = %s", [user.pk])
            assert cursor.rowcount == 0


def test_role_templates_visible_but_not_writable_by_tenant(company_a):
    with tenancy.tenant_context(company_a.pk):
        assert _rows("SELECT count(*) FROM rbac_role WHERE company_id IS NULL")[0][0] == 6
        with connection.cursor() as cursor:
            cursor.execute("UPDATE rbac_role SET rank = 1 WHERE company_id IS NULL")
            assert cursor.rowcount == 0


def test_tenant_manager_raises_without_context(company_a):
    tenancy.set_python_state(tenancy.NO_CONTEXT)
    with pytest.raises(tenancy.TenantContextMissing):
        list(User.objects.all())


def test_audit_log_is_append_only_in_database(company_a):
    entry = record(actor=None, action="test.event", company_id=company_a.pk)
    for sql in ("UPDATE audit_auditlog SET action = 'x' WHERE id = %s", "DELETE FROM audit_auditlog WHERE id = %s"):
        with pytest.raises(DatabaseError), transaction.atomic():
            _rows(sql, [entry.pk])
    with pytest.raises(PermissionError):
        AuditLog.objects.filter(pk=entry.pk).update(action="x")
    with pytest.raises(PermissionError):
        entry.delete()
