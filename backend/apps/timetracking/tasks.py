from celery import shared_task

from apps.common import tenancy


@shared_task(name="timetracking.stop_runaway_timers")
def stop_runaway_timers() -> int:
    """Beat job: close timers that ran past the company's max_timer_hours."""
    from .services import stop_runaway_timers as run

    with tenancy.platform_context():
        return run()


@shared_task(name="timetracking.remind_timesheet_submission")
def remind_timesheet_submission() -> int:
    """Daily: on the first day of a company's week, remind people with logged but
    unsubmitted time from the previous week."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from django.utils import timezone

    from apps.companies.models import Company
    from apps.notifications.services import notify

    from .models import Timesheet

    sent = 0
    with tenancy.platform_context():
        companies = list(
            Company.objects.filter(status=Company.Status.ACTIVE).values_list("pk", "timezone", "week_start")
        )
    for company_id, tz, week_start in companies:
        today = timezone.now().astimezone(ZoneInfo(tz)).date()
        if today.weekday() != week_start:
            continue
        last_week = today - timedelta(days=7)
        with tenancy.tenant_context(company_id):
            sheets = Timesheet.objects.filter(
                period_start=last_week,
                status__in=[Timesheet.Status.OPEN, Timesheet.Status.REJECTED],
                total_seconds__gt=0,
            ).select_related("user")
            for sheet in sheets:
                sent += notify(
                    recipients=[sheet.user],
                    actor=None,
                    event_type="timesheet.reminder",
                    title=f"Submit your timesheet for the week of {sheet.period_start}",
                    body="Your logged time is waiting to be submitted for approval.",
                    entity=sheet,
                )
    return sent
