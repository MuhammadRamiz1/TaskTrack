"""Scheduled jobs for tasks: due/overdue reminders, long-blocked alerts, orphan file cleanup."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import structlog
from celery import shared_task
from django.core.files.storage import default_storage
from django.utils import timezone

from apps.common import tenancy

logger = structlog.get_logger(__name__)
ORPHAN_AGE = timedelta(days=1)


def _already_sent_today(user, event_type: str, task) -> bool:
    from apps.notifications.models import Notification

    return Notification.objects.filter(
        recipient=user,
        event_type=event_type,
        entity_id=task.pk,
        created_at__gte=timezone.now() - timedelta(hours=20),
    ).exists()


def _company_today(company) -> date:
    return timezone.now().astimezone(ZoneInfo(company.timezone)).date()


@shared_task(name="tasks.send_due_reminders")
def send_due_reminders() -> int:
    """Hourly: remind assignees once a day about tasks due today/tomorrow and overdue tasks."""
    from apps.companies.models import Company
    from apps.notifications.services import notify

    from .models import OPEN_STATUSES, Task

    sent = 0
    with tenancy.platform_context():
        company_ids = list(Company.objects.filter(status=Company.Status.ACTIVE).values_list("pk", flat=True))
    for company_id in company_ids:
        with tenancy.tenant_context(company_id):
            company = Company.objects.get(pk=company_id)
            today = _company_today(company)
            tasks = Task.objects.filter(
                status__in=OPEN_STATUSES, due_date__isnull=False, due_date__lte=today + timedelta(days=1)
            ).select_related("project")
            for task in tasks.prefetch_related("assignees__user"):
                event = "task.overdue" if task.due_date < today else "task.due_soon"
                for assignee in task.assignees.all():
                    if _already_sent_today(assignee.user, event, task):
                        continue
                    when = (
                        "is overdue"
                        if event == "task.overdue"
                        else ("is due today" if task.due_date == today else "is due tomorrow")
                    )
                    sent += notify(
                        recipients=[assignee.user],
                        actor=None,
                        event_type=event,
                        title=f"{task.key} {when}",
                        body=task.title,
                        entity=task,
                    )
    return sent


@shared_task(name="tasks.notify_long_blocked")
def notify_long_blocked(hours: int = 48) -> int:
    """Daily: tell managers about tasks blocked for longer than ``hours``."""
    from apps.companies.models import Company
    from apps.notifications.services import notify

    from .models import Status, Task, TaskActivity
    from .services.details import escalation_recipients

    cutoff = timezone.now() - timedelta(hours=hours)
    sent = 0
    with tenancy.platform_context():
        company_ids = list(Company.objects.filter(status=Company.Status.ACTIVE).values_list("pk", flat=True))
    for company_id in company_ids:
        with tenancy.tenant_context(company_id):
            for task in Task.objects.filter(status=Status.BLOCKED).select_related("project__owner", "company"):
                blocked_at = (
                    TaskActivity.objects.filter(task=task, verb="status_changed", data__to=Status.BLOCKED)
                    .order_by("-created_at")
                    .values_list("created_at", flat=True)
                    .first()
                )
                if blocked_at is None or blocked_at > cutoff:
                    continue
                recipients = [
                    u for u in escalation_recipients(task) if not _already_sent_today(u, "task.long_blocked", task)
                ]
                sent += notify(
                    recipients=recipients,
                    actor=None,
                    event_type="task.long_blocked",
                    title=f"{task.key} has been blocked for over {hours} hours",
                    body=f"Reason: {task.blocked_reason}",
                    entity=task,
                )
    return sent


def _walk(prefix: str):
    dirs, files = default_storage.listdir(prefix)
    for name in files:
        yield f"{prefix}/{name}"
    for d in dirs:
        yield from _walk(f"{prefix}/{d}")


@shared_task(name="tasks.purge_orphan_files")
def purge_orphan_files() -> int:
    """Daily: delete stored attachment files with no ACTIVE row (e.g. a request that
    saved the file and then rolled back), older than one day."""
    from .models import TaskAttachment

    removed = 0
    with tenancy.platform_context():
        if not default_storage.exists("companies"):
            return 0
        active = set(
            TaskAttachment.objects.filter(status=TaskAttachment.State.ACTIVE).values_list("storage_key", flat=True)
        )
        for key in _walk("companies"):
            if "/tasks/" not in key or key in active:
                continue
            try:
                modified = default_storage.get_modified_time(key)
            except NotImplementedError, OSError:
                continue
            if timezone.now() - modified > ORPHAN_AGE:
                default_storage.delete(key)
                removed += 1
    logger.info("tasks.orphan_files_purged", removed=removed)
    return removed
