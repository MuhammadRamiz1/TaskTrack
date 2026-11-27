import django_filters
from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.response import Response

from apps.common.exceptions import NotFound
from apps.common.pagination import PageNumberPagination
from apps.common.views import LIST_FILTERS, PlatformAPIView, TenantAPIView, schema_generation

from .describe import describe_entries
from .models import AuditLog


class AuditChange(serializers.Serializer):
    field = serializers.CharField()
    before = serializers.CharField()
    after = serializers.CharField()


class AuditLogOutput(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField(help_text="What happened, as a plain-English sentence.")
    changes = serializers.SerializerMethodField(help_text="Changed fields in words (no codes or ids).")

    def _described(self, entry) -> dict:
        described = self.context.get("described")
        if described is None or entry.pk not in described:
            described = describe_entries([entry])
        return described[entry.pk]

    def get_summary(self, entry) -> str:
        return self._described(entry)["summary"]

    @extend_schema_field(AuditChange(many=True))
    def get_changes(self, entry) -> list[dict]:
        return self._described(entry)["changes"]

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "company_id",
            "actor_id",
            "actor_email",
            "impersonator_id",
            "action",
            "summary",
            "changes",
            "entity_type",
            "entity_id",
            "old_value",
            "new_value",
            "ip",
            "user_agent",
            "request_id",
        ]


#: Groups shown to people instead of action codes.
CATEGORIES = {
    "tasks": ("task.", "review."),
    "organization": ("org.",),
    "people": ("employee.", "invite.", "password.", "profile."),
    "security": ("auth.", "impersonation.", "platform.impersonation."),
    "roles": ("rbac.",),
    "time": ("time.",),
    "reports": ("report.",),
    "settings": ("company.", "workflow.", "notification."),
}


class AuditFilter(django_filters.FilterSet):
    actor = django_filters.UUIDFilter(field_name="actor_id")
    category = django_filters.ChoiceFilter(
        choices=[(k, k.title()) for k in CATEGORIES], method="filter_category", label="Kind of activity"
    )
    action = django_filters.CharFilter(field_name="action", lookup_expr="startswith")
    entity_type = django_filters.CharFilter()
    entity_id = django_filters.CharFilter()
    date_from = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lt")

    class Meta:
        model = AuditLog
        fields = ["actor", "category", "action", "entity_type", "entity_id", "date_from", "date_to"]

    def filter_category(self, queryset, name, value):
        match = Q()
        for prefix in CATEGORIES[value]:
            match |= Q(action__startswith=prefix)
        return queryset.filter(match)


class PlatformAuditFilter(AuditFilter):
    company = django_filters.UUIDFilter(field_name="company_id")

    class Meta(AuditFilter.Meta):
        fields = [*AuditFilter.Meta.fields, "company"]


class _AuditList:
    pagination_class = PageNumberPagination
    search_fields = ["action", "actor_email", "entity_type", "entity_id"]
    ordering_fields = ["created_at", "action"]
    ordering = ["-created_at"]

    @extend_schema(responses=AuditLogOutput(many=True), tags=["audit"])
    def get(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        context = {"described": describe_entries(page)}
        return self.get_paginated_response(AuditLogOutput(page, many=True, context=context).data)


class AuditListView(_AuditList, TenantAPIView):
    """Company audit log. Tenant context restricts it to the caller's company."""

    filter_backends = LIST_FILTERS
    permission_map = {"GET": "audit.view"}
    filterset_class = AuditFilter

    def get_queryset(self):
        if schema_generation(self):
            return AuditLog._base_manager.none()
        return AuditLog.objects.filter(company_id=self.request.user.company_id)


class AuditDetailView(TenantAPIView):
    queryset = AuditLog._base_manager.none()  # schema hint only
    permission_map = {"GET": "audit.view"}

    @extend_schema(responses=AuditLogOutput, tags=["audit"])
    def get(self, request, entry_id):
        entry = AuditLog.objects.filter(pk=entry_id, company_id=request.user.company_id).first()
        if entry is None:
            raise NotFound()
        return Response(AuditLogOutput(entry).data)


class PlatformAuditListView(_AuditList, PlatformAPIView):
    filter_backends = LIST_FILTERS
    permission_map = {"GET": "platform.audit.view"}
    filterset_class = PlatformAuditFilter

    def get_queryset(self):
        if schema_generation(self):
            return AuditLog._base_manager.none()
        return AuditLog.objects.all()
