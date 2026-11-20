from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),

    # API docs (open without login)
    path("api/v1/schema/", SpectacularAPIView.as_view(permission_classes=[AllowAny]), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[AllowAny]), name="docs"),

    # App URLs
    path("api/v1/accounts/", include("apps.accounts.urls")),
    path("api/v1/audit/", include("apps.audit.urls")),
    path("api/v1/core/", include("apps.core.urls")),
    path("api/v1/organizations/", include("apps.organizations.urls")),
    path("api/v1/projects/", include("apps.projects.urls")),
    path("api/v1/teams/", include("apps.teams.urls")),
]
