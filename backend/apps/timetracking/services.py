"""Time tracking: server-side timer and manual entries.

Concurrency: every timer change first locks the user's row (SELECT ... FOR UPDATE), so
two devices starting a timer at the same moment serialise; the partial unique index
``timeentry_one_running_per_user`` is the database backstop. Entries never overlap
(exclusion constraint).

Time belongs to a task and follows the task's status: once the task is in review, completed
or cancelled its entries are locked, and they
open again when the task goes back to work (changes requested, reopened).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record
from apps.common.exceptions import Conflict, Forbidden, InvalidInput, NotFound
from apps.notifications.services import notify
from apps.rbac import policy
from apps.tasks.models import Status, Task, Trigger
from apps.tasks.services import activity
from apps.tasks.services.tasks import get_task
from apps.tasks.workflow import transition_task

from .models import TimeEntry

MAX_ENTRY = timedelta(hours=24)
STARTABLE_VIA_TIMER = {Status.ASSIGNED, Status.REOPENED}
#: Task statuses whose time entries can no longer be added, changed or deleted.
LOCKED_TASK_STATUSES = frozenset({Status.IN_REVIEW, Status.COMPLETED, Status.CANCELLED})


# --- helpers ----------------------------------------------------------------------------


def local_date(user: User, moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(user.timezone or "UTC")).date()


def is_locked(entry: TimeEntry) -> bool:
    """Running entries and entries on tasks in review, completed or cancelled cannot change."""
    return entry.ended_at is None or entry.task.status in LOCKED_TASK_STATUSES


def _ensure_task_open(task: Task) -> None:
    if task.status in LOCKED_TASK_STATUSES:
        raise Conflict(
            f"{task.key} is {task.get_status_display().lower()}; its time can no longer change.",
            code="task_locked",
            details={"status": task.status},
        )


def _lock_user(user: User) -> None:
    User.objects.select_for_update().filter(pk=user.pk).exists()


def _running(user: User) -> TimeEntry | None:
    return TimeEntry.objects.select_for_update().filter(user=user, ended_at__isnull=True).first()


def _require_assignee(actor: User, task: Task) -> None:
    policy.require(actor, "time.track")
    if not task.assignees.filter(user=actor).exists():
        raise Forbidden("You can only log time on tasks assigned to you.", code="not_assignee")


def _close(entry: TimeEntry, at: datetime, reason: str) -> TimeEntry:
    at = max(at, entry.started_at + timedelta(microseconds=1))  # end must be after start
    entry.ended_at = at
    entry.duration_seconds = int((at - entry.started_at).total_seconds())
    entry.status = TimeEntry.Status.DRAFT
    entry.version += 1
    entry.save(update_fields=["ended_at", "duration_seconds", "status", "version", "updated_at"])
    task = entry.task
    activity.log(task, entry.user, "time_logged", {"minutes": entry.duration_seconds // 60, "reason": reason})
    return entry


# --- timer ------------------------------------------------------------------------------


def current_timer(user: User) -> TimeEntry | None:
    return TimeEntry.objects.filter(user=user, ended_at__isnull=True).select_related("task__project").first()


def start_timer(*, actor: User, task_id) -> TimeEntry:
    with transaction.atomic():
        _lock_user(actor)
        running = _running(actor)
        if running is not None:
            raise Conflict(
                "A timer is already running. Stop it or switch tasks.",
                code="timer_already_running",
                details={"entry_id": str(running.pk), "task_id": str(running.task_id)},
            )
        task = get_task(actor, task_id)
        _require_assignee(actor, task)
        if task.status in STARTABLE_VIA_TIMER and task.company.timer_start_moves_to_in_progress:
            transition_task(actor=actor, task_id=task.pk, to_status=Status.IN_PROGRESS, trigger=Trigger.TIMER)
            task.refresh_from_db()
        if task.status != Status.IN_PROGRESS:
            raise Conflict(
                "Timers can only run on tasks in progress.",
                code="task_not_in_progress",
                details={"status": task.status},
            )
        now = timezone.now()
        try:
            with transaction.atomic():
                entry = TimeEntry.objects.create(
                    company_id=actor.company_id,
                    user=actor,
                    task=task,
                    started_at=now,
                    work_date=local_date(actor, now),
                    source=TimeEntry.Source.TIMER,
                    status=TimeEntry.Status.RUNNING,
                )
        except IntegrityError as exc:
            if "timeentry_no_overlap" in str(exc):
                raise Conflict("This overlaps another time entry of yours.", code="time_overlap") from exc
            # Concurrent start from another device; the partial unique index caught it.
            raise Conflict("A timer is already running.", code="timer_already_running") from exc
        record(actor=actor, action="time.timer_started", entity=entry, new_value={"task": task.key})
        return entry


def stop_timer(*, actor: User, note: str = "", reason: str = "stopped") -> TimeEntry:
    with transaction.atomic():
        _lock_user(actor)
        entry = _running(actor)
        if entry is None:
            raise Conflict("No timer is running.", code="no_running_timer")
        if note:
            entry.note = note
            entry.save(update_fields=["note", "updated_at"])
        _close(entry, timezone.now(), reason)
        record(
            actor=actor,
            action=f"time.timer_{reason}",
            entity=entry,
            new_value={"duration_seconds": entry.duration_seconds, "task_id": entry.task_id},
        )
        return entry


def pause_timer(*, actor: User) -> TimeEntry:
    return stop_timer(actor=actor, reason="paused")


def resume_timer(*, actor: User) -> TimeEntry:
    last = (
        TimeEntry.objects.filter(user=actor, source=TimeEntry.Source.TIMER, ended_at__isnull=False)
        .order_by("-ended_at")
        .first()
    )
    if last is None:
        raise Conflict("There is no paused timer to resume.", code="nothing_to_resume")
    return start_timer(actor=actor, task_id=last.task_id)


def switch_timer(*, actor: User, task_id) -> TimeEntry:
    with transaction.atomic():
        if current_timer(actor) is not None:
            stop_timer(actor=actor, reason="switched")
        return start_timer(actor=actor, task_id=task_id)


def stop_timers_on_task(task: Task, *, user: User | None = None, reason: str) -> int:
    """Close running timers on ``task`` (optionally only ``user``'s). Used by signal receivers."""
    qs = TimeEntry.objects.select_for_update().filter(task=task, ended_at__isnull=True).select_related("user")
    if user is not None:
        qs = qs.filter(user=user)
    stopped = 0
    for entry in qs:
        _close(entry, timezone.now(), reason)
        record(
            actor=None,
            action="time.timer_auto_stopped",
            entity=entry,
            new_value={"reason": reason, "duration_seconds": entry.duration_seconds},
        )
        notify(
            recipients=[entry.user],
            actor=None,
            event_type="time.timer_stopped",
            title=f"Your timer on {task.key} was stopped",
            body=reason.replace("_", " "),
            entity=task,
        )
        stopped += 1
    return stopped


def stop_runaway_timers() -> int:
    """Close timers running longer than the company limit (called per company by beat)."""
    stopped = 0
    for entry in (
        TimeEntry.objects.select_for_update()
        .filter(ended_at__isnull=True)
        .select_related("company", "user", "task__project")
    ):
        limit = timedelta(hours=entry.company.max_timer_hours)
        if timezone.now() - entry.started_at > limit:
            _close(entry, entry.started_at + limit, "max_duration_reached")
            record(
                actor=None, action="time.timer_auto_stopped", entity=entry, new_value={"reason": "max_duration_reached"}
            )
            notify(
                recipients=[entry.user],
                actor=None,
                event_type="time.timer_stopped",
                title=f"Your timer on {entry.task.key} was stopped after {entry.company.max_timer_hours} hours",
                body="Edit the entry if the time is wrong.",
                entity=entry.task,
            )
            stopped += 1
    return stopped


# --- manual entries -------------------------------------------------------------------------


def _validate_range(user: User, started_at: datetime, ended_at: datetime) -> None:
    if ended_at <= started_at:
        raise InvalidInput(details={"ended_at": ["End must be after start."]})
    if ended_at - started_at > MAX_ENTRY:
        raise InvalidInput(details={"ended_at": ["An entry can cover at most 24 hours."]})
    if ended_at > timezone.now() + timedelta(minutes=1):
        raise InvalidInput(details={"ended_at": ["Time cannot be logged in the future."]})


def _save_entry(entry: TimeEntry) -> TimeEntry:
    try:
        with transaction.atomic():
            entry.save()
    except IntegrityError as exc:
        raise Conflict("This overlaps another time entry of yours.", code="time_overlap") from exc
    return entry


def create_manual(*, actor: User, task_id, started_at: datetime, ended_at: datetime, note: str = "") -> TimeEntry:
    with transaction.atomic():
        task = get_task(actor, task_id)
        _require_assignee(actor, task)
        _ensure_task_open(task)
        _validate_range(actor, started_at, ended_at)
        day = local_date(actor, started_at)
        entry = _save_entry(
            TimeEntry(
                company_id=actor.company_id,
                user=actor,
                task=task,
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=int((ended_at - started_at).total_seconds()),
                work_date=day,
                source=TimeEntry.Source.MANUAL,
                status=TimeEntry.Status.DRAFT,
                note=note,
            )
        )
        activity.log(task, actor, "time_logged", {"minutes": entry.duration_seconds // 60, "reason": "manual"})
        record(
            actor=actor,
            action="time.entry_created",
            entity=entry,
            new_value={"task": task.key, "started_at": started_at, "ended_at": ended_at, "note": note},
        )
        return entry


def get_entry(actor: User, entry_id) -> TimeEntry:
    entry = TimeEntry.objects.filter(pk=entry_id).select_related("task__project", "user").first()
    if entry is None or not policy.can(actor, "time.view", entry):
        raise NotFound()
    return entry


def _require_editable(actor: User, entry: TimeEntry) -> None:
    if entry.user_id != actor.pk:
        policy.require(actor, "time.edit_others", entry, view_code="time.view")
    else:
        policy.require(actor, "time.track")
    if entry.ended_at is None:
        raise Conflict("Stop the timer before changing this entry.", code="timer_running")
    _ensure_task_open(entry.task)


def update_entry(*, actor: User, entry_id, data: dict, expected_version: int) -> TimeEntry:
    with transaction.atomic():
        entry = get_entry(actor, entry_id)
        entry = TimeEntry.objects.select_for_update().select_related("task", "user").get(pk=entry.pk)
        _require_editable(actor, entry)
        if expected_version != entry.version:
            raise Conflict(
                "The entry was changed elsewhere. Reload and try again.",
                code="version_conflict",
                details={"current_version": entry.version},
            )
        old = {"started_at": entry.started_at, "ended_at": entry.ended_at, "note": entry.note}
        started = data.get("started_at", entry.started_at)
        ended = data.get("ended_at", entry.ended_at)
        _validate_range(entry.user, started, ended)
        entry.started_at, entry.ended_at = started, ended
        entry.duration_seconds = int((ended - started).total_seconds())
        entry.work_date = local_date(entry.user, started)
        entry.note = data.get("note", entry.note)
        entry.version += 1
        _save_entry(entry)
        record(
            actor=actor,
            action="time.entry_updated",
            entity=entry,
            old_value=old,
            new_value={"started_at": started, "ended_at": ended, "note": entry.note},
        )
        return entry


def delete_entry(*, actor: User, entry_id) -> None:
    with transaction.atomic():
        entry = get_entry(actor, entry_id)
        _require_editable(actor, entry)
        record(
            actor=actor,
            action="time.entry_deleted",
            entity=entry,
            old_value={"task_id": entry.task_id, "started_at": entry.started_at, "ended_at": entry.ended_at},
        )
        entry.delete()
