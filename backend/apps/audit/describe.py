# ruff: noqa: E501 - the sentence table reads best one action per line
"""Plain-English wording for audit entries.

The audit table stores machine-readable ``action`` codes and raw payloads. People reading
the log (company admins, HR) see a sentence instead, such as "Ada Lovelace added Mo Khan
and Mia Lee to the team Web", and a list of readable changes. Permission codes are shown
by their catalogue description, never by code.

``describe_entries`` resolves every name a page of entries needs in a few batched queries.
"""

import re
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime

from django.utils.dateparse import parse_datetime

from apps.rbac.catalogue import PERMISSIONS, ROLES

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
USER_KEYS = ("user_id", "lead_id", "target_user_id", "reviewer_id", "manager")
USER_LIST_KEYS = ("user_ids", "notified_user_ids")
#: Entity types that belong to a task: model -> how to reach the task id.
TASK_CHILDREN = {
    "taskattachment": ("tasks.TaskAttachment", "task_id"),
    "taskchecklist": ("tasks.TaskChecklist", "task_id"),
    "checklistitem": ("tasks.ChecklistItem", "checklist__task_id"),
    "taskcomment": ("tasks.TaskComment", "task_id"),
    "taskdependency": ("tasks.TaskDependency", "task_id"),
    "timeentry": ("timetracking.TimeEntry", "task_id"),
    "taskreview": ("reviews.TaskReview", "task_id"),
}
NAMED = {  # entity type -> (model, name field)
    "team": ("org.Team", "name"),
    "project": ("org.Project", "name"),
    "role": ("rbac.Role", "name"),
    "company": ("companies.Company", "name"),
    "plan": ("companies.Plan", "name"),
    "scheduledreport": ("reports.ScheduledReport", "name"),
}
SCOPES = {
    "COMPANY": "whole company",
    "TEAM": "own teams",
    "PROJECT": "own projects",
    "OWN": "own items",
    "PLATFORM": "platform",
}
FIELD_LABELS = {
    "manager": "Manager",
    "lead_id": "Team lead",
    "job_title": "Job title",
    "first_name": "First name",
    "last_name": "Last name",
    "due_date": "Due date",
    "start_date": "Start date",
    "estimated_minutes": "Estimate",
    "is_required": "Required",
    "is_done": "Done",
    "requires_comment": "Needs a comment",
    "allowed_roles": "Allowed roles",
    "is_active": "Active",
    "team_ids": "Teams",
    "week_start": "Week start",
    "max_timer_hours": "Timer limit (hours)",
    "enforce_dependencies": "Enforce dependencies",
    "timer_start_moves_to_in_progress": "Timer start moves task to In progress",
}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _model(label: str):
    from django.apps import apps

    return apps.get_model(label)


def _ids(values: Iterable) -> set[str]:
    return {str(v) for v in values if v and UUID_RE.match(str(v))}


def _payloads(entry) -> list[dict]:
    return [v for v in (entry.old_value, entry.new_value) if isinstance(v, dict)]


