from django.db import migrations

from apps.common.rls import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("reviews", "0001_initial")]

    operations = [tenant_rls("reviews_taskreview")]
