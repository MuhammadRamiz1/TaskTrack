"""Platform (super admin) company and plan management, and company settings."""

import django.dispatch
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from django.utils.text import slugify

from apps.audit.services import diff, record, snapshot
from apps.common.exceptions import Conflict, InvalidInput
from apps.rbac import policy

from .models import Company, Plan

#: Sent after a company and its roles exist; later modules seed their defaults
#: (for example the task workflow rules) in receivers.
company_provisioned = django.dispatch.Signal()

SETTINGS_FIELDS = [
    "name",
    "timezone",
    "week_start",
    "working_days",
    "daily_working_minutes",
    "invite_expiry_hours",
    "enforce_2fa",
    "require_assignment_ack",
    "timer_start_moves_to_in_progress",
    "enforce_dependencies",
    "allow_self_review",
    "max_timer_hours",
]
PLATFORM_FIELDS = ["plan", "max_users_override", "max_storage_mb_override", *SETTINGS_FIELDS]


def _unique_slug(name: str) -> str:
    base = slugify(name)[:70] or "company"
    slug, n = base, 2
    while Company.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_company(*, actor, data: dict) -> Company:
    from apps.rbac.services import provision_company_roles

    policy.require(actor, "platform.company.manage")
    data = dict(data)
    slug = data.pop("slug", None) or _unique_slug(data["name"])
    try:
        with transaction.atomic():
            company = Company.objects.create(slug=slug, **data)
    except IntegrityError as exc:
        raise InvalidInput(details={"name": ["A company with this name or slug already exists."]}) from exc
    provision_company_roles(company)
    record(
        actor=actor,
        action="platform.company.created",
        entity=company,
        new_value=snapshot(company, ["name", "slug", "plan", "status"]),
    )
    company_provisioned.send(sender=Company, company=company, actor=actor)
    return company


def update_company(*, actor, company: Company, data: dict) -> Company:
    policy.require(actor, "platform.company.manage")
    fields = [f for f in data if f in PLATFORM_FIELDS]
    before = snapshot(company, fields)
    for field in fields:
        setattr(company, field, data[field])
    try:
        with transaction.atomic():
            company.save()
    except IntegrityError as exc:
        raise InvalidInput(details={"name": ["A company with this name already exists."]}) from exc
    old, new = diff(before, snapshot(company, fields))
    if new:
        record(actor=actor, action="platform.company.updated", entity=company, old_value=old, new_value=new)
    return company


def _end_company_sessions(company: Company, reason: str) -> int:
    from apps.accounts.models import User, UserSession

    now = timezone.now()
    count = UserSession.objects.filter(company=company, revoked_at__isnull=True).update(
        revoked_at=now, revoked_reason=reason
    )
    User.objects.filter(company=company).update(session_version=F("session_version") + 1)
    return count


def suspend(*, actor, company: Company, reason: str) -> Company:
    policy.require(actor, "platform.company.manage")
    if company.status != Company.Status.ACTIVE:
        raise Conflict("Only active companies can be suspended.", code="invalid_company_status")
    company.status = Company.Status.SUSPENDED
    company.suspended_at = timezone.now()
    company.suspended_reason = reason
    company.save(update_fields=["status", "suspended_at", "suspended_reason", "updated_at"])
    revoked = _end_company_sessions(company, "company_suspended")
    record(
        actor=actor,
        action="platform.company.suspended",
        entity=company,
        new_value={"reason": reason, "sessions_revoked": revoked},
    )
    return company


def activate(*, actor, company: Company) -> Company:
    policy.require(actor, "platform.company.manage")
    if company.status == Company.Status.ACTIVE:
        raise Conflict("The company is already active.", code="invalid_company_status")
    old_status = company.status
    company.status = Company.Status.ACTIVE
    company.suspended_at = None
    company.suspended_reason = ""
    company.deleted_at = None
    company.save(update_fields=["status", "suspended_at", "suspended_reason", "deleted_at", "updated_at"])
    record(
        actor=actor,
        action="platform.company.activated",
        entity=company,
        old_value={"status": old_status},
        new_value={"status": company.status},
    )
    return company


def soft_delete(*, actor, company: Company) -> Company:
    policy.require(actor, "platform.company.manage")
    if company.status == Company.Status.DELETED:
        raise Conflict("The company is already deleted.", code="invalid_company_status")
    old_status = company.status
    company.status = Company.Status.DELETED
    company.deleted_at = timezone.now()
    company.save(update_fields=["status", "deleted_at", "updated_at"])
    revoked = _end_company_sessions(company, "company_deleted")
    record(
        actor=actor,
        action="platform.company.deleted",
        entity=company,
        old_value={"status": old_status},
        new_value={"status": company.status, "sessions_revoked": revoked},
    )
    return company


def usage(company: Company) -> dict:
    from apps.accounts.models import User

    counts = User.objects.filter(company=company).aggregate(
        active=Count("pk", filter=Q(status=User.Status.ACTIVE)),
        invited=Count("pk", filter=Q(status=User.Status.INVITED)),
        deactivated=Count("pk", filter=Q(status=User.Status.DEACTIVATED)),
    )
    return {
        "users": counts,
        "max_users": company.max_users,
        "storage_used_bytes": company.storage_used_bytes,
        "max_storage_mb": company.max_storage_mb,
    }


def seats_in_use(company: Company) -> int:
    from apps.accounts.models import User

    return User.objects.filter(company=company, status__in=[User.Status.ACTIVE, User.Status.INVITED]).count()


def update_settings(*, actor, company: Company, data: dict) -> Company:
    policy.require(actor, "company.settings.manage", company)
    fields = [f for f in data if f in SETTINGS_FIELDS]
    before = snapshot(company, fields)
    for field in fields:
        setattr(company, field, data[field])
    try:
        with transaction.atomic():
            company.save()
    except IntegrityError as exc:
        raise InvalidInput(details={"name": ["A company with this name already exists."]}) from exc
    old, new = diff(before, snapshot(company, fields))
    if new:
        record(actor=actor, action="company.settings.updated", entity=company, old_value=old, new_value=new)
    return company


def create_plan(*, actor, data: dict) -> Plan:
    policy.require(actor, "platform.plan.manage")
    try:
        with transaction.atomic():
            plan = Plan.objects.create(**data)
    except IntegrityError as exc:
        raise InvalidInput(details={"code": ["A plan with this code already exists."]}) from exc
    record(
        actor=actor,
        action="platform.plan.created",
        entity=plan,
        company_id=None,
        new_value=snapshot(plan, ["code", "name", "max_users", "max_storage_mb", "features", "is_active"]),
    )
    return plan


def update_plan(*, actor, plan: Plan, data: dict) -> Plan:
    policy.require(actor, "platform.plan.manage")
    fields = list(data)
    before = snapshot(plan, fields)
    for key, value in data.items():
        setattr(plan, key, value)
    plan.save()
    old, new = diff(before, snapshot(plan, fields))
    if new:
        record(actor=actor, action="platform.plan.updated", entity=plan, company_id=None, old_value=old, new_value=new)
    return plan
