from django.conf import settings
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.common import health
from apps.notifications import api as notifications_api
from apps.reports import api as reports_api
from apps.reviews import api as reviews_api
from apps.timetracking import api as time_api

docs_permission = [AllowAny] if settings.DOCS_PUBLIC else [IsAuthenticated]

api_v1 = [
    path("auth/", include("apps.accounts.urls_auth")),
    path("hr/", include("apps.accounts.urls_hr")),
    path("platform/", include("apps.companies.urls_platform")),
    path("company/", include("apps.companies.urls_company")),
    path("audit/", include("apps.audit.urls")),
    path("org/", include("apps.org.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("tasks/", include(reviews_api.task_urlpatterns)),
    path("tasks/", include(time_api.task_urlpatterns)),
    path("reviews/", include(reviews_api.urlpatterns)),
    path("time/", include(time_api.urlpatterns)),
    path("notifications/", include(notifications_api.urlpatterns)),
    path("dashboards/", include(reports_api.dashboard_urlpatterns)),
    path("reports/", include(reports_api.urlpatterns)),
    path("schema/", SpectacularAPIView.as_view(permission_classes=docs_permission), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=docs_permission), name="docs"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema", permission_classes=docs_permission), name="redoc"),
]

urlpatterns = [
    path("health/live", health.live, name="health-live"),
    path("health/ready", health.ready, name="health-ready"),
    path("api/v1/", include(api_v1)),
]
