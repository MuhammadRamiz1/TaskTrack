"""Task CRUD, assignment, checklists, dependencies, comments, attachments, escalation,
workload, offboarding."""

import threading
from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.utils.timezone import now as timezone_now

from apps.companies.models import Company
from apps.notifications.models import Notification
from apps.tasks.models import Status, Task, TaskAttachment, TaskDependency
from tests import factories as f

TASKS = "/api/v1/tasks/"


@pytest.fixture
def task(world):
    return f.make_task(
        world.project,
        world.manager,
        assignees=[world.member],
        title="Build login page",
        estimated_minutes=120,
        due_date=date.today() + timedelta(days=2),
    )


class TestCrud:
    def test_create_with_keys_and_assignees(self, world):
        client = f.client_for(world.manager)
        body = client.post(
            TASKS,
            {
                "project_id": str(world.project.pk),
                "title": "Set up CI",
                "priority": "HIGH",
                "acceptance_criteria": "Pipeline green",
                "assignee_ids": [str(world.member.pk)],
                "due_date": "2026-12-31",
            },
            format="json",
        ).json()
        assert body["key"] == "WEB-1" and body["status"] == "ASSIGNED" and body["priority"] == "HIGH"
        assert [a["user"]["id"] for a in body["assignees"]] == [str(world.member.pk)]
        second = client.post(TASKS, {"project_id": str(world.project.pk), "title": "Next"}, format="json").json()
        assert second["key"] == "WEB-2"
        assert client.get(f"{TASKS}by-key/web-1/").json()["id"] == body["id"]

    def test_member_cannot_create_and_cannot_see_other_projects(self, world):
        member = f.client_for(world.member)
        assert member.post(TASKS, {"project_id": str(world.project.pk), "title": "x"}, format="json").status_code == 403
        f.make_task(world.other_project, world.admin, title="Ops secret")
        assert member.get(TASKS).json()["count"] == 0

    def test_manager_cannot_create_in_foreign_project(self, world):
        response = f.client_for(world.manager).post(
            TASKS, {"project_id": str(world.other_project.pk), "title": "x"}, format="json"
        )
        assert response.status_code == 400

    def test_update_with_optimistic_locking(self, world, task):
        client = f.client_for(world.manager)
        ok = client.patch(f"{TASKS}{task.pk}/", {"title": "Build sign-in page", "version": task.version}, format="json")
        assert ok.status_code == 200 and ok.json()["version"] == task.version + 1
        stale = client.patch(f"{TASKS}{task.pk}/", {"title": "Other", "version": task.version}, format="json")
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"
        missing = client.patch(f"{TASKS}{task.pk}/", {"title": "Other"}, format="json")
        assert missing.status_code == 400

    def test_concurrent_edits_one_wins(self, world, task):
        """Two edits from the same version: the second sees a 409, never a silent overwrite."""
        a, b = f.client_for(world.manager), f.client_for(world.admin)
        first = a.patch(f"{TASKS}{task.pk}/", {"description": "A", "version": task.version}, format="json")
        second = b.patch(f"{TASKS}{task.pk}/", {"description": "B", "version": task.version}, format="json")
        assert (first.status_code, second.status_code) == (200, 409)
        task.refresh_from_db()
        assert task.description == "A"

    def test_member_cannot_edit_fields(self, world, task):
        response = f.client_for(world.member).patch(
            f"{TASKS}{task.pk}/", {"title": "x", "version": task.version}, format="json"
        )
        assert response.status_code == 403

    def test_priority_needs_permission(self, world, task):
        lead = f.client_for(world.lead)
        assert (
            lead.patch(f"{TASKS}{task.pk}/", {"priority": "URGENT", "version": task.version}, format="json").status_code
            == 403
        )
        admin = f.client_for(world.admin)
        from apps.rbac.models import Permission, RolePermission

        lead_role = f.role(world.team.company, "TEAM_LEAD")
        RolePermission.objects.create(
            role=lead_role, permission=Permission.objects.get(code="task.set_priority"), scope="TEAM"
        )
        assert admin  # grant made directly; in the product HR/Admin use PUT /company/roles/{id}/permissions/
        response = lead.patch(f"{TASKS}{task.pk}/", {"priority": "URGENT", "version": task.version}, format="json")
        assert response.status_code == 200 and response.json()["priority"] == "URGENT"

    def test_subtasks_depth_limit(self, world, task):
        client = f.client_for(world.manager)
        parent = task
        for depth in range(2):
            sub = client.post(f"{TASKS}{parent.pk}/subtasks/", {"title": f"level {depth + 2}"}, format="json")
            assert sub.status_code == 201, sub.content
            parent = Task.objects.get(pk=sub.json()["id"])
        too_deep = client.post(f"{TASKS}{parent.pk}/subtasks/", {"title": "level 4"}, format="json")
        assert too_deep.status_code == 400
        assert len(client.get(f"{TASKS}{task.pk}/subtasks/").json()) == 1
        assert client.get(f"{TASKS}{task.pk}/").json()["subtasks"][0]["title"] == "level 2"

    def test_delete_and_restore(self, world, task):
        client = f.client_for(world.manager)
        assert client.delete(f"{TASKS}{task.pk}/").status_code == 204
        assert client.get(f"{TASKS}{task.pk}/").status_code == 404
        assert client.post(f"{TASKS}{task.pk}/restore/").json()["id"] == str(task.pk)

    def test_filters_search_and_ordering(self, world, task):
        f.make_task(world.project, world.manager, title="Write docs", priority="URGENT")
        client = f.client_for(world.manager)
        assert client.get(f"{TASKS}?search=login").json()["count"] == 1
        assert client.get(f"{TASKS}?mine=true").json()["count"] == 0
        assert f.client_for(world.member).get(f"{TASKS}?mine=true").json()["count"] == 1
        assert client.get(f"{TASKS}?status=ASSIGNED&status=BACKLOG").json()["count"] == 2
        ordered = client.get(f"{TASKS}?ordering=-priority_rank").json()["results"]
        assert ordered[0]["priority"] == "URGENT"
        assert client.get(f"{TASKS}?assignee={world.member.pk}").json()["count"] == 1
        assert client.get(f"{TASKS}?parent=none").json()["count"] == 2

    def test_board_and_calendar(self, world, task):
        client = f.client_for(world.manager)
        board = client.get(f"{TASKS}board/?project={world.project.pk}").json()
        assigned = next(c for c in board["columns"] if c["status"] == "ASSIGNED")
        assert [t["id"] for t in assigned["tasks"]] == [str(task.pk)]
        today = date.today()
        cal = client.get(f"{TASKS}calendar/?start={today}&end={today + timedelta(days=7)}").json()
        assert [t["id"] for t in cal] == [str(task.pk)]
        assert client.get(f"{TASKS}calendar/?start={today}&end={today - timedelta(days=1)}").status_code == 400


