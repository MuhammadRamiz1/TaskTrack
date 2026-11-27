"""Report exports (async) and scheduled reports."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record
from apps.common.exceptions import Forbidden, InvalidInput, NotFound
from apps.notifications.services import notify
from apps.rbac import policy
from apps.rbac.catalogue import Scope

from . import builders
from .models import ExportFormat, ReportExport, ScheduledReport
from .selectors import Filters, report_rows

logger = structlog.get_logger(__name__)
EXPORT_TTL = timedelta(days=7)
MAX_RANGE_DAYS = 366


def filters_from(data: dict) -> Filters:
    start, end = data["date_from"], data["date_to"]
    if isinstance(start, str):
        start, end = date.fromisoformat(start), date.fromisoformat(end)
    if end < start or (end - start).days > MAX_RANGE_DAYS:
        raise InvalidInput(details={"date_to": [f"The range must be 0 to {MAX_RANGE_DAYS} days."]})
    return Filters(
        date_from=start,
        date_to=end,
        project=data.get("project"),
        team=data.get("team"),
        user=data.get("user"),
        group_by=data.get("group_by", "member"),
        period=data.get("period", "weekly"),
    )


def _plan_allows(company, feature: str) -> bool:
    return bool((company.plan.features or {}).get(feature, False))


def _jsonable_filters(data: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else str(v) if v is not None else None) for k, v in data.items()}


# --- exports ------------------------------------------------------------------------------


def request_export(*, actor, report_type: str, fmt: str, filters: dict) -> ReportExport:
    policy.require(actor, "report.export")
    filters_from(filters)  # validate now so the job cannot fail on input
    if fmt == ExportFormat.PDF and not _plan_allows(actor.company, "reports_pdf"):
        raise Forbidden("PDF export is not included in your plan.", code="plan_feature_unavailable")
    export = ReportExport.objects.create(
        company_id=actor.company_id,
        requested_by=actor,
        report_type=report_type,
        format=fmt,
        filters=_jsonable_filters(filters),
    )
    record(
        actor=actor,
        action="report.export_requested",
        entity=export,
        new_value={"report_type": report_type, "format": fmt, "filters": export.filters},
    )
    from .tasks import generate_export

    export_id, company_id = str(export.pk), str(export.company_id)
    transaction.on_commit(lambda: generate_export.delay(export_id, company_id=company_id))
    return export


def build_file(export: ReportExport) -> tuple[bytes, int]:
    actor = export.requested_by
    columns, rows = report_rows(actor, export.report_type, filters_from(export.filters))
    f = export.filters
    title = f"{export.report_type.title()} report"
    subtitle = (
        f"{actor.company.name} | {f['date_from']} to {f['date_to']} | by {f.get('group_by', 'member')}, "
        f"{f.get('period', 'weekly')} | generated {timezone.now():%Y-%m-%d %H:%M} UTC"
    )
    return builders.render(export.format, columns, rows, title=title, subtitle=subtitle), len(rows)


def generate(export: ReportExport) -> ReportExport:
    """Runs in the worker inside the export's tenant context."""
    ReportExport.objects.filter(pk=export.pk).update(status=ReportExport.State.RUNNING)
    try:
        content, row_count = build_file(export)
        name = f"{export.report_type}-report-{export.filters['date_from']}-{export.filters['date_to']}.{export.format}"
        key = default_storage.save(f"companies/{export.company_id}/exports/{export.pk}/{name}", ContentFile(content))
        export.status = ReportExport.State.READY
        export.storage_key, export.filename = key, name
        export.size_bytes, export.row_count = len(content), row_count
        export.expires_at = timezone.now() + EXPORT_TTL
    except Exception as exc:  # noqa: BLE001 - the requester sees FAILED; details go to logs/Sentry
        logger.exception("report.export_failed", export_id=str(export.pk))
        export.status = ReportExport.State.FAILED
        export.error = "The report could not be generated."[:300]
        if isinstance(exc, InvalidInput):
            export.error = exc.message
    export.finished_at = timezone.now()
    export.save()
    record(
        actor=None,
        action="report.export_finished",
        entity=export,
        new_value={"status": export.status, "rows": export.row_count},
    )
    if export.scheduled_report_id is None:
        notify(
            recipients=[export.requested_by],
            actor=None,
            event_type="report.ready",
            title=f"Your {export.report_type} report is {'ready' if export.status == 'READY' else 'failed'}",
            entity=export,
        )
    return export


