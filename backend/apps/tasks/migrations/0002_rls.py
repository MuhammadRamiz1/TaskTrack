from django.db import migrations

from apps.common.rls import tenant_rls

TABLES = [
    "tasks_task",
    "tasks_taskassignee",
    "tasks_taskchecklist",
    "tasks_checklistitem",
    "tasks_taskdependency",
    "tasks_taskcomment",
    "tasks_commentmention",
    "tasks_taskattachment",
    "tasks_taskactivity",
    "tasks_statustransitionrule",
]


class Migration(migrations.Migration):
    dependencies = [("tasks", "0001_initial")]

    operations = [tenant_rls(t) for t in TABLES]
