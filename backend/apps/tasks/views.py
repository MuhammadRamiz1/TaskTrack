import uuid
from datetime import date

import django_filters
from django.db.models import Count, IntegerField, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import FileResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.accounts.models import User
from apps.common.exceptions import InvalidInput, NotFound
from apps.common.pagination import CursorPagination, PageNumberPagination
from apps.common.views import LIST_FILTERS, TenantAPIView, schema_generation
from apps.org.models import Project
from apps.org.views import get_project
from apps.rbac import policy

from . import selectors
from . import serializers as s
from .models import (
    OPEN_STATUSES,
    ChecklistItem,
    Priority,
    Status,
    StatusTransitionRule,
    Task,
    TaskActivity,
    TaskAttachment,
    TaskChecklist,
    TaskComment,
    TaskDependency,
)
from .services import assignment, attachments, details, rules
from .services import tasks as task_services
from .workflow import DONE_STATUSES, allowed_targets, transition_task

TASK_HINT = Task._base_manager.none()


def _detail(request, task_id) -> dict:
    task = (
        Task.objects.select_related("project", "created_by", "reviewer")
        .prefetch_related(
            "assignees__user",
            Prefetch("checklists", queryset=TaskChecklist.objects.prefetch_related("items__done_by")),
            Prefetch("dependencies", queryset=TaskDependency.objects.select_related("blocked_by__project")),
        )
        .get(pk=task_id)
    )
    return s.TaskDetail(task, context={"request": request}).data


def _user(actor, user_id, field):
    if user_id is None:
        return None
    user = User.objects.filter(pk=user_id, company_id=actor.company_id).first()
    if user is None:
        raise InvalidInput(details={field: ["Unknown employee."]})
    return user


class TaskFilter(django_filters.FilterSet):
    project = django_filters.UUIDFilter(field_name="project_id")
    team = django_filters.UUIDFilter(field_name="project__team_id")
    status = django_filters.MultipleChoiceFilter(choices=Status.choices)
    priority = django_filters.MultipleChoiceFilter(choices=Priority.choices)
    assignee = django_filters.UUIDFilter(field_name="assignees__user_id")
    reviewer = django_filters.UUIDFilter(field_name="reviewer_id")
    created_by = django_filters.UUIDFilter(field_name="created_by_id")
    due_before = django_filters.DateFilter(field_name="due_date", lookup_expr="lte")
    due_after = django_filters.DateFilter(field_name="due_date", lookup_expr="gte")
    overdue = django_filters.BooleanFilter(method="filter_overdue")
    open = django_filters.BooleanFilter(method="filter_open")
    needs_reassignment = django_filters.BooleanFilter()
    parent = django_filters.CharFilter(method="filter_parent", help_text="Task id, or 'none' for top-level tasks")
    mine = django_filters.BooleanFilter(method="filter_mine", help_text="Tasks assigned to me")

    class Meta:
        model = Task
        fields = []

    def filter_overdue(self, qs, name, value):
        cond = Q(due_date__lt=date.today()) & Q(status__in=OPEN_STATUSES)
        return qs.filter(cond) if value else qs.exclude(cond)

    def filter_open(self, qs, name, value):
        return qs.filter(status__in=OPEN_STATUSES) if value else qs.exclude(status__in=OPEN_STATUSES)

    def filter_parent(self, qs, name, value):
        if value == "none":
            return qs.filter(parent__isnull=True)
        try:
            return qs.filter(parent_id=uuid.UUID(value))
        except ValueError as exc:
            raise InvalidInput(details={"parent": ["Use a task id or 'none'."]}) from exc

    def filter_mine(self, qs, name, value):
        user = self.request.user
        return qs.filter(assignees__user=user) if value else qs.exclude(assignees__user=user)


# --- Tasks ----------------------------------------------------------------------------