class TestAssignment:
    def test_assignee_must_belong_to_project_or_team(self, world, task):
        client = f.client_for(world.manager)
        outside = client.post(f"{TASKS}{task.pk}/assignees/", {"user_ids": [str(world.outsider.pk)]}, format="json")
        assert outside.status_code == 400
        team_member = client.post(f"{TASKS}{task.pk}/assignees/", {"user_ids": [str(world.member2.pk)]}, format="json")
        assert team_member.status_code == 201  # in the team: added to the project automatically
        assert world.project.memberships.filter(user=world.member2).exists()
        admin_assigns_anyone = f.client_for(world.admin).post(
            f"{TASKS}{task.pk}/assignees/", {"user_ids": [str(world.outsider.pk)]}, format="json"
        )
        assert admin_assigns_anyone.status_code == 201

    def test_assignment_notifies(self, world, task):
        assert Notification.objects.filter(recipient=world.member, event_type="task.assigned").count() == 1

    def test_unassign_last_reverts_to_backlog(self, world, task):
        client = f.client_for(world.manager)
        assert client.delete(f"{TASKS}{task.pk}/assignees/{world.member.pk}/").status_code == 204
        task.refresh_from_db()
        assert task.status == Status.BACKLOG

    def test_reassign(self, world, task):
        response = f.client_for(world.manager).post(
            f"{TASKS}{task.pk}/reassign/",
            {"from_user_id": str(world.member.pk), "to_user_id": str(world.member2.pk)},
            format="json",
        )
        assert response.status_code == 200
        assert [a["user"]["id"] for a in response.json()["assignees"]] == [str(world.member2.pk)]
        assert response.json()["status"] == "ASSIGNED"

    def test_bulk_assign_is_all_or_nothing(self, world, task):
        other = f.make_task(world.project, world.manager)
        foreign = f.make_task(world.other_project, world.admin)
        client = f.client_for(world.manager)
        failed = client.post(
            f"{TASKS}bulk-assign/",
            {"task_ids": [str(other.pk), str(foreign.pk)], "user_ids": [str(world.member2.pk)]},
            format="json",
        )
        assert failed.status_code == 404
        assert not other.assignees.exists()
        ok = client.post(
            f"{TASKS}bulk-assign/",
            {"task_ids": [str(other.pk), str(task.pk)], "user_ids": [str(world.member2.pk)], "mode": "replace"},
            format="json",
        )
        assert ok.json()["count"] == 2
        assert list(task.assignees.values_list("user_id", flat=True)) == [world.member2.pk]

    def test_lead_assigns_within_team_only(self, world, task):
        lead = f.client_for(world.lead)
        assert (
            lead.post(f"{TASKS}{task.pk}/assignees/", {"user_ids": [str(world.member2.pk)]}, format="json").status_code
            == 201
        )
        ops_task = f.make_task(world.other_project, world.admin)
        assert (
            lead.post(
                f"{TASKS}{ops_task.pk}/assignees/", {"user_ids": [str(world.member2.pk)]}, format="json"
            ).status_code
            == 404
        )

    def test_acknowledge(self, world, task):
        client = f.client_for(world.member)
        body = client.post(f"{TASKS}{task.pk}/acknowledge/").json()
        assert body["assignees"][0]["acknowledged_at"] is not None
        assert client.post(f"{TASKS}{task.pk}/acknowledge/").status_code == 409

    def test_offboarding_flags_open_tasks(self, world, task):
        response = f.client_for(world.hr).post(
            f"/api/v1/hr/employees/{world.member.pk}/offboard/", {"reason": "left"}, format="json"
        )
        assert response.json()["tasks_flagged"] == 1
        task.refresh_from_db()
        assert task.needs_reassignment
        assert Notification.objects.filter(recipient=world.manager, event_type="task.needs_reassignment").exists()
        f.client_for(world.manager).post(
            f"{TASKS}{task.pk}/reassign/",
            {"from_user_id": str(world.member.pk), "to_user_id": str(world.member2.pk)},
            format="json",
        )
        task.refresh_from_db()
        assert not task.needs_reassignment


