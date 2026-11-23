"""Receivers for signals sent by other modules."""

from django.dispatch import receiver

from apps.accounts.models import User
from apps.accounts.services.employees import employee_deactivated
from apps.companies.services import company_provisioned
from apps.notifications.services import notify

from .models import READ_ONLY_STATUSES, Task
from .workflow_defaults import seed_rules


@receiver(company_provisioned, dispatch_uid="tasks.seed_workflow_rules")
def seed_workflow_rules(sender, company, **kwargs):
    seed_rules(company.pk)


@receiver(employee_deactivated, dispatch_uid="tasks.flag_open_work")
def flag_open_work(sender, user: User, actor, offboard: bool, **kwargs):
    """On offboarding, flag the employee's open tasks for reassignment and tell owners."""
    if not offboard:
        return {}
    tasks = list(
        Task.objects.filter(assignees__user=user)
        .exclude(status__in=READ_ONLY_STATUSES)
        .select_related("project__owner")
        .distinct()
    )
    Task.objects.filter(pk__in=[t.pk for t in tasks]).update(needs_reassignment=True)
    for task in tasks:
        owner = task.project.owner
        notify(
            recipients=[owner] if owner else [],
            actor=actor,
            event_type="task.needs_reassignment",
            title=f"{task.key} needs a new assignee",
            body=f"{user.full_name} was offboarded.",
            entity=task,
        )
    return {"tasks_flagged": len(tasks)}
