import uuid

from django.db import models

from . import tenancy


class BaseModel(models.Model):
    """UUID primary key plus created/updated timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    pass


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Default manager for tenant-owned models.

    Filters by the active company in TENANT mode, returns everything in PLATFORM mode
    and raises otherwise, so a missing context is a loud bug instead of a data leak.
    Postgres RLS enforces the same rule independently.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        state = tenancy.current()
        if state.mode == tenancy.Mode.TENANT:
            return qs.filter(company_id=state.company_id)
        if state.mode == tenancy.Mode.PLATFORM:
            return qs
        raise tenancy.TenantContextMissing(f"{self.model.__name__} queried without a tenant context ({state.mode}).")


class TenantModel(BaseModel):
    """Abstract base for every tenant-owned table. Each concrete subclass must enable
    RLS in its migration with ``apps.common.rls.tenant_rls(<table>)``."""

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT, related_name="+", db_index=True)

    objects = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.company_id is None:
            company_id = tenancy.current_company_id()
            if company_id is None:
                raise tenancy.TenantContextMissing(f"{type(self).__name__} saved without company and tenant context.")
            self.company_id = company_id
        super().save(*args, **kwargs)
