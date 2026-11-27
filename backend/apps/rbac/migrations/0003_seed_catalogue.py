from django.db import migrations


def load(apps, schema_editor):
    from apps.rbac.catalogue import sync_catalogue

    sync_catalogue(
        apps.get_model("rbac", "Permission"), apps.get_model("rbac", "Role"), apps.get_model("rbac", "RolePermission")
    )


class Migration(migrations.Migration):
    dependencies = [("rbac", "0002_rls")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
