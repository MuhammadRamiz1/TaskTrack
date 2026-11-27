"""Role provisioning, custom roles, role permissions and user-role grants."""

import re

from django.db import IntegrityError, transaction
from django.db.models import Count, F

from apps.audit.services import record
from apps.common.exceptions import Conflict, InvalidInput, Unprocessable

from . import policy
from .catalogue import RoleKey, Scope
from .models import Permission, Role, RolePermission, UserRole

PROTECTED_GRANTS = {RoleKey.COMPANY_ADMIN: {"role.manage", "employee.assign_role"}}


def provision_company_roles(company) -> dict[str, Role]:
    """Copy the system template roles (and their grants) into a new company."""
    roles = {}
    for template in Role.objects.filter(company__isnull=True, is_system=True).exclude(key=RoleKey.SUPER_ADMIN):
        role = Role.objects.create(
            company=company,
            key=template.key,
            name=template.name,
            description=template.description,
            rank=template.rank,
            is_system=True,
        )
        RolePermission.objects.bulk_create(
            RolePermission(role=role, permission_id=g.permission_id, scope=g.scope) for g in template.grants.all()
        )
        roles[role.key] = role
    return roles


def _bump_company_rbac(company_id) -> None:
    from apps.companies.models import Company

    Company.objects.filter(pk=company_id).update(rbac_version=F("rbac_version") + 1)


def _validate_grants(grants: list[dict]) -> list[tuple[Permission, str]]:
    codes = [g["code"] for g in grants]
    if len(codes) != len(set(codes)):
        raise InvalidInput(details={"permissions": ["Each permission may appear only once."]})
    perms = {p.code: p for p in Permission.objects.filter(code__in=codes)}
    errors, result = [], []
    for g in grants:
        perm = perms.get(g["code"])
        if perm is None:
            errors.append(f"Unknown permission '{g['code']}'.")
            continue
        if g["scope"] == Scope.PLATFORM or g["scope"] not in perm.allowed_scopes:
            errors.append(f"Scope '{g['scope']}' is not allowed for '{perm.code}'.")
            continue
        result.append((perm, g["scope"]))
    if errors:
        raise InvalidInput(details={"permissions": errors})
    return result


def _require_outranks(actor, rank: int, what: str) -> None:
    if rank >= policy.rank_of(actor):
        raise Unprocessable(f"You can only {what} roles ranked below your own.", code="rank_violation")


def create_role(*, actor, name: str, description: str, rank: int, grants: list[dict]) -> Role:
    policy.require(actor, "role.manage")
    _require_outranks(actor, rank, "create")
    key = "CUSTOM_" + re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:30]
    validated = _validate_grants(grants)
    try:
        with transaction.atomic():
            role = Role.objects.create(
                company_id=actor.company_id, key=key, name=name, description=description, rank=rank, is_system=False
            )
    except IntegrityError as exc:
        raise InvalidInput(details={"name": ["A role with this name already exists."]}) from exc
    RolePermission.objects.bulk_create(RolePermission(role=role, permission=p, scope=s) for p, s in validated)
    _bump_company_rbac(actor.company_id)
    record(
        actor=actor,
        action="rbac.role.created",
        entity=role,
        new_value={"name": name, "rank": rank, "permissions": {p.code: s for p, s in validated}},
    )
    return role


def update_role(*, actor, role: Role, data: dict) -> Role:
    policy.require(actor, "role.manage", role)
    _require_outranks(actor, role.rank, "edit")
    if role.is_system and "rank" in data and data["rank"] != role.rank:
        raise InvalidInput(details={"rank": ["The rank of a system role cannot change."]})
    if "rank" in data:
        _require_outranks(actor, data["rank"], "set")
    old = {k: getattr(role, k) for k in data}
    for key, value in data.items():
        setattr(role, key, value)
    role.save()
    _bump_company_rbac(role.company_id)
    record(actor=actor, action="rbac.role.updated", entity=role, old_value=old, new_value=data)
    return role


