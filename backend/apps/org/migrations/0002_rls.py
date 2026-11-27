from django.db import migrations

from apps.common.rls import tenant_rls

TABLES = ["org_team", "org_teammember", "org_project", "org_projectmember", "org_leaveday", "org_holiday"]


class Migration(migrations.Migration):
    dependencies = [("org", "0001_initial")]

    operations = [tenant_rls(t) for t in TABLES]
