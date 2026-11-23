"""Dashboards, reports, exports and scheduled reports."""

from datetime import date, timedelta

from django.http import FileResponse
from django.urls import path
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.accounts.serializers import UserBrief
from apps.common.pagination import PageNumberPagination
from apps.common.views import TenantAPIView

from . import selectors, services
from .builders import CONTENT_TYPES
from .models import ExportFormat, ReportExport, ReportType, ScheduledReport

GROUP_BY = ["member", "team", "project"]
PERIODS = ["daily", "weekly", "monthly"]


# --- serializers -------------------------------------------------------------------------


class ReportQuery(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    project = serializers.UUIDField(required=False)
    team = serializers.UUIDField(required=False)
    user = serializers.UUIDField(required=False)
    group_by = serializers.ChoiceField(choices=GROUP_BY, default="member")
    period = serializers.ChoiceField(choices=PERIODS, default="weekly")

    def validate(self, attrs):
        today = date.today()
        attrs.setdefault("date_to", today)
        attrs.setdefault("date_from", attrs["date_to"] - timedelta(days=29))
        return attrs


class TimeRow(serializers.Serializer):
    group_id = serializers.UUIDField(allow_null=True)
    group = serializers.CharField()
    period_start = serializers.DateField()
    hours = serializers.FloatField()
    entries = serializers.IntegerField()


class TaskRow(serializers.Serializer):
    group_id = serializers.UUIDField(allow_null=True)
    group = serializers.CharField()
    period_start = serializers.DateField()
    created = serializers.IntegerField()
    completed = serializers.IntegerField()
    completed_on_time = serializers.IntegerField()


class ExportInput(ReportQuery):
    report_type = serializers.ChoiceField(choices=ReportType.choices)
    format = serializers.ChoiceField(choices=ExportFormat.choices)


class ExportOutput(serializers.ModelSerializer):
    class Meta:
        model = ReportExport
        fields = [
            "id",
            "report_type",
            "format",
            "filters",
            "status",
            "filename",
            "size_bytes",
            "row_count",
            "error",
            "created_at",
            "finished_at",
            "expires_at",
        ]


class ScheduleFilters(serializers.Serializer):
    project = serializers.UUIDField(required=False)
    team = serializers.UUIDField(required=False)
    user = serializers.UUIDField(required=False)
    group_by = serializers.ChoiceField(choices=GROUP_BY, default="member")
    period = serializers.ChoiceField(choices=PERIODS, default="daily")


class ScheduleInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    report_type = serializers.ChoiceField(choices=ReportType.choices)
    filters = ScheduleFilters(required=False, default=dict)
    format = serializers.ChoiceField(choices=ExportFormat.choices, default=ExportFormat.XLSX)
    frequency = serializers.ChoiceField(choices=ScheduledReport.Frequency.choices)
    send_at = serializers.TimeField()
    weekday = serializers.IntegerField(min_value=0, max_value=6, default=0)
    day_of_month = serializers.IntegerField(min_value=1, max_value=28, default=1)
    recipient_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list, max_length=50)
    is_active = serializers.BooleanField(default=True)


class ScheduleOutput(serializers.ModelSerializer):
    owner = UserBrief()

    class Meta:
        model = ScheduledReport
        fields = [
            "id",
            "name",
            "report_type",
            "filters",
            "format",
            "frequency",
            "send_at",
            "weekday",
            "day_of_month",
            "recipient_ids",
            "owner",
            "next_run_at",
            "last_run_at",
            "last_error",
            "is_active",
        ]


class NameHours(serializers.Serializer):
    user_id = serializers.UUIDField(required=False)
    project_id = serializers.UUIDField(required=False)
    name = serializers.CharField(required=False)
    key = serializers.CharField(required=False)
    hours = serializers.FloatField()


class ManagerDashboardOutput(serializers.Serializer):
    period = serializers.DictField()
    totals = serializers.DictField(child=serializers.IntegerField())
    workload = serializers.ListField(child=serializers.DictField())
    productivity = serializers.ListField(child=serializers.DictField())
    project_progress = serializers.ListField(child=serializers.DictField())
    time_by_employee = NameHours(many=True)
    time_by_project = NameHours(many=True)


class MemberDashboardOutput(serializers.Serializer):
    by_status = serializers.DictField(child=serializers.IntegerField())
    open = serializers.IntegerField()
    due_soon = serializers.IntegerField()
    overdue = serializers.IntegerField()
    changes_requested = serializers.IntegerField()
    reviews_waiting_for_me = serializers.IntegerField()
    hours_today = serializers.FloatField()
    hours_this_week = serializers.FloatField()


# --- views ----------------------------------------------------------------------------------

EXPORT_HINT = ReportExport._base_manager.none()
SCHEDULE_HINT = ScheduledReport._base_manager.none()


def _filters(request) -> selectors.Filters:
    query = ReportQuery(data=request.query_params)
    query.is_valid(raise_exception=True)
    return services.filters_from(query.validated_data)


class ManagerDashboardView(TenantAPIView):
    queryset = EXPORT_HINT
    permission_map = {"GET": "dashboard.manager.view"}

    @extend_schema(
        parameters=[ReportQuery],
        responses=ManagerDashboardOutput,
        tags=["dashboards"],
        summary="Team/project overview (default: last 30 days)",
    )
    def get(self, request):
        return Response(selectors.manager_summary(request.user, _filters(request)))


class MemberDashboardView(TenantAPIView):
    queryset = EXPORT_HINT
    permission_map = {"GET": "dashboard.member.view"}

    @extend_schema(responses=MemberDashboardOutput, tags=["dashboards"], summary="My work at a glance")
    def get(self, request):
        return Response(selectors.member_summary(request.user))


