from django.db import migrations

from apps.common.rls import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("companies", "0001_initial")]

    operations = [tenant_rls("companies_company", column="id")]