class TaskListView(TenantAPIView):
    pagination_class = PageNumberPagination
    permission_map = {"GET": "task.view", "POST": "task.create"}
    filter_backends = LIST_FILTERS
    filterset_class = TaskFilter
    search_fields = ["title", "description"]
    ordering_fields = ["due_date", "priority_rank", "created_at", "updated_at", "status", "number", "title"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if schema_generation(self):
            return TASK_HINT
        return selectors.visible_tasks(self.request.user)

    @extend_schema(
        responses=s.TaskSummary(many=True),
        tags=["tasks"],
        summary="Tasks you can see (filter, search, order with ?ordering=-priority_rank)",
    )
    def get(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(s.TaskSummary(page, many=True).data)

    @extend_schema(request=s.TaskCreateInput, responses={201: s.TaskDetail}, tags=["tasks"], summary="Create a task")
    def post(self, request):
        data = s.TaskCreateInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        project = Project.objects.filter(pk=values.pop("project_id")).first()
        if project is None or not policy.can(request.user, "project.view", project):
            raise InvalidInput(details={"project_id": ["Unknown project."]})
        values["project"] = project
        parent_id = values.pop("parent_id", None)
        if parent_id:
            try:
                values["parent"] = task_services.get_task(request.user, parent_id)
            except NotFound as exc:
                raise InvalidInput(details={"parent_id": ["Unknown task."]}) from exc
        values["reviewer"] = _user(request.user, values.pop("reviewer_id", None), "reviewer_id")
        if values["reviewer"] is None:
            values.pop("reviewer")
        task = task_services.create_task(actor=request.user, data=values)
        return Response(_detail(request, task.pk), status=status.HTTP_201_CREATED)


class TaskDetailView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view", "PATCH": "task.view", "DELETE": "task.delete"}

    @extend_schema(responses=s.TaskDetail, tags=["tasks"], summary="Task details")
    def get(self, request, task_id):
        task_services.get_task(request.user, task_id)
        return Response(_detail(request, task_id))

    @extend_schema(
        request=s.TaskUpdateInput,
        responses=s.TaskDetail,
        tags=["tasks"],
        summary="Edit a task (send the version you read; 409 if it changed)",
    )
    def patch(self, request, task_id):
        task_services.get_task(request.user, task_id)
        data = s.TaskUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        version = values.pop("version", None)
        if version is None:
            raise InvalidInput(details={"version": ["This field is required."]})
        if "reviewer_id" in values:
            values["reviewer"] = _user(request.user, values.pop("reviewer_id"), "reviewer_id")
        if set(values) == {"priority"}:
            task_services.set_priority(
                actor=request.user, task_id=task_id, priority=values["priority"], expected_version=version
            )
        else:
            task_services.update_task(actor=request.user, task_id=task_id, data=values, expected_version=version)
        return Response(_detail(request, task_id))

    @extend_schema(responses={204: None}, tags=["tasks"], summary="Delete a task (restorable for 30 days)")
    def delete(self, request, task_id):
        task_services.delete_task(actor=request.user, task_id=task_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TaskRestoreView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"POST": "task.delete"}

    @extend_schema(request=None, responses=s.TaskDetail, tags=["tasks"], summary="Restore a deleted task")
    def post(self, request, task_id):
        task_services.restore_task(actor=request.user, task_id=task_id)
        return Response(_detail(request, task_id))


class TaskByKeyView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view"}

    @extend_schema(responses=s.TaskDetail, tags=["tasks"], summary="Task by key, e.g. WEB-42")
    def get(self, request, key):
        project_key, _, number = key.upper().rpartition("-")
        if not number.isdigit():
            raise NotFound()
        task = Task.objects.filter(project__key=project_key, number=int(number)).select_related("project").first()
        if task is None or not policy.can(request.user, "task.view", task):
            raise NotFound()
        return Response(_detail(request, task.pk))


def _count_per_task(qs, task_field: str):
    """Correlated COUNT per task: one subquery each, so the board stays a single query without join fan-out."""
    counted = qs.filter(**{task_field: OuterRef("pk")}).order_by().values(task_field)
    counted = counted.annotate(n=Count("pk")).values("n")
    return Coalesce(Subquery(counted, output_field=IntegerField()), 0)


class TaskBoardView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view"}

    @extend_schema(
        parameters=[OpenApiParameter("project", str, required=True)],
        responses=s.BoardOutput,
        tags=["tasks"],
        summary="Kanban columns for a project",
    )
    def get(self, request):
        project_id = request.query_params.get("project")
        if not project_id:
            raise InvalidInput(details={"project": ["This parameter is required."]})
        try:
            project = get_project(request.user, uuid.UUID(project_id))
        except ValueError as exc:
            raise InvalidInput(details={"project": ["Not a valid id."]}) from exc
        from apps.reviews.models import TaskReview

        tasks = (
            selectors.visible_tasks(request.user)
            .filter(project=project)
            .select_related("company")
            .annotate(
                open_required_items=Count(
                    "checklists__items",
                    filter=Q(checklists__items__is_required=True, checklists__items__is_done=False),
                    distinct=True,
                ),
                open_blocker_count=Count(
                    "dependencies",
                    filter=~Q(dependencies__blocked_by__status__in=DONE_STATUSES),
                    distinct=True,
                ),
                checklist_total=_count_per_task(ChecklistItem.objects, "checklist__task"),
                checklist_done=_count_per_task(ChecklistItem.objects.filter(is_done=True), "checklist__task"),
                comment_count=_count_per_task(TaskComment.objects.filter(deleted_at__isnull=True), "task"),
                attachment_count=_count_per_task(
                    TaskAttachment.objects.filter(status=TaskAttachment.State.ACTIVE), "task"
                ),
            )
            .prefetch_related(
                Prefetch(
                    "reviews",
                    queryset=TaskReview.objects.filter(decision=TaskReview.Decision.PENDING),
                    to_attr="pending_reviews",
                )
            )
            .order_by("-priority_rank", "due_date")
        )
        context = {
            "request": request,
            "rules": list(StatusTransitionRule.objects.filter(company_id=project.company_id, is_active=True)),
        }
        columns = {value: [] for value in Status.values}
        for task in tasks:
            columns[task.status].append(s.BoardCard(task, context=context).data)
        return Response(
            {
                "project": {"id": str(project.pk), "key": project.key, "name": project.name},
                "columns": [{"status": k, "tasks": v} for k, v in columns.items()],
            }
        )


class TaskCalendarView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view"}

    @extend_schema(
        parameters=[OpenApiParameter("start", date, required=True), OpenApiParameter("end", date, required=True)],
        responses=s.TaskSummary(many=True),
        tags=["tasks"],
        summary="Tasks due in a date range",
    )
    def get(self, request):
        try:
            start = date.fromisoformat(request.query_params["start"])
            end = date.fromisoformat(request.query_params["end"])
        except (KeyError, ValueError) as exc:
            raise InvalidInput(details={"start": ["Use start=YYYY-MM-DD&end=YYYY-MM-DD."]}) from exc
        if end < start or (end - start).days > 92:
            raise InvalidInput(details={"end": ["The range must be 0 to 92 days."]})
        tasks = selectors.visible_tasks(request.user).filter(due_date__range=(start, end)).order_by("due_date")
        return Response(s.TaskSummary(tasks, many=True).data)


class WorkloadView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.workload.view"}

    @extend_schema(
        parameters=[OpenApiParameter("start", date), OpenApiParameter("end", date)],
        responses=s.WorkloadOutput(many=True),
        tags=["tasks"],
        summary="Open work and capacity per person (default: this week)",
    )
    def get(self, request):
        default_start, default_end = selectors.week_bounds(request.user.company, date.today())
        try:
            start = date.fromisoformat(request.query_params.get("start", default_start.isoformat()))
            end = date.fromisoformat(request.query_params.get("end", default_end.isoformat()))
        except ValueError as exc:
            raise InvalidInput(details={"start": ["Use YYYY-MM-DD."]}) from exc
        if end < start or (end - start).days > 92:
            raise InvalidInput(details={"end": ["The range must be 0 to 92 days."]})
        return Response(s.WorkloadOutput(selectors.workload(request.user, start, end), many=True).data)


# --- Assignment ----------------------------------------------------------------------------


class AssigneesView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"POST": "task.assign"}

    @extend_schema(request=s.AssignInput, responses={201: s.TaskDetail}, tags=["tasks"], summary="Assign")
    def post(self, request, task_id):
        task_services.get_task(request.user, task_id)
        data = s.AssignInput(data=request.data)
        data.is_valid(raise_exception=True)
        assignment.assign(actor=request.user, task_id=task_id, user_ids=data.validated_data["user_ids"])
        return Response(_detail(request, task_id), status=status.HTTP_201_CREATED)


class AssigneeDetailView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"DELETE": "task.assign"}

    @extend_schema(responses={204: None}, tags=["tasks"], summary="Unassign")
    def delete(self, request, task_id, user_id):
        assignment.unassign(actor=request.user, task_id=task_id, user_id=user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReassignView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"POST": "task.assign"}

    @extend_schema(request=s.ReassignInput, responses=s.TaskDetail, tags=["tasks"], summary="Reassign")
    def post(self, request, task_id):
        task_services.get_task(request.user, task_id)
        data = s.ReassignInput(data=request.data)
        data.is_valid(raise_exception=True)
        assignment.reassign(actor=request.user, task_id=task_id, **data.validated_data)
        return Response(_detail(request, task_id))


