"""Dashboards, reports, exports (CSV/XLSX/PDF) and scheduled reports."""

import csv
import io
from datetime import date, datetime, time, timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.reports.models import ReportExport, ScheduledReport
from apps.reports.services import next_run
from apps.tasks.models import Status
from apps.tasks.workflow import transition_task
from apps.timetracking.services import create_manual
from tests import factories as f

R = "/api/v1/reports/"
TODAY = date.today()


@pytest.fixture
def activity(world):
    """Two tasks: one completed on time by member, one overdue; 2.5 hours logged."""
    done = f.make_task(
        world.project,
        world.manager,
        assignees=[world.member],
        title="Done",
        due_date=TODAY + timedelta(days=1),
        estimated_minutes=60,
    )
    late = f.make_task(
        world.project,
        world.manager,
        assignees=[world.member2],
        title="Late",
        due_date=TODAY - timedelta(days=2),
        estimated_minutes=120,
    )
    transition_task(actor=world.member, task_id=done.pk, to_status=Status.IN_PROGRESS)
    began = timezone.now() - timedelta(hours=5)
    create_manual(actor=world.member, task_id=done.pk, started_at=began, ended_at=began + timedelta(minutes=150))
    transition_task(actor=world.member, task_id=done.pk, to_status=Status.IN_REVIEW, trigger="SUBMIT")
    transition_task(actor=world.manager, task_id=done.pk, to_status=Status.COMPLETED, trigger="APPROVE")
    return done, late


class TestDashboards:
    def test_manager_dashboard(self, world, activity):
        body = f.client_for(world.manager).get("/api/v1/dashboards/manager/").json()
        totals = body["totals"]
        assert totals["total"] == 2 and totals["completed"] == 1 and totals["assigned"] == 1
        assert totals["overdue"] == 1 and totals["completed_in_period"] == 1
        prod = {p["name"]: p for p in body["productivity"]}
        assert prod[world.member.full_name]["completed"] == 1
        assert prod[world.member.full_name]["on_time_rate"] == 100
        assert prod[world.member.full_name]["logged_hours"] == 2.5
        assert body["project_progress"][0] == {
            "project_id": str(world.project.pk),
            "key": "WEB",
            "name": "Project WEB",
            "total": 2,
            "completed": 1,
            "percent": 50,
        }
        assert body["time_by_employee"][0]["hours"] == 2.5
        assert body["workload"][0]["open_tasks"] == 1

    def test_dashboard_scoped_to_manager(self, world, activity):
        f.make_task(world.other_project, world.admin, title="Ops")
        assert f.client_for(world.manager).get("/api/v1/dashboards/manager/").json()["totals"]["total"] == 2
        assert f.client_for(world.admin).get("/api/v1/dashboards/manager/").json()["totals"]["total"] == 3
        assert f.client_for(world.member).get("/api/v1/dashboards/manager/").status_code == 403

    def test_member_dashboard(self, world, activity):
        body = f.client_for(world.member2).get("/api/v1/dashboards/member/").json()
        assert body["open"] == 1 and body["overdue"] == 1 and body["hours_today"] == 0
        mine = f.client_for(world.member).get("/api/v1/dashboards/member/").json()
        assert mine["by_status"]["COMPLETED"] == 1 and mine["hours_this_week"] in (0, 2.5)


