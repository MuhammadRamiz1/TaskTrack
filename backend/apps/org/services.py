"""Teams, projects, memberships, holidays and leave."""

from django.db import IntegrityError, transaction
from django.db.models import F

from apps.accounts.models import User
from apps.audit.services import diff, record, snapshot
from apps.common.exceptions import Conflict, InvalidInput
from apps.rbac import policy
from apps.rbac.catalogue import RoleKey
from apps.rbac.models import Role, UserRole

from . import scopes
from .models import Holiday, LeaveDay, Project, ProjectMember, Team, TeamMember

TEAM_FIELDS = ["name", "description"]
PROJECT_FIELDS = ["name", "description", "status", "owner", "start_date", "end_date"]


def _company_users(actor, user_ids, field="user_ids") -> list[User]:
    ids = set(user_ids)
    users = list(User.objects.filter(pk__in=ids, company_id=actor.company_id).exclude(status=User.Status.DEACTIVATED))
    if len(users) != len(ids):
        raise InvalidInput(details={field: ["One or more employees do not exist or are deactivated."]})
    return users


def _saved(fn, field: str, message: str):
    try:
        with transaction.atomic():
            return fn()
    except IntegrityError as exc:
        raise InvalidInput(details={field: [message]}) from exc


# --- Teams --------------------------------------------------------------------------


def create_team(*, actor, name: str, description: str = "") -> Team:
    policy.require(actor, "team.manage")
    team = _saved(
        lambda: Team.objects.create(company_id=actor.company_id, name=name, description=description),
        "name",
        "A team with this name already exists.",
    )
    record(actor=actor, action="org.team.created", entity=team, new_value={"name": name})
    return team


def update_team(*, actor, team: Team, data: dict) -> Team:
    policy.require(actor, "team.manage", team, view_code="team.view")
    fields = [f for f in TEAM_FIELDS if f in data]
    before = snapshot(team, fields)
    for f in fields:
        setattr(team, f, data[f])
    _saved(team.save, "name", "A team with this name already exists.")
    old, new = diff(before, snapshot(team, fields))
    if new:
        record(actor=actor, action="org.team.updated", entity=team, old_value=old, new_value=new)
    return team


def archive_team(*, actor, team: Team) -> Team:
    policy.require(actor, "team.manage", team, view_code="team.view")
    if team.projects.exclude(status=Project.Status.ARCHIVED).exists():
        raise Conflict("Archive or move the team's projects first.", code="team_has_active_projects")
    team.is_archived = True
    team.save(update_fields=["is_archived", "updated_at"])
    record(actor=actor, action="org.team.archived", entity=team)
    return team


def add_team_members(*, actor, team: Team, user_ids: list) -> list[TeamMember]:
    policy.require(actor, "team.manage", team, view_code="team.view")
    users = _company_users(actor, user_ids)
    existing = set(team.memberships.values_list("user_id", flat=True))
    created = [
        TeamMember.objects.create(company_id=team.company_id, team=team, user=u) for u in users if u.pk not in existing
    ]
    if created:
        record(
            actor=actor,
            action="org.team.members_added",
            entity=team,
            new_value={"user_ids": [m.user_id for m in created]},
        )
    scopes.clear(actor)
    return created


def remove_team_member(*, actor, team: Team, user_id) -> None:
    policy.require(actor, "team.manage", team, view_code="team.view")
    membership = team.memberships.filter(user_id=user_id).first()
    if membership is None:
        raise InvalidInput(details={"user_id": ["Not a member of this team."]})
    if team.lead_id == membership.user_id:
        _clear_lead(team)
    membership.delete()
    record(actor=actor, action="org.team.member_removed", entity=team, old_value={"user_id": user_id})


def _clear_lead(team: Team) -> None:
    if team.lead_id:
        UserRole.objects.filter(user_id=team.lead_id, team=team, role__key=RoleKey.TEAM_LEAD).delete()
        User.objects.filter(pk=team.lead_id).update(rbac_version=F("rbac_version") + 1)
    team.lead = None
    team.save(update_fields=["lead", "updated_at"])


def set_team_lead(*, actor, team: Team, user_id) -> Team:
    """Make ``user_id`` the lead: team member + TEAM_LEAD role bound to this team."""
    policy.require(actor, "team.manage", team, view_code="team.view")
    policy.require(actor, "employee.assign_role")
    (user,) = _company_users(actor, [user_id], "user_id")
    old_lead = team.lead_id
    if old_lead == user.pk:
        return team
    _clear_lead(team)
    TeamMember.objects.get_or_create(company_id=team.company_id, team=team, user=user)
    role = Role.objects.get(company_id=team.company_id, key=RoleKey.TEAM_LEAD)
    UserRole.objects.get_or_create(
        company_id=team.company_id, user=user, role=role, team=team, project=None, defaults={"granted_by": actor}
    )
    User.objects.filter(pk=user.pk).update(rbac_version=F("rbac_version") + 1)
    team.lead = user
    team.save(update_fields=["lead", "updated_at"])
    record(
        actor=actor,
        action="org.team.lead_set",
        entity=team,
        old_value={"lead_id": old_lead},
        new_value={"lead_id": user.pk},
    )
    return team


