"""Timesheets are task-based now: no weekly submission or approval, so their permissions go."""

from django.db import migrations

CODES = ["timesheet.submit", "timesheet.approve"]


def remove(apps, schema_editor):
    apps.get_model("rbac", "RolePermission")._base_manager.filter(permission__code__in=CODES).delete()
    apps.get_model("rbac", "Permission")._base_manager.filter(code__in=CODES).delete()


class Migration(migrations.Migration):
    dependencies = [("rbac", "0004_userrole_bindings")]

    # Not restored on rollback: the catalogue no longer defines them.
    operations = [migrations.RunPython(remove, migrations.RunPython.noop)]
