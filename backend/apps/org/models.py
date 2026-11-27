from django.conf import settings
from django.db import models
from django.db.models.functions import Lower, Upper
from django.utils import timezone

from apps.common.models import TenantModel


class Team(TenantModel):
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="led_teams"
    )
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint("company", Lower("name"), name="org_team_name_ci_unique")]

    def __str__(self):
        return self.name


class TeamMember(TenantModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "user"], name="org_teammember_unique")]
        indexes = [models.Index(fields=["user"], name="org_teammember_user")]


class Project(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ON_HOLD = "ON_HOLD", "On hold"
        COMPLETED = "COMPLETED", "Completed"
        ARCHIVED = "ARCHIVED", "Archived"

    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="projects")
    key = models.CharField(max_length=10, help_text="Short code used in task keys, e.g. WEB for WEB-42.")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_projects"
    )
    task_seq = models.PositiveIntegerField(default=0)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint("company", Upper("key"), name="org_project_key_ci_unique"),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(start_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="org_project_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.key} {self.name}"

    def save(self, *args, **kwargs):
        self.key = (self.key or "").upper()
        super().save(*args, **kwargs)

    @property
    def is_archived(self) -> bool:
        return self.status == self.Status.ARCHIVED


class ProjectMember(TenantModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_memberships")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "user"], name="org_projectmember_unique")]
        indexes = [models.Index(fields=["user"], name="org_projectmember_user")]


class LeaveDay(TenantModel):
    class Kind(models.TextChoices):
        ANNUAL = "ANNUAL", "Annual"
        SICK = "SICK", "Sick"
        UNPAID = "UNPAID", "Unpaid"
        OTHER = "OTHER", "Other"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_days")
    date = models.DateField()
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.ANNUAL)
    half_day = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["user", "date"], name="org_leaveday_unique")]


class Holiday(TenantModel):
    date = models.DateField()
    name = models.CharField(max_length=150)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["company", "date"], name="org_holiday_unique_date")]

    def __str__(self):
        return f"{self.name} ({self.date})"