class Names:
    """Display names for the ids a page of audit entries mentions."""

    def __init__(self, entries: list):
        user_ids, by_type, task_ids, role_keys = set(), {}, set(), set()
        for e in entries:
            user_ids |= _ids([e.actor_id])
            by_type.setdefault(e.entity_type, set()).update(_ids([e.entity_id]))
            for p in _payloads(e):
                user_ids |= _ids(p.get(k) for k in USER_KEYS)
                for k in USER_LIST_KEYS:
                    user_ids |= _ids(p.get(k) or [])
                task_ids |= _ids([p.get("task_id")]) | _ids(p.get("task_ids") or [])
                for k in ("role", "roles", "allowed_roles"):
                    value = p.get(k)
                    role_keys.update(value if isinstance(value, list) else [value] if isinstance(value, str) else [])
                if e.action == "employee.teams_set":
                    by_type.setdefault("team", set()).update(_ids(p.get("team_ids") or []))
        user_ids |= by_type.get("user", set())

        user_model = _model("accounts.User")
        self.users = {str(u.pk): u.full_name or u.email for u in user_model._base_manager.filter(pk__in=user_ids)}
        self.named = {}
        for etype, (label, field) in NAMED.items():
            ids = by_type.get(etype)
            if ids:
                rows = _model(label)._base_manager.filter(pk__in=ids).values_list("pk", field)
                self.named.update({(etype, str(pk)): name for pk, name in rows})
        self.task_of = {}
        for etype, (label, path) in TASK_CHILDREN.items():
            ids = by_type.get(etype)
            if ids:
                rows = _model(label)._base_manager.filter(pk__in=ids).values_list("pk", path)
                self.task_of.update({str(pk): str(tid) for pk, tid in rows})
        task_ids |= by_type.get("task", set()) | set(self.task_of.values())
        tasks = _model("tasks.Task")._base_manager.filter(pk__in=task_ids).select_related("project")
        self.tasks = {str(t.pk): f"{t.key} “{t.title}”" for t in tasks}
        company_ids = {e.company_id for e in entries}
        custom = (
            _model("rbac.Role")
            ._base_manager.filter(key__in=role_keys, company_id__in=company_ids)
            .values_list("key", "name")
            if role_keys
            else []
        )
        self.roles = {**{k.value: v["name"] for k, v in ROLES.items()}, **dict(custom)}

    def user(self, user_id, fallback: str = "a person") -> str:
        return self.users.get(str(user_id), fallback) if user_id else fallback

    def user_list(self, ids) -> str:
        return _join([self.user(i) for i in ids or []]) or "nobody"

    def role(self, key) -> str:
        return self.roles.get(key, str(key).replace("_", " ").title()) if key else "a role"


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _status(value) -> str:
    from apps.tasks.models import Status

    try:
        return Status(value).label
    except ValueError:
        return str(value).replace("_", " ").capitalize()


def _duration(seconds) -> str:
    minutes = int(seconds or 0) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _parse(value) -> datetime | None:
    try:
        return parse_datetime(str(value)) if value else None
    except ValueError:
        return None


def _when(value) -> str:
    moment = _parse(value)
    return moment.strftime("%d %b %Y, %H:%M") if moment else str(value or "")


class Ctx:
    """What a sentence template needs for one entry."""

    def __init__(self, entry, names: Names):
        self.e, self.n = entry, names
        self.old = entry.old_value if isinstance(entry.old_value, dict) else {}
        self.new = entry.new_value if isinstance(entry.new_value, dict) else {}
        actor = names.users.get(str(entry.actor_id)) if entry.actor_id else None
        self.actor = actor or entry.actor_email or "The system"
        self.id = str(entry.entity_id or "")

    @property
    def subject(self) -> str:
        """The user the entry is about."""
        return self.n.user(self.id, "an employee")

    def named(self, etype: str, fallback: str) -> str:
        return self.n.named.get((etype, self.id), fallback)

    @property
    def task(self) -> str:
        task_id = self.id if self.e.entity_type == "task" else self.n.task_of.get(self.id)
        task_id = task_id or self.new.get("task_id") or self.old.get("task_id")
        label = self.n.tasks.get(str(task_id)) if task_id else None
        return label or self.new.get("task") or self.old.get("task") or self.old.get("key") or "a task"

    @property
    def team(self) -> str:
        name = self.named("team", "")
        return f"the team {name}" if name else "a team"

    @property
    def project(self) -> str:
        name = self.named("project", "")
        return f"the project {name}" if name else "a project"


T = Callable[[Ctx], str]


