from django.apps import AppConfig


class RbacConfig(AppConfig):
    name = "apps.rbac"
    label = "rbac"

    def ready(self):
        from apps.rbac.adapters import ScopeAdapter, register

        from .models import Role

        register(Role, ScopeAdapter())