class BulkAssignView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"POST": "task.assign"}

    @extend_schema(
        request=s.BulkAssignInput,
        responses=s.CountOutput,
        tags=["tasks"],
        summary="Assign many tasks at once (all or nothing)",
    )
    def post(self, request):
        data = s.BulkAssignInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response({"count": assignment.bulk_assign(actor=request.user, **data.validated_data)})


class AcknowledgeView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"POST": "task.acknowledge"}

    @extend_schema(request=None, responses=s.TaskDetail, tags=["tasks"], summary="Acknowledge my assignment")
    def post(self, request, task_id):
        assignment.acknowledge(actor=request.user, task_id=task_id)
        return Response(_detail(request, task_id))


# --- Workflow ---------------------------------------------------------------------------------


class TransitionView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"POST": "task.transition"}

    @extend_schema(
        request=s.TransitionInput,
        responses=s.TaskDetail,
        tags=["tasks"],
        summary="Change status (only transitions allowed by the company's rules)",
    )
    def post(self, request, task_id):
        task_services.get_task(request.user, task_id)
        data = s.TransitionInput(data=request.data)
        data.is_valid(raise_exception=True)
        transition_task(
            actor=request.user,
            task_id=task_id,
            to_status=data.validated_data["to_status"],
            comment=data.validated_data["comment"],
            expected_version=data.validated_data.get("version"),
        )
        return Response(_detail(request, task_id))


