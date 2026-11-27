"""Drop weekly timesheets: time lives on tasks and locks by task status."""

from django.db import migrations

from apps.common.rls import tenant_rls


def drop_rls(table: str) -> migrations.RunSQL:
    """Inverse of ``tenant_rls``: the policy depends on company_id, so it must go first."""
    rls = tenant_rls(table)
    return migrations.RunSQL(sql=rls.reverse_sql, reverse_sql=rls.sql)


class Migration(migrations.Migration):
    dependencies = [("timetracking", "0002_rls")]

    operations = [
        migrations.RemoveField(model_name="timeentry", name="timesheet"),
        drop_rls("timetracking_timesheetapproval"),
        drop_rls("timetracking_timesheet"),
        migrations.DeleteModel(name="TimesheetApproval"),
        migrations.DeleteModel(name="Timesheet"),
    ]
