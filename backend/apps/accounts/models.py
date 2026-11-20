from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from apps.core.models import BaseModel


class Role(models.TextChoices):
    """Default RBAC roles (PRD section 5)."""

    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Manager / Team Lead"
    MEMBER = "member", "Team Member"
    VIEWER = "viewer", "HR / Management Viewer"


def default_working_days():
    """Mon-Fri, using Python weekday numbers (Monday=0)."""
    return [0, 1, 2, 3, 4]


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValidationError(f"'{value}' is not a valid IANA time zone.")


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", Role.ADMIN)
        if extra_fields["is_staff"] is not True or extra_fields["is_superuser"] is not True:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(max_length=254, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER, db_index=True)
    department = models.CharField(max_length=120, blank=True)
    designation = models.CharField(max_length=120, blank=True)
    manager = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="direct_reports",
        help_text="Primary reporting manager (one per user, per PRD assumptions).",
    )

    timezone = models.CharField(max_length=64, default="Asia/Karachi", validators=[validate_timezone])
    work_start_time = models.TimeField(default=time(9, 0))
    work_end_time = models.TimeField(default=time(18, 0))
    working_days = models.JSONField(
        default=default_working_days,
        blank=True,
        help_text="Weekday numbers worked, Monday=0 ... Sunday=6.",
    )

    # Deactivate instead of deleting so historical reports keep their data (FR-40).
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        ordering = ["first_name", "last_name"]
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        if self.manager_id and self.manager_id == self.id:
            raise ValidationError({"manager": "A user cannot be their own manager."})
        if self.work_end_time <= self.work_start_time:
            raise ValidationError({"work_end_time": "Work end time must be after start time."})

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.first_name

    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_manager(self):
        return self.role == Role.MANAGER

    @property
    def is_viewer(self):
        return self.role == Role.VIEWER