class TestChecklists:
    def test_manage_and_complete(self, world, task):
        manager, member = f.client_for(world.manager), f.client_for(world.member)
        checklist = manager.post(f"{TASKS}{task.pk}/checklists/", {"title": "Definition of done"}, format="json").json()
        item = manager.post(
            f"{TASKS}{task.pk}/checklists/{checklist['id']}/items/",
            {"text": "Tests pass", "is_required": True},
            format="json",
        ).json()
        assert member.post(f"{TASKS}{task.pk}/checklists/", {"title": "x"}, format="json").status_code == 403
        assert (
            member.patch(
                f"{TASKS}{task.pk}/checklist-items/{item['id']}/", {"text": "changed"}, format="json"
            ).status_code
            == 403
        )
        done = member.patch(f"{TASKS}{task.pk}/checklist-items/{item['id']}/", {"is_done": True}, format="json")
        assert done.json()["is_done"] is True and done.json()["done_by"]["id"] == str(world.member.pk)
        renamed = manager.patch(f"{TASKS}{task.pk}/checklists/{checklist['id']}/", {"title": "DoD"}, format="json")
        assert renamed.json()["title"] == "DoD"
        listed = member.get(f"{TASKS}{task.pk}/checklists/").json()
        assert listed[0]["items"][0]["is_required"] is True
        assert manager.delete(f"{TASKS}{task.pk}/checklist-items/{item['id']}/").status_code == 204
        assert manager.delete(f"{TASKS}{task.pk}/checklists/{checklist['id']}/").status_code == 204


class TestDependencies:
    def test_cycle_detection(self, world):
        a, b, c = (f.make_task(world.project, world.manager, title=t) for t in "ABC")
        client = f.client_for(world.manager)

        def dep(task, blocker):
            return client.post(f"{TASKS}{task.pk}/dependencies/", {"blocked_by_id": str(blocker.pk)}, format="json")

        assert dep(a, b).status_code == 201
        assert dep(b, c).status_code == 201
        cycle = dep(c, a)
        assert cycle.status_code == 409 and cycle.json()["error"]["code"] == "dependency_cycle"
        assert dep(a, a).status_code == 400
        assert dep(a, b).status_code == 409  # duplicate
        listed = client.get(f"{TASKS}{a.pk}/dependencies/").json()
        assert listed[0]["blocked_by"]["key"] == b.key
        assert client.get(f"{TASKS}{b.pk}/").json()["dependents"][0]["key"] == a.key
        dep_id = TaskDependency.objects.get(task=a).pk
        assert client.delete(f"{TASKS}{a.pk}/dependencies/{dep_id}/").status_code == 204
        assert dep(c, a).status_code == 201  # no cycle any more

    def test_cannot_depend_on_invisible_task(self, world, task):
        foreign = f.make_task(world.other_project, world.admin)
        response = f.client_for(world.manager).post(
            f"{TASKS}{task.pk}/dependencies/", {"blocked_by_id": str(foreign.pk)}, format="json"
        )
        assert response.status_code == 400