class TestReports:
    def test_time_report_grouping(self, world, activity):
        client = f.client_for(world.manager)
        by_member = client.get(f"{R}time/?group_by=member&period=monthly").json()
        assert len(by_member) == 1 and by_member[0]["hours"] == 2.5 and by_member[0]["entries"] == 1
        by_project = client.get(f"{R}time/?group_by=project&period=daily").json()
        assert by_project[0]["group"] == "WEB Project WEB"
        assert client.get(f"{R}time/?group_by=team").json()[0]["group"] == "Web"

    def test_time_by_task_report(self, world, activity):
        done, _ = activity
        rows = f.client_for(world.manager).get(f"{R}time/tasks/").json()
        assert len(rows) == 1
        row = rows[0]
        assert row["member"] == world.member.full_name
        assert row["task_id"] == str(done.pk) and row["task_key"] == f"WEB-{done.number}"
        assert row["task_title"] == "Done" and row["project_key"] == "WEB"
        assert row["hours"] == 2.5 and row["entries"] == 1 and row["work_date"]

    def test_time_by_task_report_is_scoped(self, world, activity):
        assert f.client_for(world.member2).get(f"{R}time/tasks/").json() == []
        assert len(f.client_for(world.member).get(f"{R}time/tasks/").json()) == 1
        assert f.client_for(world.hr).get(f"{R}time/tasks/").status_code == 403

    def test_task_report(self, world, activity):
        rows = f.client_for(world.manager).get(f"{R}tasks/?group_by=project&period=monthly").json()
        assert sum(r["created"] for r in rows) == 2
        assert sum(r["completed"] for r in rows) == 1 and sum(r["completed_on_time"] for r in rows) == 1

    def test_member_report_is_limited_to_own_data(self, world, activity):
        rows = f.client_for(world.member2).get(f"{R}time/").json()
        assert rows == []
        assert f.client_for(world.hr).get(f"{R}time/").status_code == 403

    def test_range_validation(self, world):
        bad = f.client_for(world.manager).get(f"{R}time/?date_from=2026-01-01&date_to=2025-01-01")
        assert bad.status_code == 400


class TestExports:
    def export(self, client, fmt, mailbox, report_type="time"):
        with mailbox():
            response = client.post(
                f"{R}exports/", {"report_type": report_type, "format": fmt, "group_by": "member"}, format="json"
            )
        assert response.status_code == 202, response.content
        return response.json()["id"]

    def download(self, client, export_id):
        detail = client.get(f"{R}exports/{export_id}/").json()
        assert detail["status"] == "READY", detail
        response = client.get(f"{R}exports/{export_id}/download/")
        assert response.status_code == 200
        return b"".join(response.streaming_content)

    @pytest.fixture(autouse=True)
    def _storage(self, settings, tmp_path):
        settings.STORAGES = {
            **settings.STORAGES,
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tmp_path}},
        }

    def test_csv(self, world, activity, mailbox):
        client = f.client_for(world.manager)
        content = self.download(client, self.export(client, "csv", mailbox))
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        assert rows[0] == ["Group", "Period start", "Hours", "Entries"]
        assert rows[1][0] == world.member.full_name and rows[1][2] == "2.5"

    def test_xlsx(self, world, activity, mailbox):
        from openpyxl import load_workbook

        client = f.client_for(world.manager)
        content = self.download(client, self.export(client, "xlsx", mailbox, "tasks"))
        sheet = load_workbook(io.BytesIO(content)).active
        assert sheet["A1"].value == "Tasks report"
        assert [c.value for c in sheet[4]] == ["Group", "Period start", "Created", "Completed", "Completed on time"]

    def test_pdf_and_plan_gate(self, world, activity, mailbox, company_a):
        client = f.client_for(world.manager)
        content = self.download(client, self.export(client, "pdf", mailbox))
        assert content.startswith(b"%PDF-")
        plan = company_a.plan
        plan.features = {"reports_pdf": False, "scheduled_reports": True}
        plan.save()
        blocked = client.post(f"{R}exports/", {"report_type": "time", "format": "pdf"}, format="json")
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "plan_feature_unavailable"

    def test_formula_injection_is_neutralised(self, world, mailbox):
        evil = f.make_user(world.team.company, first_name='=HYPERLINK("http://x")', last_name="")
        world.project.memberships.create(company=world.team.company, user=evil)
        task = f.make_task(world.project, world.manager, assignees=[evil])
        transition_task(actor=evil, task_id=task.pk, to_status=Status.IN_PROGRESS)
        began = timezone.now() - timedelta(hours=3)
        create_manual(actor=evil, task_id=task.pk, started_at=began, ended_at=began + timedelta(minutes=30))
        client = f.client_for(world.manager)
        content = self.download(client, self.export(client, "csv", mailbox)).decode("utf-8-sig")
        assert "'=HYPERLINK" in content

    def test_exports_are_private_to_requester(self, world, activity, mailbox):
        client = f.client_for(world.manager)
        export_id = self.export(client, "csv", mailbox)
        assert f.client_for(world.admin).get(f"{R}exports/{export_id}/download/").status_code == 404
        assert [e["id"] for e in client.get(f"{R}exports/").json()["results"]] == [export_id]

    def test_expired_exports_are_purged(self, world, activity, mailbox):
        from apps.reports.tasks import purge_expired_exports

        client = f.client_for(world.manager)
        export_id = self.export(client, "csv", mailbox)
        with freeze_time(timezone.now() + timedelta(days=8)):
            assert purge_expired_exports() == 1
        assert not ReportExport.objects.filter(pk=export_id).exists()