def set_employee_teams(*, actor, target: User, team_ids: list) -> list[Team]:
    policy.require(actor, "employee.assign_team", target, view_code="employee.view_private")
    teams = list(Team.objects.filter(pk__in=set(team_ids), is_archived=False))
    if len(teams) != len(set(team_ids)):
        raise InvalidInput(details={"team_ids": ["Unknown or archived team."]})
    before = set(TeamMember.objects.filter(user=target).values_list("team_id", flat=True))
    after = {t.pk for t in teams}
    for team in Team.objects.filter(pk__in=before - after, lead_id=target.pk):
        _clear_lead(team)
    TeamMember.objects.filter(user=target, team_id__in=before - after).delete()
    for team in teams:
        if team.pk not in before:
            TeamMember.objects.create(company_id=target.company_id, team=team, user=target)
    if before != after:
        record(
            actor=actor,
            action="employee.teams_set",
            entity=target,
            old_value={"team_ids": sorted(map(str, before))},
            new_value={"team_ids": sorted(map(str, after))},
        )
    return teams


# --- Projects --------------------------------------------------------------------------


def create_project(*, actor, team: Team, data: dict) -> Project:
    policy.require(actor, "project.manage", team, view_code="team.view")
    if team.is_archived:
        raise Conflict("The team is archived.", code="team_archived")
    owner = data.get("owner") or actor
    if owner.company_id != actor.company_id:
        raise InvalidInput(details={"owner_id": ["Unknown employee."]})
    project = _saved(
        lambda: Project.objects.create(
            company_id=actor.company_id,
            team=team,
            key=data["key"],
            name=data["name"],
            description=data.get("description", ""),
            owner=owner,
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
        ),
        "key",
        "A project with this key already exists.",
    )
    ProjectMember.objects.create(company_id=project.company_id, project=project, user=owner)
    record(
        actor=actor,
        action="org.project.created",
        entity=project,
        new_value=snapshot(project, ["key", "name", "team", "owner"]),
    )
    scopes.clear(actor)
    return project


def update_project(*, actor, project: Project, data: dict) -> Project:
    policy.require(actor, "project.manage", project, view_code="project.view")
    fields = [f for f in PROJECT_FIELDS if f in data]
    before = snapshot(project, fields)
    for f in fields:
        setattr(project, f, data[f])
    if project.owner_id:
        ProjectMember.objects.get_or_create(company_id=project.company_id, project=project, user_id=project.owner_id)
    if project.start_date and project.end_date and project.end_date < project.start_date:
        raise InvalidInput(details={"end_date": ["End date must be on or after the start date."]})
    project.save()
    old, new = diff(before, snapshot(project, fields))
    if new:
        record(actor=actor, action="org.project.updated", entity=project, old_value=old, new_value=new)
    return project


def archive_project(*, actor, project: Project) -> Project:
    return update_project(actor=actor, project=project, data={"status": Project.Status.ARCHIVED})


def add_project_members(*, actor, project: Project, user_ids: list) -> list[ProjectMember]:
    policy.require(actor, "project.member.manage", project, view_code="project.view")
    users = _company_users(actor, user_ids)
    existing = set(project.memberships.values_list("user_id", flat=True))
    created = [
        ProjectMember.objects.create(company_id=project.company_id, project=project, user=u)
        for u in users
        if u.pk not in existing
    ]
    if created:
        record(
            actor=actor,
            action="org.project.members_added",
            entity=project,
            new_value={"user_ids": [m.user_id for m in created]},
        )
    return created


def remove_project_member(*, actor, project: Project, user_id) -> None:
    policy.require(actor, "project.member.manage", project, view_code="project.view")
    membership = project.memberships.filter(user_id=user_id).first()
    if membership is None:
        raise InvalidInput(details={"user_id": ["Not a member of this project."]})
    if project.owner_id == membership.user_id:
        raise Conflict("Change the project owner before removing them.", code="project_owner")
    membership.delete()
    record(actor=actor, action="org.project.member_removed", entity=project, old_value={"user_id": user_id})


# --- Holidays and leave ------------------------------------------------------------------


def create_holiday(*, actor, date, name: str) -> Holiday:
    policy.require(actor, "holiday.manage")
    holiday = _saved(
        lambda: Holiday.objects.create(company_id=actor.company_id, date=date, name=name),
        "date",
        "There is already a holiday on this date.",
    )
    record(actor=actor, action="org.holiday.created", entity=holiday, new_value={"date": date, "name": name})
    return holiday


def delete_holiday(*, actor, holiday: Holiday) -> None:
    policy.require(actor, "holiday.manage")
    record(
        actor=actor,
        action="org.holiday.deleted",
        entity=holiday,
        old_value={"date": holiday.date, "name": holiday.name},
    )
    holiday.delete()


def record_leave(*, actor, user: User, data: dict) -> LeaveDay:
    probe = LeaveDay(company_id=user.company_id, user=user)
    policy.require(actor, "leave.manage", probe, view_code="leave.view")
    leave = _saved(
        lambda: LeaveDay.objects.create(company_id=user.company_id, user=user, recorded_by=actor, **data),
        "date",
        "Leave is already recorded for this date.",
    )
    record(
        actor=actor,
        action="org.leave.recorded",
        entity=leave,
        new_value={"user_id": user.pk, "date": leave.date, "kind": leave.kind, "half_day": leave.half_day},
    )
    return leave


def delete_leave(*, actor, leave: LeaveDay) -> None:
    policy.require(actor, "leave.manage", leave, view_code="leave.view")
    record(
        actor=actor, action="org.leave.deleted", entity=leave, old_value={"user_id": leave.user_id, "date": leave.date}
    )
    leave.delete()
