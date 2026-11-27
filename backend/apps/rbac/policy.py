"""Central policy layer. Every view and service asks here; nothing checks role names.

permissions_for(user)            -> {"task.view": ["PROJECT"], ...}
has_perm(user, code)             -> holds the permission at any scope
can(user, code, obj)             -> holds it at a scope covering obj (+ rank rule)
require(user, code, obj=None, view_code=None)
                                 -> raises NotFound (obj not visible) / Forbidden / rank_violation
scope_queryset(user, code, qs)   -> qs restricted to objects the grant covers
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q, QuerySet

from apps.common.exceptions import Forbidden, NotFound, Unprocessable

from .adapters import adapter_for, registry
from .catalogue import RANKED_PERMISSIONS, RoleKey, Scope


@dataclass(frozen=True, slots=True)
class Grant:
    code: str
    scope: Scope
    role_key: str
    rank: int
    team_id: object = None
    project_id: object = None


@dataclass(slots=True)
class _Resolved:
    version: tuple
    grants: dict[str, list[Grant]]
    rank: int
    role_keys: frozenset[str]


def _load(user) -> _Resolved:
    from .models import RolePermission, UserRole

    version = (user.pk, user.rbac_version, getattr(user, "_company_rbac_version", None))
    cached = getattr(user, "_rbac_resolved", None)
    if cached is not None and cached.version == version:
        return cached

    grants: dict[str, list[Grant]] = {}
    if user.is_platform_admin:
        rows = RolePermission.objects.filter(role__company__isnull=True, role__key=RoleKey.SUPER_ADMIN).select_related(
            "permission", "role"
        )
        for rp in rows:
            grants.setdefault(rp.permission.code, []).append(
                Grant(rp.permission.code, Scope(rp.scope), rp.role.key, rp.role.rank)
            )
        resolved = _Resolved(version, grants, 100, frozenset({RoleKey.SUPER_ADMIN}))
    else:
        user_roles = list(
            UserRole.objects.filter(user_id=user.pk, role__company_id=user.company_id).select_related("role")
        )
        bindings = {ur.role_id: ur for ur in user_roles}
        rows = RolePermission.objects.filter(role_id__in=bindings.keys()).select_related("permission", "role")
        for rp in rows:
            ur = bindings[rp.role_id]
            grants.setdefault(rp.permission.code, []).append(
                Grant(
                    rp.permission.code,
                    Scope(rp.scope),
                    rp.role.key,
                    rp.role.rank,
                    getattr(ur, "team_id", None),
                    getattr(ur, "project_id", None),
                )
            )
        rank = max((ur.role.rank for ur in user_roles), default=0)
        resolved = _Resolved(version, grants, rank, frozenset(ur.role.key for ur in user_roles))
    user._rbac_resolved = resolved
    return resolved


def invalidate(user) -> None:
    if hasattr(user, "_rbac_resolved"):
        del user._rbac_resolved


def rank_of(user) -> int:
    if user is None:
        return 0
    return _load(user).rank


def role_keys(user) -> frozenset[str]:
    return _load(user).role_keys


def permissions_for(user) -> dict[str, list[str]]:
    return {code: sorted({g.scope.value for g in gs}) for code, gs in sorted(_load(user).grants.items())}


def has_perm(user, code: str) -> bool:
    return bool(user and code in _load(user).grants)


def _grant_covers(user, grant: Grant, obj, adapter) -> bool:
    if grant.scope == Scope.PLATFORM:
        return user.is_platform_admin
    if grant.scope == Scope.COMPANY:
        return True
    if grant.scope == Scope.OWN:
        return bool(adapter.own_check and adapter.own_check(user, obj))
    if grant.scope == Scope.TEAM:
        if not adapter.team_ids_of:
            return False
        return bool(registry.team_resolver(user, grant.team_id) & adapter.team_ids_of(obj))
    if grant.scope == Scope.PROJECT:
        if not adapter.project_ids_of:
            return False
        covered = registry.project_resolver(user, grant.team_id, grant.project_id)
        return bool(covered & adapter.project_ids_of(obj))
    return False


def _same_tenant(user, obj, adapter) -> bool:
    obj_company = getattr(obj, adapter.company_attr, None)
    if user.is_platform_admin:
        return True
    return obj_company is not None and obj_company == user.company_id


def _check(user, code: str, obj) -> str:
    """'ok', 'scope' (not covered) or 'rank' (covered, but target outranks actor)."""
    if user is None:
        return "scope"
    grants = _load(user).grants.get(code)
    if not grants:
        return "scope"
    adapter = adapter_for(type(obj))
    if not _same_tenant(user, obj, adapter):
        return "scope"
    if not any(_grant_covers(user, g, obj, adapter) for g in grants):
        return "scope"
    from apps.accounts.models import User

    if code in RANKED_PERMISSIONS and isinstance(obj, User) and obj.pk != user.pk and rank_of(user) <= rank_of(obj):
        return "rank"
    return "ok"


def can(user, code: str, obj) -> bool:
    return _check(user, code, obj) == "ok"


def require(user, code: str, obj=None, *, view_code: str | None = None) -> None:
    if obj is None:
        if not has_perm(user, code):
            raise Forbidden()
        return
    result = _check(user, code, obj)
    if result == "ok":
        return
    if view_code and not can(user, view_code, obj):
        raise NotFound()
    if result == "rank":
        raise Unprocessable(
            "You cannot perform this action on a user with an equal or higher role.", code="rank_violation"
        )
    raise Forbidden()


def scope_q(user, code: str, model) -> Q | None:
    """Q covering every object of ``model`` the user may act on with ``code``.
    Returns None when the user has no grant (caller should return an empty queryset)."""
    grants = _load(user).grants.get(code) if user else None
    if not grants:
        return None
    adapter = adapter_for(model)
    clauses: list[Q] = []
    for g in grants:
        if g.scope == Scope.PLATFORM:
            if user.is_platform_admin:
                return Q()
        elif g.scope == Scope.COMPANY:
            return Q(**{adapter.company_attr: user.company_id})
        elif g.scope == Scope.OWN and adapter.own_q:
            clauses.append(adapter.own_q(user))
        elif g.scope == Scope.TEAM and adapter.team_q:
            ids = registry.team_resolver(user, g.team_id)
            if ids:
                clauses.append(adapter.team_q(ids))
        elif g.scope == Scope.PROJECT and adapter.project_q:
            ids = registry.project_resolver(user, g.team_id, g.project_id)
            if ids:
                clauses.append(adapter.project_q(ids))
    if not clauses:
        return None
    combined = clauses[0]
    for clause in clauses[1:]:
        combined |= clause
    if not user.is_platform_admin:
        combined &= Q(**{adapter.company_attr: user.company_id})
    return combined


def scope_queryset(user, code: str, qs: QuerySet) -> QuerySet:
    q = scope_q(user, code, qs.model)
    if q is None:
        return qs.none()
    qs = qs.filter(q)
    return qs.distinct() if adapter_for(qs.model).needs_distinct else qs