class TestComments:
    def test_comment_with_mentions(self, world, task):
        f.client_for(world.manager).post(
            f"{TASKS}{task.pk}/assignees/", {"user_ids": [str(world.member2.pk)]}, format="json"
        )
        body = f"Please review @[Mia](user:{world.member2.pk}) thanks"
        response = f.client_for(world.member).post(f"{TASKS}{task.pk}/comments/", {"body": body}, format="json")
        assert response.status_code == 201 and response.json()["mentions"] == [str(world.member2.pk)]
        assert Notification.objects.filter(recipient=world.member2, event_type="task.mentioned").exists()
        assert Notification.objects.filter(recipient=world.manager, event_type="task.commented").exists()

    def test_cannot_mention_someone_who_cannot_see_the_task(self, world, task):
        body = f"hey @[Otto](user:{world.outsider.pk})"
        response = f.client_for(world.member).post(f"{TASKS}{task.pk}/comments/", {"body": body}, format="json")
        assert response.status_code == 400
        forged = f"hey @[X](user:{f.make_user(None).pk})"
        assert (
            f.client_for(world.member).post(f"{TASKS}{task.pk}/comments/", {"body": forged}, format="json").status_code
            == 400
        )

    def test_edit_window_and_delete(self, world, task):
        member, manager = f.client_for(world.member), f.client_for(world.manager)
        comment = member.post(f"{TASKS}{task.pk}/comments/", {"body": "first"}, format="json").json()
        url = f"{TASKS}{task.pk}/comments/{comment['id']}/"
        assert member.patch(url, {"body": "edited"}, format="json").json()["edited_at"] is not None
        assert manager.patch(url, {"body": "hijack"}, format="json").status_code == 403
        from apps.tasks.models import TaskComment

        TaskComment.objects.filter(pk=comment["id"]).update(created_at=timezone_now() - timedelta(minutes=16))
        assert member.patch(url, {"body": "late"}, format="json").status_code == 409
        assert f.client_for(world.member2).delete(url).status_code == 404  # cannot see task
        assert manager.delete(url).status_code == 204  # task manager moderates
        listed = member.get(f"{TASKS}{task.pk}/comments/").json()["results"]
        assert listed[0]["is_deleted"] is True and listed[0]["body"] == ""


class TestAttachments:
    def upload(self, client, task, name, content):
        return client.post(
            f"{TASKS}{task.pk}/attachments/", {"file": SimpleUploadedFile(name, content)}, format="multipart"
        )

    def test_upload_download_delete(self, world, task, settings, tmp_path):
        settings.STORAGES = {
            **settings.STORAGES,
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tmp_path}},
        }
        member = f.client_for(world.member)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        created = self.upload(member, task, "screen shot.png", png)
        assert created.status_code == 201, created.content
        body = created.json()
        assert body["content_type"] == "image/png" and body["size_bytes"] == len(png)
        stored = TaskAttachment.objects.get(pk=body["id"])
        assert stored.storage_key.startswith(f"companies/{task.company_id}/tasks/{task.pk}/")
        assert Company.objects.get(pk=task.company_id).storage_used_bytes == len(png)
        download = member.get(f"{TASKS}{task.pk}/attachments/{body['id']}/download/")
        assert download.status_code == 200 and b"".join(download.streaming_content) == png
        assert download["Content-Disposition"].startswith("attachment")
        assert download["X-Content-Type-Options"] == "nosniff"
        assert (
            f.client_for(world.member2).get(f"{TASKS}{task.pk}/attachments/{body['id']}/download/").status_code == 404
        )
        assert member.delete(f"{TASKS}{task.pk}/attachments/{body['id']}/").status_code == 204
        assert Company.objects.get(pk=task.company_id).storage_used_bytes == 0

    @pytest.mark.parametrize(
        ("name", "content"),
        [
            ("evil.html", b"<html><script>alert(1)</script></html>"),
            ("image.svg", b"<svg onload=alert(1)>"),
            ("fake.png", b"<html>not an image</html>"),
            ("notes.txt", b"<!DOCTYPE html><html></html>"),
            ("run.exe", b"MZ\x90\x00"),
            ("empty.txt", b""),
        ],
    )
    def test_rejected_files(self, world, task, name, content):
        assert self.upload(f.client_for(world.member), task, name, content).status_code == 400

    def test_size_and_quota_limits(self, world, task, settings, company_a):
        settings.ATTACHMENT_MAX_MB = 0
        too_big = self.upload(f.client_for(world.member), task, "a.txt", b"hello")
        assert too_big.status_code == 413 and too_big.json()["error"]["code"] == "file_too_large"
        settings.ATTACHMENT_MAX_MB = 25
        Company.objects.filter(pk=company_a.pk).update(max_storage_mb_override=0)
        quota = self.upload(f.client_for(world.member), task, "a.txt", b"hello")
        assert quota.status_code == 413 and quota.json()["error"]["code"] == "storage_limit_exceeded"

    def test_others_cannot_delete_my_file(self, world, task, settings, tmp_path):
        settings.STORAGES = {
            **settings.STORAGES,
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tmp_path}},
        }
        f.client_for(world.manager).post(
            f"{TASKS}{task.pk}/assignees/", {"user_ids": [str(world.member2.pk)]}, format="json"
        )
        file_id = self.upload(f.client_for(world.member), task, "a.csv", b"a,b\n1,2\n").json()["id"]
        assert f.client_for(world.member2).delete(f"{TASKS}{task.pk}/attachments/{file_id}/").status_code == 403
        assert f.client_for(world.manager).delete(f"{TASKS}{task.pk}/attachments/{file_id}/").status_code == 204


