from django.db import migrations

from apps.common.rls import tenant_rls

APPEND_ONLY = """
CREATE OR REPLACE FUNCTION audit_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditlog is append-only (% rejected)', TG_OP USING ERRCODE = 'insufficient_privilege';
END;
$$;
CREATE TRIGGER audit_no_update_delete BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_reject_change();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        tenant_rls("audit_auditlog"),
        migrations.RunSQL(
            APPEND_ONLY,
            reverse_sql="DROP TRIGGER IF EXISTS audit_no_update_delete ON audit_auditlog;"
            "DROP FUNCTION IF EXISTS audit_reject_change();",
        ),
    ]
