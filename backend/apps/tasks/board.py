"""Which columns a board card may be dragged to, per actor."""

from apps.rbac import policy

from .models import Status, StatusTransitionRule, Task, Trigger
from .workflow import actor_allowed, open_blockers

_ACTIONS = {
    Trigger.MANUAL: "transition",
    Trigger.ASSIGN: "assign",
    Trigger.SUBMIT: "submit",
    Trigger.APPROVE: "approve",
    Trigger.REQUEST_CHANGES: "request_changes",
}
_ORDER = {value: i for i, value in enumerate(Status.values)}


def _open_review(task: Task):
    """The pending review, from the ``pending_reviews`` prefetch when present."""
    if hasattr(task, "pending_reviews"):
        return task.pending_reviews[0] if task.pending_reviews else None
    return task.reviews.filter(decision="PENDING").first()


def _open_required_items(task: Task) -> int:
    """Open required checklist items, from the board's annotation when present."""
    if hasattr(task, "open_required_items"):
        return task.open_required_items
    from .services.details import required_items_open

    return required_items_open(task)


def _has_open_blockers(task: Task) -> bool:
    """Open blockers, from the board's annotation when present (only if the company enforces dependencies)."""
    if not task.company.enforce_dependencies:
        return False
    if hasattr(task, "open_blocker_count"):
        return task.open_blocker_count > 0
    return bool(open_blockers(task))


def _permitted(actor, task: Task, rule: StatusTransitionRule) -> bool:
    from apps.reviews.services import can_decide

    if rule.to_status == Status.IN_PROGRESS and _has_open_blockers(task):
        return False  # the transition would be refused with dependency_blocked
    if rule.trigger == Trigger.MANUAL:
        if task.locked_at and task.status != Status.COMPLETED:
            return False
        return actor_allowed(actor, rule, task)
    if not actor_allowed(actor, rule, task):
        return False
    if rule.trigger == Trigger.ASSIGN:
        return policy.can(actor, "task.assign", task)
    if rule.trigger == Trigger.SUBMIT:
        return (
            policy.can(actor, "review.submit", task)
            and any(a.user_id == actor.pk for a in task.assignees.all())
            and _open_required_items(task) == 0
        )
    review = _open_review(task)  # APPROVE / REQUEST_CHANGES
    return review is not None and can_decide(actor, task, review)


def allowed_moves(actor, task: Task, *, rules: list[StatusTransitionRule]) -> list[dict]:
    """Moves ``actor`` may make from the task's status; one per target, MANUAL winning ties."""
    by_target: dict[str, dict] = {}
    for rule in rules:
        if rule.from_status != task.status or rule.trigger not in _ACTIONS or not rule.is_active:
            continue
        if rule.to_status in by_target and rule.trigger != Trigger.MANUAL:
            continue
        if not _permitted(actor, task, rule):
            continue
        by_target[rule.to_status] = {
            "to_status": rule.to_status,
            "action": _ACTIONS[rule.trigger],
            "requires_comment": rule.requires_comment or rule.trigger == Trigger.REQUEST_CHANGES,
        }
    return sorted(by_target.values(), key=lambda m: _ORDER[m["to_status"]])