def get_export(actor, export_id) -> ReportExport:
    export = ReportExport.objects.filter(pk=export_id, requested_by=actor).first()
    if export is None:
        raise NotFound()
    return export


def open_export(actor, export_id):
    export = get_export(actor, export_id)
    policy.require(actor, "report.export")
    if export.status != ReportExport.State.READY or (export.expires_at and export.expires_at < timezone.now()):
        raise NotFound("The file is not available.")
    return export, default_storage.open(export.storage_key, "rb")


def purge_expired_exports() -> int:
    count = 0
    for export in ReportExport.objects.filter(expires_at__lt=timezone.now()):
        if export.storage_key:
            default_storage.delete(export.storage_key)
        export.delete()
        count += 1
    return count


# --- schedules ------------------------------------------------------------------------------


def next_run(schedule: ScheduledReport, after: datetime) -> datetime:
    tz = ZoneInfo(schedule.company.timezone)
    local = after.astimezone(tz)
    candidate = local.replace(hour=schedule.send_at.hour, minute=schedule.send_at.minute, second=0, microsecond=0)
    if schedule.frequency == ScheduledReport.Frequency.DAILY:
        if candidate <= local:
            candidate += timedelta(days=1)
    elif schedule.frequency == ScheduledReport.Frequency.WEEKLY:
        candidate += timedelta(days=(schedule.weekday - candidate.weekday()) % 7)
        if candidate <= local:
            candidate += timedelta(days=7)
    else:
        day = min(schedule.day_of_month, 28)
        candidate = candidate.replace(day=day)
        if candidate <= local:
            month, year = (candidate.month % 12) + 1, candidate.year + (candidate.month == 12)
            candidate = candidate.replace(year=year, month=month, day=day)
    return candidate.astimezone(ZoneInfo("UTC"))


def period_for(schedule: ScheduledReport, run_at: datetime) -> tuple[date, date]:
    today = run_at.astimezone(ZoneInfo(schedule.company.timezone)).date()
    if schedule.frequency == ScheduledReport.Frequency.DAILY:
        return today - timedelta(days=1), today - timedelta(days=1)
    if schedule.frequency == ScheduledReport.Frequency.WEEKLY:
        return today - timedelta(days=7), today - timedelta(days=1)
    first_this_month = today.replace(day=1)
    last_month_end = first_this_month - timedelta(days=1)
    return last_month_end.replace(day=1), last_month_end


def _validate_recipients(actor, recipient_ids) -> list[str]:
    users = list(User.objects.filter(pk__in=set(recipient_ids), status=User.Status.ACTIVE))
    if len(users) != len(set(recipient_ids)):
        raise InvalidInput(details={"recipient_ids": ["Unknown or inactive employee."]})
    for user in users:
        allowed = user.pk == actor.pk or Scope.COMPANY.value in policy.permissions_for(user).get("report.view", [])
        if not allowed:
            raise InvalidInput(
                details={
                    "recipient_ids": [
                        f"{user.full_name} cannot receive company reports (needs company-wide report access)."
                    ]
                }
            )
    return [str(u.pk) for u in users]


def _schedules_for(actor):
    qs = ScheduledReport.objects.select_related("owner", "company")
    if Scope.COMPANY.value in policy.permissions_for(actor).get("report.schedule", []):
        return qs
    return qs.filter(owner=actor)


def get_schedule(actor, schedule_id) -> ScheduledReport:
    schedule = _schedules_for(actor).filter(pk=schedule_id).first()
    if schedule is None:
        raise NotFound()
    return schedule


