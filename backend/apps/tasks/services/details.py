"""Checklists, dependencies, comments with mentions, escalation."""

import re
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record
from apps.common.exceptions import Conflict, Forbidden, InvalidInput, NotFound
from apps.notifications.services import notify
from apps.rbac import policy
from apps.rbac.catalogue import RoleKey
from apps.rbac.models import UserRole

from ..models import (
    ChecklistItem,
    CommentMention,
    Status,
    Task,
    TaskActivity,
    TaskChecklist,
    TaskComment,
    TaskDependency,
)
from . import activity
from .tasks import ensure_editable, ensure_not_in_review, get_task

COMMENT_EDIT_WINDOW = timedelta(minutes=15)
ESCALATION_COOLDOWN = timedelta(hours=1)
MENTION_RE = re.compile(r"@\[([^\]\n]{1,100})\]\(user:([0-9a-fA-F-]{36})\)")


# --- Checklists ---------------------------------------------------------------------


def _checklist_task(actor, checklist: TaskChecklist, code: str) -> Task:
    task = get_task(actor, checklist.task_id)
    policy.require(actor, code, task)
    ensure_editable(task)
    ensure_not_in_review(task)
    return task


def add_checklist(*, actor, task_id, title: str, position: int | None = None) -> TaskChecklist:
    task = get_task(actor, task_id)
    policy.require(actor, "task.checklist.manage", task)
    ensure_editable(task)
    ensure_not_in_review(task)
    if position is None:
        position = task.checklists.count()
    checklist = TaskChecklist.objects.create(company_id=task.company_id, task=task, title=title, position=position)
    activity.log(task, actor, "checklist_added", {"title": title})
    record(
        actor=actor, action="task.checklist.created", entity=checklist, new_value={"task_id": task.pk, "title": title}
    )
    return checklist


def update_checklist(*, actor, checklist: TaskChecklist, data: dict) -> TaskChecklist:
    _checklist_task(actor, checklist, "task.checklist.manage")
    old = {k: getattr(checklist, k) for k in data}
    for key, value in data.items():
        setattr(checklist, key, value)
    checklist.save()
    record(actor=actor, action="task.checklist.updated", entity=checklist, old_value=old, new_value=data)
    return checklist


def delete_checklist(*, actor, checklist: TaskChecklist) -> None:
    task = _checklist_task(actor, checklist, "task.checklist.manage")
    activity.log(task, actor, "checklist_removed", {"title": checklist.title})
    record(actor=actor, action="task.checklist.deleted", entity=checklist, old_value={"title": checklist.title})
    checklist.delete()


def add_item(*, actor, checklist: TaskChecklist, text: str, is_required: bool = False) -> ChecklistItem:
    _checklist_task(actor, checklist, "task.checklist.manage")
    item = ChecklistItem.objects.create(
        company_id=checklist.company_id,
        checklist=checklist,
        text=text,
        is_required=is_required,
        position=checklist.items.count(),
    )
    record(
        actor=actor,
        action="task.checklist_item.created",
        entity=item,
        new_value={"checklist_id": checklist.pk, "text": text, "is_required": is_required},
    )
    return item


def update_item(*, actor, item: ChecklistItem, data: dict) -> ChecklistItem:
    structural = {k for k in data if k != "is_done"}
    task = _checklist_task(actor, item.checklist, "task.checklist.manage" if structural else "task.checklist.complete")
    old = {k: getattr(item, k) for k in data}
    for key, value in data.items():
        setattr(item, key, value)
    if "is_done" in data:
        item.done_by = actor if item.is_done else None
        item.done_at = timezone.now() if item.is_done else None
        activity.log(
            task, actor, "checklist_item_done" if item.is_done else "checklist_item_undone", {"text": item.text}
        )
    item.save()
    record(actor=actor, action="task.checklist_item.updated", entity=item, old_value=old, new_value=data)
    return item


def delete_item(*, actor, item: ChecklistItem) -> None:
    _checklist_task(actor, item.checklist, "task.checklist.manage")
    record(actor=actor, action="task.checklist_item.deleted", entity=item, old_value={"text": item.text})
    item.delete()


def required_items_open(task: Task) -> int:
    return ChecklistItem.objects.filter(checklist__task=task, is_required=True, is_done=False).count()


