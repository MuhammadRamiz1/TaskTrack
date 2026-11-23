"""TEAM and PROJECT scope resolution, registered with the rbac policy layer.

Resolution for one grant (from docs/architecture/03-rbac.md section 3.2):

* TEAM:    bound team -> {that team}; unbound -> teams the user is a member of.
* PROJECT: bound project -> {it}; bound team -> that team's projects;
           unbound -> projects the user is a member or owner of.

Results are cached on the user object for the duration of the request.
"""

from django.db.models import Q

from apps.rbac.adapters import ScopeAdapter, register, set_resolvers


def _cache(user) -> dict:
    cache = getattr(user, "_scope_cache", None)
    if cache is None:
        cache = user._scope_cache = {}
    return cache


def team_ids_for(user, bound_team) -> set:
    from .models import TeamMember

    if bound_team:
        return {bound_team}
    cache = _cache(user)
    if "teams" not in cache:
        cache["teams"] = set(
            TeamMember.objects.filter(user_id=user.pk, team__is_archived=False).values_list("team_id", flat=True)
        )
    return cache["teams"]


def project_ids_for(user, bound_team, bound_project) -> set:
    from .models import Project, ProjectMember

    if bound_project:
        return {bound_project}
    cache = _cache(user)
    key = ("projects", bound_team)
    if key not in cache:
        if bound_team:
            ids = set(Project.objects.filter(team_id=bound_team).values_list("pk", flat=True))
        else:
            ids = set(ProjectMember.objects.filter(user_id=user.pk).values_list("project_id", flat=True))
            ids |= set(Project.objects.filter(owner_id=user.pk).values_list("pk", flat=True))
        cache[key] = ids
    return cache[key]


def clear(user) -> None:
    if hasattr(user, "_scope_cache"):
        del user._scope_cache


def _user_team_ids(user_obj) -> set:
    return set(user_obj.team_memberships.values_list("team_id", flat=True))


def _user_project_ids(user_obj) -> set:
    return set(user_obj.project_memberships.values_list("project_id", flat=True))


def register_all() -> None:
    from apps.accounts.models import User

    from .models import LeaveDay, Project, Team

    set_resolvers(team=team_ids_for, project=project_ids_for)

    register(
        User,
        ScopeAdapter(
            own_q=lambda u: Q(pk=u.pk),
            own_check=lambda u, o: o.pk == u.pk,
            team_q=lambda ids: Q(team_memberships__team_id__in=ids),
            team_ids_of=_user_team_ids,
            project_q=lambda ids: Q(project_memberships__project_id__in=ids),
            project_ids_of=_user_project_ids,
            needs_distinct=True,
        ),
    )
    register(
        Team,
        ScopeAdapter(
            own_q=lambda u: Q(memberships__user_id=u.pk),
            own_check=lambda u, o: o.memberships.filter(user_id=u.pk).exists(),
            team_q=lambda ids: Q(pk__in=ids),
            team_ids_of=lambda o: {o.pk},
            needs_distinct=True,
        ),
    )
    register(
        Project,
        ScopeAdapter(
            own_q=lambda u: Q(memberships__user_id=u.pk) | Q(owner_id=u.pk),
            own_check=lambda u, o: o.owner_id == u.pk or o.memberships.filter(user_id=u.pk).exists(),
            team_q=lambda ids: Q(team_id__in=ids),
            team_ids_of=lambda o: {o.team_id},
            project_q=lambda ids: Q(pk__in=ids),
            project_ids_of=lambda o: {o.pk},
            needs_distinct=True,
        ),
    )
    register(
        LeaveDay,
        ScopeAdapter(
            own_q=lambda u: Q(user_id=u.pk),
            own_check=lambda u, o: o.user_id == u.pk,
            team_q=lambda ids: Q(user__team_memberships__team_id__in=ids),
            team_ids_of=lambda o: _user_team_ids(o.user),
            needs_distinct=True,
        ),
    )