SENTENCES: dict[str, T] = {
    # sign-in and security
    "auth.login": lambda c: f"{c.subject} signed in",
    "auth.login_failed": lambda c: f"A sign-in attempt for {c.subject} failed",
    "auth.account_locked": lambda c: (
        f"{c.subject}'s account was locked for {c.new.get('minutes', 'some')} minutes after failed sign-ins"
    ),
    "auth.logout": lambda c: f"{c.actor} signed out",
    "auth.logout_all": lambda c: f"{c.actor} signed out of all devices",
    "auth.session_revoked": lambda c: f"{c.actor} ended a signed-in session",
    "auth.refresh_reuse_detected": lambda c: (
        f"A reused sign-in token was detected for {c.n.user(c.new.get('user_id'))}; their sessions were ended"
    ),
    "auth.mfa_setup_started": lambda c: f"{c.subject} started setting up two-step verification",
    "auth.mfa_enabled": lambda c: f"{c.subject} turned on two-step verification",
    "auth.mfa_disabled": lambda c: f"Two-step verification was turned off for {c.subject}",
    "auth.mfa_challenge": lambda c: f"{c.subject} was asked for a two-step verification code",
    "auth.mfa_recovery_codes_regenerated": lambda c: f"{c.subject} created new recovery codes",
    "auth.recovery_code_used": lambda c: f"{c.subject} signed in with a recovery code",
    "password.changed": lambda c: f"{c.subject} changed their password",
    "password.reset_requested": lambda c: f"A password reset link was requested for {c.subject}",
    "password.reset_completed": lambda c: f"{c.subject} reset their password",
    "password.hr_reset_link_sent": lambda c: f"{c.actor} sent {c.subject} a password reset link",
    "password.hr_temporary_set": lambda c: f"{c.actor} set a temporary password for {c.subject}",
    "profile.updated": lambda c: f"{c.subject} updated their profile",
    # people
    "employee.created": lambda c: (
        f"{c.actor} added {c.subject} as {_join([c.n.role(r) for r in c.new.get('roles', [])]) or 'an employee'}"
    ),
    "employee.updated": lambda c: f"{c.actor} updated {c.subject}'s details",
    "employee.imported": lambda c: f"{c.actor} imported employees from a file",
    "employee.offboarded": lambda c: f"{c.actor} offboarded {c.subject}",
    "employee.deactivated": lambda c: f"{c.actor} deactivated {c.subject}",
    "employee.reactivated": lambda c: f"{c.actor} reactivated {c.subject}",
    "employee.sessions_revoked": lambda c: f"{c.actor} signed {c.subject} out of all devices",
    "employee.teams_set": lambda c: f"{c.actor} changed {c.subject}'s teams",
    "invite.created": lambda c: f"{c.actor} invited {c.subject}",
    "invite.resent": lambda c: f"{c.actor} sent {c.subject} a new invitation",
    "invite.revoked": lambda c: f"{c.actor} cancelled {c.subject}'s invitation",
    "invite.accepted": lambda c: f"{c.subject} accepted their invitation",
    # roles
    "rbac.role.created": lambda c: f"{c.actor} created the role {c.named('role', c.new.get('name', ''))}",
    "rbac.role.updated": lambda c: f"{c.actor} updated the role {c.named('role', '')}",
    "rbac.role.permissions_set": lambda c: f"{c.actor} changed what the role {c.named('role', '')} can do",
    "rbac.role.deleted": lambda c: f"{c.actor} deleted the role {c.old.get('name', '')}",
    "rbac.user_role.granted": lambda c: f"{c.actor} gave {c.subject} the {c.n.role(c.new.get('role'))} role",
    "rbac.user_role.revoked": lambda c: f"{c.actor} removed the {c.n.role(c.old.get('role'))} role from {c.subject}",
    # organisation
    "org.team.created": lambda c: f"{c.actor} created the team {c.new.get('name') or c.named('team', '')}",
    "org.team.updated": lambda c: f"{c.actor} updated {c.team}",
    "org.team.archived": lambda c: f"{c.actor} archived {c.team}",
    "org.team.members_added": lambda c: f"{c.actor} added {c.n.user_list(c.new.get('user_ids'))} to {c.team}",
    "org.team.member_removed": lambda c: f"{c.actor} removed {c.n.user(c.old.get('user_id'))} from {c.team}",
    "org.team.lead_set": lambda c: (
        f"{c.actor} made {c.n.user(c.new.get('lead_id'))} the lead of {c.team}"
        if c.new.get("lead_id")
        else f"{c.actor} removed the lead of {c.team}"
    ),
    "org.project.created": lambda c: f"{c.actor} created the project {c.new.get('name') or c.named('project', '')}",
    "org.project.updated": lambda c: f"{c.actor} updated {c.project}",
    "org.project.members_added": lambda c: f"{c.actor} added {c.n.user_list(c.new.get('user_ids'))} to {c.project}",
    "org.project.member_removed": lambda c: f"{c.actor} removed {c.n.user(c.old.get('user_id'))} from {c.project}",
    "org.holiday.created": lambda c: f"{c.actor} added the holiday {c.new.get('name', '')} on {c.new.get('date', '')}",
    "org.holiday.deleted": lambda c: (
        f"{c.actor} removed the holiday {c.old.get('name', '')} on {c.old.get('date', '')}"
    ),
    "org.leave.recorded": lambda c: (
        f"{c.actor} recorded leave for {c.n.user(c.new.get('user_id'))} on {c.new.get('date', '')}"
    ),
    "org.leave.deleted": lambda c: (
        f"{c.actor} removed leave for {c.n.user(c.old.get('user_id'))} on {c.old.get('date', '')}"
    ),
    "company.settings.updated": lambda c: f"{c.actor} changed the company settings",
    "workflow.rule.updated": lambda c: f"{c.actor} changed a task status rule",
    "workflow.rules.reset": lambda c: f"{c.actor} restored the default task status rules",
    "notification.preferences_updated": lambda c: f"{c.actor} changed their notification settings",
    "notification.read": lambda c: f"{c.actor} read a notification",
    "notification.read_all": lambda c: f"{c.actor} marked all notifications as read",
    # tasks
    "task.created": lambda c: f"{c.actor} created {c.task}",
    "task.updated": lambda c: f"{c.actor} edited {c.task}",
    "task.deleted": lambda c: f"{c.actor} deleted {c.task}",
    "task.restored": lambda c: f"{c.actor} restored {c.task}",
    "task.transition": lambda c: (
        f"{c.actor} moved {c.task} from {_status(c.old.get('status'))} to {_status(c.new.get('status'))}"
    ),
    "task.assigned": lambda c: f"{c.actor} assigned {c.task} to {c.n.user_list(c.new.get('user_ids'))}",
    "task.bulk_assigned": lambda c: (
        f"{c.actor} assigned {len(c.new.get('task_ids') or [])} tasks to {c.n.user_list(c.new.get('user_ids'))}"
    ),
    "task.unassigned": lambda c: f"{c.actor} removed {c.n.user(c.old.get('user_id'))} from {c.task}",
    "task.reassigned": lambda c: (
        f"{c.actor} reassigned {c.task} from {c.n.user(c.old.get('user_id'))} to {c.n.user(c.new.get('user_id'))}"
    ),
    "task.acknowledged": lambda c: f"{c.actor} acknowledged {c.task}",
    "task.priority_changed": lambda c: (
        f"{c.actor} changed the priority of {c.task} from {str(c.old.get('priority', '')).title()} to {str(c.new.get('priority', '')).title()}"
    ),
    "task.escalated": lambda c: f"{c.actor} escalated {c.task} to {c.n.user_list(c.new.get('notified_user_ids'))}",
    "task.comment.created": lambda c: f"{c.actor} commented on {c.task}",
    "task.comment.edited": lambda c: f"{c.actor} edited a comment on {c.task}",
    "task.comment.deleted": lambda c: f"{c.actor} deleted a comment on {c.task}",
    "task.attachment.uploaded": lambda c: f"{c.actor} attached {c.new.get('filename', 'a file')} to {c.task}",
    "task.attachment.deleted": lambda c: f"{c.actor} removed {c.old.get('filename', 'a file')} from {c.task}",
    "task.checklist.created": lambda c: f"{c.actor} added the checklist “{c.new.get('title', '')}” to {c.task}",
    "task.checklist.updated": lambda c: f"{c.actor} edited a checklist on {c.task}",
    "task.checklist.deleted": lambda c: f"{c.actor} removed the checklist “{c.old.get('title', '')}” from {c.task}",
    "task.checklist_item.created": lambda c: (
        f"{c.actor} added the checklist item “{c.new.get('text', '')}” to {c.task}"
    ),
    "task.checklist_item.updated": lambda c: (
        f"{c.actor} {'ticked' if c.new.get('is_done') else 'unticked'} a checklist item on {c.task}"
        if "is_done" in c.new
        else f"{c.actor} edited a checklist item on {c.task}"
    ),
    "task.checklist_item.deleted": lambda c: (
        f"{c.actor} removed the checklist item “{c.old.get('text', '')}” from {c.task}"
    ),
    "task.dependency.created": lambda c: (
        f"{c.actor} marked {c.task} as blocked by {c.new.get('blocked_by', 'another task')}"
    ),
    "task.dependency.deleted": lambda c: (
        f"{c.actor} removed the dependency of {c.task} on {c.old.get('blocked_by', 'another task')}"
    ),
    "review.submitted": lambda c: f"{c.actor} sent {c.task} to {c.n.user(c.new.get('reviewer_id'))} for review",
    "review.approved": lambda c: f"{c.actor} approved the work on {c.task}",
    "review.changes_requested": lambda c: f"{c.actor} asked for changes on {c.task}",
    # time
    "time.timer_started": lambda c: f"{c.actor} started a timer on {c.task}",
    "time.timer_stopped": lambda c: (
        f"{c.actor} stopped the timer on {c.task} after {_duration(c.new.get('duration_seconds'))}"
    ),
    "time.timer_paused": lambda c: (
        f"{c.actor} paused the timer on {c.task} after {_duration(c.new.get('duration_seconds'))}"
    ),
    "time.timer_switched": lambda c: (
        f"{c.actor} switched away from {c.task} after {_duration(c.new.get('duration_seconds'))}"
    ),
    "time.timer_auto_stopped": lambda c: (
        f"The timer on {c.task} was stopped automatically ({str(c.new.get('reason', '')).replace('_', ' ')})"
    ),
    "time.entry_created": lambda c: f"{c.actor} logged time on {c.task}",
    "time.entry_updated": lambda c: f"{c.actor} corrected a time entry on {c.task}",
    "time.entry_deleted": lambda c: f"{c.actor} deleted a time entry on {c.task}",
    # reports
    "report.export_requested": lambda c: (
        f"{c.actor} requested a {str(c.new.get('report_type', '')).replace('_', ' ')} report export"
    ),
    "report.export_finished": lambda c: f"A report export finished ({c.new.get('rows', 0)} rows)",
    "report.schedule_created": lambda c: f"{c.actor} scheduled the report {c.named('scheduledreport', '')}".strip(),
    "report.schedule_updated": lambda c: (
        f"{c.actor} changed the scheduled report {c.named('scheduledreport', '')}".strip()
    ),
    "report.schedule_deleted": lambda c: f"{c.actor} deleted the scheduled report {c.old.get('name', '')}".strip(),
    "report.schedule_ran": lambda c: f"The scheduled report {c.named('scheduledreport', '')} ran".replace("  ", " "),
    # platform (visible to companies when it concerns them)
    "impersonation.request": lambda c: "A support session viewed or changed data",
    "platform.impersonation.started": lambda c: (
        f"Platform support started a session as {c.n.user(c.new.get('target_user_id'))}"
    ),
    "platform.impersonation.ended": lambda c: "Platform support ended a session",
    "platform.company.created": lambda c: f"{c.actor} created the company {c.named('company', '')}",
    "platform.company.updated": lambda c: f"{c.actor} updated the company {c.named('company', '')}",
    "platform.company.activated": lambda c: f"{c.actor} activated the company {c.named('company', '')}",
    "platform.company.suspended": lambda c: f"{c.actor} suspended the company {c.named('company', '')}",
    "platform.company.deleted": lambda c: f"{c.actor} deleted the company {c.named('company', '')}",
    "platform.company.users_listed": lambda c: f"{c.actor} viewed the people in {c.named('company', 'a company')}",
    "platform.company_admin.created": lambda c: f"{c.actor} added {c.subject} as a company admin",
    "platform.super_admin.created": lambda c: f"{c.actor} added {c.subject} as a platform admin",
    "platform.plan.created": lambda c: f"{c.actor} created the plan {c.named('plan', '')}",
    "platform.plan.updated": lambda c: f"{c.actor} updated the plan {c.named('plan', '')}",
}


