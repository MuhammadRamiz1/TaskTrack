from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        from django.db.models import Q

        from apps.rbac.adapters import ScopeAdapter, register

        from . import schema  # noqa: F401 - registers the OpenAPI auth extension
        from .models import User

        # Team/project paths for employees are added by the org module.
        register(User, ScopeAdapter(own_q=lambda u: Q(pk=u.pk), own_check=lambda u, o: o.pk == u.pk))
