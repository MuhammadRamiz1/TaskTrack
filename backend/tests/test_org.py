from apps.audit.models import AuditLog
from apps.org.models import Project, TeamMember
from apps.rbac import policy
from apps.rbac.models import UserRole
from apps.tasks.models import Task
from tests import factories as f


class TestTeams:
    def test_hr_creates_team_members_and_lead(self, world, company_a):
        client = f.client_for(world.hr)
        team = client.post("/api/v1/org/teams/", {"name": "Mobile"}, format="json").json()
        assert client.post("/api/v1/org/teams/", {"name": "mobile"}, format="json").status_code == 400
        added = client.post(
            f"/api/v1/org/teams/{team['id']}/members/", {"user_ids": [str(world.member2.pk)]}, format="json"
        )
        assert added.status_code == 201 and len(added.json()) == 1
        led = client.post(f"/api/v1/org/teams/{team['id']}/lead/", {"user_id": str(world.member.pk)}, format="json")
        assert led.json()["lead"]["id"] == str(world.member.pk)
        binding = UserRole.objects.get(user=world.member, role__key="TEAM_LEAD")
        assert str(binding.team_id) == team["id"]
        assert TeamMember.objects.filter(team_id=team["id"], user=world.member).exists()
        detail = client.get(f"/api/v1/org/teams/{team['id']}/").json()
        assert detail["name"] == "Mobile"
        renamed = client.patch(f"/api/v1/org/teams/{team['id']}/", {"name": "Mobile Apps"}, format="json")
        assert renamed.json()["name"] == "Mobile Apps"
        members = client.get(f"/api/v1/org/teams/{team['id']}/members/").json()
        assert {m["user"]["id"] for m in members} == {str(world.member.pk), str(world.member2.pk)}

    def test_changing_lead_moves_the_binding(self, world):
        client = f.client_for(world.hr)
        client.post(f"/api/v1/org/teams/{world.team.pk}/lead/", {"user_id": str(world.member2.pk)}, format="json")
        assert not UserRole.objects.filter(user=world.lead, team=world.team).exists()
        assert UserRole.objects.filter(user=world.member2, team=world.team, role__key="TEAM_LEAD").exists()

    def test_remove_member_and_archive(self, world):
        client = f.client_for(world.hr)
        url = f"/api/v1/org/teams/{world.other_team.pk}"
        assert client.delete(f"{url}/members/{world.outsider.pk}/").status_code == 204
        assert client.delete(f"{url}/").status_code == 409  # has an active project
        world.other_project.status = Project.Status.ARCHIVED
        world.other_project.save()
        assert client.delete(f"{url}/").json()["is_archived"] is True

    def test_team_visibility_follows_scope(self, world):
        member_teams = {t["name"] for t in f.client_for(world.member).get("/api/v1/org/teams/").json()["results"]}
        hr_teams = {t["name"] for t in f.client_for(world.hr).get("/api/v1/org/teams/").json()["results"]}
        assert member_teams == {"Web"} and hr_teams == {"Web", "Ops"}
        assert f.client_for(world.member).get(f"/api/v1/org/teams/{world.other_team.pk}/").status_code == 404

    def test_member_cannot_manage_teams(self, world):
        assert f.client_for(world.member).post("/api/v1/org/teams/", {"name": "X"}, format="json").status_code == 403

    def test_set_employee_teams(self, world):
        client = f.client_for(world.hr)
        response = client.put(
            f"/api/v1/hr/employees/{world.member2.pk}/teams/", {"team_ids": [str(world.other_team.pk)]}, format="json"
        )
        assert response.status_code == 200 and [t["name"] for t in response.json()] == ["Ops"]
        assert set(TeamMember.objects.filter(user=world.member2).values_list("team__name", flat=True)) == {"Ops"}
        assert AuditLog.objects.filter(action="employee.teams_set", entity_id=str(world.member2.pk)).exists()


