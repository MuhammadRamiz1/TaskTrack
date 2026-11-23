# 03. RBAC and Policy Layer

Permissions are data. Code asks one question, "may this user perform permission P
on object O?", and the answer comes from `Role -> RolePermission(scope) -> UserRole`
rows. No view or service contains `if user.role == ...`.

## 3.1 Concepts

| Concept | Meaning |
| --- | --- |
| Permission | A code such as `task.assign`. Global catalogue, seeded by migration. |
| Role | Named bundle of permissions with a `rank`. Six system roles are copied into every company; companies may add custom roles. |
| RolePermission | `(role, permission, scope)`. Scope is the maximum reach of that grant. |
| UserRole | `(user, role, team?, project?)`. A user can hold several roles. The optional binding narrows TEAM and PROJECT scopes. |
| Scope | `PLATFORM`, `COMPANY`, `TEAM`, `PROJECT`, `OWN`. |
| Rank | Integer privilege level used for "who may act on whom" rules. |

## 3.2 Scope resolution

For a grant obtained through `UserRole ur`:

| Scope | Objects covered |
| --- | --- |
| `PLATFORM` | Platform objects (companies, plans, platform audit). Super admin only. |
| `COMPANY` | Every object in `user.company`. |
| `TEAM` | If `ur.team` is set: that team. Otherwise: every team the user is a `TeamMember` of. An object is in a team when its team path (below) matches. |
| `PROJECT` | If `ur.project` is set: that project. If `ur.team` is set: every project of that team. Otherwise: projects where the user is a `ProjectMember` or the owner. |
| `OWN` | Objects related to the user through the model's own-relation (below). |

A user's effective reach for a permission is the **union** over all grants.

Each tenant model registers a `ScopeAdapter` in `rbac/adapters.py`:

| Model | team path | project path | own relation |
| --- | --- | --- | --- |
| Task (and checklist, comment, attachment, review, activity via `task__`) | `project__team_id` | `project_id` | assignee, reviewer or creator |
| TimeEntry, Timesheet | `user__team_memberships__team_id` | `task__project_id` | `user_id = me` |
| Project | `team_id` | `id` | owner or member |
| Team | `id` | none | member |
| User (employee) | `team_memberships__team_id` | `project_memberships__project_id` | `id = me` |
| ReportExport, ScheduledReport | none | none | `requested_by` / `owner` |

Adapters return a Django `Q` for querysets and a boolean for single objects, from the same
definition, so list filtering and object checks cannot diverge.

## 3.3 Permission catalogue and default matrix

Legend: **C** company, **T** team, **P** project, **O** own, **PL** platform, blank = not granted.
SA = SUPER_ADMIN, CA = COMPANY_ADMIN, HR, MG = MANAGER, TL = TEAM_LEAD, TM = TEAM_MEMBER.

### Platform

| Permission | SA | CA | HR | MG | TL | TM |
| --- | --- | --- | --- | --- | --- | --- |
| `platform.company.manage` (create, edit, suspend, activate, delete, limits) | PL | | | | | |
| `platform.plan.manage` | PL | | | | | |
| `platform.company_admin.invite` (first HR/admin account) | PL | | | | | |
| `platform.audit.view` | PL | | | | | |
| `platform.impersonate` | PL | | | | | |

### Company administration

| Permission | SA | CA | HR | MG | TL | TM |
| --- | --- | --- | --- | --- | --- | --- |
| `company.settings.manage` (time zone, 2FA enforcement, invite expiry, timer rules) | | C | | | | |
| `workflow.manage` (status transition rules) | | C | C | | | |
| `role.manage` (custom roles, role permissions) | | C | | | | |
| `holiday.manage` | | C | C | | | |
| `leave.manage` | | C | C | T | | |
| `leave.view` | | C | C | T | T | O |
| `audit.view` | | C | C | | | |

### Employees (HR)

| Permission | SA | CA | HR | MG | TL | TM |
| --- | --- | --- | --- | --- | --- | --- |
| `employee.view` (directory: name, email, title, teams) | | C | C | C | C | C |
| `employee.view_private` (status, invite state, manager, roles) | | C | C | T | | O |
| `employee.create` | | C | C | | | |
| `employee.update` | | C | C | | | O (own profile fields only) |
| `employee.invite` (create, resend, revoke link) | | C | C | | | |
| `employee.reset_password` (send link or temporary password) | | C | C | | | |
| `employee.assign_role` | | C | C | | | |
| `employee.assign_team` / set manager | | C | C | | | |
| `employee.deactivate` (deactivate, offboard, revoke sessions) | | C | C | | | |

### Organisation

| Permission | SA | CA | HR | MG | TL | TM |
| --- | --- | --- | --- | --- | --- | --- |
| `team.view` | | C | C | C | T | T |
| `team.manage` (create, edit, archive, members, lead) | | C | C | | | |
| `project.view` | | C | C | P | T | P |
| `project.manage` (create, edit, archive) | | C | | T | | |
| `project.member.manage` | | C | | P | T | |

HR sees project names and members for org setup. HR has **no** `task.*` permissions,
so it cannot see task content unless it also holds a MANAGER `UserRole`.

### Tasks

