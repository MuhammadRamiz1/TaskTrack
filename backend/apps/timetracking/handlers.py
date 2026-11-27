"""Stop timers when work on a task can no longer continue."""

from django.dispatch import receiver

from apps.accounts.services.employees import employee_deactivated
from apps.tasks.models import Status
from apps.tasks.services.assignment import assignee_removed
from apps.tasks.workflow import task_status_changed

from .models import TimeEntry
from .services import stop_timers_on_task


@receiver(task_status_changed, dispatch_uid="timetracking.stop_on_status_change")
def stop_when_leaving_in_progress(sender, task, actor, old_status, **kwargs):
    if old_status == Status.IN_PROGRESS and task.status != Status.IN_PROGRESS:
        reason = "submitted_for_review" if task.status == Status.IN_REVIEW else f"task_{task.status.lower()}"
        stop_timers_on_task(task, reason=reason)


@receiver(assignee_removed, dispatch_uid="timetracking.stop_on_unassign")
def stop_when_unassigned(sender, task, user, **kwargs):
    stop_timers_on_task(task, user=user, reason="unassigned")


@receiver(employee_deactivated, dispatch_uid="timetracking.stop_on_deactivation")
def stop_when_deactivated(sender, user, **kwargs):
    stopped = 0
    for entry in TimeEntry.objects.filter(user=user, ended_at__isnull=True).select_related("task"):
        stopped += stop_timers_on_task(entry.task, user=user, reason="account_deactivated")
    return {"timers_stopped": stopped}
