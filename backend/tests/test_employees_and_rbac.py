import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.rbac import policy
from apps.rbac.catalogue import GRANTS, PERMISSIONS, RoleKey
from apps.rbac.models import Permission, Role, RolePermission, UserRole
from tests import factories as f

EMPLOYEES = "/api/v1/hr/employees/"


@pytest.fixture
def hr(company_a):
    return f.make_user(company_a, "HR", email="hr@acme.test")


@pytest.fixture
def admin(company_a):
    return f.make_user(company_a, "COMPANY_ADMIN", email="admin@acme.test")


class TestCatalogue:
    def test_catalogue_loaded_into_database(self):
        assert set(Permission.objects.values_list("code", flat=True)) == set(PERMISSIONS)
        for key, grants in GRANTS.items():
            template = Role.objects.get(company__isnull=True, key=key)
            stored = dict(RolePermission.objects.filter(role=template).values_list("permission__code", "scope"))
            assert stored == {c: s.value for c, s in grants.items()}

    def test_company_gets_its_own_copy_of_roles(self, company_a):
        keys = set(Role.objects.filter(company=company_a).values_list("key", flat=True))
        assert keys == {k.value for k in RoleKey} - {"SUPER_ADMIN"}

    def test_hr_cannot_see_task_content(self, hr):
        assert not any(code.startswith("task.") for code in policy.permissions_for(hr))

    def test_scopes_resolve_per_role(self, company_a):
        member = f.make_user(company_a)
        other = f.make_user(company_a)
        assert policy.can(member, "employee.view_private", member)
        assert not policy.can(member, "employee.view_private", other)
        qs = policy.scope_queryset(member, "employee.view_private", User.objects.all())
        assert list(qs) == [member]