class AllowedTransitionsView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view"}

    @extend_schema(
        responses=s.AllowedTransitionOutput(many=True), tags=["tasks"], summary="Statuses you may move this task to"
    )
    def get(self, request, task_id):
        return Response(allowed_targets(request.user, task_services.get_task(request.user, task_id)))


class ReopenView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"POST": "task.reopen"}

    @extend_schema(
        request=s.CommentInput,
        responses=s.TaskDetail,
        tags=["tasks"],
        summary="Reopen a completed task (reason required)",
    )
    def post(self, request, task_id):
        task = task_services.get_task(request.user, task_id)
        policy.require(request.user, "task.reopen", task)
        data = s.CommentInput(data=request.data)
        data.is_valid(raise_exception=True)
        transition_task(
            actor=request.user, task_id=task_id, to_status=Status.REOPENED, comment=data.validated_data["comment"]
        )
        return Response(_detail(request, task_id))


class EscalateView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"POST": "task.escalate"}

    @extend_schema(
        request=s.NoteInput, responses=s.CountOutput, tags=["tasks"], summary="Escalate a blocked task to managers"
    )
    def post(self, request, task_id):
        task_services.get_task(request.user, task_id)
        data = s.NoteInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            {"count": details.escalate(actor=request.user, task_id=task_id, note=data.validated_data["note"])}
        )


