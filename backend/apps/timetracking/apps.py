from django.apps import AppConfig


class TimetrackingConfig(AppConfig):
    name = "apps.timetracking"
    label = "timetracking"

    def ready(self):
        from django.db.models import Q

        from apps.org.scopes import _user_project_ids, _user_team_ids
        from apps.rbac.adapters import ScopeAdapter, register

        from . import handlers  # noqa: F401 - connects signal receivers
        from .models import TimeEntry, Timesheet

        register(
            TimeEntry,
            ScopeAdapter(
                own_q=lambda u: Q(user_id=u.pk),
                own_check=lambda u, e: e.user_id == u.pk,
                team_q=lambda ids: Q(user__team_memberships__team_id__in=ids),
                team_ids_of=lambda e: _user_team_ids(e.user),
                project_q=lambda ids: Q(task__project_id__in=ids),
                project_ids_of=lambda e: {e.task.project_id},
                needs_distinct=True,
            ),
        )
        register(
            Timesheet,
            ScopeAdapter(
                own_q=lambda u: Q(user_id=u.pk),
                own_check=lambda u, s: s.user_id == u.pk,
                team_q=lambda ids: Q(user__team_memberships__team_id__in=ids),
                team_ids_of=lambda s: _user_team_ids(s.user),
                project_q=lambda ids: Q(user__project_memberships__project_id__in=ids),
                project_ids_of=lambda s: _user_project_ids(s.user),
                needs_distinct=True,
            ),
        )
