import uuid

from django.db import models


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Audit log entries are append-only.")

    def delete(self):
        raise PermissionError("Audit log entries are append-only.")


class AuditLogManager(models.Manager.from_queryset(AuditLogQuerySet)):
    """Tenant-aware like TenantManager, but company may be NULL (platform events)."""

    def get_queryset(self):
        from apps.common import tenancy

        qs = super().get_queryset()
        state = tenancy.current()
        if state.mode == tenancy.Mode.TENANT:
            return qs.filter(company_id=state.company_id)
        if state.mode == tenancy.Mode.PLATFORM:
            return qs
        raise tenancy.TenantContextMissing("AuditLog queried without a tenant context.")


class AuditLog(models.Model):
    """Append-only security record of every mutation.

    IDs are stored as plain UUIDs (no foreign keys) so entries outlive the rows they
    describe. A database trigger rejects UPDATE and DELETE, and the runtime role has
    only INSERT and SELECT on this table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    company_id = models.UUIDField(null=True, blank=True)
    actor_id = models.UUIDField(null=True, blank=True)
    actor_email = models.CharField(max_length=254, blank=True)
    impersonator_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=80)
    entity_type = models.CharField(max_length=60, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    objects = AuditLogManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company_id", "-created_at"], name="audit_company_time_idx"),
            models.Index(fields=["entity_type", "entity_id"], name="audit_entity_idx"),
            models.Index(fields=["actor_id", "-created_at"], name="audit_actor_time_idx"),
            models.Index(fields=["action"], name="audit_action_idx"),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.action} {self.entity_type}:{self.entity_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Audit log entries are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit log entries are append-only.")
