"""Serializers, views and URLs for the review workflow (small module, kept together)."""

from django.urls import path
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.accounts.serializers import UserBrief
from apps.common.pagination import PageNumberPagination
from apps.common.views import TenantAPIView
from apps.tasks.models import Task
from apps.tasks.services.tasks import get_task

from . import services
from .models import TaskReview

HINT = Task._base_manager.none()


class ReviewOutput(serializers.ModelSerializer):
    submitted_by = UserBrief()
    reviewer = UserBrief()
    decided_by = UserBrief(allow_null=True)

    class Meta:
        model = TaskReview
        fields = [
            "id",
            "round",
            "submitted_by",
            "submitted_at",
            "submission_note",
            "reviewer",
            "decision",
            "decided_by",
            "comment",
            "decided_at",
        ]


class QueueTaskOutput(serializers.Serializer):
    id = serializers.UUIDField()
    key = serializers.CharField()
    title = serializers.CharField()
    priority = serializers.CharField()
    due_date = serializers.DateField(allow_null=True)


class QueueItemOutput(ReviewOutput):
    task = serializers.SerializerMethodField()

    class Meta(ReviewOutput.Meta):
        fields = [*ReviewOutput.Meta.fields, "task"]

    @extend_schema_field(QueueTaskOutput)
    def get_task(self, review) -> dict:
        t = review.task
        return {"id": str(t.pk), "key": t.key, "title": t.title, "priority": t.priority, "due_date": t.due_date}


class SubmitInput(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=5000)


class ReviewDecisionInput(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=5000)


class SubmitView(TenantAPIView):
    queryset = HINT
    permission_map = {"POST": "review.submit"}

    @extend_schema(
        request=SubmitInput,
        responses={201: ReviewOutput},
        tags=["reviews"],
        summary="Submit for review (required checklist items must be done)",
    )
    def post(self, request, task_id):
        get_task(request.user, task_id)
        data = SubmitInput(data=request.data)
        data.is_valid(raise_exception=True)
        review = services.submit(actor=request.user, task_id=task_id, note=data.validated_data["note"])
        return Response(ReviewOutput(review).data, status=status.HTTP_201_CREATED)


class ApproveView(TenantAPIView):
    queryset = HINT
    permission_map = {"POST": "review.decide"}

    @extend_schema(
        request=ReviewDecisionInput,
        responses=ReviewOutput,
        tags=["reviews"],
        summary="Approve: the task becomes COMPLETED and read-only",
    )
    def post(self, request, task_id):
        get_task(request.user, task_id)
        data = ReviewDecisionInput(data=request.data)
        data.is_valid(raise_exception=True)
        review = services.approve(actor=request.user, task_id=task_id, comment=data.validated_data["comment"])
        return Response(ReviewOutput(review).data)


class RequestChangesView(TenantAPIView):
    queryset = HINT
    permission_map = {"POST": "review.decide"}

    @extend_schema(
        request=ReviewDecisionInput,
        responses=ReviewOutput,
        tags=["reviews"],
        summary="Request changes (comment required): the task goes back to IN_PROGRESS",
    )
    def post(self, request, task_id):
        get_task(request.user, task_id)
        data = ReviewDecisionInput(data=request.data)
        data.is_valid(raise_exception=True)
        review = services.request_changes(actor=request.user, task_id=task_id, comment=data.validated_data["comment"])
        return Response(ReviewOutput(review).data)


class HistoryView(TenantAPIView):
    queryset = HINT
    permission_map = {"GET": "review.view"}
    pagination_class = None

    @extend_schema(responses=ReviewOutput(many=True), tags=["reviews"], summary="All review rounds of a task")
    def get(self, request, task_id):
        return Response(ReviewOutput(services.history(actor=request.user, task_id=task_id), many=True).data)


class QueueView(TenantAPIView):
    pagination_class = PageNumberPagination
    queryset = TaskReview._base_manager.none()
    permission_map = {"GET": "review.decide"}

    @extend_schema(responses=QueueItemOutput(many=True), tags=["reviews"], summary="Reviews waiting for me")
    def get(self, request):
        page = self.paginate_queryset(services.queue(request.user))
        return self.get_paginated_response(QueueItemOutput(page, many=True).data)


task_urlpatterns = [
    path("<uuid:task_id>/review/submit/", SubmitView.as_view(), name="review-submit"),
    path("<uuid:task_id>/review/approve/", ApproveView.as_view(), name="review-approve"),
    path("<uuid:task_id>/review/request-changes/", RequestChangesView.as_view(), name="review-request-changes"),
    path("<uuid:task_id>/reviews/", HistoryView.as_view(), name="review-history"),
]
urlpatterns = [path("queue/", QueueView.as_view(), name="review-queue")]
