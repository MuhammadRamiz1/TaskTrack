from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import BaseModel


class ImmutableError(Exception):
    """Raised on any attempt to modify or delete audit records."""


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableError("Audit log entries cannot be updated.")

    def delete(self):
        raise ImmutableError("Audit log entries cannot be deleted.")


class AuditLog(BaseModel):
    """Append-only record of who did what and when (FR-52, FR-53)."""

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        ASSIGN = "assign", "Assign"
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        ROLE_CHANGE = "role_change", "Role change"
        SETTING_CHANGE = "setting_change", "Setting change"
        LOGIN = "login", "Login"
        OTHER = "other", "Other"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    actor_email = models.EmailField(blank=True, help_text="Kept even if the user is later removed.")
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)

    changes = models.JSONField(default=dict, blank=True, help_text='{"field": {"old": ..., "new": ...}}')
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"], name="audit_target_idx"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_time_idx"),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_email or 'system'} {self.action} {self.object_repr}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableError("Audit log entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableError("Audit log entries cannot be deleted.")
