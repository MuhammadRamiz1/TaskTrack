"""HR employee lifecycle: create, edit, invite, password actions, deactivate, offboard."""

import django.dispatch
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import diff, record, snapshot
from apps.common.exceptions import Conflict, InvalidInput, Unprocessable
from apps.companies.services import seats_in_use
from apps.rbac import policy
from apps.rbac import services as rbac_services
from apps.rbac.catalogue import RoleKey
from apps.rbac.models import Role

from .. import emails
from ..models import InviteToken, User
from . import invites, passwords, sessions

#: Sent when an employee is deactivated. ``offboard=True`` asks receivers (tasks,
#: time tracking) to stop timers and flag open work; receivers return a dict of counts.
employee_deactivated = django.dispatch.Signal()

PROFILE_FIELDS = ["first_name", "last_name", "job_title", "timezone"]
VIEW = "employee.view_private"


def _not_self(actor: User, target: User, action: str) -> None:
    if actor.pk == target.pk:
        raise Conflict(f"You cannot {action} your own account here.", code="self_action_not_allowed")


def _resolve_manager(actor: User, manager_id) -> User | None:
    if manager_id is None:
        return None
    manager = (
        User.objects.filter(pk=manager_id, company_id=actor.company_id).exclude(status=User.Status.DEACTIVATED).first()
    )
    if manager is None:
        raise InvalidInput(details={"manager_id": ["Unknown employee."]})
    return manager


def _resolve_roles(actor: User, role_ids: list) -> list[Role]:
    roles = list(Role.objects.filter(company_id=actor.company_id, pk__in=role_ids))
    if len(roles) != len(set(role_ids)):
        raise InvalidInput(details={"role_ids": ["Unknown role."]})
    return roles


def create(*, actor: User, data: dict) -> User:
    policy.require(actor, "employee.create")
    company = actor.company
    if seats_in_use(company) >= company.max_users:
        raise Unprocessable(
            "The company has reached its user limit.",
            code="user_limit_exceeded",
            details={"max_users": company.max_users},
        )
    role_ids = data.get("role_ids") or []
    if role_ids:
        policy.require(actor, "employee.assign_role")
        roles = _resolve_roles(actor, role_ids)
        if any(r.rank >= policy.rank_of(actor) for r in roles):
            raise Unprocessable("You can only grant roles ranked below your own.", code="rank_violation")
    else:
        roles = [Role.objects.get(company_id=actor.company_id, key=RoleKey.TEAM_MEMBER)]
    if data.get("manager_id"):
        policy.require(actor, "employee.assign_team")
    manager = _resolve_manager(actor, data.get("manager_id"))

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=data["email"],
                company=company,
                first_name=data["first_name"],
                last_name=data.get("last_name", ""),
                job_title=data.get("job_title", ""),
                timezone=data.get("timezone") or company.timezone,
                manager=manager,
                status=User.Status.INVITED,
            )
    except IntegrityError as exc:
        raise InvalidInput(details={"email": ["This email address cannot be used."]}) from exc

    for role in roles:
        rbac_services.grant(actor=actor, user=user, role=role, check_policy=False)
    record(
        actor=actor,
        action="employee.created",
        entity=user,
        new_value={
            **snapshot(user, ["email", "first_name", "last_name", "job_title", "manager", "status"]),
            "roles": [r.key for r in roles],
        },
    )
    if data.get("send_invite", True):
        policy.require(actor, "employee.invite")
        invites.issue(actor=actor, user=user)
    return user


def update(*, actor: User, target: User, data: dict) -> User:
    policy.require(actor, "employee.update", target, view_code=VIEW)
    fields = [f for f in PROFILE_FIELDS if f in data]
    if "manager_id" in data:
        policy.require(actor, "employee.assign_team", target, view_code=VIEW)
        manager = _resolve_manager(actor, data["manager_id"])
        if manager and manager.pk == target.pk:
            raise InvalidInput(details={"manager_id": ["An employee cannot be their own manager."]})
        target.manager = manager
        fields.append("manager")
    before = snapshot(User.objects.get(pk=target.pk), fields)
    for field in PROFILE_FIELDS:
        if field in data:
            setattr(target, field, data[field])
    target.full_clean(exclude=["password", "email", "company"], validate_unique=False, validate_constraints=False)
    target.save()
    old, new = diff(before, snapshot(target, fields))
    if new:
        record(actor=actor, action="employee.updated", entity=target, old_value=old, new_value=new)
    return target