| Permission | SA | CA | HR | MG | TL | TM |
| --- | --- | --- | --- | --- | --- | --- |
| `task.view` | | C | | P | T | O |
| `task.create` (tasks and subtasks) | | C | | P | | |
| `task.update` (title, description, instructions, acceptance criteria, dates, estimate, reviewer) | | C | | P | | |
| `task.delete` (soft) | | C | | P | | |
| `task.assign` (assign, reassign, bulk assign, unassign) | | C | | P | T | |
| `task.set_priority` | | C | | P | (grantable) | |
| `task.transition` (subject to transition rules) | | C | | P | T | O |
| `task.acknowledge` | | | | | | O |
| `task.escalate` (notify manager of a blocked task) | | | | | T | |
| `task.checklist.manage` (add, edit, remove items, mark required) | | C | | P | T | |
| `task.checklist.complete` (tick items) | | C | | P | T | O |
| `task.dependency.manage` | | C | | P | T | |
| `task.comment` | | C | | P | T | O |
| `task.attachment.upload` | | C | | P | T | O |
| `task.attachment.delete` (others' files; own files always deletable while task unlocked) | | C | | P | | |
| `task.reopen` | | C | | P | | |
| `task.workload.view` | | C | | P | T | |

### Review (separate module)

| Permission | SA | CA | HR | MG | TL | TM |
| --- | --- | --- | --- | --- | --- | --- |
| `review.submit` | | | | P | T | O |
| `review.decide` (approve, request changes) | | C | | P | (grantable) | |
| `review.view` (history) | | C | | P | T | O |

`review.decide` also requires that the actor is the task's effective reviewer
(explicit `reviewer`, else `created_by`), or holds `review.decide` at COMPANY scope.

### Time tracking (separate module)

| Permission | SA | CA | HR | MG | TL | TM |
| --- | --- | --- | --- | --- | --- | --- |
| `time.track` (timer, manual entries on own assigned tasks) | | O | | O | O | O |
| `time.view` | | C | | P | T | O |
| `time.edit_others` (correct entries of others before approval) | | C | | P | | |
| `timesheet.submit` | | O | | O | O | O |
| `timesheet.approve` (approve, reject) | | C | | T | | |

### Dashboards, reports, notifications

| Permission | SA | CA | HR | MG | TL | TM |
| --- | --- | --- | --- | --- | --- | --- |
| `dashboard.manager.view` | | C | | P | T | |
| `dashboard.member.view` | | O | | O | O | O |
| `report.view` | | C | | P | T | O |
| `report.export` | | C | | P | T | O |
| `report.schedule` | | C | | P | | |

Notifications and own profile/security settings need only authentication; every query
is filtered to `recipient = me` / `user = me`.

## 3.4 Rank rules (actor versus target user)

Some permissions act on another user. These also require
`max_rank(actor) > max_rank(target)`:

`employee.reset_password`, `employee.deactivate`, `employee.update` (on others),
`employee.assign_role` (and the role being granted must have `rank < max_rank(actor)`),
`platform.impersonate` (target cannot be a super admin).

With default ranks (SA 100, CA 90, HR 70, MG 50, TL 30, TM 10) this gives the required
outcome: HR cannot reset the password of HR, Company Admin or Super Admin accounts.
Ranks are stored on `Role`, so the rule is data-driven.

## 3.5 Policy API (`apps/rbac/policy.py`)

```python
def permissions_for(user) -> dict[str, list[Scope]]
    """{'task.view': ['PROJECT'], ...}. Returned by /auth/me for UI gating."""

def has_perm(user, code: str) -> bool
    """User holds the permission at any scope."""

def can(user, code: str, obj) -> bool
    """User holds the permission at a scope that covers obj (+ rank rules)."""

def require(user, code: str, obj=None) -> None
    """Raise NotFound if the user cannot even view obj, else PermissionDenied."""

def scope_queryset(user, code: str, qs: QuerySet) -> QuerySet
    """qs filtered to objects the user may act on with `code`. Empty if no grant."""

def scope_q(user, code: str, model) -> Q
    """The Q object behind scope_queryset, for annotations and aggregates."""
```

- **Grant loading.** One pair of queries (`UserRole` + `RolePermission`) per request, cached
  on the user object for the rest of that request. Permissions are therefore read fresh on
  every request: a role or grant change takes effect immediately, with no cache to
  invalidate. (A Redis cache keyed by `rbac_version` can be added if profiling shows a need;
  the version columns already exist.)
- **DRF integration.** Tenant and platform views declare
  `permission_map = {"GET": "employee.view_private", "POST": "employee.create", ...}`;
  `rbac.permissions.PolicyPermission` denies any method without an entry (fail closed).
  A test fails if any API view lacks an entry for one of its methods or does not inherit
  one of the `common.views` base classes.
- **Services call `require()` again.** Views are not trusted to have checked. Services
  are also called by Celery and management commands.
- **Status codes.** Object outside view scope: `404`. Object visible but action not
  allowed: `403`. Cross-tenant IDs always give `404`.

## 3.6 Role assignment rules

- Exactly one of `SUPER_ADMIN` (platform) or company roles. A company user always has at
  least one role; removing the last one is rejected.
- Bindings are optional. `POST /org/teams/{id}/lead/` creates a `TEAM_LEAD` role bound to
  that team. An unbound `TEAM_LEAD` covers the teams the user is a member of; an unbound
  `MANAGER` covers the projects they are a member or owner of (TEAM grants: their teams).
  `MANAGER` may also be bound to one team or one project.
- Granting or removing a role bumps `user.session_version` only when a permission is
  removed (so tokens issued earlier cannot use it), and always bumps `rbac_version`.
- Every change writes `AuditLog(action="rbac.user_role.grant|revoke")`.

## 3.7 What /auth/me returns

```json
{
  "id": "…", "email": "…", "first_name": "…", "last_name": "…",
  "company": {"id": "…", "name": "…", "slug": "…", "enforce_2fa": false},
  "roles": [{"key": "MANAGER", "team": null, "project": {"id": "…", "key": "WEB"}}],
  "permissions": {"task.view": ["PROJECT"], "task.assign": ["PROJECT"], "time.track": ["OWN"]},
  "must_change_password": false,
  "totp_enabled": false,
  "impersonation": null
}
```

The frontend uses `permissions` only to hide navigation and controls. Every action is
re-checked on the server.