class TestSchedules:
    def make(self, client, **overrides):
        body = {
            "name": "Weekly hours",
            "report_type": "time",
            "format": "csv",
            "frequency": "WEEKLY",
            "send_at": "08:00",
            "weekday": 0,
            **overrides,
        }
        return client.post(f"{R}schedules/", body, format="json")

    def test_next_run_computation(self, world, company_a):
        company_a.timezone = "Asia/Karachi"
        company_a.save()
        s = ScheduledReport(company=company_a, frequency="DAILY", send_at=time(8, 0))
        after = datetime(2026, 11, 23, 4, 0, tzinfo=timezone.UTC)  # 09:00 in Karachi
        assert next_run(s, after) == datetime(2026, 11, 24, 3, 0, tzinfo=timezone.UTC)
        s.frequency, s.weekday = "WEEKLY", 4  # Friday
        assert next_run(s, after).date() == date(2026, 11, 27)
        s.frequency, s.day_of_month = "MONTHLY", 1
        assert next_run(s, after) == datetime(2026, 12, 1, 3, 0, tzinfo=timezone.UTC)

    def test_create_and_run_schedule(self, world, activity, mailbox, settings, tmp_path):
        settings.STORAGES = {
            **settings.STORAGES,
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tmp_path}},
        }
        client = f.client_for(world.manager)
        created = self.make(client, frequency="DAILY", recipient_ids=[str(world.admin.pk)])
        assert created.status_code == 201, created.content
        schedule = ScheduledReport.objects.get(pk=created.json()["id"])
        from apps.reports.tasks import dispatch_scheduled_reports

        with freeze_time(schedule.next_run_at + timedelta(minutes=1)):
            assert dispatch_scheduled_reports() == 1
        mail = mailbox.outbox[-1]
        assert mail.to == [world.admin.email] and mail.attachments[0][0].endswith(".csv")
        schedule.refresh_from_db()
        assert schedule.last_run_at is not None and schedule.next_run_at > schedule.last_run_at

    def test_recipients_need_company_report_access(self, world):
        response = self.make(f.client_for(world.manager), recipient_ids=[str(world.member.pk)])
        assert response.status_code == 400

    def test_owner_losing_permission_pauses_schedule(self, world):
        client = f.client_for(world.manager)
        schedule = ScheduledReport.objects.get(pk=self.make(client).json()["id"])
        from apps.rbac.models import UserRole

        UserRole.objects.filter(user=world.manager).delete()
        from apps.reports.services import run_schedule

        world.manager.refresh_from_db()
        run_schedule(
            ScheduledReport.objects.select_related("owner__company", "company").get(pk=schedule.pk), timezone.now()
        )
        schedule.refresh_from_db()
        assert schedule.is_active is False and "paused" in schedule.last_error

    def test_edit_delete_and_scope(self, world):
        client = f.client_for(world.manager)
        schedule_id = self.make(client).json()["id"]
        patched = client.patch(
            f"{R}schedules/{schedule_id}/", {"frequency": "MONTHLY", "day_of_month": 15}, format="json"
        )
        assert patched.json()["frequency"] == "MONTHLY"
        assert len(f.client_for(world.admin).get(f"{R}schedules/").json()) == 1  # company-wide sees all
        assert f.client_for(world.member).get(f"{R}schedules/").status_code == 403
        assert client.delete(f"{R}schedules/{schedule_id}/").status_code == 204

    def test_plan_gate(self, world, company_a):
        plan = company_a.plan
        plan.features = {"reports_pdf": True, "scheduled_reports": False}
        plan.save()
        assert self.make(f.client_for(world.manager)).status_code == 403
