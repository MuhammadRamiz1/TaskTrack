from django.db import migrations

PLANS = [
    {
        "code": "starter",
        "name": "Starter",
        "max_users": 10,
        "max_storage_mb": 2048,
        "features": {"reports_pdf": False, "scheduled_reports": False},
    },
    {
        "code": "business",
        "name": "Business",
        "max_users": 100,
        "max_storage_mb": 20480,
        "features": {"reports_pdf": True, "scheduled_reports": True},
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "max_users": 1000,
        "max_storage_mb": 204800,
        "features": {"reports_pdf": True, "scheduled_reports": True},
    },
]


def load(apps, schema_editor):
    Plan = apps.get_model("companies", "Plan")
    for plan in PLANS:
        Plan.objects.get_or_create(code=plan["code"], defaults=plan)


class Migration(migrations.Migration):
    dependencies = [("companies", "0002_rls")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
