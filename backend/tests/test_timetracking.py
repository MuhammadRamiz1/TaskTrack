"""Timer rules, manual entries, timesheets and their approval (separate from task review)."""

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone
from freezegun import freeze_time

from apps.notifications.models import Notification
from apps.tasks.models import Status, Task
from apps.timetracking.models import TimeEntry, Timesheet, TimesheetApproval
from tests import factories as f

TIME = "/api/v1/time/"


@pytest.fixture
def task(world):
    return f.make_task(world.project, world.manager, assignees=[world.member], title="Timer task")


def start(client, task):
    return client.post(f"{TIME}timer/start/", {"task_id": str(task.pk)}, format="json")


class TestTimer:
    def test_start_moves_assigned_task_to_in_progress(self, world, task):
        client = f.client_for(world.member)
        response = start(client, task)
        assert response.status_code == 201
        body = response.json()
        assert body["entry"]["task"]["id"] == str(task.pk) and body["entry"]["status"] == "RUNNING"
        task.refresh_from_db()
        assert task.status == Status.IN_PROGRESS

    def test_setting_off_requires_in_progress(self, world, task, company_a):
        company_a.timer_start_moves_to_in_progress = False
        company_a.save()
        response = start(f.client_for(world.member), task)
        assert response.status_code == 409 and response.json()["error"]["code"] == "task_not_in_progress"

    def test_one_running_timer_and_switch(self, world, task):
        other = f.make_task(world.project, world.manager, assignees=[world.member])
        client = f.client_for(world.member)
        start(client, task)
        second = start(client, other)
        assert second.status_code == 409 and second.json()["error"]["code"] == "timer_already_running"
        switched = client.post(f"{TIME}timer/switch/", {"task_id": str(other.pk)}, format="json")
        assert switched.json()["entry"]["task"]["id"] == str(other.pk)
        assert TimeEntry.objects.filter(user=world.member, ended_at__isnull=True).count() == 1

    def test_timer_survives_devices_and_reports_elapsed(self, world, task):
        laptop, phone = f.client_for(world.member), f.client_for(world.member)
        start(laptop, task)
        with freeze_time(timezone.now() + timedelta(minutes=5)):
            body = phone.get(f"{TIME}timer/current/").json()
        assert body["entry"]["task"]["id"] == str(task.pk)
        assert 295 <= body["entry"]["elapsed_seconds"] <= 305

    def test_pause_resume_stop(self, world, task):
        client = f.client_for(world.member)
        start(client, task)
        paused = client.post(f"{TIME}timer/pause/")
        assert paused.json()["status"] == "DRAFT" and paused.json()["ended_at"]
        assert client.get(f"{TIME}timer/current/").json()["entry"] is None
        resumed = client.post(f"{TIME}timer/resume/")
        assert resumed.json()["entry"]["task"]["id"] == str(task.pk)
        stopped = client.post(f"{TIME}timer/stop/", {"note": "done for today"}, format="json")
        assert stopped.json()["note"] == "done for today"
        assert client.post(f"{TIME}timer/stop/", {}, format="json").status_code == 409
        assert TimeEntry.objects.filter(user=world.member).count() == 2

    def test_only_assignees_can_time(self, world, task):
        response = start(f.client_for(world.manager), task)
        assert response.status_code == 403 and response.json()["error"]["code"] == "not_assignee"

    def test_timer_stops_when_task_leaves_in_progress(self, world, task):
        member = f.client_for(world.member)
        start(member, task)
        member.post(f"/api/v1/tasks/{task.pk}/review/submit/", {}, format="json")
        entry = TimeEntry.objects.get(user=world.member)
        assert entry.ended_at is not None
        assert Notification.objects.filter(recipient=world.member, event_type="time.timer_stopped").exists()

    def test_timer_stops_when_unassigned_or_offboarded(self, world, task):
        start(f.client_for(world.member), task)
        f.client_for(world.manager).delete(f"/api/v1/tasks/{task.pk}/assignees/{world.member.pk}/")
        assert not TimeEntry.objects.filter(user=world.member, ended_at__isnull=True).exists()
        other = f.make_task(world.project, world.manager, assignees=[world.member2])
        start(f.client_for(world.member2), other)
        body = (
            f.client_for(world.hr).post(f"/api/v1/hr/employees/{world.member2.pk}/offboard/", {}, format="json").json()
        )
        assert body["timers_stopped"] == 1

    def test_runaway_timers_are_capped(self, world, task):
        from apps.timetracking.tasks import stop_runaway_timers

        start(f.client_for(world.member), task)
        with freeze_time(timezone.now() + timedelta(hours=13)):
            assert stop_runaway_timers() == 1
        entry = TimeEntry.objects.get(user=world.member)
        assert entry.duration_seconds == 12 * 3600