class TimeReportView(TenantAPIView):
    queryset = EXPORT_HINT
    permission_map = {"GET": "report.view"}

    @extend_schema(
        parameters=[ReportQuery],
        responses=TimeRow(many=True),
        tags=["reports"],
        summary="Logged hours by member/team/project per day/week/month",
    )
    def get(self, request):
        return Response(TimeRow(selectors.time_report(request.user, _filters(request)), many=True).data)


class TaskReportView(TenantAPIView):
    queryset = EXPORT_HINT
    permission_map = {"GET": "report.view"}

    @extend_schema(
        parameters=[ReportQuery],
        responses=TaskRow(many=True),
        tags=["reports"],
        summary="Tasks created/completed (and on time) by member/team/project per period",
    )
    def get(self, request):
        return Response(TaskRow(selectors.task_report(request.user, _filters(request)), many=True).data)


class ExportListView(TenantAPIView):
    pagination_class = PageNumberPagination
    queryset = EXPORT_HINT
    permission_map = {"GET": "report.export", "POST": "report.export"}

    @extend_schema(responses=ExportOutput(many=True), tags=["reports"], summary="My exports")
    def get(self, request):
        page = self.paginate_queryset(
            ReportExport.objects.filter(requested_by=request.user, scheduled_report__isnull=True)
        )
        return self.get_paginated_response(ExportOutput(page, many=True).data)

    @extend_schema(
        request=ExportInput,
        responses={202: ExportOutput},
        tags=["reports"],
        summary="Export a report as CSV, XLSX or PDF (generated in the background)",
    )
    def post(self, request):
        data = ExportInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        export = services.request_export(
            actor=request.user, report_type=values.pop("report_type"), fmt=values.pop("format"), filters=values
        )
        return Response(ExportOutput(export).data, status=status.HTTP_202_ACCEPTED)


class ExportDetailView(TenantAPIView):
    queryset = EXPORT_HINT
    permission_map = {"GET": "report.export"}

    @extend_schema(responses=ExportOutput, tags=["reports"], summary="Export status")
    def get(self, request, export_id):
        return Response(ExportOutput(services.get_export(request.user, export_id)).data)


class ExportDownloadView(TenantAPIView):
    queryset = EXPORT_HINT
    permission_map = {"GET": "report.export"}

    @extend_schema(
        responses={(200, "application/octet-stream"): bytes}, tags=["reports"], summary="Download a finished export"
    )
    def get(self, request, export_id):
        export, handle = services.open_export(request.user, export_id)
        response = FileResponse(
            handle, as_attachment=True, filename=export.filename, content_type=CONTENT_TYPES[export.format]
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response


class ScheduleListView(TenantAPIView):
    queryset = SCHEDULE_HINT
    permission_map = {"GET": "report.schedule", "POST": "report.schedule"}
    pagination_class = None

    @extend_schema(responses=ScheduleOutput(many=True), tags=["reports"], summary="Scheduled reports")
    def get(self, request):
        return Response(ScheduleOutput(services.list_schedules(request.user), many=True).data)

    @extend_schema(
        request=ScheduleInput,
        responses={201: ScheduleOutput},
        tags=["reports"],
        summary="Schedule a report to be emailed daily, weekly or monthly",
    )
    def post(self, request):
        data = ScheduleInput(data=request.data)
        data.is_valid(raise_exception=True)
        schedule = services.save_schedule(actor=request.user, data=dict(data.validated_data))
        return Response(ScheduleOutput(schedule).data, status=status.HTTP_201_CREATED)


class ScheduleDetailView(TenantAPIView):
    queryset = SCHEDULE_HINT
    permission_map = {"GET": "report.schedule", "PATCH": "report.schedule", "DELETE": "report.schedule"}

    @extend_schema(responses=ScheduleOutput, tags=["reports"], summary="Scheduled report")
    def get(self, request, schedule_id):
        return Response(ScheduleOutput(services.get_schedule(request.user, schedule_id)).data)

    @extend_schema(request=ScheduleInput, responses=ScheduleOutput, tags=["reports"], summary="Edit a scheduled report")
    def patch(self, request, schedule_id):
        schedule = services.get_schedule(request.user, schedule_id)
        data = ScheduleInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        schedule = services.save_schedule(actor=request.user, data=dict(data.validated_data), schedule=schedule)
        return Response(ScheduleOutput(schedule).data)

    @extend_schema(responses={204: None}, tags=["reports"], summary="Delete a scheduled report")
    def delete(self, request, schedule_id):
        services.delete_schedule(actor=request.user, schedule=services.get_schedule(request.user, schedule_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


dashboard_urlpatterns = [
    path("manager/", ManagerDashboardView.as_view(), name="dashboard-manager"),
    path("member/", MemberDashboardView.as_view(), name="dashboard-member"),
]
urlpatterns = [
    path("tasks/", TaskReportView.as_view(), name="report-tasks"),
    path("time/", TimeReportView.as_view(), name="report-time"),
    path("exports/", ExportListView.as_view(), name="report-exports"),
    path("exports/<uuid:export_id>/", ExportDetailView.as_view(), name="report-export-detail"),
    path("exports/<uuid:export_id>/download/", ExportDownloadView.as_view(), name="report-export-download"),
    path("schedules/", ScheduleListView.as_view(), name="report-schedules"),
    path("schedules/<uuid:schedule_id>/", ScheduleDetailView.as_view(), name="report-schedule-detail"),
]