class SubtasksView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view", "POST": "task.create"}

    @extend_schema(responses=s.TaskSummary(many=True), tags=["tasks"], summary="Subtasks")
    def get(self, request, task_id):
        parent = task_services.get_task(request.user, task_id)
        subtasks = selectors.visible_tasks(request.user).filter(parent=parent).order_by("number")
        return Response(s.TaskSummary(subtasks, many=True).data)

    @extend_schema(
        request=s.TaskCreateInput,
        responses={201: s.TaskDetail},
        tags=["tasks"],
        summary="Create a subtask (project and parent come from the URL)",
    )
    def post(self, request, task_id):
        parent = task_services.get_task(request.user, task_id)
        payload = {**request.data, "project_id": str(parent.project_id)}
        data = s.TaskCreateInput(data=payload)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("project_id")
        values.pop("parent_id", None)
        values.update(project=parent.project, parent=parent)
        values["reviewer"] = _user(request.user, values.pop("reviewer_id", None), "reviewer_id")
        if values["reviewer"] is None:
            values.pop("reviewer")
        task = task_services.create_task(actor=request.user, data=values)
        return Response(_detail(request, task.pk), status=status.HTTP_201_CREATED)


# --- Checklists ---------------------------------------------------------------------------------


def _checklist(request, task_id, checklist_id) -> TaskChecklist:
    task = task_services.get_task(request.user, task_id)
    checklist = TaskChecklist.objects.filter(pk=checklist_id, task=task).first()
    if checklist is None:
        raise NotFound()
    return checklist


def _item(request, task_id, item_id) -> ChecklistItem:
    task = task_services.get_task(request.user, task_id)
    item = ChecklistItem.objects.filter(pk=item_id, checklist__task=task).select_related("checklist").first()
    if item is None:
        raise NotFound()
    return item


class ChecklistsView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view", "POST": "task.checklist.manage"}

    @extend_schema(responses=s.ChecklistOutput(many=True), tags=["tasks"], summary="Checklists")
    def get(self, request, task_id):
        task = task_services.get_task(request.user, task_id)
        return Response(s.ChecklistOutput(task.checklists.prefetch_related("items__done_by"), many=True).data)

    @extend_schema(
        request=s.ChecklistInput, responses={201: s.ChecklistOutput}, tags=["tasks"], summary="Add a checklist"
    )
    def post(self, request, task_id):
        task_services.get_task(request.user, task_id)
        data = s.ChecklistInput(data=request.data)
        data.is_valid(raise_exception=True)
        checklist = details.add_checklist(actor=request.user, task_id=task_id, **data.validated_data)
        return Response(s.ChecklistOutput(checklist).data, status=status.HTTP_201_CREATED)


