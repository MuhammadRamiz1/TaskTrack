import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.companies.models import Plan
from apps.rbac.models import Role
from tests import factories as f

COMPANIES = "/api/v1/platform/companies/"


@pytest.fixture
def root(super_admin):
    return f.client_for(super_admin)


def test_company_lifecycle(root, mailbox):
    plan = Plan.objects.get(code="business")
    created = root.post(COMPANIES, {"name": "Initech", "plan": str(plan.pk), "timezone": "Asia/Karachi"}, format="json")
    assert created.status_code == 201, created.content
    company_id = created.json()["id"]
    assert created.json()["slug"] == "initech" and created.json()["max_users"] == 100
    assert Role.objects.filter(company_id=company_id).count() == 5

    with mailbox():
        admin = root.post(
            f"{COMPANIES}{company_id}/admins/", {"email": "hr@initech.test", "first_name": "Hannah"}, format="json"
        )
    assert admin.status_code == 201
    hr = User.objects.get(email="hr@initech.test")
    assert hr.status == User.Status.INVITED and hr.user_roles.get().role.key == "HR"
    assert "/accept-invite/" in mailbox.outbox[-1].body

    patched = root.patch(f"{COMPANIES}{company_id}/", {"max_users_override": 3}, format="json")
    assert patched.json()["max_users"] == 3
    usage = root.get(f"{COMPANIES}{company_id}/usage/").json()
    assert usage["users"]["invited"] == 1 and usage["max_users"] == 3
    assert root.get(COMPANIES + "?search=init").json()["count"] == 1

    assert root.delete(f"{COMPANIES}{company_id}/").json()["status"] == "DELETED"
    assert root.post(f"{COMPANIES}{company_id}/activate/").json()["status"] == "ACTIVE"
    assert AuditLog.objects.filter(company_id=company_id, action__startswith="platform.company.").count() >= 4


def test_duplicate_company_name_rejected(root, company_a):
    plan = Plan.objects.get(code="business")
    assert root.post(COMPANIES, {"name": "ACME", "plan": str(plan.pk)}, format="json").status_code == 400


def test_suspend_blocks_existing_tokens_and_login(root, company_a, anon):
    member = f.make_user(company_a)
    member_client = f.client_for(member)
    response = root.post(f"{COMPANIES}{company_a.pk}/suspend/", {"reason": "unpaid invoice"}, format="json")
    assert response.status_code == 200 and response.json()["status"] == "SUSPENDED"
    assert member_client.get("/api/v1/auth/me/").status_code in (401, 403)
    assert (
        anon.post("/api/v1/auth/login/", {"email": member.email, "password": f.PASSWORD}, format="json").status_code
        == 401
    )
    root.post(f"{COMPANIES}{company_a.pk}/activate/")
    assert (
        anon.post("/api/v1/auth/login/", {"email": member.email, "password": f.PASSWORD}, format="json").status_code
        == 200
    )


def test_plans(root):
    created = root.post(
        "/api/v1/platform/plans/",
        {"code": "pro", "name": "Pro", "max_users": 50, "max_storage_mb": 1000},
        format="json",
    )
    assert created.status_code == 201
    plan_id = created.json()["id"]
    assert root.patch(f"/api/v1/platform/plans/{plan_id}/", {"max_users": 60}, format="json").json()["max_users"] == 60
    assert root.get(f"/api/v1/platform/plans/{plan_id}/").status_code == 200
    assert {p["code"] for p in root.get("/api/v1/platform/plans/").json()} >= {"starter", "business", "pro"}


def test_company_users_cannot_use_platform_endpoints(company_a):
    admin = f.client_for(f.make_user(company_a, "COMPANY_ADMIN"))
    for url in (COMPANIES, "/api/v1/platform/plans/", "/api/v1/platform/audit/"):
        assert admin.get(url).status_code == 403


def test_super_admin_cannot_read_tenant_data_directly(root):
    for url in ("/api/v1/hr/employees/", "/api/v1/audit/", "/api/v1/company/settings/"):
        assert root.get(url).status_code == 403


def test_impersonation_is_read_only_and_audited(root, super_admin, company_a):
    target = f.make_user(company_a, "HR")
    started = root.post(
        "/api/v1/platform/impersonations/", {"user_id": str(target.pk), "reason": "Support ticket #4521"}, format="json"
    )
    assert started.status_code == 201
    imp = f.client_for(None)
    imp.credentials(HTTP_AUTHORIZATION=f"Bearer {started.json()['access']}")
    me = imp.get("/api/v1/auth/me/").json()
    assert me["id"] == str(target.pk) and me["impersonation"]["super_admin_email"] == super_admin.email
    assert imp.get("/api/v1/hr/employees/").status_code == 200
    blocked = imp.post("/api/v1/hr/employees/", {"email": "x@acme.test", "first_name": "X"}, format="json")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "impersonation_read_only"
    entries = AuditLog.objects.filter(action="impersonation.request", company_id=company_a.pk)
    assert entries.count() >= 2 and entries.first().actor_id == super_admin.pk
    assert entries.first().impersonator_id == super_admin.pk
    assert imp.get("/api/v1/platform/companies/").status_code == 403  # not a platform session

    session_id = started.json()["id"]
    assert root.post(f"/api/v1/platform/impersonations/{session_id}/end/").status_code == 204
    assert imp.get("/api/v1/auth/me/").status_code == 401


def test_cannot_impersonate_super_admin(root, super_admin):
    response = root.post(
        "/api/v1/platform/impersonations/", {"user_id": str(super_admin.pk), "reason": "Should not work"}, format="json"
    )
    assert response.status_code == 404


def test_platform_audit_spans_companies(root, company_a, company_b):
    f.client_for(f.make_user(company_a, "COMPANY_ADMIN")).patch(
        "/api/v1/company/settings/", {"enforce_2fa": True}, format="json"
    )
    f.client_for(f.make_user(company_b, "COMPANY_ADMIN")).patch(
        "/api/v1/company/settings/", {"enforce_2fa": True}, format="json"
    )
    body = root.get("/api/v1/platform/audit/?action=company.settings").json()
    assert {e["company_id"] for e in body["results"]} == {str(company_a.pk), str(company_b.pk)}
    filtered = root.get(f"/api/v1/platform/audit/?company={company_a.pk}&action=company.settings").json()
    assert filtered["count"] == 1


def test_create_super_admin_command(capsys):
    import os

    from django.core.management import call_command

    os.environ["TT_TEST_ROOT_PW"] = "Root-Passw0rd-2026!"
    call_command("create_super_admin", email="ops@platform.test", password_env="TT_TEST_ROOT_PW")
    user = User.objects.get(email="ops@platform.test")
    assert user.is_platform_admin and user.company_id is None and user.is_active


def test_company_users_listing_is_identity_only_and_audited(root, company_a):
    member = f.make_user(company_a, "MANAGER", first_name="Zed")
    body = root.get(f"{COMPANIES}{company_a.pk}/users/?search=zed").json()
    assert body["count"] == 1
    assert set(body["results"][0]) == {"id", "email", "full_name", "status", "roles", "last_login"}
    assert body["results"][0]["roles"] == ["Manager"] and body["results"][0]["id"] == str(member.pk)
    assert AuditLog.objects.filter(action="platform.company.users_listed", company_id=company_a.pk).exists()
