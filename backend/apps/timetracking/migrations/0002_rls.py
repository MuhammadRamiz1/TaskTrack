from django.db import migrations

from apps.common.rls import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("timetracking", "0001_initial")]

    operations = [
        tenant_rls("timetracking_timesheet"),
        tenant_rls("timetracking_timeentry"),
        tenant_rls("timetracking_timesheetapproval"),
    ]
