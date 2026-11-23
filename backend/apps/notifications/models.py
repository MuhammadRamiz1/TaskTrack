from django.conf import settings
from django.db import models

from apps.common.models import TenantModel


class Notification(TenantModel):
    """A notification for one recipient. ``show_in_app`` is false when the recipient
    turned off in-app delivery but still wants the email."""

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    event_type = models.CharField(max_length=60)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    entity_type = models.CharField(max_length=40, blank=True)
    entity_id = models.UUIDField(null=True, blank=True)
    show_in_app = models.BooleanField(default=True)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at", "-created_at"], name="notif_recipient_unread")]


class NotificationPreference(TenantModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences"
    )
    event_type = models.CharField(max_length=60)
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "event_type"], name="notif_pref_unique")]