class ChecklistDetailView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"PATCH": "task.checklist.manage", "DELETE": "task.checklist.manage"}

    @extend_schema(
        request=s.ChecklistUpdateInput,
        responses=s.ChecklistOutput,
        tags=["tasks"],
        summary="Rename or reorder a checklist",
    )
    def patch(self, request, task_id, checklist_id):
        checklist = _checklist(request, task_id, checklist_id)
        data = s.ChecklistUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        checklist = details.update_checklist(actor=request.user, checklist=checklist, data=data.validated_data)
        return Response(s.ChecklistOutput(checklist).data)

    @extend_schema(responses={204: None}, tags=["tasks"], summary="Delete a checklist")
    def delete(self, request, task_id, checklist_id):
        details.delete_checklist(actor=request.user, checklist=_checklist(request, task_id, checklist_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChecklistItemsView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"POST": "task.checklist.manage"}

    @extend_schema(
        request=s.ChecklistItemInput,
        responses={201: s.ChecklistItemOutput},
        tags=["tasks"],
        summary="Add a checklist item",
    )
    def post(self, request, task_id, checklist_id):
        checklist = _checklist(request, task_id, checklist_id)
        data = s.ChecklistItemInput(data=request.data)
        data.is_valid(raise_exception=True)
        item = details.add_item(actor=request.user, checklist=checklist, **data.validated_data)
        return Response(s.ChecklistItemOutput(item).data, status=status.HTTP_201_CREATED)


class ChecklistItemDetailView(TenantAPIView):
    queryset = TASK_HINT
    # Ticking needs task.checklist.complete; editing text/required needs .manage (checked in the service).
    permission_map = {"PATCH": "task.checklist.complete", "DELETE": "task.checklist.manage"}

    @extend_schema(
        request=s.ChecklistItemUpdateInput,
        responses=s.ChecklistItemOutput,
        tags=["tasks"],
        summary="Tick, untick or edit an item",
    )
    def patch(self, request, task_id, item_id):
        item = _item(request, task_id, item_id)
        data = s.ChecklistItemUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        item = details.update_item(actor=request.user, item=item, data=data.validated_data)
        return Response(s.ChecklistItemOutput(item).data)

    @extend_schema(responses={204: None}, tags=["tasks"], summary="Delete a checklist item")
    def delete(self, request, task_id, item_id):
        details.delete_item(actor=request.user, item=_item(request, task_id, item_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Dependencies -----------------------------------------------------------------------------


class DependenciesView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view", "POST": "task.dependency.manage"}

    @extend_schema(responses=s.DependencyOutput(many=True), tags=["tasks"], summary="Tasks this task waits on")
    def get(self, request, task_id):
        task = task_services.get_task(request.user, task_id)
        deps = task.dependencies.select_related("blocked_by__project")
        return Response(s.DependencyOutput(deps, many=True).data)

    @extend_schema(
        request=s.DependencyInput,
        responses={201: s.DependencyOutput},
        tags=["tasks"],
        summary="Add a dependency (409 if it would create a cycle)",
    )
    def post(self, request, task_id):
        task_services.get_task(request.user, task_id)
        data = s.DependencyInput(data=request.data)
        data.is_valid(raise_exception=True)
        dep = details.add_dependency(
            actor=request.user, task_id=task_id, blocked_by_id=data.validated_data["blocked_by_id"]
        )
        return Response(s.DependencyOutput(dep).data, status=status.HTTP_201_CREATED)


class DependencyDetailView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"DELETE": "task.dependency.manage"}

    @extend_schema(responses={204: None}, tags=["tasks"], summary="Remove a dependency")
    def delete(self, request, task_id, dependency_id):
        task = task_services.get_task(request.user, task_id)
        dep = TaskDependency.objects.filter(pk=dependency_id, task=task).select_related("blocked_by__project").first()
        if dep is None:
            raise NotFound()
        details.remove_dependency(actor=request.user, dependency=dep)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Comments -------------------------------------------------------------------------------------


class CommentsView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view", "POST": "task.comment"}
    pagination_class = CursorPagination

    @extend_schema(responses=s.CommentOutput(many=True), tags=["tasks"], summary="Comments (newest first)")
    def get(self, request, task_id):
        task = task_services.get_task(request.user, task_id)
        qs = TaskComment.objects.filter(task=task).select_related("author").prefetch_related("mentions")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(s.CommentOutput(page, many=True).data)

    @extend_schema(
        request=s.CommentBodyInput,
        responses={201: s.CommentOutput},
        tags=["tasks"],
        summary="Comment (Markdown; mention with @[Name](user:<uuid>))",
    )
    def post(self, request, task_id):
        task_services.get_task(request.user, task_id)
        data = s.CommentBodyInput(data=request.data)
        data.is_valid(raise_exception=True)
        comment = details.add_comment(actor=request.user, task_id=task_id, body=data.validated_data["body"])
        return Response(s.CommentOutput(comment).data, status=status.HTTP_201_CREATED)


class CommentDetailView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"PATCH": "task.comment", "DELETE": "task.view"}

    def _comment(self, request, task_id, comment_id) -> TaskComment:
        task = task_services.get_task(request.user, task_id)
        comment = TaskComment.objects.filter(pk=comment_id, task=task).first()
        if comment is None:
            raise NotFound()
        return comment

    @extend_schema(
        request=s.CommentBodyInput,
        responses=s.CommentOutput,
        tags=["tasks"],
        summary="Edit own comment (within 15 minutes)",
    )
    def patch(self, request, task_id, comment_id):
        comment = self._comment(request, task_id, comment_id)
        data = s.CommentBodyInput(data=request.data)
        data.is_valid(raise_exception=True)
        comment = details.edit_comment(actor=request.user, comment=comment, body=data.validated_data["body"])
        return Response(s.CommentOutput(comment).data)

    @extend_schema(responses={204: None}, tags=["tasks"], summary="Delete a comment (author or task manager)")
    def delete(self, request, task_id, comment_id):
        details.delete_comment(actor=request.user, comment=self._comment(request, task_id, comment_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Attachments --------------------------------------------------------------------------------------


class AttachmentsView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view", "POST": "task.attachment.upload"}
    pagination_class = None

    @extend_schema(responses=s.AttachmentOutput(many=True), tags=["tasks"], summary="Attachments")
    def get(self, request, task_id):
        task = task_services.get_task(request.user, task_id)
        files = task.attachments.filter(status=TaskAttachment.State.ACTIVE).select_related("uploaded_by")
        return Response(s.AttachmentOutput(files, many=True).data)

    @extend_schema(
        request={"multipart/form-data": s.AttachmentInput},
        responses={201: s.AttachmentOutput},
        tags=["tasks"],
        summary="Upload a file (multipart field 'file')",
    )
    def post(self, request, task_id):
        task_services.get_task(request.user, task_id)
        upload = request.FILES.get("file")
        if upload is None:
            raise InvalidInput(details={"file": ["Attach a file in the 'file' field."]})
        attachment = attachments.upload(actor=request.user, task_id=task_id, uploaded_file=upload)
        return Response(s.AttachmentOutput(attachment).data, status=status.HTTP_201_CREATED)


class AttachmentDownloadView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view"}

    @extend_schema(
        responses={(200, "application/octet-stream"): bytes},
        tags=["tasks"],
        summary="Download a file (streamed after a permission check)",
    )
    def get(self, request, task_id, attachment_id):
        attachment, handle = attachments.open_for_download(
            actor=request.user, task_id=task_id, attachment_id=attachment_id
        )
        response = FileResponse(
            handle, as_attachment=True, filename=attachment.filename, content_type=attachment.content_type
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response


class AttachmentDetailView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"DELETE": "task.view"}

    @extend_schema(responses={204: None}, tags=["tasks"], summary="Delete a file (uploader or task manager)")
    def delete(self, request, task_id, attachment_id):
        attachments.delete(actor=request.user, task_id=task_id, attachment_id=attachment_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Activity ------------------------------------------------------------------------------------


class ActivityView(TenantAPIView):
    queryset = TASK_HINT
    permission_map = {"GET": "task.view"}
    pagination_class = CursorPagination

    @extend_schema(responses=s.ActivityOutput(many=True), tags=["tasks"], summary="Task activity timeline")
    def get(self, request, task_id):
        task = task_services.get_task(request.user, task_id)
        page = self.paginate_queryset(TaskActivity.objects.filter(task=task).select_related("actor"))
        return self.get_paginated_response(s.ActivityOutput(page, many=True).data)


# --- Company workflow rules ----------------------------------------------------------------------------


class RuleListView(TenantAPIView):
    queryset = StatusTransitionRule._base_manager.none()
    permission_map = {"GET": "employee.view"}
    pagination_class = None

    @extend_schema(responses=s.RuleOutput(many=True), tags=["company"], summary="Status transition rules")
    def get(self, request):
        return Response(s.RuleOutput(StatusTransitionRule.objects.all(), many=True).data)


class RuleDetailView(TenantAPIView):
    queryset = StatusTransitionRule._base_manager.none()
    permission_map = {"PATCH": "workflow.manage"}

    @extend_schema(request=s.RuleUpdateInput, responses=s.RuleOutput, tags=["company"], summary="Edit a rule")
    def patch(self, request, rule_id):
        rule = StatusTransitionRule.objects.filter(pk=rule_id).first()
        if rule is None:
            raise NotFound()
        data = s.RuleUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(s.RuleOutput(rules.update_rule(actor=request.user, rule=rule, data=data.validated_data)).data)


class RuleResetView(TenantAPIView):
    queryset = StatusTransitionRule._base_manager.none()
    permission_map = {"POST": "workflow.manage"}

    @extend_schema(request=None, responses=s.CountOutput, tags=["company"], summary="Restore default rules")
    def post(self, request):
        return Response({"count": rules.reset_rules(actor=request.user)})
