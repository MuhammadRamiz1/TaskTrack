from django.urls import path

from apps.accounts import views_platform as imp
from apps.audit.views import PlatformAuditListView

from . import views as v

urlpatterns = [
    path("companies/", v.CompanyListView.as_view(), name="platform-companies"),
    path("companies/<uuid:company_id>/", v.CompanyDetailView.as_view(), name="platform-company-detail"),
    path("companies/<uuid:company_id>/suspend/", v.CompanySuspendView.as_view(), name="platform-company-suspend"),
    path("companies/<uuid:company_id>/activate/", v.CompanyActivateView.as_view(), name="platform-company-activate"),
    path("companies/<uuid:company_id>/usage/", v.CompanyUsageView.as_view(), name="platform-company-usage"),
    path("companies/<uuid:company_id>/admins/", v.CompanyAdminCreateView.as_view(), name="platform-company-admins"),
    path("companies/<uuid:company_id>/users/", v.CompanyUsersView.as_view(), name="platform-company-users"),
    path("plans/", v.PlanListView.as_view(), name="platform-plans"),
    path("plans/<uuid:plan_id>/", v.PlanDetailView.as_view(), name="platform-plan-detail"),
    path("impersonations/", imp.ImpersonationStartView.as_view(), name="platform-impersonations"),
    path(
        "impersonations/<uuid:session_id>/end/", imp.ImpersonationEndView.as_view(), name="platform-impersonation-end"
    ),
    path("audit/", PlatformAuditListView.as_view(), name="platform-audit"),
]
