from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("demo/", views.demo_list, name="demo-list"),
    path("demo/create/", views.demo_create, name="demo-create"),
    path("demo/<int:pk>/", views.demo_detail, name="demo-detail"),
    path("api/accounts/", include("apps.accounts.urls")),
    path("api/audits/", include("apps.companies.urls")),
    path("api/core/", include("apps.tasks.urls")),
    path("api/projects/", include("apps.screenshots.urls")),
    path("api/teams/", include("apps.analytics.urls"))
]
