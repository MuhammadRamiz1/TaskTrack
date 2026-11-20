"""Default RBAC matrix from PRD section 5.

Each role maps capabilities to a Scope:
  ALL  - any record in the organisation
  TEAM - records belonging to teams the user manages
  OWN  - records the user created or is assigned to
Capabilities missing from a role's map are denied.

Interpretation notes (PRD marks some cells only with a tick):
  * LOG_TIME is OWN for every role: timers and entries are always personal.
  * CREATE_TASK is ALL for admin and manager (PRD tick), OWN for members
    ("own / self-assigned").
  * VIEW_AUDIT_LOG is ALL for viewers; the PRD says "read-only (HR-relevant)",
    so the view layer may narrow which entries a viewer sees.
"""

from enum import Enum

from .models import Role


class Scope(str, Enum):
    NONE = "none"
    OWN = "own"
    TEAM = "team"
    ALL = "all"


class Capability(str, Enum):
    MANAGE_USERS = "manage_users"
    MANAGE_TEAMS_PROJECTS = "manage_teams_projects"
    CREATE_TASK = "create_task"
    ASSIGN_TASK = "assign_task"
    EDIT_TASK = "edit_task"
    DELETE_TASK = "delete_task"
    LOG_TIME = "log_time"
    EDIT_TIME_ENTRY = "edit_time_entry"
    APPROVE_TIMESHEET = "approve_timesheet"
    VIEW_TIME = "view_time"
    GENERATE_REPORTS = "generate_reports"
    SCHEDULE_REPORTS = "schedule_reports"
    VIEW_INSIGHTS = "view_insights"
    VIEW_AUDIT_LOG = "view_audit_log"
    CONFIGURE_INTEGRATIONS = "configure_integrations"


C, S = Capability, Scope

ROLE_CAPABILITIES = {
    Role.ADMIN: {
        C.MANAGE_USERS: S.ALL,
        C.MANAGE_TEAMS_PROJECTS: S.ALL,
        C.CREATE_TASK: S.ALL,
        C.ASSIGN_TASK: S.ALL,
        C.EDIT_TASK: S.ALL,
        C.DELETE_TASK: S.ALL,
        C.LOG_TIME: S.OWN,
        C.EDIT_TIME_ENTRY: S.ALL,
        C.APPROVE_TIMESHEET: S.ALL,
        C.VIEW_TIME: S.ALL,
        C.GENERATE_REPORTS: S.ALL,
        C.SCHEDULE_REPORTS: S.ALL,
        C.VIEW_INSIGHTS: S.ALL,
        C.VIEW_AUDIT_LOG: S.ALL,
        C.CONFIGURE_INTEGRATIONS: S.ALL,
    },
    Role.MANAGER: {
        C.MANAGE_TEAMS_PROJECTS: S.TEAM,
        C.CREATE_TASK: S.ALL,
        C.ASSIGN_TASK: S.TEAM,
        C.EDIT_TASK: S.TEAM,
        C.DELETE_TASK: S.TEAM,
        C.LOG_TIME: S.OWN,
        C.EDIT_TIME_ENTRY: S.TEAM,
        C.APPROVE_TIMESHEET: S.TEAM,
        C.VIEW_TIME: S.TEAM,
        C.GENERATE_REPORTS: S.TEAM,
        C.SCHEDULE_REPORTS: S.TEAM,
        C.VIEW_INSIGHTS: S.TEAM,
    },
    Role.MEMBER: {
        C.CREATE_TASK: S.OWN,
        C.EDIT_TASK: S.OWN,  # status and comments only; field-level limits live in the API layer
        C.LOG_TIME: S.OWN,
        C.EDIT_TIME_ENTRY: S.OWN,  # only before approval
        C.VIEW_TIME: S.OWN,
        C.GENERATE_REPORTS: S.OWN,
        C.VIEW_INSIGHTS: S.OWN,
    },
    Role.VIEWER: {
        C.VIEW_TIME: S.ALL,
        C.GENERATE_REPORTS: S.ALL,
        C.SCHEDULE_REPORTS: S.ALL,
        C.VIEW_INSIGHTS: S.ALL,
        C.VIEW_AUDIT_LOG: S.ALL,
    },
}


def scope_for(user, capability):
    """Return the Scope a user holds for a capability (NONE if denied)."""
    if user is None or not getattr(user, "is_authenticated", False) or not user.is_active:
        return Scope.NONE
    return ROLE_CAPABILITIES.get(user.role, {}).get(Capability(capability), Scope.NONE)


def has_capability(user, capability):
    return scope_for(user, capability) is not Scope.NONE
