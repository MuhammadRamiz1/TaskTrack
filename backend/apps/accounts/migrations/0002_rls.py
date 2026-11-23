from django.db import migrations

from apps.common.rls import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        tenant_rls("accounts_user", auth_lookup=True),
        tenant_rls("accounts_invitetoken", auth_lookup=True),
        tenant_rls("accounts_passwordresettoken", auth_lookup=True),
        tenant_rls("accounts_usersession"),
        tenant_rls("accounts_recoverycode"),
        tenant_rls("accounts_impersonationsession"),
    ]
