from ..models import Task, TaskActivity


def log(task: Task, actor, verb: str, data: dict | None = None) -> TaskActivity:
    from apps.audit.services import _jsonable

    return TaskActivity.objects.create(
        company_id=task.company_id, task=task, actor=actor, verb=verb, data=_jsonable(data or {})
    )