class TestManualEntries:
    def entry(self, client, task, start_at, minutes, note=""):
        return client.post(
            f"{TIME}entries/",
            {
                "task_id": str(task.pk),
                "started_at": start_at.isoformat(),
                "ended_at": (start_at + timedelta(minutes=minutes)).isoformat(),
                "note": note,
            },
            format="json",
        )

    def test_create_validate_and_overlap(self, world, task):
        client = f.client_for(world.member)
        base = timezone.now() - timedelta(hours=5)
        ok = self.entry(client, task, base, 60, "Investigated")
        assert ok.status_code == 201 and ok.json()["duration_seconds"] == 3600 and ok.json()["source"] == "MANUAL"
        overlap = self.entry(client, task, base + timedelta(minutes=30), 60)
        assert overlap.status_code == 409 and overlap.json()["error"]["code"] == "time_overlap"
        assert self.entry(client, task, base + timedelta(hours=1), 30).status_code == 201  # adjacent is fine
        future = self.entry(client, task, timezone.now() + timedelta(hours=1), 30)
        assert future.status_code == 400
        assert self.entry(client, task, base - timedelta(days=2), 25 * 60).status_code == 400
        reversed_range = client.post(
            f"{TIME}entries/",
            {
                "task_id": str(task.pk),
                "started_at": base.isoformat(),
                "ended_at": (base - timedelta(minutes=5)).isoformat(),
            },
            format="json",
        )
        assert reversed_range.status_code == 400

    def test_edit_and_delete_own_draft(self, world, task):
        client = f.client_for(world.member)
        base = timezone.now() - timedelta(hours=3)
        entry = self.entry(client, task, base, 30).json()
        url = f"{TIME}entries/{entry['id']}/"
        edited = client.patch(
            url,
            {"version": entry["version"], "note": "fixed", "ended_at": (base + timedelta(minutes=45)).isoformat()},
            format="json",
        )
        assert edited.json()["duration_seconds"] == 45 * 60 and edited.json()["note"] == "fixed"
        stale = client.patch(url, {"version": entry["version"], "note": "x"}, format="json")
        assert stale.status_code == 409
        assert client.delete(url).status_code == 204

    def test_manager_corrects_others_member_cannot(self, world, task):
        entry = self.entry(f.client_for(world.member), task, timezone.now() - timedelta(hours=2), 30).json()
        url = f"{TIME}entries/{entry['id']}/"
        assert f.client_for(world.member2).patch(url, {"version": 1, "note": "x"}, format="json").status_code == 404
        fixed = f.client_for(world.manager).patch(
            url, {"version": entry["version"], "note": "corrected by manager"}, format="json"
        )
        assert fixed.status_code == 200

    def test_visibility_and_task_log(self, world, task):
        self.entry(f.client_for(world.member), task, timezone.now() - timedelta(hours=2), 30)
        assert f.client_for(world.member).get(f"{TIME}entries/").json()["count"] == 1
        assert f.client_for(world.member2).get(f"{TIME}entries/").json()["count"] == 0
        assert f.client_for(world.manager).get(f"{TIME}entries/?task={task.pk}").json()["count"] == 1
        assert f.client_for(world.lead).get(f"{TIME}entries/").json()["count"] == 1  # same team
        assert len(f.client_for(world.manager).get(f"/api/v1/tasks/{task.pk}/time-entries/").json()) == 1

    def test_cannot_log_on_completed_task(self, world, task):
        from apps.tasks.workflow import transition_task

        transition_task(actor=world.manager, task_id=task.pk, to_status=Status.CANCELLED, comment="x")
        response = self.entry(f.client_for(world.member), task, timezone.now() - timedelta(hours=2), 30)
        assert response.status_code == 409