def _fallback(c: Ctx) -> str:
    """Unknown action: say what happened in words, without the code."""
    verb = c.e.action.rsplit(".", 1)[-1].replace("_", " ")
    thing = c.e.entity_type.replace("_", " ") or "item"
    return f"{c.actor} made a change ({verb}) to a {thing}"


def sentence(entry, names: Names) -> str:
    c = Ctx(entry, names)
    try:
        text = SENTENCES.get(entry.action, _fallback)(c)
    except Exception:  # noqa: BLE001 - a malformed old payload must not break the log
        text = _fallback(c)
    return re.sub(r"\s+", " ", text).strip().rstrip(".") + "."


# --- readable changes -------------------------------------------------------------------

#: Actions whose old/new values are field-by-field changes worth listing.
DIFF_ACTIONS = {
    "employee.updated",
    "profile.updated",
    "org.team.updated",
    "org.project.updated",
    "task.updated",
    "task.checklist.updated",
    "task.checklist_item.updated",
    "company.settings.updated",
    "workflow.rule.updated",
    "rbac.role.updated",
    "platform.company.updated",
    "platform.plan.updated",
    "time.entry_updated",
    "employee.teams_set",
    "employee.offboarded",
    "employee.deactivated",
    "employee.reactivated",
}
HIDDEN_FIELDS = {"version", "user_role_id", "token_id", "session_id", "invite_id", "sha256"}


