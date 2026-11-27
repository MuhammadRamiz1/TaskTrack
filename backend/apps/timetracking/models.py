from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models
from django.db.models import Func

from apps.common.models import TenantModel


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = models.DateTimeField()  # only used inside the exclusion constraint


class Timesheet(TenantModel):
    """One user's time for one week (week start from company settings)."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="timesheets")
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    total_seconds = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-period_start"]
        constraints = [models.UniqueConstraint(fields=["user", "period_start"], name="timesheet_user_week_unique")]

    @property
    def is_locked(self) -> bool:
        return self.status in (self.Status.SUBMITTED, self.Status.APPROVED)


class TimeEntry(TenantModel):
    class Source(models.TextChoices):
        TIMER = "TIMER", "Timer"
        MANUAL = "MANUAL", "Manual"

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="time_entries")
    task = models.ForeignKey("tasks.Task", on_delete=models.PROTECT, related_name="time_entries")
    timesheet = models.ForeignKey(Timesheet, null=True, blank=True, on_delete=models.SET_NULL, related_name="entries")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    work_date = models.DateField(help_text="Start date in the user's time zone.")
    source = models.CharField(max_length=6, choices=Source.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    note = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            # One running timer per user, enforced by the database.
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(ended_at__isnull=True), name="timeentry_one_running_per_user"
            ),
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True) | models.Q(ended_at__gt=models.F("started_at")),
                name="timeentry_end_after_start",
            ),
            # A person cannot be in two places at once: no overlapping entries per user.
            ExclusionConstraint(
                name="timeentry_no_overlap",
                expressions=[
                    ("user", RangeOperators.EQUAL),
                    (TsTzRange("started_at", "ended_at"), RangeOperators.OVERLAPS),
                ],
            ),
        ]
        indexes = [
            models.Index(fields=["user", "work_date"], name="timeentry_user_date"),
            models.Index(fields=["company", "work_date"], name="timeentry_company_date"),
            models.Index(fields=["task"], name="timeentry_task"),
        ]


class TimesheetApproval(TenantModel):
    """Append-only approval decisions (separate from task review)."""

    class Decision(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    timesheet = models.ForeignKey(Timesheet, on_delete=models.CASCADE, related_name="approvals")
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decision = models.CharField(max_length=8, choices=Decision.choices)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
