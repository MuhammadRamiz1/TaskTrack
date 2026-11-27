from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "apps.audit"
    label = "audit"

    def ready(self):
        from django.db.models import Q

        from apps.rbac.adapters import ScopeAdapter, register

        from .models import AuditLog

        register(AuditLog, ScopeAdapter(own_q=lambda u: Q(actor_id=u.pk), own_check=lambda u, o: o.actor_id == u.pk))
