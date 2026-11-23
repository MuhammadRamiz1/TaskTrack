"""Read-only aggregates for dashboards and reports.

Every query starts from the policy layer (task.view / time.view scopes), so a report
can never contain rows the requester could not open one by one. Postgres RLS applies
underneath as well.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek

from apps.rbac import policy
from apps.reviews.models import TaskReview
from apps.tasks.models import OPEN_STATUSES, Status, Task, TaskAssignee
from apps.timetracking.models import TimeEntry

TRUNC = {"daily": TruncDay, "weekly": TruncWeek, "monthly": TruncMonth}


@dataclass(frozen=True)
class Filters:
    date_from: date
    date_to: date
    project: object = None
    team: object = None
    user: object = None
    group_by: str = "member"
    period: str = "weekly"


def scoped_tasks(actor, f: Filters):
    qs = policy.scope_queryset(actor, "task.view", Task.objects.all())
    ids = qs.values("pk")
    base = Task.objects.filter(pk__in=ids)
    if f.project:
        base = base.filter(project_id=f.project)
    if f.team:
        base = base.filter(project__team_id=f.team)
    if f.user:
        base = base.filter(assignees__user_id=f.user)
    return base


def scoped_entries(actor, f: Filters):
    qs = policy.scope_queryset(actor, "time.view", TimeEntry.objects.filter(ended_at__isnull=False))
    base = TimeEntry.objects.filter(pk__in=qs.values("pk"), work_date__range=(f.date_from, f.date_to))
    if f.project:
        base = base.filter(task__project_id=f.project)
    if f.team:
        base = base.filter(task__project__team_id=f.team)
    if f.user:
        base = base.filter(user_id=f.user)
    return base


def _hours(seconds) -> float:
    return round((seconds or 0) / 3600, 2)


def _name(first, last) -> str:
    return f"{first} {last}".strip()


# --- dashboards ---------------------------------------------------------------------


def manager_summary(actor, f: Filters) -> dict:
    today = date.today()
    tasks = scoped_tasks(actor, f)
    by_status = {row["status"]: row["n"] for row in tasks.values("status").annotate(n=Count("pk"))}
    overdue = tasks.filter(status__in=OPEN_STATUSES, due_date__lt=today).count()
    completed_in_period = tasks.filter(completed_at__date__range=(f.date_from, f.date_to))

    workload = [
        {
            "user_id": r["user_id"],
            "name": _name(r["user__first_name"], r["user__last_name"]),
            "open_tasks": r["n"],
            "estimated_hours": _hours((r["est"] or 0) * 60),
        }
        for r in TaskAssignee.objects.filter(task__in=tasks.filter(status__in=OPEN_STATUSES))
        .values("user_id", "user__first_name", "user__last_name")
        .annotate(n=Count("task", distinct=True), est=Sum("task__estimated_minutes"))
        .order_by("-n")
    ]

    entries = scoped_entries(actor, f)
    logged = {r["user_id"]: r["s"] for r in entries.values("user_id").annotate(s=Sum("duration_seconds"))}
    productivity = []
    for r in (
        TaskAssignee.objects.filter(task__in=completed_in_period)
        .values("user_id", "user__first_name", "user__last_name")
        .annotate(
            completed=Count("task", distinct=True),
            on_time=Count(
                "task",
                distinct=True,
                filter=Q(task__due_date__isnull=True) | Q(task__completed_at__date__lte=F("task__due_date")),
            ),
        )
        .order_by("-completed")
    ):
        productivity.append(
            {
                "user_id": r["user_id"],
                "name": _name(r["user__first_name"], r["user__last_name"]),
                "completed": r["completed"],
                "on_time_rate": round(r["on_time"] * 100 / r["completed"]) if r["completed"] else None,
                "logged_hours": _hours(logged.get(r["user_id"])),
            }
        )

    projects = [
        {
            "project_id": r["project_id"],
            "key": r["project__key"],
            "name": r["project__name"],
            "total": r["total"],
            "completed": r["done"],
            "percent": round(r["done"] * 100 / r["total"]) if r["total"] else 0,
        }
        for r in tasks.exclude(status=Status.CANCELLED)
        .values("project_id", "project__key", "project__name")
        .annotate(total=Count("pk"), done=Count("pk", filter=Q(status=Status.COMPLETED)))
        .order_by("project__key")
    ]
    time_by_employee = [
        {"user_id": r["user_id"], "name": _name(r["user__first_name"], r["user__last_name"]), "hours": _hours(r["s"])}
        for r in entries.values("user_id", "user__first_name", "user__last_name")
        .annotate(s=Sum("duration_seconds"))
        .order_by("-s")
    ]
    time_by_project = [
        {"project_id": r["task__project_id"], "key": r["task__project__key"], "hours": _hours(r["s"])}
        for r in entries.values("task__project_id", "task__project__key")
        .annotate(s=Sum("duration_seconds"))
        .order_by("-s")
    ]
    return {
        "period": {"from": f.date_from, "to": f.date_to},
        "totals": {
            "total": sum(by_status.values()),
            "backlog": by_status.get(Status.BACKLOG, 0),
            "assigned": by_status.get(Status.ASSIGNED, 0),
            "in_progress": by_status.get(Status.IN_PROGRESS, 0) + by_status.get(Status.REOPENED, 0),
            "pending_review": by_status.get(Status.IN_REVIEW, 0),
            "blocked": by_status.get(Status.BLOCKED, 0),
            "on_hold": by_status.get(Status.ON_HOLD, 0),
            "completed": by_status.get(Status.COMPLETED, 0),
            "cancelled": by_status.get(Status.CANCELLED, 0),
            "overdue": overdue,
            "completed_in_period": completed_in_period.count(),
        },
        "workload": workload,
        "productivity": productivity,
        "project_progress": projects,
        "time_by_employee": time_by_employee,
        "time_by_project": time_by_project,
    }


def member_summary(user) -> dict:
    today = date.today()
    mine = Task.objects.filter(assignees__user=user)
    by_status = {r["status"]: r["n"] for r in mine.values("status").annotate(n=Count("pk"))}
    week_start = today - timedelta(days=(today.weekday() - user.company.week_start) % 7)
    own = TimeEntry.objects.filter(user=user, ended_at__isnull=False)
    changes = TaskReview.objects.filter(
        task__in=mine.filter(status=Status.IN_PROGRESS),
        decision=TaskReview.Decision.CHANGES_REQUESTED,
        round=F("task__review_round"),
    ).count()
    return {
        "by_status": {s: by_status.get(s, 0) for s in Status.values},
        "open": mine.filter(status__in=OPEN_STATUSES).count(),
        "due_soon": mine.filter(status__in=OPEN_STATUSES, due_date__range=(today, today + timedelta(days=7))).count(),
        "overdue": mine.filter(status__in=OPEN_STATUSES, due_date__lt=today).count(),
        "changes_requested": changes,
        "reviews_waiting_for_me": TaskReview.objects.filter(
            reviewer=user, decision=TaskReview.Decision.PENDING
        ).count(),
        "hours_today": _hours(own.filter(work_date=today).aggregate(s=Sum("duration_seconds"))["s"]),
        "hours_this_week": _hours(own.filter(work_date__gte=week_start).aggregate(s=Sum("duration_seconds"))["s"]),
    }


# --- reports ----------------------------------------------------------------------------------

TIME_COLUMNS = ["Group", "Period start", "Hours", "Entries"]
TASK_COLUMNS = ["Group", "Period start", "Created", "Completed", "Completed on time"]

_GROUPS = {
    "time": {
        "member": ("user_id", ("user__first_name", "user__last_name")),
        "project": ("task__project_id", ("task__project__key", "task__project__name")),
        "team": ("task__project__team_id", ("task__project__team__name",)),
    },
    "tasks": {
        "member": ("assignees__user_id", ("assignees__user__first_name", "assignees__user__last_name")),
        "project": ("project_id", ("project__key", "project__name")),
        "team": ("project__team_id", ("project__team__name",)),
    },
}


def _label(row, fields) -> str:
    return " ".join(str(row[x]) for x in fields if row.get(x)).strip() or "Unassigned"


def time_report(actor, f: Filters) -> list[dict]:
    key, label_fields = _GROUPS["time"][f.group_by]
    trunc = TRUNC[f.period]("work_date")
    rows = (
        scoped_entries(actor, f)
        .annotate(bucket=trunc)
        .values(key, *label_fields, "bucket")
        .annotate(seconds=Sum("duration_seconds"), entries=Count("pk"))
        .order_by(*label_fields, "bucket")
    )
    return [
        {
            "group_id": r[key],
            "group": _label(r, label_fields),
            "period_start": r["bucket"],
            "hours": _hours(r["seconds"]),
            "entries": r["entries"],
        }
        for r in rows
    ]


def time_by_task(actor, f: Filters) -> list[dict]:
    """Hours per employee, task and day: who worked on what, and when."""
    rows = (
        scoped_entries(actor, f)
        .values(
            "user_id",
            "user__first_name",
            "user__last_name",
            "task_id",
            "task__number",
            "task__title",
            "task__project__key",
            "work_date",
        )
        .annotate(seconds=Sum("duration_seconds"), entries=Count("pk"))
        .order_by("user__first_name", "user__last_name", "task__project__key", "task__number", "work_date")
    )
    return [
        {
            "user_id": r["user_id"],
            "member": _name(r["user__first_name"], r["user__last_name"]),
            "task_id": r["task_id"],
            "task_key": f"{r['task__project__key']}-{r['task__number']}",
            "task_title": r["task__title"],
            "project_key": r["task__project__key"],
            "work_date": r["work_date"],
            "hours": _hours(r["seconds"]),
            "entries": r["entries"],
        }
        for r in rows
    ]


def task_report(actor, f: Filters) -> list[dict]:
    key, label_fields = _GROUPS["tasks"][f.group_by]
    base = scoped_tasks(actor, f)
    trunc = TRUNC[f.period]
    merged: dict[tuple, dict] = {}

    def bucket(r):
        return (r[key], r["bucket"].date() if hasattr(r["bucket"], "date") else r["bucket"])

    created = (
        base.filter(created_at__date__range=(f.date_from, f.date_to))
        .annotate(bucket=trunc("created_at"))
        .values(key, *label_fields, "bucket")
        .annotate(n=Count("pk", distinct=True))
    )
    for r in created:
        merged.setdefault(bucket(r), {"label": _label(r, label_fields), "created": 0, "completed": 0, "on_time": 0})
        merged[bucket(r)]["created"] = r["n"]
    completed = (
        base.filter(completed_at__date__range=(f.date_from, f.date_to))
        .annotate(bucket=trunc("completed_at"))
        .values(key, *label_fields, "bucket")
        .annotate(
            n=Count("pk", distinct=True),
            on_time=Count(
                "pk", distinct=True, filter=Q(due_date__isnull=True) | Q(completed_at__date__lte=F("due_date"))
            ),
        )
    )
    for r in completed:
        merged.setdefault(bucket(r), {"label": _label(r, label_fields), "created": 0, "completed": 0, "on_time": 0})
        merged[bucket(r)].update(completed=r["n"], on_time=r["on_time"])
    rows = [
        {
            "group_id": gid,
            "group": v["label"],
            "period_start": period,
            "created": v["created"],
            "completed": v["completed"],
            "completed_on_time": v["on_time"],
        }
        for (gid, period), v in merged.items()
    ]
    return sorted(rows, key=lambda r: (r["group"], r["period_start"]))


def report_rows(actor, report_type: str, f: Filters) -> tuple[list[str], list[list]]:
    """Table form used by every export format."""
    if report_type == "time":
        data = time_report(actor, f)
        return TIME_COLUMNS, [[r["group"], r["period_start"], r["hours"], r["entries"]] for r in data]
    data = task_report(actor, f)
    return TASK_COLUMNS, [
        [r["group"], r["period_start"], r["created"], r["completed"], r["completed_on_time"]] for r in data
    ]
