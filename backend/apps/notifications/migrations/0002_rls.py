from django.db import migrations

from apps.common.rls import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]

    operations = [tenant_rls("notifications_notification")]
