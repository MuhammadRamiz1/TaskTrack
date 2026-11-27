"""Read queries for task lists, board, calendar and workload."""

from datetime import date, timedelta

from django.db.models import Case, Count, IntegerField, Q, Sum, Value, When

from apps.accounts.models import User
from apps.org.models import Holiday, LeaveDay
from apps.rbac import policy

from .models import OPEN_STATUSES, Priority, Task

PRIORITY_RANK = Case(
    When(priority=Priority.URGENT, then=Value(4)),
    When(priority=Priority.HIGH, then=Value(3)),
    When(priority=Priority.MEDIUM, then=Value(2)),
    default=Value(1),
    output_field=IntegerField(),
)


def visible_tasks(actor):
    qs = Task.objects.select_related("project", "reviewer", "created_by").prefetch_related("assignees__user")
    return policy.scope_queryset(actor, "task.view", qs).annotate(priority_rank=PRIORITY_RANK)


def week_bounds(company, today: date) -> tuple[date, date]:
    start = today - timedelta(days=(today.weekday() - company.week_start) % 7)
    return start, start + timedelta(days=6)


def workload(actor, start: date, end: date) -> list[dict]:
    company = actor.company
    users = policy.scope_queryset(actor, "task.workload.view", User.objects.filter(status=User.Status.ACTIVE))
    users = list(users.order_by("first_name", "last_name"))
    holidays = set(Holiday.objects.filter(date__range=(start, end)).values_list("date", flat=True))
    work_days = [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() in company.working_days and (start + timedelta(days=i)) not in holidays
    ]
    leave = {}
    for row in LeaveDay.objects.filter(user__in=users, date__in=work_days).values("user_id", "half_day"):
        leave[row["user_id"]] = leave.get(row["user_id"], 0) + (0.5 if row["half_day"] else 1)

    stats = {
        row["assignees__user_id"]: row
        for row in Task.objects.filter(assignees__user__in=users, status__in=OPEN_STATUSES)
        .values("assignees__user_id")
        .annotate(
            open_tasks=Count("pk", distinct=True),
            estimated_minutes=Sum("estimated_minutes"),
            due_in_period=Count("pk", filter=Q(due_date__range=(start, end)), distinct=True),
            overdue=Count("pk", filter=Q(due_date__lt=date.today()), distinct=True),
        )
    }
    result = []
    for user in users:
        s = stats.get(user.pk, {})
        capacity = int((len(work_days) - leave.get(user.pk, 0)) * company.daily_working_minutes)
        estimated = s.get("estimated_minutes") or 0
        result.append(
            {
                "user": user,
                "open_tasks": s.get("open_tasks", 0),
                "estimated_minutes": estimated,
                "due_in_period": s.get("due_in_period", 0),
                "overdue": s.get("overdue", 0),
                "capacity_minutes": max(capacity, 0),
                "leave_days": leave.get(user.pk, 0),
                "load_percent": round(estimated * 100 / capacity) if capacity > 0 else None,
            }
        )
    return result