def _label(field: str) -> str:
    if field in FIELD_LABELS:
        return FIELD_LABELS[field]
    return field.removesuffix("_id").replace("_", " ").capitalize()


def _value(field: str, value, names: Names) -> str:
    if value is None or value == "" or value == []:
        return "none"
    if value == "[redacted]":
        return "(hidden)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if field == "status":
        return _status(value)
    if field == "week_start" and isinstance(value, int) and 0 <= value < 7:
        return WEEKDAYS[value]
    if field == "estimated_minutes" and isinstance(value, int):
        return _duration(value * 60)
    if field == "team_ids" and isinstance(value, list):
        return _join([names.named.get(("team", str(v)), "a team") for v in value])
    if field == "allowed_roles" and isinstance(value, list):
        return _join([names.role(v) for v in value])
    if isinstance(value, list):
        if all(isinstance(v, str) and UUID_RE.match(v) for v in value):
            return names.user_list(value)
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return "updated"
    text = str(value)
    if UUID_RE.match(text):
        return names.users.get(text, "updated")
    if "T" in text and _parse(text):
        return _when(text)
    return text if len(text) <= 120 else text[:117] + "…"


def changes(entry, names: Names) -> list[dict]:
    """``[{"field", "before", "after"}]`` in words. Empty when the sentence says it all."""
    old = entry.old_value if isinstance(entry.old_value, dict) else {}
    new = entry.new_value if isinstance(entry.new_value, dict) else {}
    if entry.action in ("rbac.role.permissions_set", "rbac.role.created"):
        old = old if entry.action == "rbac.role.permissions_set" else {}
        new = new if entry.action == "rbac.role.permissions_set" else new.get("permissions") or {}
        rows = []
        for code in sorted(set(old) | set(new), key=lambda k: PERMISSIONS.get(k, ("", k))[1]):
            before, after = old.get(code), new.get(code)
            if before == after:
                continue
            rows.append(
                {
                    "field": PERMISSIONS[code][1] if code in PERMISSIONS else "A permission that no longer exists",
                    "before": SCOPES.get(before, "not allowed") if before else "not allowed",
                    "after": SCOPES.get(after, "not allowed") if after else "not allowed",
                }
            )
        return rows
    if entry.action not in DIFF_ACTIONS:
        return []
    rows = []
    for field in [*old, *(k for k in new if k not in old)]:
        if field in HIDDEN_FIELDS or old.get(field) == new.get(field):
            continue
        rows.append(
            {
                "field": _label(field),
                "before": _value(field, old.get(field), names),
                "after": _value(field, new.get(field), names),
            }
        )
    return rows


def describe_entries(entries: Iterable) -> dict[uuid.UUID, dict]:
    """``{entry.id: {"summary": str, "changes": [...]}}`` for a page of entries."""
    entries = list(entries)
    names = Names(entries)
    return {e.pk: {"summary": sentence(e, names), "changes": changes(e, names)} for e in entries}
