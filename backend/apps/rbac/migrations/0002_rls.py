from django.db import migrations

from apps.common.rls import tenant_rls

# Role grants have no company column: a grant is visible when its role is visible,
# and the sub-select is itself filtered by the rbac_role policies.
ROLEPERMISSION_RLS = """
ALTER TABLE rbac_rolepermission ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON rbac_rolepermission
    USING (EXISTS (SELECT 1 FROM rbac_role r WHERE r.id = role_id))
    WITH CHECK (
        EXISTS (SELECT 1 FROM rbac_role r WHERE r.id = role_id AND (
            r.company_id = NULLIF(current_setting('app.company_id', true), '')::uuid
            OR current_setting('app.platform', true) = 'on'))
    );
"""


class Migration(migrations.Migration):
    dependencies = [("rbac", "0001_initial")]

    operations = [
        tenant_rls("rbac_role", shared_null_rows=True),
        tenant_rls("rbac_userrole"),
        migrations.RunSQL(
            ROLEPERMISSION_RLS,
            reverse_sql="DROP POLICY IF EXISTS tenant_isolation ON rbac_rolepermission;"
            "ALTER TABLE rbac_rolepermission DISABLE ROW LEVEL SECURITY;",
        ),
    ]