class TestTimesheets:
    def log(self, world, task, hours_ago=3, minutes=90):
        client = f.client_for(world.member)
        start_at = timezone.now() - timedelta(hours=hours_ago)
        return client.post(
            f"{TIME}entries/",
            {
                "task_id": str(task.pk),
                "started_at": start_at.isoformat(),
                "ended_at": (start_at + timedelta(minutes=minutes)).isoformat(),
            },
            format="json",
        ).json()

    def test_submit_approve_flow(self, world, task):
        world.member.manager = world.manager
        world.member.save()
        entry = self.log(world, task)
        member = f.client_for(world.member)
        sheet = member.get(f"{TIME}timesheets/current/").json()
        assert sheet["total_seconds"] == 90 * 60 and len(sheet["entries"]) == 1
        submitted = member.post(f"{TIME}timesheets/{sheet['id']}/submit/")
        assert submitted.json()["status"] == "SUBMITTED"
        assert Notification.objects.filter(recipient=world.manager, event_type="timesheet.submitted").exists()
        locked = member.patch(
            f"{TIME}entries/{entry['id']}/", {"version": entry["version"], "note": "x"}, format="json"
        )
        assert locked.status_code == 409 and locked.json()["error"]["code"] == "timesheet_locked"
        assert member.post(f"{TIME}timesheets/{sheet['id']}/approve/", {}, format="json").status_code == 403
        manager = f.client_for(world.manager)
        queue = manager.get(f"{TIME}approvals/queue/").json()["results"]
        assert [q["id"] for q in queue] == [sheet["id"]]
        approved = manager.post(f"{TIME}timesheets/{sheet['id']}/approve/", {"comment": "ok"}, format="json")
        assert approved.json()["status"] == "APPROVED"
        assert TimeEntry.objects.get(pk=entry["id"]).status == "APPROVED"
        assert [a["decision"] for a in manager.get(f"{TIME}timesheets/{sheet['id']}/approvals/").json()] == ["APPROVED"]

    def test_reject_reopens_entries(self, world, task):
        entry = self.log(world, task)
        member, manager = f.client_for(world.member), f.client_for(world.manager)
        sheet_id = member.get(f"{TIME}timesheets/current/").json()["id"]
        member.post(f"{TIME}timesheets/{sheet_id}/submit/")
        assert manager.post(f"{TIME}timesheets/{sheet_id}/reject/", {}, format="json").status_code == 400
        rejected = manager.post(f"{TIME}timesheets/{sheet_id}/reject/", {"comment": "Missing Friday"}, format="json")
        assert rejected.json()["status"] == "REJECTED"
        fixed = member.patch(
            f"{TIME}entries/{entry['id']}/", {"version": entry["version"], "note": "fixed"}, format="json"
        )
        assert fixed.status_code == 200
        assert member.post(f"{TIME}timesheets/{sheet_id}/submit/").json()["status"] == "SUBMITTED"
        assert TimesheetApproval.objects.filter(timesheet_id=sheet_id).count() == 1

    def test_cannot_submit_with_running_timer_or_empty(self, world, task):
        member = f.client_for(world.member)
        sheet_id = member.get(f"{TIME}timesheets/current/").json()["id"]
        assert member.post(f"{TIME}timesheets/{sheet_id}/submit/").json()["error"]["code"] == "timesheet_empty"
        start(member, task)
        assert member.post(f"{TIME}timesheets/{sheet_id}/submit/").json()["error"]["code"] == "timer_running"

    def test_timer_blocked_in_submitted_week(self, world, task):
        self.log(world, task)
        member = f.client_for(world.member)
        sheet_id = member.get(f"{TIME}timesheets/current/").json()["id"]
        member.post(f"{TIME}timesheets/{sheet_id}/submit/")
        response = start(member, task)
        assert response.status_code == 409 and response.json()["error"]["code"] == "timesheet_locked"

    def test_lead_cannot_approve_by_default(self, world, task):
        self.log(world, task)
        member = f.client_for(world.member)
        sheet_id = member.get(f"{TIME}timesheets/current/").json()["id"]
        member.post(f"{TIME}timesheets/{sheet_id}/submit/")
        assert (
            f.client_for(world.lead).post(f"{TIME}timesheets/{sheet_id}/approve/", {}, format="json").status_code == 403
        )

    def test_timesheet_review_is_separate_from_task_review(self):
        import ast
        import pathlib

        source = pathlib.Path("apps/timetracking/services.py").read_text()
        imported = {node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)}
        assert not any(m and m.startswith("apps.reviews") for m in imported)
        assert Timesheet._meta.db_table != "reviews_taskreview"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_timer_starts_allow_exactly_one(company_a):
    """Two devices press Start at the same time: one timer runs, the other gets 409."""
    from apps.common import tenancy
    from apps.common.exceptions import Conflict
    from apps.timetracking.services import start_timer

    with tenancy.platform_context():
        manager = f.make_user(company_a, "COMPANY_ADMIN")
        member = f.make_user(company_a)
        team = f.make_team(company_a, "T", members=[member])
        project = f.make_project(team, key="RACE", owner=manager, members=[member])
    with tenancy.tenant_context(company_a.pk):
        tasks = [f.make_task(project, manager, assignees=[member]) for _ in range(4)]
    results, barrier = [], threading.Barrier(4)

    def worker(task):
        try:
            with tenancy.tenant_context(company_a.pk):
                barrier.wait()
                start_timer(actor=member, task_id=task.pk)
            results.append("ok")
        except Conflict as exc:
            results.append(exc.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(t,)) for t in tasks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "timer_already_running", "timer_already_running", "timer_already_running"]
    with tenancy.platform_context():
        assert TimeEntry.objects.filter(user=member, ended_at__isnull=True).count() == 1
        assert Task.objects.filter(pk__in=[t.pk for t in tasks], status=Status.IN_PROGRESS).count() == 1