class TestEmployees:
    def test_create_employee(self, hr, company_a):
        manager = f.make_user(company_a, "MANAGER")
        lead_role = f.role(company_a, "TEAM_LEAD")
        response = f.client_for(hr).post(
            EMPLOYEES,
            {
                "email": "Lead@Acme.test",
                "first_name": "Lea",
                "job_title": "Lead",
                "manager_id": str(manager.pk),
                "role_ids": [str(lead_role.pk)],
                "send_invite": False,
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["email"] == "lead@acme.test" and body["status"] == "INVITED"
        assert [r["key"] for r in body["roles"]] == ["TEAM_LEAD"] and body["manager"]["id"] == str(manager.pk)
        assert body["invite"]["state"] == "none"

    def test_duplicate_email_rejected_even_across_companies(self, hr, company_b):
        f.make_user(company_b, email="taken@globex.test")
        response = f.client_for(hr).post(EMPLOYEES, {"email": "TAKEN@globex.test", "first_name": "X"}, format="json")
        assert response.status_code == 400 and "email" in response.json()["error"]["details"]

    def test_hr_cannot_grant_equal_or_higher_role(self, hr, company_a):
        response = f.client_for(hr).post(
            EMPLOYEES,
            {
                "email": "x@acme.test",
                "first_name": "X",
                "role_ids": [str(f.role(company_a, "HR").pk)],
            },
            format="json",
        )
        assert response.status_code == 422 and response.json()["error"]["code"] == "rank_violation"

    def test_user_limit(self, hr, company_a):
        company_a.max_users_override = 1
        company_a.save()
        response = f.client_for(hr).post(EMPLOYEES, {"email": "x@acme.test", "first_name": "X"}, format="json")
        assert response.status_code == 422 and response.json()["error"]["code"] == "user_limit_exceeded"

    def test_list_filter_and_search(self, hr, company_a):
        f.make_user(company_a, "MANAGER", first_name="Maria")
        f.make_user(company_a, status=User.Status.DEACTIVATED, first_name="Gone")
        client = f.client_for(hr)
        assert {e["first_name"] for e in client.get(EMPLOYEES + "?role=MANAGER").json()["results"]} == {"Maria"}
        assert client.get(EMPLOYEES + "?search=gone").json()["count"] == 1
        assert client.get(EMPLOYEES + "?status=DEACTIVATED").json()["count"] == 1

    def test_member_sees_only_self(self, company_a):
        member = f.make_user(company_a)
        f.make_user(company_a)
        body = f.client_for(member).get(EMPLOYEES).json()
        assert [e["id"] for e in body["results"]] == [str(member.pk)]

    def test_member_cannot_create(self, company_a):
        member = f.make_user(company_a)
        response = f.client_for(member).post(EMPLOYEES, {"email": "x@acme.test", "first_name": "X"}, format="json")
        assert response.status_code == 403

    def test_update_and_audit_diff(self, hr, company_a):
        member = f.make_user(company_a, job_title="Dev")
        response = f.client_for(hr).patch(f"{EMPLOYEES}{member.pk}/", {"job_title": "Senior Dev"}, format="json")
        assert response.status_code == 200 and response.json()["job_title"] == "Senior Dev"
        entry = AuditLog.objects.get(action="employee.updated", entity_id=str(member.pk))
        assert entry.old_value == {"job_title": "Dev"} and entry.new_value == {"job_title": "Senior Dev"}
        assert entry.actor_id == hr.pk and entry.company_id == company_a.pk

    def test_member_edits_own_profile_but_not_manager(self, company_a):
        member = f.make_user(company_a)
        manager = f.make_user(company_a, "MANAGER")
        client = f.client_for(member)
        assert client.patch(f"{EMPLOYEES}{member.pk}/", {"job_title": "Me"}, format="json").status_code == 200
        response = client.patch(f"{EMPLOYEES}{member.pk}/", {"manager_id": str(manager.pk)}, format="json")
        assert response.status_code == 403

    def test_deactivate_revokes_sessions(self, hr, company_a, mailbox):
        member = f.make_user(company_a)
        member_client = f.client_for(member)
        with mailbox():
            response = f.client_for(hr).post(f"{EMPLOYEES}{member.pk}/deactivate/", {"reason": "left"}, format="json")
        assert response.status_code == 200 and response.json()["sessions_revoked"] == 1
        assert member_client.get("/api/v1/auth/me/").status_code == 401
        member.refresh_from_db()
        assert member.status == User.Status.DEACTIVATED
        again = f.client_for(hr).post(f"{EMPLOYEES}{member.pk}/deactivate/", {}, format="json")
        assert again.status_code == 409

    def test_offboard_and_reactivate(self, hr, company_a):
        member = f.make_user(company_a)
        client = f.client_for(hr)
        assert (
            client.post(f"{EMPLOYEES}{member.pk}/offboard/", {"reason": "contract ended"}, format="json").status_code
            == 200
        )
        assert AuditLog.objects.filter(action="employee.offboarded", entity_id=str(member.pk)).exists()
        response = client.post(f"{EMPLOYEES}{member.pk}/reactivate/")
        assert response.status_code == 200 and response.json()["status"] == "ACTIVE"

    def test_revoke_sessions(self, hr, company_a):
        member = f.make_user(company_a)
        member_client = f.client_for(member)
        response = f.client_for(hr).post(f"{EMPLOYEES}{member.pk}/revoke-sessions/")
        assert response.status_code == 200 and response.json()["sessions_revoked"] == 1
        assert member_client.get("/api/v1/auth/me/").status_code == 401

    def test_hr_cannot_deactivate_hr_or_self(self, hr, company_a):
        other_hr = f.make_user(company_a, "HR")
        client = f.client_for(hr)
        assert client.post(f"{EMPLOYEES}{other_hr.pk}/deactivate/", {}, format="json").status_code == 422
        assert client.post(f"{EMPLOYEES}{hr.pk}/deactivate/", {}, format="json").status_code in (409, 422)


class TestRoleAssignment:
    def test_grant_and_revoke_role(self, hr, company_a):
        member = f.make_user(company_a)
        client = f.client_for(hr)
        manager_role = f.role(company_a, "MANAGER")
        granted = client.post(f"{EMPLOYEES}{member.pk}/roles/", {"role_id": str(manager_role.pk)}, format="json")
        assert granted.status_code == 201 and {r["key"] for r in granted.json()} == {"MANAGER", "TEAM_MEMBER"}
        assert (
            client.post(f"{EMPLOYEES}{member.pk}/roles/", {"role_id": str(manager_role.pk)}, format="json").status_code
            == 409
        )
        member_client = f.client_for(member)
        user_role = UserRole.objects.get(user=member, role=manager_role)
        assert client.delete(f"{EMPLOYEES}{member.pk}/roles/{user_role.pk}/").status_code == 204
        assert member_client.get("/api/v1/auth/me/").status_code == 401  # forced to refresh
        assert client.get(f"{EMPLOYEES}{member.pk}/roles/").json()[0]["key"] == "TEAM_MEMBER"

    def test_cannot_remove_last_role(self, hr, company_a):
        member = f.make_user(company_a)
        user_role = UserRole.objects.get(user=member)
        response = f.client_for(hr).delete(f"{EMPLOYEES}{member.pk}/roles/{user_role.pk}/")
        assert response.status_code == 409 and response.json()["error"]["code"] == "last_role"

    def test_grantable_roles_below_own_rank(self, hr):
        keys = {r["key"] for r in f.client_for(hr).get("/api/v1/hr/roles/").json()}
        assert keys == {"MANAGER", "TEAM_LEAD", "TEAM_MEMBER"}

    def test_foreign_role_rejected(self, hr, company_a, company_b):
        member = f.make_user(company_a)
        response = f.client_for(hr).post(
            f"{EMPLOYEES}{member.pk}/roles/", {"role_id": str(f.role(company_b, "TEAM_LEAD").pk)}, format="json"
        )
        assert response.status_code == 400


class TestCompanyRoles:
    def test_custom_role_lifecycle(self, admin, company_a):
        client = f.client_for(admin)
        created = client.post(
            "/api/v1/company/roles/",
            {
                "name": "Auditor",
                "rank": 20,
                "permissions": [{"code": "audit.view", "scope": "COMPANY"}],
            },
            format="json",
        )
        assert created.status_code == 201, created.content
        role_id = created.json()["id"]
        updated = client.put(
            f"/api/v1/company/roles/{role_id}/permissions/",
            {
                "permissions": [
                    {"code": "audit.view", "scope": "COMPANY"},
                    {"code": "employee.view", "scope": "COMPANY"},
                ]
            },
            format="json",
        )
        assert {p["code"] for p in updated.json()["permissions"]} == {"audit.view", "employee.view"}
        assert (
            client.patch(f"/api/v1/company/roles/{role_id}/", {"name": "Auditors"}, format="json").json()["name"]
            == "Auditors"
        )
        member = f.make_user(company_a)
        f.client_for(admin).post(f"{EMPLOYEES}{member.pk}/roles/", {"role_id": role_id}, format="json")
        assert f.client_for(member).get("/api/v1/audit/").status_code == 200  # data-driven grant works
        assert client.delete(f"/api/v1/company/roles/{role_id}/").status_code == 409  # still held
        UserRole.objects.filter(role_id=role_id).delete()
        assert client.delete(f"/api/v1/company/roles/{role_id}/").status_code == 204

    def test_invalid_scope_and_platform_permissions_rejected(self, admin):
        client = f.client_for(admin)
        for grant in (
            {"code": "employee.create", "scope": "OWN"},
            {"code": "platform.audit.view", "scope": "COMPANY"},
            {"code": "nope", "scope": "COMPANY"},
        ):
            response = client.post(
                "/api/v1/company/roles/", {"name": "Bad", "rank": 5, "permissions": [grant]}, format="json"
            )
            assert response.status_code == 400

    def test_protected_grants_and_system_roles(self, admin, company_a):
        client = f.client_for(admin)
        admin_role = f.role(company_a, "COMPANY_ADMIN")
        assert (
            client.put(
                f"/api/v1/company/roles/{admin_role.pk}/permissions/", {"permissions": []}, format="json"
            ).status_code
            == 422
        )  # cannot edit own-rank role
        assert client.delete(f"/api/v1/company/roles/{f.role(company_a, 'MANAGER').pk}/").status_code == 409

    def test_catalogue_hides_platform_permissions(self, admin):
        codes = {p["code"] for p in f.client_for(admin).get("/api/v1/company/permissions/").json()}
        assert "task.view" in codes and not any(c.startswith("platform.") for c in codes)

    def test_hr_cannot_manage_roles(self, hr):
        assert f.client_for(hr).get("/api/v1/company/roles/").status_code == 403


class TestCompanySettings:
    def test_admin_updates_settings(self, admin, company_a):
        client = f.client_for(admin)
        response = client.patch(
            "/api/v1/company/settings/", {"invite_expiry_hours": 24, "working_days": [0, 1, 2]}, format="json"
        )
        assert response.status_code == 200 and response.json()["invite_expiry_hours"] == 24
        assert AuditLog.objects.filter(action="company.settings.updated", company_id=company_a.pk).exists()
        assert client.patch("/api/v1/company/settings/", {"working_days": [9]}, format="json").status_code == 400

    def test_member_reads_but_cannot_edit(self, company_a):
        client = f.client_for(f.make_user(company_a))
        assert client.get("/api/v1/company/settings/").status_code == 200
        assert client.patch("/api/v1/company/settings/", {"enforce_2fa": True}, format="json").status_code == 403
