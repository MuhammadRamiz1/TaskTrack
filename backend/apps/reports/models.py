from django.conf import settings
from django.db import models

from apps.common.models import TenantModel


class ReportType(models.TextChoices):
    TASKS = "tasks", "Tasks"
    TIME = "time", "Time"


class ExportFormat(models.TextChoices):
    CSV = "csv", "CSV"
    XLSX = "xlsx", "Excel"
    PDF = "pdf", "PDF"


class ScheduledReport(TenantModel):
    class Frequency(models.TextChoices):
        DAILY = "DAILY", "Daily"
        WEEKLY = "WEEKLY", "Weekly"
        MONTHLY = "MONTHLY", "Monthly"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scheduled_reports")
    name = models.CharField(max_length=120)
    report_type = models.CharField(max_length=10, choices=ReportType.choices)
    filters = models.JSONField(default=dict, blank=True, help_text="group_by, period, project, team, user")
    format = models.CharField(max_length=5, choices=ExportFormat.choices, default=ExportFormat.XLSX)
    frequency = models.CharField(max_length=8, choices=Frequency.choices)
    send_at = models.TimeField(help_text="Local time in the company time zone.")
    weekday = models.PositiveSmallIntegerField(default=0, help_text="0=Monday; used for WEEKLY")
    day_of_month = models.PositiveSmallIntegerField(default=1, help_text="1-28; used for MONTHLY")
    # User ids (validated on write). A JSON list keeps every row tenant-scoped; an M2M
    # join table would have no company column for RLS.
    recipient_ids = models.JSONField(default=list, blank=True)
    next_run_at = models.DateTimeField()
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active", "next_run_at"], name="schedrep_due")]


class ReportExport(TenantModel):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="report_exports")
    scheduled_report = models.ForeignKey(
        ScheduledReport, null=True, blank=True, on_delete=models.SET_NULL, related_name="exports"
    )
    report_type = models.CharField(max_length=10, choices=ReportType.choices)
    format = models.CharField(max_length=5, choices=ExportFormat.choices)
    filters = models.JSONField(default=dict)
    status = models.CharField(max_length=8, choices=State.choices, default=State.QUEUED)
    storage_key = models.CharField(max_length=500, blank=True)
    filename = models.CharField(max_length=200, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    row_count = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
