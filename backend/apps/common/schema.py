"""OpenAPI generator that works with fail-closed tenant managers.

drf-spectacular introspects filters with ``Model._default_manager.none()``. Tenant
managers raise without a context, so introspection runs in a Python-only platform
state. Only empty querysets are built; no query reaches the database, and the
Postgres RLS settings are left untouched.
"""

from drf_spectacular.generators import SchemaGenerator

from . import tenancy


class TenantSafeSchemaGenerator(SchemaGenerator):
    def get_schema(self, request=None, public=False):
        previous = tenancy.current()
        tenancy.set_python_state(tenancy.TenantState(tenancy.Mode.PLATFORM))
        try:
            return super().get_schema(request=request, public=public)
        finally:
            tenancy.set_python_state(previous)
