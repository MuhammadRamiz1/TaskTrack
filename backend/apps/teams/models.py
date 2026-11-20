from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel
from apps.organizations.models import Organization


class Team(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_teams",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="TeamMembership",
        related_name="teams",
    )
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="teams_team_unique_name_per_org"),
        ]

    def __str__(self):
        return self.name


class TeamMembership(BaseModel):
    class MemberRole(models.TextChoices):
        LEAD = "lead", "Team lead"
        MEMBER = "member", "Member"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
    role = models.CharField(max_length=10, choices=MemberRole.choices, default=MemberRole.MEMBER)
    joined_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["team__name", "user__first_name"]
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="teams_membership_unique_user_per_team"),
        ]

    def __str__(self):
        return f"{self.user} in {self.team}"
