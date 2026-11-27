from django.apps import AppConfig


class CompaniesConfig(AppConfig):
    name = "apps.companies"
    label = "companies"

    def ready(self):
        from apps.rbac.adapters import ScopeAdapter, register

        from .models import Company

        register(Company, ScopeAdapter(company_attr="id"))
