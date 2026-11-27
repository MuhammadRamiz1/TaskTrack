"""Permission catalogue and default role grants (docs/architecture/03-rbac.md).

This module is data. Migrations call ``sync_catalogue`` to load it into the
``Permission``/``Role``/``RolePermission`` tables; runtime code reads the tables.
"""

from enum import StrEnum


class Scope(StrEnum):
    PLATFORM = "PLATFORM"
    COMPANY = "COMPANY"
    TEAM = "TEAM"
    PROJECT = "PROJECT"
    OWN = "OWN"


class RoleKey(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    COMPANY_ADMIN = "COMPANY_ADMIN"
    HR = "HR"
    MANAGER = "MANAGER"
    TEAM_LEAD = "TEAM_LEAD"
    TEAM_MEMBER = "TEAM_MEMBER"


P, C, T, PR, O = Scope.PLATFORM, Scope.COMPANY, Scope.TEAM, Scope.PROJECT, Scope.OWN
ALL_TENANT = [C, T, PR, O]

# code: (module, description, allowed scopes)
PERMISSIONS: dict[str, tuple[str, str, list[Scope]]] = {
    # Platform
    "platform.company.manage": ("platform", "Create, edit, suspend, activate and delete companies", [P]),
    "platform.plan.manage": ("platform", "Manage plans and limits", [P]),
    "platform.company_admin.invite": ("platform", "Create a company's first HR or admin account", [P]),
    "platform.audit.view": ("platform", "View the platform audit log", [P]),
    "platform.impersonate": ("platform", "Impersonate a company user (read-only, audited)", [P]),
    # Company administration
    "company.settings.manage": ("company", "Edit company settings", [C]),
    "workflow.manage": ("company", "Edit task status transition rules", [C]),
    "role.manage": ("company", "Create roles and edit role permissions", [C]),
    "holiday.manage": ("company", "Manage company holidays", [C]),
    "leave.manage": ("company", "Record employee leave", [C, T]),
    "leave.view": ("company", "View employee leave", ALL_TENANT),
    "audit.view": ("company", "View the company audit log", [C]),
    # Employees
    "employee.view": ("employees", "View the employee directory", [C, T, PR]),
    "employee.view_private": ("employees", "View employee account details", ALL_TENANT),
    "employee.create": ("employees", "Create employees", [C]),
    "employee.update": ("employees", "Edit employee profiles", [C, O]),
    "employee.invite": ("employees", "Create, resend and revoke invite links", [C]),
    "employee.reset_password": ("employees", "Send reset links or set temporary passwords", [C]),
    "employee.assign_role": ("employees", "Grant and revoke roles", [C]),
    "employee.assign_team": ("employees", "Set teams and manager", [C]),
    "employee.deactivate": ("employees", "Deactivate, reactivate and offboard employees", [C]),
    # Organisation
    "team.view": ("org", "View teams", [C, T]),
    "team.manage": ("org", "Create, edit and archive teams and their members", [C]),
    "project.view": ("org", "View projects", ALL_TENANT),
    "project.manage": ("org", "Create, edit and archive projects", [C, T]),
    "project.member.manage": ("org", "Manage project members", [C, T, PR]),
    # Tasks
    "task.view": ("tasks", "View tasks", ALL_TENANT),
    "task.create": ("tasks", "Create tasks and subtasks", [C, T, PR]),
    "task.update": ("tasks", "Edit task details", [C, T, PR]),
    "task.delete": ("tasks", "Delete and restore tasks", [C, T, PR]),
    "task.assign": ("tasks", "Assign and reassign tasks", [C, T, PR]),
    "task.set_priority": ("tasks", "Change task priority", [C, T, PR]),
    "task.transition": ("tasks", "Change task status", ALL_TENANT),
    "task.acknowledge": ("tasks", "Acknowledge assignments", [O]),
    "task.escalate": ("tasks", "Escalate blocked tasks to managers", [C, T, PR]),
    "task.checklist.manage": ("tasks", "Edit checklists", [C, T, PR]),
    "task.checklist.complete": ("tasks", "Tick checklist items", ALL_TENANT),
    "task.dependency.manage": ("tasks", "Manage task dependencies", [C, T, PR]),
    "task.comment": ("tasks", "Comment on tasks", ALL_TENANT),
    "task.attachment.upload": ("tasks", "Upload attachments", ALL_TENANT),
    "task.attachment.delete": ("tasks", "Delete other people's attachments", [C, T, PR]),
    "task.reopen": ("tasks", "Reopen completed tasks", [C, T, PR]),
    "task.workload.view": ("tasks", "View workload", [C, T, PR]),
    # Reviews
    "review.submit": ("reviews", "Submit tasks for review", ALL_TENANT),
    "review.decide": ("reviews", "Approve or request changes", [C, T, PR]),
    "review.view": ("reviews", "View review history", ALL_TENANT),
    # Time tracking
    "time.track": ("time", "Track own time", [O]),
    "time.view": ("time", "View time records", ALL_TENANT),
    "time.edit_others": ("time", "Correct other people's time entries", [C, T, PR]),
    "timesheet.submit": ("time", "Submit own timesheets", [O]),
    "timesheet.approve": ("time", "Approve and reject timesheets", [C, T, PR]),
    # Dashboards and reports
    "dashboard.manager.view": ("reports", "View the manager dashboard", [C, T, PR]),
    "dashboard.member.view": ("reports", "View the personal dashboard", [O]),
    "report.view": ("reports", "View reports", ALL_TENANT),
    "report.export": ("reports", "Export reports", ALL_TENANT),
    "report.schedule": ("reports", "Schedule reports", [C, T, PR]),
}

ROLES: dict[RoleKey, dict] = {
    RoleKey.SUPER_ADMIN: {"name": "Super Admin", "rank": 100, "description": "Platform administrator."},
    RoleKey.COMPANY_ADMIN: {"name": "Company Admin", "rank": 90, "description": "Full control of the company."},
    RoleKey.HR: {"name": "HR", "rank": 70, "description": "Employees, invites, passwords and org setup."},
    RoleKey.MANAGER: {"name": "Manager", "rank": 50, "description": "Plans, assigns and reviews work."},
    RoleKey.TEAM_LEAD: {"name": "Team Lead", "rank": 30, "description": "Coordinates work inside teams."},
    RoleKey.TEAM_MEMBER: {"name": "Team Member", "rank": 10, "description": "Works on assigned tasks."},
}

_PLATFORM_CODES = [code for code, (_, _, scopes) in PERMISSIONS.items() if scopes == [P]]
_COMPANY_ADMIN_OWN = {"time.track", "timesheet.submit", "dashboard.member.view", "task.acknowledge"}

GRANTS: dict[RoleKey, dict[str, Scope]] = {
    RoleKey.SUPER_ADMIN: {code: P for code in _PLATFORM_CODES},
    RoleKey.COMPANY_ADMIN: {
        code: (O if code in _COMPANY_ADMIN_OWN else C)
        for code, (_, _, scopes) in PERMISSIONS.items()
        if scopes != [P] and (C in scopes or code in _COMPANY_ADMIN_OWN)
    },
    RoleKey.HR: {
        "workflow.manage": C,
        "holiday.manage": C,
        "leave.manage": C,
        "leave.view": C,
        "audit.view": C,
        "employee.view": C,
        "employee.view_private": C,
        "employee.create": C,
        "employee.update": C,
        "employee.invite": C,
        "employee.reset_password": C,
        "employee.assign_role": C,
        "employee.assign_team": C,
        "employee.deactivate": C,
        "team.view": C,
        "team.manage": C,
        "project.view": C,
    },
    RoleKey.MANAGER: {
        "leave.manage": T,
        "leave.view": T,
        "employee.view": C,
        "employee.view_private": T,
        "employee.update": O,
        "team.view": C,
        "project.view": PR,
        "project.manage": T,
        "project.member.manage": PR,
        "task.view": PR,
        "task.create": PR,
        "task.update": PR,
        "task.delete": PR,
        "task.assign": PR,
        "task.set_priority": PR,
        "task.transition": PR,
        "task.checklist.manage": PR,
        "task.checklist.complete": PR,
        "task.dependency.manage": PR,
        "task.comment": PR,
        "task.attachment.upload": PR,
        "task.attachment.delete": PR,
        "task.reopen": PR,
        "task.workload.view": PR,
        "review.submit": PR,
        "review.decide": PR,
        "review.view": PR,
        "time.track": O,
        "time.view": PR,
        "time.edit_others": PR,
        "timesheet.submit": O,
        "timesheet.approve": T,
        "dashboard.manager.view": PR,
        "dashboard.member.view": O,
        "report.view": PR,
        "report.export": PR,
        "report.schedule": PR,
    },
    RoleKey.TEAM_LEAD: {
        "leave.view": T,
        "employee.view": C,
        "employee.update": O,
        "employee.view_private": O,
        "team.view": T,
        "project.view": T,
        "project.member.manage": T,
        "task.view": T,
        "task.assign": T,
        "task.transition": T,
        "task.escalate": T,
        "task.checklist.manage": T,
        "task.checklist.complete": T,
        "task.dependency.manage": T,
        "task.comment": T,
        "task.attachment.upload": T,
        "task.workload.view": T,
        "review.submit": T,
        "review.view": T,
        "time.track": O,
        "time.view": T,
        "timesheet.submit": O,
        "dashboard.manager.view": T,
        "dashboard.member.view": O,
        "report.view": T,
        "report.export": T,
    },
    RoleKey.TEAM_MEMBER: {
        "leave.view": O,
        "employee.view": C,
        "employee.view_private": O,
        "employee.update": O,
        "team.view": T,
        "project.view": PR,
        "task.view": O,
        "task.transition": O,
        "task.acknowledge": O,
        "task.checklist.complete": O,
        "task.comment": O,
        "task.attachment.upload": O,
        "review.submit": O,
        "review.view": O,
        "time.track": O,
        "time.view": O,
        "timesheet.submit": O,
        "dashboard.member.view": O,
        "report.view": O,
        "report.export": O,
    },
}

# Permissions that act on another user: also require actor rank > target rank.
RANKED_PERMISSIONS = frozenset(
    {
        "employee.update",
        "employee.invite",
        "employee.reset_password",
        "employee.assign_role",
        "employee.assign_team",
        "employee.deactivate",
        "platform.impersonate",
    }
)


def validate_catalogue() -> None:
    for role, grants in GRANTS.items():
        for code, scope in grants.items():
            if code not in PERMISSIONS:
                raise ValueError(f"{role}: unknown permission {code}")
            if scope not in PERMISSIONS[code][2]:
                raise ValueError(f"{role}: scope {scope} not allowed for {code}")


validate_catalogue()


def sync_catalogue(Permission, Role, RolePermission, Company=None) -> None:  # noqa: N803 - model classes
    """Idempotently load the catalogue. Usable from migrations (historical models).

    * Permissions: created or updated; never deleted (removal needs its own migration).
    * System template roles (company NULL): grants reset to the catalogue.
    * Company copies of system roles: missing grants added, customisations kept.
    """
    perms = {}
    for code, (module, description, scopes) in PERMISSIONS.items():
        perm, _ = Permission.objects.update_or_create(
            code=code, defaults={"module": module, "description": description, "allowed_scopes": list(scopes)}
        )
        perms[code] = perm

    for key, meta in ROLES.items():
        template, _ = Role.objects.update_or_create(company=None, key=key, defaults={**meta, "is_system": True})
        RolePermission.objects.filter(role=template).exclude(permission__code__in=GRANTS[key].keys()).delete()
        for code, scope in GRANTS[key].items():
            RolePermission.objects.update_or_create(role=template, permission=perms[code], defaults={"scope": scope})

        for company_role in Role.objects.filter(company__isnull=False, key=key, is_system=True):
            existing = set(RolePermission.objects.filter(role=company_role).values_list("permission__code", flat=True))
            for code, scope in GRANTS[key].items():
                if code not in existing:
                    RolePermission.objects.create(role=company_role, permission=perms[code], scope=scope)
