"""Assign, unassign, reassign, bulk assign and acknowledge."""

import django.dispatch
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record
from apps.common.exceptions import Conflict, InvalidInput
from apps.notifications.services import notify
from apps.org.models import ProjectMember, TeamMember
from apps.rbac import policy
from apps.rbac.catalogue import Scope

from ..models import Status, Task, TaskAssignee, Trigger
from ..workflow import transition_task
from . import activity
from .tasks import ensure_editable, get_task

#: Sent when someone stops being an assignee (time tracking stops their timer).
assignee_removed = django.dispatch.Signal()


def _has_company_scope(actor, code: str) -> bool:
    return Scope.COMPANY.value in policy.permissions_for(actor).get(code, [])


def _resolve_assignees(actor, task: Task, user_ids) -> list[User]:
    """Assignees must be active employees in the project, or in its team (then they are
    added to the project). Company-wide assigners may assign any active employee."""
    ids = set(user_ids)
    users = list(User.objects.filter(pk__in=ids, company_id=task.company_id, status=User.Status.ACTIVE))
    if len(users) != len(ids):
        raise InvalidInput(details={"user_ids": ["One or more employees do not exist or are not active."]})
    project_members = set(ProjectMember.objects.filter(project=task.project).values_list("user_id", flat=True))
    team_members = set(TeamMember.objects.filter(team_id=task.project.team_id).values_list("user_id", flat=True))
    company_wide = _has_company_scope(actor, "task.assign")
    outside = [u.full_name for u in users if u.pk not in project_members | team_members and not company_wide]
    if outside:
        raise InvalidInput(details={"user_ids": [f"Not in this project or its team: {', '.join(outside)}."]})
    for user in users:
        if user.pk not in project_members:
            ProjectMember.objects.create(company_id=task.company_id, project=task.project, user=user)
    return users


def _refresh_reassignment_flag(task: Task) -> None:
    flagged = task.assignees.exclude(user__status=User.Status.ACTIVE).exists()
    if flagged != task.needs_reassignment:
        Task.objects.filter(pk=task.pk).update(needs_reassignment=flagged)
        task.needs_reassignment = flagged


def assign(*, actor, task_id, user_ids, notify_users: bool = True) -> list[TaskAssignee]:
    with transaction.atomic():
        task = get_task(actor, task_id, for_update=True)
        policy.require(actor, "task.assign", task)
        ensure_editable(task)
        users = _resolve_assignees(actor, task, user_ids)
        existing = set(task.assignees.values_list("user_id", flat=True))
        created = [
            TaskAssignee.objects.create(
                company_id=task.company_id, task=task, user=u, task_status=task.status, assigned_by=actor
            )
            for u in users
            if u.pk not in existing
        ]
        if not created:
            return []
        if task.status == Status.BACKLOG:
            transition_task(actor=actor, task_id=task.pk, to_status=Status.ASSIGNED, trigger=Trigger.ASSIGN)
            task.refresh_from_db()
        _refresh_reassignment_flag(task)
        new_ids = [a.user_id for a in created]
        activity.log(task, actor, "assigned", {"user_ids": new_ids})
        record(actor=actor, action="task.assigned", entity=task, new_value={"user_ids": new_ids})
        if notify_users:
            notify(
                recipients=[a.user for a in created],
                actor=actor,
                event_type="task.assigned",
                title=f"{task.key} was assigned to you",
                body=task.title,
                entity=task,
            )
        return created


def unassign(*, actor, task_id, user_id, revert_to_backlog: bool = True) -> None:
    with transaction.atomic():
        task = get_task(actor, task_id, for_update=True)
        policy.require(actor, "task.assign", task)
        ensure_editable(task)
        row = task.assignees.filter(user_id=user_id).select_related("user").first()
        if row is None:
            raise InvalidInput(details={"user_id": ["Not assigned to this task."]})
        row.delete()
        assignee_removed.send(sender=Task, task=task, user=row.user, actor=actor)
        if revert_to_backlog and task.status == Status.ASSIGNED and not task.assignees.exists():
            transition_task(actor=actor, task_id=task.pk, to_status=Status.BACKLOG, trigger=Trigger.SYSTEM)
            task.refresh_from_db()
        _refresh_reassignment_flag(task)
        activity.log(task, actor, "unassigned", {"user_id": user_id})
        record(actor=actor, action="task.unassigned", entity=task, old_value={"user_id": user_id})


def reassign(*, actor, task_id, from_user_id, to_user_id) -> list[TaskAssignee]:
    if from_user_id == to_user_id:
        raise InvalidInput(details={"to_user_id": ["Choose a different employee."]})
    with transaction.atomic():
        unassign(actor=actor, task_id=task_id, user_id=from_user_id, revert_to_backlog=False)
        created = assign(actor=actor, task_id=task_id, user_ids=[to_user_id])
        task = Task.objects.get(pk=task_id)
        record(
            actor=actor,
            action="task.reassigned",
            entity=task,
            old_value={"user_id": from_user_id},
            new_value={"user_id": to_user_id},
        )
        return created


def bulk_assign(*, actor, task_ids, user_ids, mode: str = "add") -> int:
    """All-or-nothing: any failure rolls back every task."""
    with transaction.atomic():
        changed = 0
        for task_id in dict.fromkeys(task_ids):
            if mode == "replace":
                task = get_task(actor, task_id)
                for user_id in task.assignees.exclude(user_id__in=user_ids).values_list("user_id", flat=True):
                    unassign(actor=actor, task_id=task_id, user_id=user_id, revert_to_backlog=False)
            changed += bool(assign(actor=actor, task_id=task_id, user_ids=user_ids))
        record(
            actor=actor,
            action="task.bulk_assigned",
            entity_type="task",
            new_value={"task_ids": list(map(str, task_ids)), "user_ids": list(map(str, user_ids)), "mode": mode},
        )
        return changed


def acknowledge(*, actor, task_id) -> TaskAssignee:
    with transaction.atomic():
        task = get_task(actor, task_id)
        policy.require(actor, "task.acknowledge", task)
        row = task.assignees.select_for_update().filter(user=actor).first()
        if row is None:
            raise InvalidInput(details={"task": ["You are not assigned to this task."]})
        if row.acknowledged_at:
            raise Conflict("You already acknowledged this assignment.", code="already_acknowledged")
        row.acknowledged_at = timezone.now()
        row.save(update_fields=["acknowledged_at", "updated_at"])
        activity.log(task, actor, "acknowledged")
        record(actor=actor, action="task.acknowledged", entity=task)
        return row
