"""Task review workflow: submit, approve, request changes.

Separate from time tracking by design (different app, tables and endpoints). Status
changes go through tasks.workflow.transition_task with the SUBMIT / APPROVE /
REQUEST_CHANGES triggers, which the generic transition endpoint cannot use.
"""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record
from apps.common.exceptions import Conflict, Forbidden, InvalidInput
from apps.notifications.services import notify
from apps.rbac import policy
from apps.rbac.catalogue import Scope
from apps.tasks.models import Status, Task, TaskComment, Trigger
from apps.tasks.services import activity
from apps.tasks.services.details import required_items_open
from apps.tasks.services.tasks import get_task
from apps.tasks.workflow import transition_task

from .models import TaskReview


def _pending(task: Task) -> TaskReview | None:
    return TaskReview.objects.select_for_update().filter(task=task, decision=TaskReview.Decision.PENDING).first()


def _company_wide_reviewer(actor) -> bool:
    return Scope.COMPANY.value in policy.permissions_for(actor).get("review.decide", [])


def submit(*, actor, task_id, note: str = "") -> TaskReview:
    with transaction.atomic():
        task = get_task(actor, task_id, for_update=True)
        policy.require(actor, "review.submit", task)
        if not task.assignees.filter(user=actor).exists():
            raise Forbidden("Only an assignee can submit this task for review.", code="not_assignee")
        if task.status != Status.IN_PROGRESS:
            raise Conflict("Only tasks in progress can be submitted for review.", code="invalid_transition")
        open_items = required_items_open(task)
        if open_items:
            raise InvalidInput(
                f"{open_items} required checklist item(s) are not done.",
                code="checklist_incomplete",
                details={"open_required_items": open_items},
            )
        if _pending(task) is not None:
            raise Conflict("This task already has an open review.", code="review_already_open")
        reviewer = User.objects.filter(pk=task.effective_reviewer_id, status=User.Status.ACTIVE).first()
        if reviewer is None:
            raise InvalidInput(
                "The task's reviewer is not an active employee. Ask a manager to set one.", code="reviewer_required"
            )

        task.review_round += 1
        Task.objects.filter(pk=task.pk).update(review_round=task.review_round)
        review = TaskReview.objects.create(
            company_id=task.company_id,
            task=task,
            round=task.review_round,
            submitted_by=actor,
            submission_note=note,
            reviewer=reviewer,
        )
        transition_task(actor=actor, task_id=task.pk, to_status=Status.IN_REVIEW, trigger=Trigger.SUBMIT, comment=note)
        activity.log(task, actor, "review_submitted", {"round": review.round, "reviewer_id": reviewer.pk})
        record(
            actor=actor,
            action="review.submitted",
            entity=review,
            new_value={"task": task.key, "round": review.round, "reviewer_id": reviewer.pk},
        )
        notify(
            recipients=[reviewer],
            actor=actor,
            event_type="review.requested",
            title=f"{task.key} is ready for your review",
            body=note or task.title,
            entity=task,
        )
        return review


def _decide_block(actor, task: Task, review: TaskReview) -> str | None:
    """Why ``actor`` may not decide ``review``: ``not_reviewer``, ``self_review`` or None."""
    company_wide = _company_wide_reviewer(actor)
    if actor.pk != review.reviewer_id and not company_wide:
        return "not_reviewer"
    is_assignee = any(a.user_id == actor.pk for a in task.assignees.all())
    if is_assignee and not (task.company.allow_self_review and company_wide):
        return "self_review"
    return None


def can_decide(actor, task: Task, review: TaskReview) -> bool:
    """True when ``actor`` may approve or request changes on the task's open review."""
    return policy.can(actor, "review.decide", task) and _decide_block(actor, task, review) is None


def _decide(actor, task_id, *, approve: bool, comment: str) -> TaskReview:
    comment = (comment or "").strip()
    with transaction.atomic():
        task = get_task(actor, task_id, for_update=True)
        policy.require(actor, "review.decide", task)
        review = _pending(task)
        if review is None or task.status != Status.IN_REVIEW:
            raise Conflict("There is no open review for this task.", code="no_open_review")
        blocked = _decide_block(actor, task, review)
        if blocked == "not_reviewer":
            raise Forbidden("Only the assigned reviewer can decide this review.", code="not_reviewer")
        if blocked == "self_review":
            raise Forbidden("You cannot review a task you are assigned to.", code="self_review")
        if not approve and not comment:
            raise InvalidInput(
                "Explain what needs to change.",
                code="comment_required",
                details={"comment": ["This field is required."]},
            )

        transition_task(
            actor=actor,
            task_id=task.pk,
            to_status=Status.COMPLETED if approve else Status.IN_PROGRESS,
            trigger=Trigger.APPROVE if approve else Trigger.REQUEST_CHANGES,
            comment="" if approve else comment,
        )
        if approve and comment:
            TaskComment.objects.create(
                company_id=task.company_id, task=task, author=actor, body=comment, kind=TaskComment.Kind.REVIEW
            )
        review.decision = TaskReview.Decision.APPROVED if approve else TaskReview.Decision.CHANGES_REQUESTED
        review.decided_by = actor
        review.comment = comment
        review.decided_at = timezone.now()
        review.save(update_fields=["decision", "decided_by", "comment", "decided_at", "updated_at"])

        activity.log(
            task,
            actor,
            "review_approved" if approve else "review_changes_requested",
            {"round": review.round, "comment": comment},
        )
        record(
            actor=actor,
            action="review.approved" if approve else "review.changes_requested",
            entity=review,
            old_value={"decision": "PENDING"},
            new_value={"decision": review.decision, "comment": comment, "round": review.round},
        )
        outcome = "approved" if approve else "changes requested"
        notify(
            recipients=[a.user for a in task.assignees.select_related("user")],
            actor=actor,
            event_type="review.approved" if approve else "review.changes_requested",
            title=f"{task.key}: {outcome}",
            body=comment,
            entity=task,
        )
        return review


def approve(*, actor, task_id, comment: str = "") -> TaskReview:
    return _decide(actor, task_id, approve=True, comment=comment)


def request_changes(*, actor, task_id, comment: str) -> TaskReview:
    return _decide(actor, task_id, approve=False, comment=comment)


def history(*, actor, task_id):
    task = get_task(actor, task_id)
    policy.require(actor, "review.view", task)
    return TaskReview.objects.filter(task=task).select_related("submitted_by", "reviewer", "decided_by")


def queue(actor):
    """Open reviews waiting for this person (all open reviews in scope for company-wide reviewers)."""
    qs = TaskReview.objects.filter(decision=TaskReview.Decision.PENDING).select_related(
        "task__project", "submitted_by", "reviewer", "decided_by"
    )
    if not _company_wide_reviewer(actor):
        qs = qs.filter(reviewer=actor)
    return qs.order_by("submitted_at")
