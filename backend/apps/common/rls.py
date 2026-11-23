"""Migration helpers that enable Postgres Row-Level Security on a table.

Policies are permissive, so they are OR-ed:

* ``tenant_isolation`` (all commands): row's company equals ``app.company_id`` or
  ``app.platform`` is on. Applies to SELECT, INSERT, UPDATE and DELETE.
* ``auth_lookup`` (SELECT only, optional): ``app.auth_lookup`` is on.
* ``shared_rows`` (SELECT only, optional): rows with NULL company (system templates).

With no settings, ``current_setting(..., true)`` is NULL/empty and no row matches.
"""

from django.db import migrations

COMPANY_MATCH = "{column} = NULLIF(current_setting('app.company_id', true), '')::uuid"
PLATFORM_ON = "current_setting('app.platform', true) = 'on'"
AUTH_ON = "current_setting('app.auth_lookup', true) = 'on'"


def tenant_rls(
    table: str, *, column: str = "company_id", auth_lookup: bool = False, shared_null_rows: bool = False
) -> migrations.RunSQL:
    condition = f"({COMPANY_MATCH.format(column=column)} OR {PLATFORM_ON})"
    statements = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation ON {table} USING {condition} WITH CHECK {condition}",
    ]
    reverse = [f"DROP POLICY IF EXISTS tenant_isolation ON {table}"]
    if auth_lookup:
        statements.append(f"CREATE POLICY auth_lookup ON {table} FOR SELECT USING ({AUTH_ON})")
        reverse.append(f"DROP POLICY IF EXISTS auth_lookup ON {table}")
    if shared_null_rows:
        statements.append(f"CREATE POLICY shared_rows ON {table} FOR SELECT USING ({column} IS NULL)")
        reverse.append(f"DROP POLICY IF EXISTS shared_rows ON {table}")
    reverse.append(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    return migrations.RunSQL(sql=[s + ";" for s in statements], reverse_sql=[s + ";" for s in reverse])