def list_schedules(actor):
    return _schedules_for(actor)


SCHEDULE_FIELDS = [
    "name",
    "report_type",
    "filters",
    "format",
    "frequency",
    "send_at",
    "weekday",
    "day_of_month",
    "is_active",
]


def save_schedule(*, actor, data: dict, schedule: ScheduledReport | None = None) -> ScheduledReport:
    policy.require(actor, "report.schedule")
    if not _plan_allows(actor.company, "scheduled_reports"):
        raise Forbidden("Scheduled reports are not included in your plan.", code="plan_feature_unavailable")
    if data.get("format") == ExportFormat.PDF and not _plan_allows(actor.company, "reports_pdf"):
        raise Forbidden("PDF export is not included in your plan.", code="plan_feature_unavailable")
    if "recipient_ids" in data:
        data["recipient_ids"] = _validate_recipients(actor, data["recipient_ids"])
    if "filters" in data:
        data["filters"] = _jsonable_filters(
            {k: v for k, v in data["filters"].items() if k not in ("date_from", "date_to")}
        )
    creating = schedule is None
    old = {} if creating else {k: getattr(schedule, k) for k in data}
    if creating:
        schedule = ScheduledReport(company_id=actor.company_id, owner=actor, next_run_at=timezone.now())
    for key, value in data.items():
        setattr(schedule, key, value)
    schedule.company = actor.company
    schedule.next_run_at = next_run(schedule, timezone.now())
    schedule.save()
    record(
        actor=actor,
        action="report.schedule_created" if creating else "report.schedule_updated",
        entity=schedule,
        old_value=old or None,
        new_value={**data, "next_run_at": schedule.next_run_at},
    )
    return schedule


def delete_schedule(*, actor, schedule: ScheduledReport) -> None:
    policy.require(actor, "report.schedule")
    record(actor=actor, action="report.schedule_deleted", entity=schedule, old_value={"name": schedule.name})
    schedule.delete()


def run_schedule(schedule: ScheduledReport, now: datetime) -> ReportExport | None:
    """Generate and email one scheduled report. Runs inside the company's tenant context."""
    owner = schedule.owner
    if not owner.is_active or not policy.has_perm(owner, "report.schedule"):
        schedule.is_active = False
        schedule.last_error = "Owner is inactive or lost report permissions; schedule paused."
        schedule.save(update_fields=["is_active", "last_error", "updated_at"])
        return None
    start, end = period_for(schedule, now)
    export = ReportExport.objects.create(
        company_id=schedule.company_id,
        requested_by=owner,
        scheduled_report=schedule,
        report_type=schedule.report_type,
        format=schedule.format,
        filters={**schedule.filters, "date_from": start.isoformat(), "date_to": end.isoformat()},
    )
    export = generate(export)
    if export.status == ReportExport.State.READY:
        recipients = list(User.objects.filter(pk__in=schedule.recipient_ids or [owner.pk], status="ACTIVE"))
        content = default_storage.open(export.storage_key, "rb").read()
        for user in recipients:
            context = {
                "first_name": user.first_name,
                "title": schedule.name,
                "filename": export.filename,
                "period": f"{start} to {end}",
                "link": "/reports",
                "product_name": "TaskTrack",
            }
            message = EmailMultiAlternatives(
                subject=render_to_string("email/report_ready.subject.txt", context).strip(),
                body=render_to_string("email/report_ready.txt", context),
                to=[user.email],
            )
            message.attach(export.filename, content, builders.CONTENT_TYPES[export.format])
            message.send()
        schedule.last_error = ""
    else:
        schedule.last_error = export.error
    schedule.last_run_at = now
    schedule.next_run_at = next_run(schedule, now)
    schedule.save(update_fields=["last_run_at", "next_run_at", "last_error", "updated_at"])
    record(
        actor=None,
        action="report.schedule_ran",
        entity=schedule,
        new_value={"export_id": export.pk, "status": export.status, "next_run_at": schedule.next_run_at},
    )
    return export
