from django.db import migrations


def forwards(apps, schema_editor):
    from apps.rbac.catalogue import sync_catalogue  # your import path from step 3

    sync_catalogue(
        apps.get_model("rbac", "Permission"),
        apps.get_model("rbac", "Role"),
        apps.get_model("rbac", "RolePermission"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("rbac", "0005_sync_hr_task_report_view"),  # leave what Django generated
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