class TestProjects:
    def test_manager_creates_project_in_own_team_only(self, world):
        client = f.client_for(world.manager)
        created = client.post(
            "/api/v1/org/projects/", {"team_id": str(world.team.pk), "key": "api", "name": "Public API"}, format="json"
        )
        assert created.status_code == 201 and created.json()["key"] == "API"
        assert created.json()["owner"]["id"] == str(world.manager.pk)
        dup = client.post(
            "/api/v1/org/projects/", {"team_id": str(world.team.pk), "key": "API", "name": "Dup"}, format="json"
        )
        assert dup.status_code == 400
        other = client.post(
            "/api/v1/org/projects/", {"team_id": str(world.other_team.pk), "key": "OPZ", "name": "Nope"}, format="json"
        )
        assert other.status_code in (403, 404)

    def test_project_members_and_update(self, world):
        client = f.client_for(world.manager)
        url = f"/api/v1/org/projects/{world.project.pk}"
        added = client.post(f"{url}/members/", {"user_ids": [str(world.member2.pk)]}, format="json")
        assert added.status_code == 201
        assert client.delete(f"{url}/members/{world.manager.pk}/").status_code == 409  # owner
        assert client.delete(f"{url}/members/{world.member2.pk}/").status_code == 204
        patched = client.patch(f"{url}/", {"name": "Website", "end_date": "2027-01-31"}, format="json")
        assert patched.json()["name"] == "Website"
        archived = client.delete(f"{url}/")
        assert archived.json()["status"] == "ARCHIVED"

    def test_project_list_scoping(self, world):
        member_projects = {p["key"] for p in f.client_for(world.member).get("/api/v1/org/projects/").json()["results"]}
        lead_projects = {p["key"] for p in f.client_for(world.lead).get("/api/v1/org/projects/").json()["results"]}
        admin_projects = {p["key"] for p in f.client_for(world.admin).get("/api/v1/org/projects/").json()["results"]}
        assert member_projects == {"WEB"} and lead_projects == {"WEB"} and admin_projects == {"WEB", "OPS"}

    def test_directory_and_mentions_source(self, world):
        body = f.client_for(world.member).get("/api/v1/org/directory/?search=mi").json()
        assert [u["first_name"] for u in body["results"]] == ["Mia"]


class TestScopes:
    def test_team_lead_binding_limits_scope(self, world):
        web_task = f.make_task(world.project, world.manager)
        ops_task = f.make_task(world.other_project, world.admin)
        assert policy.can(world.lead, "task.view", web_task)
        assert not policy.can(world.lead, "task.view", ops_task)
        assert policy.can(world.manager, "task.update", web_task)
        assert not policy.can(world.manager, "task.update", ops_task)
        visible = policy.scope_queryset(world.lead, "task.view", Task.objects.all())
        assert list(visible) == [web_task]

    def test_project_bound_manager(self, world, company_a):
        bound = f.make_user(company_a)
        UserRole.objects.create(
            company=company_a, user=bound, role=f.role(company_a, "MANAGER"), project=world.other_project
        )
        task = f.make_task(world.other_project, world.admin)
        assert policy.can(bound, "task.assign", task)
        assert not policy.can(bound, "task.assign", f.make_task(world.project, world.manager))

    def test_hr_binds_role_to_team_via_api(self, world):
        response = f.client_for(world.hr).post(
            f"/api/v1/hr/employees/{world.member2.pk}/roles/",
            {"role_id": str(f.role(world.team.company, "TEAM_LEAD").pk), "team_id": str(world.other_team.pk)},
            format="json",
        )
        assert response.status_code == 201
        assert any(r["team_id"] == str(world.other_team.pk) for r in response.json())


class TestLeaveAndHolidays:
    def test_holidays(self, world):
        client = f.client_for(world.hr)
        created = client.post("/api/v1/hr/holidays/", {"date": "2026-12-25", "name": "Christmas"}, format="json")
        assert created.status_code == 201
        assert (
            client.post("/api/v1/hr/holidays/", {"date": "2026-12-25", "name": "Dup"}, format="json").status_code == 400
        )
        assert [h["name"] for h in f.client_for(world.member).get("/api/v1/hr/holidays/?year=2026").json()] == [
            "Christmas"
        ]
        assert client.delete(f"/api/v1/hr/holidays/{created.json()['id']}/").status_code == 204
        assert (
            f.client_for(world.member)
            .post("/api/v1/hr/holidays/", {"date": "2026-12-26", "name": "x"}, format="json")
            .status_code
            == 403
        )

    def test_leave_scoping(self, world):
        hr = f.client_for(world.hr)
        created = hr.post(
            "/api/v1/hr/leave/",
            {"user_id": str(world.member.pk), "date": "2026-12-01", "half_day": True},
            format="json",
        )
        assert created.status_code == 201
        hr.post("/api/v1/hr/leave/", {"user_id": str(world.outsider.pk), "date": "2026-12-01"}, format="json")
        own = f.client_for(world.member).get("/api/v1/hr/leave/").json()["results"]
        assert [r["user"]["id"] for r in own] == [str(world.member.pk)]
        lead_view = f.client_for(world.lead).get("/api/v1/hr/leave/").json()["results"]
        assert {r["user"]["id"] for r in lead_view} == {str(world.member.pk)}
        assert hr.delete(f"/api/v1/hr/leave/{created.json()['id']}/").status_code == 204
