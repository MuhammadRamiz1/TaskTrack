"""Serializers, views and URLs for time tracking."""

import django_filters
from django.urls import path
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.accounts.serializers import UserBrief
from apps.common.exceptions import InvalidInput
from apps.common.pagination import PageNumberPagination
from apps.common.views import LIST_FILTERS, TenantAPIView, schema_generation
from apps.rbac import policy
from apps.tasks.services.tasks import get_task

from . import services
from .models import TimeEntry

# --- serializers -----------------------------------------------------------------------


class TaskRef(serializers.Serializer):
    id = serializers.UUIDField()
    key = serializers.CharField()
    title = serializers.CharField()


class EntryOutput(serializers.ModelSerializer):
    user = UserBrief()
    task = TaskRef()
    elapsed_seconds = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()

    class Meta:
        model = TimeEntry
        fields = [
            "id",
            "user",
            "task",
            "started_at",
            "ended_at",
            "duration_seconds",
            "elapsed_seconds",
            "work_date",
            "source",
            "status",
            "note",
            "version",
            "is_locked",
        ]

    def get_is_locked(self, entry) -> bool:
        """True while the timer runs or once the task is in review, completed or cancelled."""
        return services.is_locked(entry)

    def get_elapsed_seconds(self, entry) -> int:
        if entry.ended_at:
            return entry.duration_seconds
        return int((timezone.now() - entry.started_at).total_seconds())


class CurrentTimerOutput(serializers.Serializer):
    server_time = serializers.DateTimeField()
    entry = EntryOutput(allow_null=True)


class StartInput(serializers.Serializer):
    task_id = serializers.UUIDField()


class StopInput(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)


class ManualEntryInput(serializers.Serializer):
    task_id = serializers.UUIDField()
    started_at = serializers.DateTimeField()
    ended_at = serializers.DateTimeField()
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)


