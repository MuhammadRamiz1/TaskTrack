from django.urls import path

from apps.rbac import views as rbac
from apps.tasks import views as tasks

from . import views as v

urlpatterns = [
    path("settings/", v.CompanySettingsView.as_view(), name="company-settings"),
    path("permissions/", rbac.PermissionCatalogueView.as_view(), name="company-permissions"),
    path("roles/", rbac.RoleListView.as_view(), name="company-roles"),
    path("roles/<uuid:role_id>/", rbac.RoleDetailView.as_view(), name="company-role-detail"),
    path("roles/<uuid:role_id>/permissions/", rbac.RolePermissionsView.as_view(), name="company-role-permissions"),
    path("workflow/rules/", tasks.RuleListView.as_view(), name="company-workflow-rules"),
    path("workflow/rules/reset/", tasks.RuleResetView.as_view(), name="company-workflow-rules-reset"),
    path("workflow/rules/<uuid:rule_id>/", tasks.RuleDetailView.as_view(), name="company-workflow-rule-detail"),
]
