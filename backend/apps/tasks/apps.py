from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    label = "tasks"

    def ready(self):
        from django.db.models import Q

        from apps.rbac.adapters import ScopeAdapter, register

        from . import handlers  # noqa: F401 - connects signal receivers
        from .models import Task

        register(
            Task,
            ScopeAdapter(
                own_q=lambda u: Q(assignees__user_id=u.pk) | Q(reviewer_id=u.pk) | Q(created_by_id=u.pk),
                own_check=lambda u, t: (
                    u.pk in (t.reviewer_id, t.created_by_id) or t.assignees.filter(user_id=u.pk).exists()
                ),
                team_q=lambda ids: Q(project__team_id__in=ids),
                team_ids_of=lambda t: {t.project.team_id},
                project_q=lambda ids: Q(project_id__in=ids),
                project_ids_of=lambda t: {t.project_id},
                needs_distinct=True,
            ),
        )
