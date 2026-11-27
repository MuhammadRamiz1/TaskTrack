from django.apps import AppConfig
from django.conf import settings
from django.db import connection
from django.db.models.signals import post_migrate


def grant_runtime_privileges(sender, **kwargs):
    """Give the runtime role DML on every table (owner role creates them).

    Runs after every migrate, including the pytest database. The audit table is
    append-only: the runtime role may INSERT and SELECT but not UPDATE or DELETE.
    """
    if sender.name != "apps.common" or connection.vendor != "postgresql":
        return
    role = settings.DB_APP_ROLE
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        if cursor.fetchone() is None:
            return
        cursor.execute("SELECT current_user")
        if cursor.fetchone()[0] == role:
            return
        cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"')
        cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        cursor.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON audit_auditlog FROM "{role}"')


class CommonConfig(AppConfig):
    name = "apps.common"
    label = "common"

    def ready(self):
        # common is listed before the other apps, but post_migrate fires for every app;
        # the handler runs once (sender == common) after all migrations are applied.
        post_migrate.connect(grant_runtime_privileges, dispatch_uid="common.grant_runtime_privileges")
