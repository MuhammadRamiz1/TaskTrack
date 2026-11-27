"""Task create / edit / delete / restore and shared lookups."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import diff, record, snapshot
from apps.common.exceptions import Conflict, InvalidInput, NotFound
from apps.org.models import Project
from apps.rbac import policy

from ..models import Priority, Status, Task
from . import activity

EDITABLE_FIELDS = [
    "title",
    "description",
    "instructions",
    "acceptance_criteria",
    "priority",
    "start_date",
    "due_date",
    "estimated_minutes",
    "reviewer",
]
MAX_DEPTH = 3
RESTORE_WINDOW = timedelta(days=30)


def get_task(actor, task_id, *, include_deleted: bool = False, for_update: bool = False) -> Task:
    """A task the actor may view, else 404 (also for other tenants' ids)."""
    manager = Task.with_deleted if include_deleted else Task.objects
    qs = manager.select_related("project", "company", "created_by", "reviewer")
    if for_update:
        qs = qs.select_for_update(of=("self",))
    task = qs.filter(pk=task_id).first()
    if task is None or not policy.can(actor, "task.view", task):
        raise NotFound()
    return task


def ensure_editable(task: Task) -> None:
    if task.is_read_only:
        raise Conflict(
            "This task is completed or cancelled and is read-only. Reopen it to make changes.", code="task_locked"
        )


def ensure_not_in_review(task: Task) -> None:
    """While a task waits for review its content is frozen; comments and files still work."""
    if task.status == Status.IN_REVIEW:
        raise Conflict(
            "The task is waiting for review. Ask the reviewer to request changes first.", code="task_in_review"
        )


def ensure_version(task: Task, expected) -> None:
    if expected is not None and int(expected) != task.version:
        raise Conflict(
            "The task was changed by someone else. Reload and try again.",
            code="version_conflict",
            details={"current_version": task.version},
        )


def _validate_reviewer(actor, reviewer: User | None) -> None:
    if reviewer is not None and (reviewer.company_id != actor.company_id or not reviewer.is_active):
        raise InvalidInput(details={"reviewer_id": ["Unknown or inactive employee."]})


def _validate_dates(start, due) -> None:
    if start and due and due < start:
        raise InvalidInput(details={"due_date": ["Due date must be on or after the start date."]})


def _depth(parent: Task) -> int:
    depth, node = 1, parent
    while node.parent_id:
        depth += 1
        node = Task.objects.only("parent_id").get(pk=node.parent_id)
    return depth


def create_task(*, actor, data: dict) -> Task:
    from .assignment import assign

    project: Project = data["project"]
    policy.require(actor, "task.create", project, view_code="project.view")
    if project.status != Project.Status.ACTIVE:
        raise Conflict("Tasks can only be added to active projects.", code="project_not_active")
    parent: Task | None = data.get("parent")
    if parent is not None:
        if parent.project_id != project.pk:
            raise InvalidInput(details={"parent_id": ["A subtask must be in the same project as its parent."]})
        ensure_editable(parent)
        if _depth(parent) >= MAX_DEPTH:
            raise InvalidInput(details={"parent_id": [f"Subtasks can be nested at most {MAX_DEPTH} levels deep."]})
    if data.get("priority", Priority.MEDIUM) != Priority.MEDIUM:
        policy.require(actor, "task.set_priority", project, view_code="project.view")
    _validate_reviewer(actor, data.get("reviewer"))
    _validate_dates(data.get("start_date"), data.get("due_date"))

    with transaction.atomic():
        locked_project = Project.objects.select_for_update().get(pk=project.pk)
        locked_project.task_seq += 1
        locked_project.save(update_fields=["task_seq", "updated_at"])
        task = Task.objects.create(
            company_id=actor.company_id,
            project=locked_project,
            parent=parent,
            number=locked_project.task_seq,
            created_by=actor,
            **{f: data[f] for f in EDITABLE_FIELDS if f in data},
        )
        activity.log(task, actor, "created", {"title": task.title, "parent_id": parent.pk if parent else None})
        record(
            actor=actor,
            action="task.created",
            entity=task,
            new_value={"key": task.key, **snapshot(task, ["title", "project", "parent", "priority", "due_date"])},
        )
        if data.get("assignee_ids"):
            assign(actor=actor, task_id=task.pk, user_ids=data["assignee_ids"])
            task.refresh_from_db()
    return task


def update_task(*, actor, task_id, data: dict, expected_version) -> Task:
    with transaction.atomic():
        task = get_task(actor, task_id, for_update=True)
        policy.require(actor, "task.update", task)
        ensure_editable(task)
        ensure_not_in_review(task)
        ensure_version(task, expected_version)
        fields = [f for f in EDITABLE_FIELDS if f in data]
        if "priority" in data and data["priority"] != task.priority:
            policy.require(actor, "task.set_priority", task)
        if "reviewer" in data:
            _validate_reviewer(actor, data["reviewer"])
        _validate_dates(data.get("start_date", task.start_date), data.get("due_date", task.due_date))
        before = snapshot(task, fields)
        for field in fields:
            setattr(task, field, data[field])
        old, new = diff(before, snapshot(task, fields))
        if not new:
            return task
        task.version += 1
        task.save()
        activity.log(task, actor, "updated", {"changes": new})
        record(actor=actor, action="task.updated", entity=task, old_value=old, new_value=new)
        return task


def set_priority(*, actor, task_id, priority: str, expected_version) -> Task:
    """Priority-only change, for leads who hold task.set_priority but not task.update."""
    with transaction.atomic():
        task = get_task(actor, task_id, for_update=True)
        policy.require(actor, "task.set_priority", task)
        ensure_editable(task)
        ensure_not_in_review(task)
        ensure_version(task, expected_version)
        if priority == task.priority:
            return task
        old = task.priority
        task.priority = priority
        task.version += 1
        task.save()
        activity.log(task, actor, "updated", {"changes": {"priority": priority}})
        record(
            actor=actor,
            action="task.priority_changed",
            entity=task,
            old_value={"priority": old},
            new_value={"priority": priority},
        )
        return task


def delete_task(*, actor, task_id) -> None:
    with transaction.atomic():
        task = get_task(actor, task_id, for_update=True)
        policy.require(actor, "task.delete", task)
        if Task.objects.filter(parent=task).exists():
            raise Conflict("Delete or move the subtasks first.", code="task_has_subtasks")
        task.deleted_at = timezone.now()
        task.version += 1
        task.save(update_fields=["deleted_at", "version", "updated_at"])
        activity.log(task, actor, "deleted")
        record(actor=actor, action="task.deleted", entity=task, old_value={"key": task.key, "status": task.status})


def restore_task(*, actor, task_id) -> Task:
    with transaction.atomic():
        task = get_task(actor, task_id, include_deleted=True, for_update=True)
        policy.require(actor, "task.delete", task)
        if task.deleted_at is None:
            raise Conflict("The task is not deleted.", code="task_not_deleted")
        if timezone.now() - task.deleted_at > RESTORE_WINDOW:
            raise Conflict("Deleted tasks can be restored for 30 days only.", code="restore_window_passed")
        if task.parent_id and Task.with_deleted.filter(pk=task.parent_id, deleted_at__isnull=False).exists():
            raise Conflict("Restore the parent task first.", code="parent_deleted")
        task.deleted_at = None
        task.version += 1
        task.save(update_fields=["deleted_at", "version", "updated_at"])
        activity.log(task, actor, "restored")
        record(actor=actor, action="task.restored", entity=task)
        return task
