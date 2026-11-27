from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    label = "tasks"

    def ready(self):
        from django.db.models import Q

        from apps.rbac.adapters import ScopeAdapter, register

        from . import handlers  # noqa: F401 - connects signal receivers
        from .models import Task

        def _own_check(user, task) -> bool:
            if user.pk in (task.reviewer_id, task.created_by_id):
                return True
            if "assignees" in getattr(task, "_prefetched_objects_cache", {}):  # board/list: no query per task
                return any(a.user_id == user.pk for a in task.assignees.all())
            return task.assignees.filter(user_id=user.pk).exists()

        register(
            Task,
            ScopeAdapter(
                own_q=lambda u: Q(assignees__user_id=u.pk) | Q(reviewer_id=u.pk) | Q(created_by_id=u.pk),
                own_check=_own_check,
                team_q=lambda ids: Q(project__team_id__in=ids),
                team_ids_of=lambda t: {t.project.team_id},
                project_q=lambda ids: Q(project_id__in=ids),
                project_ids_of=lambda t: {t.project_id},
                needs_distinct=True,
            ),
        )
