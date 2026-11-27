"""Scheduled (Celery beat) jobs."""

from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from apps.common.tasks import verify_tenant_integrity
from apps.notifications.models import Notification
from apps.tasks.models import Status, Task, TaskActivity
from apps.tasks.tasks import notify_long_blocked, purge_orphan_files, send_due_reminders
from apps.tasks.workflow import transition_task
from tests import factories as f


def test_every_beat_job_is_a_registered_task():
    from config.celery import app

    app.loader.import_default_modules()
    for entry in settings.CELERY_BEAT_SCHEDULE.values():
        assert entry["task"] in app.tasks, entry["task"]


def test_due_and_overdue_reminders_are_sent_once_per_day(world):
    today = date.today()
    f.make_task(world.project, world.manager, assignees=[world.member], due_date=today + timedelta(days=1))
    f.make_task(world.project, world.manager, assignees=[world.member], due_date=today - timedelta(days=3))
    f.make_task(world.project, world.manager, assignees=[world.member], due_date=today + timedelta(days=9))
    assert send_due_reminders() == 2
    assert send_due_reminders() == 0
    events = set(Notification.objects.filter(recipient=world.member).values_list("event_type", flat=True))
    assert {"task.due_soon", "task.overdue"} <= events


def test_long_blocked_alert(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    transition_task(actor=world.member, task_id=task.pk, to_status=Status.BLOCKED, comment="Waiting on vendor")
    assert notify_long_blocked() == 0
    TaskActivity.objects.filter(task=task, verb="status_changed").update(
        created_at=timezone.now() - timedelta(hours=50)
    )
    assert notify_long_blocked() >= 1
    assert Notification.objects.filter(recipient=world.manager, event_type="task.long_blocked").exists()
    assert notify_long_blocked() == 0


def test_orphan_files_are_removed(world, settings, tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.tasks.services import attachments

    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": tmp_path}},
    }
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    kept = attachments.upload(
        actor=world.member, task_id=task.pk, uploaded_file=SimpleUploadedFile("a.txt", b"keep me")
    )
    orphan = tmp_path / "companies" / str(task.company_id) / "tasks" / str(task.pk) / "ghost" / "b.txt"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("orphan")
    assert purge_orphan_files() == 0  # too new
    with freeze_time(timezone.now() + timedelta(days=2)):
        assert purge_orphan_files() == 1
    assert not orphan.exists() and (tmp_path / kept.storage_key).exists()


def test_tenant_integrity_check_finds_violations(world, company_b):
    assert verify_tenant_integrity() == {}
    task = f.make_task(world.project, world.manager)
    Task.objects.filter(pk=task.pk).update(company=company_b)  # simulate corruption (platform context)
    assert verify_tenant_integrity() == {"tasks.Task.project__company_id": 1}
