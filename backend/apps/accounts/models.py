from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.common import tenancy
from apps.common.models import BaseModel, TenantModel


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ValidationError(f"'{value}' is not a valid IANA time zone.") from exc


class _AccountScopedManagerMixin:
    """Tenant-aware manager for account tables whose company may be NULL (super admin).
    AUTH mode is allowed (read-only lookups by email or token hash)."""

    def get_queryset(self):
        qs = super().get_queryset()
        state = tenancy.current()
        if state.mode == tenancy.Mode.TENANT:
            return qs.filter(company_id=state.company_id)
        if state.mode in (tenancy.Mode.PLATFORM, tenancy.Mode.AUTH):
            return qs
        raise tenancy.TenantContextMissing(f"{self.model.__name__} queried without a tenant context.")


class AccountScopedManager(_AccountScopedManagerMixin, models.Manager):
    pass


class UserManager(_AccountScopedManagerMixin, BaseUserManager):
    use_in_migrations = False

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)

    def create_user(self, email, password=None, **fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **fields):
        fields.update(is_platform_admin=True, company=None, status=User.Status.ACTIVE)
        return self.create_user(email, password, **fields)


class User(BaseModel, AbstractBaseUser):
    """Email-login account. ``company`` is NULL only for platform super admins."""

    class Status(models.TextChoices):
        INVITED = "INVITED", "Invited"
        ACTIVE = "ACTIVE", "Active"
        DEACTIVATED = "DEACTIVATED", "Deactivated"

    company = models.ForeignKey(
        "companies.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    email = models.EmailField(max_length=254)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    timezone = models.CharField(max_length=64, default="UTC", validators=[validate_timezone])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.INVITED)
    is_platform_admin = models.BooleanField(default=False)
    manager = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="direct_reports")

    must_change_password = models.BooleanField(default=False)
    session_version = models.PositiveIntegerField(default=1)
    rbac_version = models.PositiveIntegerField(default=1)
    failed_login_count = models.PositiveIntegerField(default=0)
    lockout_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)

    totp_secret_enc = models.BinaryField(null=True, blank=True, editable=False)
    totp_enabled = models.BooleanField(default=False)

    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    class Meta:
        ordering = ["first_name", "last_name"]
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
            models.CheckConstraint(
                condition=models.Q(is_platform_admin=True, company__isnull=True)
                | models.Q(is_platform_admin=False, company__isnull=False),
                name="accounts_user_platform_admin_has_no_company",
            ),
        ]
        indexes = [models.Index(fields=["company", "status"], name="accounts_user_company_status")]

    def __str__(self):
        return self.email

    # ``is_active`` is what Django and DRF consult.
    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())


class _OneTimeToken(models.Model):
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def state(self) -> str:
        if self.used_at:
            return "used"
        if self.revoked_at:
            return "revoked"
        if self.expires_at <= timezone.now():
            return "expired"
        return "valid"


class InviteToken(TenantModel, _OneTimeToken):
    """One-time sign-up link. Only the SHA-256 of the token is stored."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="invites")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    send_count = models.PositiveIntegerField(default=1)

    objects = AccountScopedManager()  # AUTH mode may look up by token hash

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(used_at__isnull=True, revoked_at__isnull=True),
                name="accounts_invite_one_open_per_user",
            )
        ]


class PasswordResetToken(BaseModel, _OneTimeToken):
    class Origin(models.TextChoices):
        SELF = "SELF", "Self-service"
        HR = "HR", "Sent by HR"

    company = models.ForeignKey("companies.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_tokens")
    origin = models.CharField(max_length=4, choices=Origin.choices)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    objects = AccountScopedManager()

    class Meta:
        ordering = ["-created_at"]


class UserSession(BaseModel):
    """One refresh-token family (one browser/device sign-in)."""

    company = models.ForeignKey("companies.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    refresh_jti = models.CharField(max_length=64)
    user_agent = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    last_used_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=40, blank=True)

    objects = AccountScopedManager()

    class Meta:
        ordering = ["-last_used_at"]
        indexes = [models.Index(fields=["user", "revoked_at"], name="accounts_session_user_active")]

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()


class RecoveryCode(BaseModel):
    company = models.ForeignKey("companies.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)

    objects = AccountScopedManager()


class ImpersonationSession(TenantModel):
    """A super admin viewing a company as one of its users (read-only, time-boxed)."""

    super_admin = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    target_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField()
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_active(self) -> bool:
        return self.ended_at is None and self.expires_at > timezone.now()
