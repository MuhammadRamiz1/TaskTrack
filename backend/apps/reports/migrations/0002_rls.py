from django.db import migrations

from apps.common.rls import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("reports", "0001_initial")]

    operations = [tenant_rls("reports_scheduledreport"), tenant_rls("reports_reportexport")]
