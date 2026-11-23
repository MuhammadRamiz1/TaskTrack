from django.urls import path

from . import views as v

urlpatterns = [
    path("", v.AuditListView.as_view(), name="audit-list"),
    path("<uuid:entry_id>/", v.AuditDetailView.as_view(), name="audit-detail"),
]