# --- Dependencies -------------------------------------------------------------------------


def _creates_cycle(task: Task, blocker: Task) -> bool:
    """Adding ``task`` -> ``blocker`` closes a cycle if ``task`` is already reachable
    from ``blocker`` by following blocked_by edges. Serialised per company with an
    advisory lock so two concurrent inserts cannot each miss the other's edge."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"task-deps:{task.company_id}"])
        cursor.execute(
            """
            WITH RECURSIVE chain(id) AS (
                SELECT blocked_by_id FROM tasks_taskdependency WHERE task_id = %(start)s
                UNION
                SELECT d.blocked_by_id FROM tasks_taskdependency d JOIN chain c ON d.task_id = c.id
            )
            SELECT EXISTS (SELECT 1 FROM chain WHERE id = %(target)s)
            """,
            {"start": blocker.pk, "target": task.pk},
        )
        return cursor.fetchone()[0]


def add_dependency(*, actor, task_id, blocked_by_id) -> TaskDependency:
    with transaction.atomic():
        task = get_task(actor, task_id)
        policy.require(actor, "task.dependency.manage", task)
        ensure_editable(task)
        try:
            blocker = get_task(actor, blocked_by_id)
        except NotFound as exc:
            raise InvalidInput(details={"blocked_by_id": ["Unknown task."]}) from exc
        if blocker.pk == task.pk:
            raise InvalidInput(details={"blocked_by_id": ["A task cannot depend on itself."]})
        if TaskDependency.objects.filter(task=task, blocked_by=blocker).exists():
            raise Conflict("This dependency already exists.", code="dependency_exists")
        if _creates_cycle(task, blocker):
            raise Conflict(
                f"{blocker.key} already depends on {task.key}; this would create a cycle.", code="dependency_cycle"
            )
        dep = TaskDependency.objects.create(company_id=task.company_id, task=task, blocked_by=blocker, created_by=actor)
        activity.log(task, actor, "dependency_added", {"blocked_by": blocker.key})
        record(
            actor=actor,
            action="task.dependency.created",
            entity=dep,
            new_value={"task": task.key, "blocked_by": blocker.key},
        )
        return dep


def remove_dependency(*, actor, dependency: TaskDependency) -> None:
    task = get_task(actor, dependency.task_id)
    policy.require(actor, "task.dependency.manage", task)
    ensure_editable(task)
    activity.log(task, actor, "dependency_removed", {"blocked_by": dependency.blocked_by.key})
    record(
        actor=actor,
        action="task.dependency.deleted",
        entity=dependency,
        old_value={"task": task.key, "blocked_by": dependency.blocked_by.key},
    )
    dependency.delete()


# --- Comments ----------------------------------------------------------------------------


def _mentioned_users(task: Task, body: str) -> list[User]:
    ids = {m.group(2).lower() for m in MENTION_RE.finditer(body)}
    if not ids:
        return []
    users = list(User.objects.filter(pk__in=ids, company_id=task.company_id, status=User.Status.ACTIVE))
    hidden = [u.full_name for u in users if not policy.can(u, "task.view", task)]
    if len(users) != len(ids):
        raise InvalidInput(details={"body": ["A mentioned person does not exist or is not active."]})
    if hidden:
        raise InvalidInput(details={"body": [f"Cannot mention people who cannot see this task: {', '.join(hidden)}."]})
    return users


def _store_mentions(comment: TaskComment, users: list[User]) -> list[User]:
    existing = set(comment.mentions.values_list("user_id", flat=True))
    new = [u for u in users if u.pk not in existing]
    CommentMention.objects.bulk_create(
        CommentMention(company_id=comment.company_id, comment=comment, user=u) for u in new
    )
    return new


def add_comment(*, actor, task_id, body: str) -> TaskComment:
    with transaction.atomic():
        task = get_task(actor, task_id)
        policy.require(actor, "task.comment", task)
        ensure_editable(task)
        mentioned = _mentioned_users(task, body)
        comment = TaskComment.objects.create(company_id=task.company_id, task=task, author=actor, body=body)
        _store_mentions(comment, mentioned)
        activity.log(task, actor, "commented", {"comment_id": comment.pk})
        record(
            actor=actor,
            action="task.comment.created",
            entity=comment,
            new_value={"task_id": task.pk, "mentions": [u.pk for u in mentioned]},
        )
        notify(
            recipients=mentioned,
            actor=actor,
            event_type="task.mentioned",
            title=f"{actor.full_name} mentioned you on {task.key}",
            body=body[:300],
            entity=task,
        )
        watchers = [a.user for a in task.assignees.select_related("user")] + [task.created_by]
        notify(
            recipients=[w for w in watchers if w not in mentioned],
            actor=actor,
            event_type="task.commented",
            title=f"New comment on {task.key}",
            body=body[:300],
            entity=task,
        )
        return comment


def edit_comment(*, actor, comment: TaskComment, body: str) -> TaskComment:
    with transaction.atomic():
        task = get_task(actor, comment.task_id)
        ensure_editable(task)
        if comment.author_id != actor.pk or comment.deleted_at or comment.kind != TaskComment.Kind.COMMENT:
            raise Forbidden("Only the author can edit their comment.")
        if timezone.now() - comment.created_at > COMMENT_EDIT_WINDOW:
            raise Conflict("Comments can be edited for 15 minutes after posting.", code="edit_window_passed")
        mentioned = _mentioned_users(task, body)
        old = comment.body
        comment.body = body
        comment.edited_at = timezone.now()
        comment.save(update_fields=["body", "edited_at", "updated_at"])
        new = _store_mentions(comment, mentioned)
        record(
            actor=actor, action="task.comment.edited", entity=comment, old_value={"body": old}, new_value={"body": body}
        )
        notify(
            recipients=new,
            actor=actor,
            event_type="task.mentioned",
            title=f"{actor.full_name} mentioned you on {task.key}",
            body=body[:300],
            entity=task,
        )
        return comment


def delete_comment(*, actor, comment: TaskComment) -> None:
    task = get_task(actor, comment.task_id)
    ensure_editable(task)
    if comment.deleted_at:
        raise NotFound()
    if comment.author_id != actor.pk and not policy.can(actor, "task.update", task):
        raise Forbidden("Only the author or a task manager can delete this comment.")
    record(actor=actor, action="task.comment.deleted", entity=comment, old_value={"body": comment.body})
    comment.body = ""
    comment.deleted_at = timezone.now()
    comment.save(update_fields=["body", "deleted_at", "updated_at"])


# --- Escalation -------------------------------------------------------------------------


def escalation_recipients(task: Task) -> list[User]:
    candidates = {task.project.owner} if task.project.owner_id else set()
    manager_ids = UserRole.objects.filter(
        company_id=task.company_id, role__key__in=[RoleKey.MANAGER, RoleKey.COMPANY_ADMIN]
    ).values_list("user_id", flat=True)
    for user in User.objects.filter(pk__in=manager_ids, status=User.Status.ACTIVE).select_related("company"):
        if policy.can(user, "task.update", task):
            candidates.add(user)
    return [u for u in candidates if u is not None and u.is_active]


def escalate(*, actor, task_id, note: str = "") -> int:
    with transaction.atomic():
        task = get_task(actor, task_id, for_update=True)
        policy.require(actor, "task.escalate", task)
        if task.status != Status.BLOCKED:
            raise Conflict("Only blocked tasks can be escalated.", code="not_blocked")
        recent = TaskActivity.objects.filter(
            task=task, verb="escalated", created_at__gte=timezone.now() - ESCALATION_COOLDOWN
        ).exists()
        if recent:
            raise Conflict(
                "This task was escalated less than an hour ago.", code="escalation_throttled", status_code=429
            )
        recipients = escalation_recipients(task)
        sent = notify(
            recipients=recipients,
            actor=actor,
            event_type="task.escalated",
            title=f"{task.key} is blocked and needs a manager",
            body=f"Reason: {task.blocked_reason}\n{note}".strip(),
            entity=task,
        )
        activity.log(task, actor, "escalated", {"note": note, "notified": sent})
        record(
            actor=actor,
            action="task.escalated",
            entity=task,
            new_value={"note": note, "notified_user_ids": [u.pk for u in recipients]},
        )
        return sent
