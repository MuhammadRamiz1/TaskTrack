from django.urls import path

from apps.org import views as org
from apps.rbac.views import GrantableRolesView

from . import views_hr as v

urlpatterns = [
    path("employees/", v.EmployeeListView.as_view(), name="hr-employees"),
    path("employees/import/preview/", v.EmployeeImportPreviewView.as_view(), name="hr-employee-import-preview"),
    path("employees/import/", v.EmployeeImportView.as_view(), name="hr-employee-import"),
    path("employees/<uuid:user_id>/", v.EmployeeDetailView.as_view(), name="hr-employee-detail"),
    path("employees/<uuid:user_id>/invite/", v.EmployeeInviteView.as_view(), name="hr-employee-invite"),
    path(
        "employees/<uuid:user_id>/password-reset-link/",
        v.EmployeeResetLinkView.as_view(),
        name="hr-employee-reset-link",
    ),
    path(
        "employees/<uuid:user_id>/temporary-password/",
        v.EmployeeTemporaryPasswordView.as_view(),
        name="hr-employee-temporary-password",
    ),
    path("employees/<uuid:user_id>/deactivate/", v.EmployeeDeactivateView.as_view(), name="hr-employee-deactivate"),
    path("employees/<uuid:user_id>/reactivate/", v.EmployeeReactivateView.as_view(), name="hr-employee-reactivate"),
    path("employees/<uuid:user_id>/offboard/", v.EmployeeOffboardView.as_view(), name="hr-employee-offboard"),
    path(
        "employees/<uuid:user_id>/revoke-sessions/",
        v.EmployeeRevokeSessionsView.as_view(),
        name="hr-employee-revoke-sessions",
    ),
    path("employees/<uuid:user_id>/roles/", v.EmployeeRolesView.as_view(), name="hr-employee-roles"),
    path(
        "employees/<uuid:user_id>/roles/<uuid:user_role_id>/",
        v.EmployeeRoleDetailView.as_view(),
        name="hr-employee-role-detail",
    ),
    path("employees/<uuid:user_id>/teams/", org.EmployeeTeamsView.as_view(), name="hr-employee-teams"),
    path("roles/", GrantableRolesView.as_view(), name="hr-grantable-roles"),
    path("holidays/", org.HolidayListView.as_view(), name="hr-holidays"),
    path("holidays/<uuid:holiday_id>/", org.HolidayDetailView.as_view(), name="hr-holiday-detail"),
    path("leave/", org.LeaveListView.as_view(), name="hr-leave"),
    path("leave/<uuid:leave_id>/", org.LeaveDetailView.as_view(), name="hr-leave-detail"),
]