class EntryUpdateInput(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    started_at = serializers.DateTimeField(required=False)
    ended_at = serializers.DateTimeField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


# --- views -----------------------------------------------------------------------------------

ENTRY_HINT = TimeEntry._base_manager.none()


def _timer_body(user):
    return {"server_time": timezone.now(), "entry": services.current_timer(user)}


class CurrentTimerView(TenantAPIView):
    queryset = ENTRY_HINT
    permission_map = {"GET": "time.track"}

    @extend_schema(
        responses=CurrentTimerOutput,
        tags=["time"],
        summary="My running timer (server_time lets clients compute elapsed time)",
    )
    def get(self, request):
        return Response(CurrentTimerOutput(_timer_body(request.user)).data)


class TimerStartView(TenantAPIView):
    queryset = ENTRY_HINT
    permission_map = {"POST": "time.track"}

    @extend_schema(
        request=StartInput,
        responses={201: CurrentTimerOutput},
        tags=["time"],
        summary="Start a timer (moves ASSIGNED/REOPENED tasks to IN_PROGRESS if enabled)",
    )
    def post(self, request):
        data = StartInput(data=request.data)
        data.is_valid(raise_exception=True)
        services.start_timer(actor=request.user, task_id=data.validated_data["task_id"])
        return Response(CurrentTimerOutput(_timer_body(request.user)).data, status=status.HTTP_201_CREATED)


class TimerSwitchView(TenantAPIView):
    queryset = ENTRY_HINT
    permission_map = {"POST": "time.track"}

    @extend_schema(
        request=StartInput,
        responses={201: CurrentTimerOutput},
        tags=["time"],
        summary="Stop the running timer and start one on another task",
    )
    def post(self, request):
        data = StartInput(data=request.data)
        data.is_valid(raise_exception=True)
        services.switch_timer(actor=request.user, task_id=data.validated_data["task_id"])
        return Response(CurrentTimerOutput(_timer_body(request.user)).data, status=status.HTTP_201_CREATED)


class TimerStopView(TenantAPIView):
    queryset = ENTRY_HINT
    permission_map = {"POST": "time.track"}

    @extend_schema(request=StopInput, responses=EntryOutput, tags=["time"], summary="Stop the timer")
    def post(self, request):
        data = StopInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(EntryOutput(services.stop_timer(actor=request.user, note=data.validated_data["note"])).data)


class TimerPauseView(TenantAPIView):
    queryset = ENTRY_HINT
    permission_map = {"POST": "time.track"}

    @extend_schema(
        request=None, responses=EntryOutput, tags=["time"], summary="Pause (closes the current time segment)"
    )
    def post(self, request):
        return Response(EntryOutput(services.pause_timer(actor=request.user)).data)


class TimerResumeView(TenantAPIView):
    queryset = ENTRY_HINT
    permission_map = {"POST": "time.track"}

    @extend_schema(
        request=None, responses={201: CurrentTimerOutput}, tags=["time"], summary="Resume the last timed task"
    )
    def post(self, request):
        services.resume_timer(actor=request.user)
        return Response(CurrentTimerOutput(_timer_body(request.user)).data, status=status.HTTP_201_CREATED)


class EntryFilter(django_filters.FilterSet):
    user = django_filters.UUIDFilter(field_name="user_id")
    task = django_filters.UUIDFilter(field_name="task_id")
    project = django_filters.UUIDFilter(field_name="task__project_id")
    date_from = django_filters.DateFilter(field_name="work_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="work_date", lookup_expr="lte")
    status = django_filters.MultipleChoiceFilter(choices=TimeEntry.Status.choices)
    source = django_filters.ChoiceFilter(choices=TimeEntry.Source.choices)

    class Meta:
        model = TimeEntry
        fields = ["user", "task", "project", "date_from", "date_to", "status", "source"]


def visible_entries(actor):
    qs = TimeEntry.objects.select_related("user", "task__project")
    return policy.scope_queryset(actor, "time.view", qs)


class EntryListView(TenantAPIView):
    pagination_class = PageNumberPagination
    permission_map = {"GET": "time.view", "POST": "time.track"}
    filter_backends = LIST_FILTERS
    filterset_class = EntryFilter
    ordering_fields = ["started_at", "work_date", "duration_seconds"]
    ordering = ["-started_at"]

    def get_queryset(self):
        return ENTRY_HINT if schema_generation(self) else visible_entries(self.request.user)

    @extend_schema(responses=EntryOutput(many=True), tags=["time"], summary="Time entries you can see")
    def get(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(EntryOutput(page, many=True).data)

    @extend_schema(
        request=ManualEntryInput,
        responses={201: EntryOutput},
        tags=["time"],
        summary="Log time manually (no overlaps, not in the future, max 24 h)",
    )
    def post(self, request):
        data = ManualEntryInput(data=request.data)
        data.is_valid(raise_exception=True)
        entry = services.create_manual(actor=request.user, **data.validated_data)
        return Response(EntryOutput(entry).data, status=status.HTTP_201_CREATED)


class EntryDetailView(TenantAPIView):
    queryset = ENTRY_HINT
    permission_map = {"PATCH": "time.view", "DELETE": "time.view"}

    @extend_schema(
        request=EntryUpdateInput,
        responses=EntryOutput,
        tags=["time"],
        summary="Correct an entry (own draft entries, or others' with time.edit_others)",
    )
    def patch(self, request, entry_id):
        services.get_entry(request.user, entry_id)
        data = EntryUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        version = values.pop("version", None)
        if version is None:
            raise InvalidInput(details={"version": ["This field is required."]})
        entry = services.update_entry(actor=request.user, entry_id=entry_id, data=values, expected_version=version)
        return Response(EntryOutput(entry).data)

    @extend_schema(responses={204: None}, tags=["time"], summary="Delete a draft entry")
    def delete(self, request, entry_id):
        services.delete_entry(actor=request.user, entry_id=entry_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TaskTimeEntriesView(TenantAPIView):
    queryset = ENTRY_HINT
    permission_map = {"GET": "task.view"}
    pagination_class = None

    @extend_schema(responses=EntryOutput(many=True), tags=["time"], summary="Time logged on a task (that you may see)")
    def get(self, request, task_id):
        task = get_task(request.user, task_id)
        entries = visible_entries(request.user).filter(task=task).order_by("-started_at")
        return Response(EntryOutput(entries, many=True).data)


urlpatterns = [
    path("timer/current/", CurrentTimerView.as_view(), name="time-timer-current"),
    path("timer/start/", TimerStartView.as_view(), name="time-timer-start"),
    path("timer/pause/", TimerPauseView.as_view(), name="time-timer-pause"),
    path("timer/resume/", TimerResumeView.as_view(), name="time-timer-resume"),
    path("timer/stop/", TimerStopView.as_view(), name="time-timer-stop"),
    path("timer/switch/", TimerSwitchView.as_view(), name="time-timer-switch"),
    path("entries/", EntryListView.as_view(), name="time-entries"),
    path("entries/<uuid:entry_id>/", EntryDetailView.as_view(), name="time-entry-detail"),
]
task_urlpatterns = [
    path("<uuid:task_id>/time-entries/", TaskTimeEntriesView.as_view(), name="task-time-entries"),
]
