from django.db import models

from apps.accounts.models import default_working_days, validate_timezone
from apps.core.models import BaseModel


class Organization(BaseModel):
    """Organisation-wide settings (PRD FR-17, 22-24, 37, NFR-02, NFR-14)."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)

    # Localisation (NFR-14)
    default_timezone = models.CharField(max_length=64, default="Asia/Karachi", validators=[validate_timezone])
    working_days = models.JSONField(default=default_working_days, help_text="Monday=0 ... Sunday=6.")
    currency = models.CharField(max_length=3, default="PKR")

    # Working hours and overtime (FR-22)
    daily_working_hours = models.DecimalField(max_digits=4, decimal_places=2, default=8)
    overtime_daily_threshold_hours = models.DecimalField(max_digits=4, decimal_places=2, default=8)
    overtime_weekly_threshold_hours = models.DecimalField(max_digits=5, decimal_places=2, default=40)

    # Time tracking policy (FR-17, 23, 24)
    require_manual_entry_approval = models.BooleanField(default=True)
    long_running_timer_hours = models.PositiveSmallIntegerField(default=4)
    idle_detection_enabled = models.BooleanField(default=False)

    # Reminders (FR-37)
    due_soon_reminder_hours = models.PositiveSmallIntegerField(default=24)

    # Security (NFR-02) and data retention (NFR-13)
    enforce_2fa = models.BooleanField(default=False)
    task_data_retention_years = models.PositiveSmallIntegerField(default=5)
    audit_log_retention_years = models.PositiveSmallIntegerField(default=3)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Holiday(BaseModel):
    """Public/company holiday, excluded from available hours (FR-49)."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="holidays")
    date = models.DateField()
    name = models.CharField(max_length=150)

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "date"], name="organizations_holiday_unique_date"),
        ]

    def __str__(self):
        return f"{self.name} ({self.date})"