def send_invite(*, actor: User, target: User) -> InviteToken:
    policy.require(actor, "employee.invite", target, view_code=VIEW)
    return invites.issue(actor=actor, user=target)


def revoke_invite(*, actor: User, target: User) -> None:
    policy.require(actor, "employee.invite", target, view_code=VIEW)
    invites.revoke(actor=actor, user=target)


def send_reset_link(*, actor: User, target: User) -> None:
    policy.require(actor, "employee.reset_password", target, view_code=VIEW)
    _not_self(actor, target, "reset the password of")
    passwords.hr_send_reset_link(actor, target)


def set_temporary_password(*, actor: User, target: User, password: str) -> None:
    policy.require(actor, "employee.reset_password", target, view_code=VIEW)
    _not_self(actor, target, "reset the password of")
    passwords.hr_set_temporary_password(actor, target, password)


def revoke_sessions(*, actor: User, target: User) -> int:
    policy.require(actor, "employee.deactivate", target, view_code=VIEW)
    count = sessions.end_all_sessions(target, "revoked_by_hr")
    record(actor=actor, action="employee.sessions_revoked", entity=target, new_value={"sessions_revoked": count})
    return count


def _deactivate(actor: User, target: User, *, offboard: bool, reason: str) -> dict:
    policy.require(actor, "employee.deactivate", target, view_code=VIEW)
    _not_self(actor, target, "deactivate")
    if target.status == User.Status.DEACTIVATED and not offboard:
        raise Conflict("The employee is already deactivated.", code="already_deactivated")
    now = timezone.now()
    old_status = target.status
    target.status = User.Status.DEACTIVATED
    target.deactivated_at = target.deactivated_at or now
    target.save(update_fields=["status", "deactivated_at", "updated_at"])
    InviteToken.objects.filter(user=target, used_at__isnull=True, revoked_at__isnull=True).update(revoked_at=now)
    revoked = sessions.end_all_sessions(target, "offboarded" if offboard else "deactivated")
    summary = {"sessions_revoked": revoked}
    for _receiver, result in employee_deactivated.send(sender=User, user=target, actor=actor, offboard=offboard):
        if isinstance(result, dict):
            summary.update(result)
    record(
        actor=actor,
        action="employee.offboarded" if offboard else "employee.deactivated",
        entity=target,
        old_value={"status": old_status},
        new_value={"status": target.status, "reason": reason, **summary},
    )
    emails.account_deactivated(target)
    return summary


def deactivate(*, actor: User, target: User, reason: str = "") -> dict:
    return _deactivate(actor, target, offboard=False, reason=reason)


def offboard(*, actor: User, target: User, reason: str = "") -> dict:
    return _deactivate(actor, target, offboard=True, reason=reason)


def reactivate(*, actor: User, target: User) -> User:
    policy.require(actor, "employee.deactivate", target, view_code=VIEW)
    if target.status != User.Status.DEACTIVATED:
        raise Conflict("Only deactivated employees can be reactivated.", code="not_deactivated")
    if seats_in_use(actor.company) >= actor.company.max_users:
        raise Unprocessable("The company has reached its user limit.", code="user_limit_exceeded")
    target.status = User.Status.ACTIVE if target.has_usable_password() else User.Status.INVITED
    target.deactivated_at = None
    target.save(update_fields=["status", "deactivated_at", "updated_at"])
    record(
        actor=actor,
        action="employee.reactivated",
        entity=target,
        old_value={"status": "DEACTIVATED"},
        new_value={"status": target.status},
    )
    return target
