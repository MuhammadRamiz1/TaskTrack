"""The task state machine. ``transition_task()`` is the only code allowed to change
``Task.status``; any other status write raises ``DirectStatusWrite``."""

import contextvars
from contextlib import contextmanager

import django.dispatch
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.common.exceptions import Conflict, InvalidInput
from apps.rbac import policy

from .models import READ_ONLY_STATUSES, Status, StatusTransitionRule, Task, TaskAssignee, TaskComment, Trigger

#: Sent after a status change commits to the row (inside the transaction). Time tracking
#: stops timers when a task leaves IN_PROGRESS; notifications fan out.
task_status_changed = django.dispatch.Signal()

_writing = contextvars.ContextVar("tasks_workflow_writing", default=False)
DONE_STATUSES = {Status.COMPLETED, Status.CANCELLED}


class DirectStatusWrite(RuntimeError):
    pass


def guard_status_write(task: Task) -> None:
    if _writing.get():
        return
    if task._state.adding:
        if task.status != Status.BACKLOG:
            raise DirectStatusWrite("New tasks start in BACKLOG; use transition_task().")
        return
    if task.status != task._loaded_status:
        raise DirectStatusWrite("Task.status may only change through tasks.workflow.transition_task().")


@contextmanager
def _status_write():
    token = _writing.set(True)
    try:
        yield
    finally:
        _writing.reset(token)


class InvalidTransition(Conflict):
    code = "invalid_transition"


def rules_from(task: Task, trigger: str = Trigger.MANUAL):
    return StatusTransitionRule.objects.filter(
        company_id=task.company_id, from_status=task.status, trigger=trigger, is_active=True
    )


def _actor_allowed(actor, rule: StatusTransitionRule, task: Task) -> bool:
    if rule.trigger == Trigger.SYSTEM:
        return True
    if rule.trigger != Trigger.ASSIGN and not policy.can(actor, "task.transition", task):
        return False  # assignment rights are checked by the assignment service
    return bool(policy.role_keys(actor) & set(rule.allowed_roles))


def allowed_targets(actor, task: Task) -> list[dict]:
    """Manual transitions this actor may make from the task's current status."""
    if task.locked_at and task.status != Status.COMPLETED:
        return []
    return [
        {"to_status": r.to_status, "requires_comment": r.requires_comment}
        for r in rules_from(task)
        if _actor_allowed(actor, r, task)
    ]


def open_blockers(task: Task) -> list[str]:
    from .models import TaskDependency

    deps = TaskDependency.objects.filter(task=task).select_related("blocked_by__project")
    return [d.blocked_by.key for d in deps if d.blocked_by.status not in DONE_STATUSES]


def transition_task(
    *,
    actor,
    task_id,
    to_status: str,
    trigger: str = Trigger.MANUAL,
    comment: str = "",
    expected_version: int | None = None,
) -> Task:
    comment = (comment or "").strip()
    with transaction.atomic():
        task = Task.objects.select_for_update(of=("self",)).select_related("project", "company").get(pk=task_id)
        if actor is not None:
            policy.require(actor, "task.view", task)
        if expected_version is not None and expected_version != task.version:
            raise Conflict(
                "The task was changed by someone else. Reload and try again.",
                code="version_conflict",
                details={"current_version": task.version},
            )
        if task.status == to_status:
            raise InvalidTransition(f"The task is already {to_status}.")

        rule = StatusTransitionRule.objects.filter(
            company_id=task.company_id,
            from_status=task.status,
            to_status=to_status,
            trigger=trigger,
            is_active=True,
        ).first()
        if rule is None:
            raise InvalidTransition(
                f"Cannot move the task from {task.status} to {to_status}.",
                details={"allowed": [t["to_status"] for t in allowed_targets(actor, task)] if actor else []},
            )
        if actor is not None and not _actor_allowed(actor, rule, task):
            raise InvalidTransition(
                "Your role cannot make this status change.",
                code="transition_not_allowed",
                status_code=403,
            )
        if rule.requires_comment and not comment:
            raise InvalidInput(
                "A comment is required for this status change.",
                code="comment_required",
                details={"comment": ["This field is required."]},
            )
        if rule.requires_reviewer and not task.effective_reviewer_id:
            raise InvalidInput("The task needs a reviewer.", code="reviewer_required")
        if to_status == Status.IN_PROGRESS and task.company.enforce_dependencies:
            blockers = open_blockers(task)
            if blockers:
                raise Conflict(
                    "The task is waiting on other tasks.", code="dependency_blocked", details={"blocked_by": blockers}
                )

        old_status = task.status
        now = timezone.now()
        task.status = to_status
        if to_status == Status.BLOCKED:
            task.blocked_reason = comment
        elif old_status == Status.BLOCKED:
            task.blocked_reason = ""
        if to_status == Status.COMPLETED:
            task.completed_at = now
            task.locked_at = now
        if to_status == Status.REOPENED:
            task.completed_at = None
            task.locked_at = None
        task.version += 1
        with _status_write():
            task.save()
        TaskAssignee.objects.filter(task=task).update(task_status=to_status)
        if comment:
            TaskComment.objects.create(
                company_id=task.company_id, task=task, author=actor, body=comment, kind=TaskComment.Kind.SYSTEM
            )
        from .services.activity import log

        log(
            task, actor, "status_changed", {"from": old_status, "to": to_status, "trigger": trigger, "comment": comment}
        )
        record(
            actor=actor,
            action="task.transition",
            entity=task,
            old_value={"status": old_status},
            new_value={"status": to_status, "trigger": trigger, "comment": comment},
        )
        task_status_changed.send(sender=Task, task=task, actor=actor, old_status=old_status, trigger=trigger)
        task._loaded_status = task.status
        return task


def is_read_only(task: Task) -> bool:
    return task.status in READ_ONLY_STATUSES or task.locked_at is not None
