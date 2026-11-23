"""Catalogue of notification events and their default delivery channels."""

EVENTS: dict[str, dict] = {
    "task.assigned": {"label": "A task is assigned to me", "in_app": True, "email": True},
    "task.mentioned": {"label": "Someone mentions me", "in_app": True, "email": True},
    "task.commented": {"label": "New comment on my task", "in_app": True, "email": False},
    "task.escalated": {"label": "A blocked task is escalated to me", "in_app": True, "email": True},
    "task.needs_reassignment": {"label": "A task needs a new assignee", "in_app": True, "email": True},
    "task.due_soon": {"label": "My task is due within a day", "in_app": True, "email": True},
    "task.overdue": {"label": "My task is overdue", "in_app": True, "email": True},
    "task.long_blocked": {"label": "A task has been blocked for over 48 hours", "in_app": True, "email": False},
    "review.requested": {"label": "A task is waiting for my review", "in_app": True, "email": True},
    "review.approved": {"label": "My task is approved", "in_app": True, "email": True},
    "review.changes_requested": {"label": "Changes are requested on my task", "in_app": True, "email": True},
    "time.timer_stopped": {"label": "My timer was stopped automatically", "in_app": True, "email": False},
    "timesheet.submitted": {"label": "A timesheet is waiting for my approval", "in_app": True, "email": True},
    "timesheet.approved": {"label": "My timesheet is approved", "in_app": True, "email": False},
    "timesheet.rejected": {"label": "My timesheet is rejected", "in_app": True, "email": True},
    "timesheet.reminder": {"label": "Reminder to submit last week's timesheet", "in_app": True, "email": True},
    "report.ready": {"label": "My report export is ready", "in_app": True, "email": False},
}


def defaults(event_type: str) -> tuple[bool, bool]:
    meta = EVENTS.get(event_type, {"in_app": True, "email": False})
    return meta["in_app"], meta["email"]
