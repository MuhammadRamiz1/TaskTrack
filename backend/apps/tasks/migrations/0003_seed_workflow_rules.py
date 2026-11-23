from django.db import migrations


def seed(apps, schema_editor):
    from apps.tasks.workflow_defaults import seed_rules

    Company = apps.get_model("companies", "Company")
    Rule = apps.get_model("tasks", "StatusTransitionRule")
    for company_id in Company.objects.values_list("pk", flat=True):
        seed_rules(company_id, Rule)


class Migration(migrations.Migration):
    dependencies = [("tasks", "0002_rls"), ("companies", "0003_default_plans")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
