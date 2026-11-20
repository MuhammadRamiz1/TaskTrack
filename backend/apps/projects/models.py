from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from apps.core.models import BaseModel
from apps.organizations.models import Organization
from apps.teams.models import Team


class Project(BaseModel):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private (members only)"
        TEAM = "team", "Team"
        ORGANIZATION = "organization", "Organisation"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ON_HOLD = "on_hold", "On hold"
        COMPLETED = "completed", "Completed"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="projects")
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=12, help_text="Short key, unique per organisation (e.g. WEB).")
    description = models.TextField(blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_projects",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="ProjectMembership",
        related_name="projects",
    )
    visibility = models.CharField(max_length=15, choices=Visibility.choices, default=Visibility.TEAM)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    default_estimate_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("code"), "organization", name="projects_project_unique_code_per_org"),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(start_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="projects_project_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.upper()
        super().save(*args, **kwargs)


class ProjectMembership(BaseModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_memberships")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="projects_membership_unique_user_per_project"),
        ]

    def __str__(self):
        return f"{self.user} on {self.project}"
