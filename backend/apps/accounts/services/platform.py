"""Super admin actions on accounts: first company admin, impersonation, super admin creation."""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record
from apps.common.exceptions import Conflict, InvalidInput, NotFound
from apps.rbac import policy
from apps.rbac import services as rbac_services
from apps.rbac.catalogue import RoleKey
from apps.rbac.models import Role

from .. import tokens
from ..models import ImpersonationSession, User
from . import invites

FIRST_ADMIN_ROLES = (RoleKey.HR, RoleKey.COMPANY_ADMIN)


def create_company_admin(*, actor: User, company, data: dict) -> User:
    """Create a company's HR or Company Admin account and email the invite."""
    from apps.companies.services import seats_in_use

    policy.require(actor, "platform.company_admin.invite")
    if not company.is_active:
        raise Conflict("The company is not active.", code="invalid_company_status")
    if seats_in_use(company) >= company.max_users:
        raise Conflict("The company has reached its user limit.", code="user_limit_exceeded")
    role = Role.objects.get(company=company, key=data["role"])
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=data["email"],
                company=company,
                first_name=data["first_name"],
                last_name=data.get("last_name", ""),
                job_title=data.get("job_title", ""),
                timezone=company.timezone,
                status=User.Status.INVITED,
            )
    except IntegrityError as exc:
        raise InvalidInput(details={"email": ["This email address cannot be used."]}) from exc
    rbac_services.grant(actor=actor, user=user, role=role, check_policy=False)
    record(
        actor=actor,
        action="platform.company_admin.created",
        entity=user,
        company_id=company.pk,
        new_value={"email": user.email, "role": role.key},
    )
    invites.issue(actor=actor, user=user)
    return user


def start_impersonation(*, actor: User, target_user_id, reason: str) -> tuple[ImpersonationSession, str]:
    policy.require(actor, "platform.impersonate")
    target = User.objects.select_related("company").filter(pk=target_user_id, is_platform_admin=False).first()
    if target is None:
        raise NotFound()
    if not target.is_active or not target.company.is_active:
        raise Conflict("Only active users of active companies can be impersonated.", code="target_not_active")
    session = ImpersonationSession.objects.create(
        company_id=target.company_id,
        super_admin=actor,
        target_user=target,
        reason=reason,
        expires_at=timezone.now() + timedelta(minutes=settings.IMPERSONATION_MINUTES),
    )
    record(
        actor=actor,
        action="platform.impersonation.started",
        entity=session,
        company_id=target.company_id,
        new_value={"target_user_id": target.pk, "reason": reason, "expires_at": session.expires_at},
    )
    return session, tokens.issue_access(target, impersonation=session)


def end_impersonation(*, actor: User, session_id) -> ImpersonationSession:
    policy.require(actor, "platform.impersonate")
    session = ImpersonationSession.objects.filter(pk=session_id, super_admin=actor).first()
    if session is None:
        raise NotFound()
    if session.ended_at is None:
        session.ended_at = timezone.now()
        session.save(update_fields=["ended_at", "updated_at"])
        record(actor=actor, action="platform.impersonation.ended", entity=session, company_id=session.company_id)
    return session


def create_super_admin(*, email: str, password: str, first_name: str, last_name: str = "") -> User:
    """Used by the create_super_admin management command (runs in platform context)."""
    user = User.objects.create_superuser(email=email, password=password, first_name=first_name, last_name=last_name)
    record(
        actor=None, action="platform.super_admin.created", entity=user, company_id=None, new_value={"email": user.email}
    )
    return user
