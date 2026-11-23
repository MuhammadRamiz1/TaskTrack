import structlog
from celery import shared_task
from django.utils import timezone

from apps.common import tenancy
from apps.common.tasks import TenantTask

logger = structlog.get_logger(__name__)


@shared_task(name="reports.generate_export", base=TenantTask, bind=True)
def generate_export(self, export_id: str, *, company_id: str) -> str:
    from .models import ReportExport
    from .services import generate

    export = ReportExport.objects.select_related("requested_by__company").filter(pk=export_id).first()
    if export is None or export.status != ReportExport.State.QUEUED:
        return "skipped"
    return generate(export).status


@shared_task(name="reports.dispatch_scheduled_reports")
def dispatch_scheduled_reports() -> int:
    """Beat job (every 15 minutes): run every schedule whose next_run_at has passed."""
    from .models import ScheduledReport
    from .services import run_schedule

    now = timezone.now()
    with tenancy.platform_context():
        due = list(
            ScheduledReport.objects.filter(is_active=True, next_run_at__lte=now, company__status="ACTIVE").values_list(
                "pk", "company_id"
            )
        )
    ran = 0
    for schedule_id, company_id in due:
        try:
            with tenancy.tenant_context(company_id):
                schedule = ScheduledReport.objects.select_related("owner__company", "company").get(pk=schedule_id)
                run_schedule(schedule, now)
                ran += 1
        except Exception:  # noqa: BLE001 - one broken schedule must not stop the others
            logger.exception("report.schedule_failed", schedule_id=str(schedule_id))
    return ran


@shared_task(name="reports.purge_expired_exports")
def purge_expired_exports() -> int:
    from .services import purge_expired_exports as purge

    with tenancy.platform_context():
        return purge()
