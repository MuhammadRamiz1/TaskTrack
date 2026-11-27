from django.urls import path
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response

from apps.accounts.serializers import UserBrief
from apps.common.pagination import CursorPagination
from apps.common.views import TenantAPIView

from . import services
from .models import Notification

HINT = Notification._base_manager.none()
#: Every company user may manage their own notifications; "employee.view" is held by all roles.
OWN = "employee.view"


class NotificationOutput(serializers.ModelSerializer):
    actor = UserBrief(allow_null=True)
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "event_type",
            "title",
            "body",
            "entity_type",
            "entity_id",
            "actor",
            "is_read",
            "read_at",
            "created_at",
        ]

    def get_is_read(self, n) -> bool:
        return n.read_at is not None


class UnreadCountOutput(serializers.Serializer):
    unread = serializers.IntegerField()


class PreferenceSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=60)
    label = serializers.CharField(read_only=True)
    in_app = serializers.BooleanField()
    email = serializers.BooleanField()


class PreferencesInput(serializers.Serializer):
    preferences = PreferenceSerializer(many=True)


class ReadCountOutput(serializers.Serializer):
    count = serializers.IntegerField()


class NotificationListView(TenantAPIView):
    queryset = HINT
    permission_map = {"GET": OWN}
    pagination_class = CursorPagination

    @extend_schema(
        parameters=[OpenApiParameter("unread", bool, description="Only unread notifications")],
        responses=NotificationOutput(many=True),
        tags=["notifications"],
        summary="My notifications, newest first (?unread=true)",
    )
    def get(self, request):
        qs = services.inbox(request.user).select_related("actor")
        if request.query_params.get("unread") in ("true", "1"):
            qs = qs.filter(read_at__isnull=True)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(NotificationOutput(page, many=True).data)


class UnreadCountView(TenantAPIView):
    queryset = HINT
    permission_map = {"GET": OWN}

    @extend_schema(responses=UnreadCountOutput, tags=["notifications"], summary="Unread badge count")
    def get(self, request):
        return Response({"unread": services.inbox(request.user).filter(read_at__isnull=True).count()})


class MarkReadView(TenantAPIView):
    queryset = HINT
    permission_map = {"POST": OWN}

    @extend_schema(request=None, responses=NotificationOutput, tags=["notifications"], summary="Mark as read")
    def post(self, request, notification_id):
        return Response(
            NotificationOutput(services.mark_read(actor=request.user, notification_id=notification_id)).data
        )


class MarkAllReadView(TenantAPIView):
    queryset = HINT
    permission_map = {"POST": OWN}

    @extend_schema(request=None, responses=ReadCountOutput, tags=["notifications"], summary="Mark all as read")
    def post(self, request):
        return Response({"count": services.mark_all_read(actor=request.user)})


class PreferencesView(TenantAPIView):
    queryset = HINT
    pagination_class = None
    permission_map = {"GET": OWN, "PUT": OWN}

    @extend_schema(
        responses=PreferenceSerializer(many=True),
        tags=["notifications"],
        summary="My in-app and email settings per event",
    )
    def get(self, request):
        return Response(services.preferences_for(request.user))

    @extend_schema(
        request=PreferencesInput,
        responses=PreferenceSerializer(many=True),
        tags=["notifications"],
        summary="Update notification settings",
    )
    def put(self, request):
        data = PreferencesInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(services.set_preferences(actor=request.user, items=data.validated_data["preferences"]))


urlpatterns = [
    path("", NotificationListView.as_view(), name="notifications"),
    path("unread-count/", UnreadCountView.as_view(), name="notifications-unread-count"),
    path("read-all/", MarkAllReadView.as_view(), name="notifications-read-all"),
    path("preferences/", PreferencesView.as_view(), name="notifications-preferences"),
    path("<uuid:notification_id>/read/", MarkReadView.as_view(), name="notification-read"),
]