class TestEscalationAndActivity:
    def test_lead_escalates_blocked_task(self, world, task):
        member, lead = f.client_for(world.member), f.client_for(world.lead)
        assert lead.post(f"{TASKS}{task.pk}/escalate/", {}, format="json").status_code == 409  # not blocked
        member.post(f"{TASKS}{task.pk}/transition/", {"to_status": "BLOCKED", "comment": "No access"}, format="json")
        sent = lead.post(f"{TASKS}{task.pk}/escalate/", {"note": "Urgent"}, format="json")
        assert sent.status_code == 200 and sent.json()["count"] >= 1
        assert Notification.objects.filter(recipient=world.manager, event_type="task.escalated").exists()
        assert lead.post(f"{TASKS}{task.pk}/escalate/", {}, format="json").status_code == 429
        assert member.post(f"{TASKS}{task.pk}/escalate/", {}, format="json").status_code == 403

    def test_activity_timeline(self, world, task):
        verbs = [a["verb"] for a in f.client_for(world.member).get(f"{TASKS}{task.pk}/activity/").json()["results"]]
        assert verbs[-1] == "created" and "assigned" in verbs


class TestWorkload:
    def test_capacity_accounts_for_leave_and_holidays(self, world, company_a):
        from apps.org.models import Holiday, LeaveDay

        monday = date(2026, 11, 30)
        f.make_task(
            world.project,
            world.manager,
            assignees=[world.member],
            estimated_minutes=600,
            due_date=monday + timedelta(days=2),
        )
        Holiday.objects.create(company=company_a, date=monday + timedelta(days=1), name="Holiday")
        LeaveDay.objects.create(company=company_a, user=world.member, date=monday + timedelta(days=2), half_day=True)
        rows = (
            f.client_for(world.manager).get(f"{TASKS}workload/?start={monday}&end={monday + timedelta(days=6)}").json()
        )
        mine = next(r for r in rows if r["user"]["id"] == str(world.member.pk))
        # 5 working days - 1 holiday - 0.5 leave = 3.5 days of 480 minutes
        assert mine["capacity_minutes"] == 1680 and mine["estimated_minutes"] == 600
        assert mine["due_in_period"] == 1 and mine["load_percent"] == 36
        assert str(world.outsider.pk) not in {r["user"]["id"] for r in rows}

    def test_member_has_no_workload_view(self, world):
        assert f.client_for(world.member).get(f"{TASKS}workload/").status_code == 403


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_task_numbers_are_unique(company_a):
    """Parallel creates in one project never reuse a task number (row lock on the project)."""
    from apps.common import tenancy
    from apps.tasks.services.tasks import create_task

    with tenancy.platform_context():
        manager = f.make_user(company_a, "COMPANY_ADMIN")
        team = f.make_team(company_a, "T")
        project = f.make_project(team, key="RACE", owner=manager)
    errors = []

    def worker(n):
        try:
            with tenancy.tenant_context(company_a.pk):
                create_task(actor=manager, data={"project": project, "title": f"t{n}"})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with tenancy.platform_context():
        numbers = sorted(Task.objects.filter(project=project).values_list("number", flat=True))
    assert numbers == [1, 2, 3, 4, 5, 6]
