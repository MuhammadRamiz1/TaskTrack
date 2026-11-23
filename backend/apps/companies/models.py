from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower

from apps.common import tenancy
from apps.common.models import BaseModel


def default_working_days():
    return [0, 1, 2, 3, 4]  # Monday=0 ... Sunday=6


def default_features():
    return {"reports_pdf": True, "scheduled_reports": True}


class Plan(BaseModel):
    """Subscription plan with default limits. Platform-managed, not tenant data."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=100)
    max_users = models.PositiveIntegerField(default=25)
    max_storage_mb = models.PositiveIntegerField(default=5120)
    features = models.JSONField(default=default_features, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["max_users", "name"]

    def __str__(self):
        return self.name


class CompanyManager(models.Manager):
    """A company user sees only their own company; platform context sees all."""

    def get_queryset(self):
        qs = super().get_queryset()
        state = tenancy.current()
        if state.mode == tenancy.Mode.TENANT:
            return qs.filter(id=state.company_id)
        if state.mode == tenancy.Mode.PLATFORM:
            return qs
        raise tenancy.TenantContextMissing("Company queried without a tenant context.")


class Company(BaseModel):
    """A tenant. Settings that drive workflow and security live here."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        DELETED = "DELETED", "Deleted"

    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="companies")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    max_users_override = models.PositiveIntegerField(null=True, blank=True)
    max_storage_mb_override = models.PositiveIntegerField(null=True, blank=True)
    storage_used_bytes = models.BigIntegerField(default=0)

    # Localisation
    timezone = models.CharField(max_length=64, default="UTC")
    week_start = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(6)])
    working_days = models.JSONField(default=default_working_days)
    daily_working_minutes = models.PositiveIntegerField(default=480)

    # Security and onboarding
    invite_expiry_hours = models.PositiveIntegerField(
        default=48, validators=[MinValueValidator(1), MaxValueValidator(720)]
    )
    enforce_2fa = models.BooleanField(default=False)

    # Workflow
    require_assignment_ack = models.BooleanField(default=False)
    timer_start_moves_to_in_progress = models.BooleanField(default=True)
    enforce_dependencies = models.BooleanField(default=True)
    allow_self_review = models.BooleanField(default=False)
    max_timer_hours = models.PositiveSmallIntegerField(
        default=12, validators=[MinValueValidator(1), MaxValueValidator(24)]
    )

    rbac_version = models.PositiveIntegerField(default=1)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_reason = models.TextField(blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = CompanyManager()

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"
        constraints = [
            models.UniqueConstraint(Lower("name"), name="companies_company_name_ci_unique"),
            models.CheckConstraint(
                condition=models.Q(storage_used_bytes__gte=0), name="companies_storage_non_negative"
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    @property
    def max_users(self) -> int:
        return self.max_users_override if self.max_users_override is not None else self.plan.max_users

    @property
    def max_storage_mb(self) -> int:
        return self.max_storage_mb_override if self.max_storage_mb_override is not None else self.plan.max_storage_mb