def set_role_permissions(*, actor, role: Role, grants: list[dict]) -> Role:
    policy.require(actor, "role.manage", role)
    _require_outranks(actor, role.rank, "edit")
    validated = _validate_grants(grants)
    new_codes = {p.code for p, _ in validated}
    missing_protected = PROTECTED_GRANTS.get(role.key, set()) - new_codes if role.is_system else set()
    if missing_protected:
        raise InvalidInput(
            details={"permissions": [f"'{c}' cannot be removed from this role." for c in sorted(missing_protected)]}
        )
    old = {g.permission.code: g.scope for g in role.grants.select_related("permission")}
    RolePermission.objects.filter(role=role).delete()
    RolePermission.objects.bulk_create(RolePermission(role=role, permission=p, scope=s) for p, s in validated)
    _bump_company_rbac(role.company_id)
    record(
        actor=actor,
        action="rbac.role.permissions_set",
        entity=role,
        old_value=old,
        new_value={p.code: s for p, s in validated},
    )
    return role


def delete_role(*, actor, role: Role) -> None:
    policy.require(actor, "role.manage", role)
    if role.is_system:
        raise Conflict("System roles cannot be deleted.", code="system_role")
    _require_outranks(actor, role.rank, "delete")
    if role.user_roles.exists():
        raise Conflict("Remove this role from all users first.", code="role_in_use")
    record(actor=actor, action="rbac.role.deleted", entity=role, old_value={"name": role.name, "rank": role.rank})
    role.delete()
    _bump_company_rbac(actor.company_id)


def grantable_roles(actor):
    return Role.objects.filter(company_id=actor.company_id, rank__lt=policy.rank_of(actor)).annotate(
        holders=Count("user_roles")
    )


def grant(*, actor, user, role: Role, team=None, project=None, check_policy: bool = True) -> UserRole:
    """Grant ``role``, optionally bound to one team or one project (narrows its scopes)."""
    if check_policy:
        policy.require(actor, "employee.assign_role", user, view_code="employee.view_private")
        _require_outranks(actor, role.rank, "grant")
    if role.company_id != user.company_id:
        raise InvalidInput(details={"role_id": ["Unknown role."]})
    if team is not None and project is not None:
        raise InvalidInput(details={"team_id": ["Bind a role to a team or a project, not both."]})
    for obj, field in ((team, "team_id"), (project, "project_id")):
        if obj is not None and obj.company_id != user.company_id:
            raise InvalidInput(details={field: ["Unknown."]})
    try:
        with transaction.atomic():
            user_role = UserRole.objects.create(
                company_id=user.company_id, user=user, role=role, team=team, project=project, granted_by=actor
            )
    except IntegrityError as exc:
        raise Conflict("The user already has this role with this binding.", code="role_already_granted") from exc
    type(user).objects.filter(pk=user.pk).update(rbac_version=F("rbac_version") + 1)
    record(
        actor=actor,
        action="rbac.user_role.granted",
        entity=user,
        new_value={
            "role": role.key,
            "user_role_id": user_role.pk,
            "team_id": team.pk if team else None,
            "project_id": project.pk if project else None,
        },
    )
    return user_role


def revoke(*, actor, user_role: UserRole) -> None:
    from apps.accounts.services import sessions

    user = user_role.user
    policy.require(actor, "employee.assign_role", user, view_code="employee.view_private")
    _require_outranks(actor, user_role.role.rank, "revoke")
    if UserRole.objects.filter(user=user).count() <= 1:
        raise Conflict("A user must keep at least one role.", code="last_role")
    record(
        actor=actor,
        action="rbac.user_role.revoked",
        entity=user,
        old_value={"role": user_role.role.key, "user_role_id": user_role.pk},
    )
    user_role.delete()
    type(user).objects.filter(pk=user.pk).update(rbac_version=F("rbac_version") + 1)
    # Permissions are read from the database on every request, so the change is
    # already effective; bumping the session version also forces a fresh /me.
    sessions.bump_session_version(user)
