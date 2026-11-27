import django_filters
from django.db.models import Count, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.serializers import EmployeeTeamsInput
from apps.accounts.views_hr import get_employee
from apps.common.exceptions import InvalidInput, NotFound
from apps.common.pagination import PageNumberPagination
from apps.common.views import LIST_FILTERS, TenantAPIView, schema_generation
from apps.rbac import policy

from . import serializers as s
from . import services
from .models import Holiday, LeaveDay, Project, Team


def _visible(actor, model, code: str, pk, **related):
    obj = model.objects.filter(pk=pk).select_related(*related.get("select", ())).first()
    if obj is None or not policy.can(actor, code, obj):
        raise NotFound()
    return obj


def get_team(actor, team_id) -> Team:
    return _visible(actor, Team, "team.view", team_id, select=("lead",))


def get_project(actor, project_id) -> Project:
    return _visible(actor, Project, "project.view", project_id, select=("team", "owner"))


def _company_user(actor, user_id, field="owner_id") -> User:
    user = User.objects.filter(pk=user_id, company_id=actor.company_id).first()
    if user is None:
        raise InvalidInput(details={field: ["Unknown employee."]})
    return user


def _members_response(users):
    return Response(s.MemberOutput(users, many=True).data)


# --- Teams ------------------------------------------------------------------------


class TeamFilter(django_filters.FilterSet):
    is_archived = django_filters.BooleanFilter()

    class Meta:
        model = Team
        fields = ["is_archived"]


class TeamListView(TenantAPIView):
    pagination_class = PageNumberPagination
    permission_map = {"GET": "team.view", "POST": "team.manage"}
    filter_backends = LIST_FILTERS
    filterset_class = TeamFilter
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        if schema_generation(self):
            return Team._base_manager.none()
        qs = Team.objects.select_related("lead").annotate(
            member_count=Count("memberships", distinct=True), project_count=Count("projects", distinct=True)
        )
        return policy.scope_queryset(self.request.user, "team.view", qs)

    @extend_schema(responses=s.TeamOutput(many=True), tags=["org"], summary="Teams you can see")
    def get(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(s.TeamOutput(page, many=True).data)

    @extend_schema(request=s.TeamInput, responses={201: s.TeamOutput}, tags=["org"], summary="Create a team")
    def post(self, request):
        data = s.TeamInput(data=request.data)
        data.is_valid(raise_exception=True)
        team = services.create_team(actor=request.user, **data.validated_data)
        return Response(s.TeamOutput(team).data, status=status.HTTP_201_CREATED)


class TeamDetailView(TenantAPIView):
    queryset = Team._base_manager.none()
    permission_map = {"GET": "team.view", "PATCH": "team.manage", "DELETE": "team.manage"}

    @extend_schema(responses=s.TeamOutput, tags=["org"], summary="Team details")
    def get(self, request, team_id):
        return Response(s.TeamOutput(get_team(request.user, team_id)).data)

    @extend_schema(request=s.TeamUpdateInput, responses=s.TeamOutput, tags=["org"], summary="Edit a team")
    def patch(self, request, team_id):
        team = get_team(request.user, team_id)
        data = s.TeamUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(
            s.TeamOutput(services.update_team(actor=request.user, team=team, data=data.validated_data)).data
        )

    @extend_schema(responses=s.TeamOutput, tags=["org"], summary="Archive a team")
    def delete(self, request, team_id):
        team = services.archive_team(actor=request.user, team=get_team(request.user, team_id))
        return Response(s.TeamOutput(team).data)


class TeamMembersView(TenantAPIView):
    queryset = Team._base_manager.none()
    permission_map = {"GET": "team.view", "POST": "team.manage"}
    pagination_class = None

    @extend_schema(responses=s.MemberOutput(many=True), tags=["org"], summary="Team members")
    def get(self, request, team_id):
        team = get_team(request.user, team_id)
        return _members_response(User.objects.filter(team_memberships__team=team).order_by("first_name"))

    @extend_schema(
        request=s.UserIdsInput, responses={201: s.MemberOutput(many=True)}, tags=["org"], summary="Add team members"
    )
    def post(self, request, team_id):
        team = get_team(request.user, team_id)
        data = s.UserIdsInput(data=request.data)
        data.is_valid(raise_exception=True)
        services.add_team_members(actor=request.user, team=team, user_ids=data.validated_data["user_ids"])
        users = User.objects.filter(team_memberships__team=team).order_by("first_name")
        return Response(s.MemberOutput(users, many=True).data, status=status.HTTP_201_CREATED)


class TeamMemberDetailView(TenantAPIView):
    queryset = Team._base_manager.none()
    permission_map = {"DELETE": "team.manage"}

    @extend_schema(responses={204: None}, tags=["org"], summary="Remove a team member")
    def delete(self, request, team_id, user_id):
        services.remove_team_member(actor=request.user, team=get_team(request.user, team_id), user_id=user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamLeadView(TenantAPIView):
    queryset = Team._base_manager.none()
    permission_map = {"POST": "team.manage"}

    @extend_schema(
        request=s.UserIdInput,
        responses=s.TeamOutput,
        tags=["org"],
        summary="Set the team lead (adds the TEAM_LEAD role bound to this team)",
    )
    def post(self, request, team_id):
        team = get_team(request.user, team_id)
        data = s.UserIdInput(data=request.data)
        data.is_valid(raise_exception=True)
        team = services.set_team_lead(actor=request.user, team=team, user_id=data.validated_data["user_id"])
        return Response(s.TeamOutput(team).data)


# --- Projects -----------------------------------------------------------------------


class ProjectFilter(django_filters.FilterSet):
    team = django_filters.UUIDFilter(field_name="team_id")
    status = django_filters.MultipleChoiceFilter(choices=Project.Status.choices)

    class Meta:
        model = Project
        fields = ["team", "status"]


class ProjectListView(TenantAPIView):
    pagination_class = PageNumberPagination
    permission_map = {"GET": "project.view", "POST": "project.manage"}
    filter_backends = LIST_FILTERS
    filterset_class = ProjectFilter
    search_fields = ["key", "name", "description"]
    ordering_fields = ["name", "key", "created_at", "end_date"]
    ordering = ["name"]

    def get_queryset(self):
        if schema_generation(self):
            return Project._base_manager.none()
        qs = Project.objects.select_related("team", "owner").annotate(
            member_count=Count("memberships", distinct=True),
            open_task_count=Count(
                "tasks",
                filter=Q(tasks__deleted_at__isnull=True) & ~Q(tasks__status__in=["COMPLETED", "CANCELLED"]),
                distinct=True,
            ),
        )
        return policy.scope_queryset(self.request.user, "project.view", qs)

    @extend_schema(responses=s.ProjectOutput(many=True), tags=["org"], summary="Projects you can see")
    def get(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(s.ProjectOutput(page, many=True).data)

    @extend_schema(
        request=s.ProjectInput, responses={201: s.ProjectOutput}, tags=["org"], summary="Create a project in a team"
    )
    def post(self, request):
        data = s.ProjectInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        team = Team.objects.filter(pk=values.pop("team_id")).first()
        if team is None:
            raise InvalidInput(details={"team_id": ["Unknown team."]})
        owner_id = values.pop("owner_id", None)
        if owner_id:
            values["owner"] = _company_user(request.user, owner_id)
        project = services.create_project(actor=request.user, team=team, data=values)
        return Response(s.ProjectOutput(project).data, status=status.HTTP_201_CREATED)


class ProjectDetailView(TenantAPIView):
    queryset = Project._base_manager.none()
    permission_map = {"GET": "project.view", "PATCH": "project.manage", "DELETE": "project.manage"}

    @extend_schema(responses=s.ProjectOutput, tags=["org"], summary="Project details")
    def get(self, request, project_id):
        return Response(s.ProjectOutput(get_project(request.user, project_id)).data)

    @extend_schema(request=s.ProjectUpdateInput, responses=s.ProjectOutput, tags=["org"], summary="Edit a project")
    def patch(self, request, project_id):
        project = get_project(request.user, project_id)
        data = s.ProjectUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        if "owner_id" in values:
            owner_id = values.pop("owner_id")
            values["owner"] = _company_user(request.user, owner_id) if owner_id else None
        project = services.update_project(actor=request.user, project=project, data=values)
        return Response(s.ProjectOutput(project).data)

    @extend_schema(responses=s.ProjectOutput, tags=["org"], summary="Archive a project")
    def delete(self, request, project_id):
        project = services.archive_project(actor=request.user, project=get_project(request.user, project_id))
        return Response(s.ProjectOutput(project).data)


class ProjectMembersView(TenantAPIView):
    queryset = Project._base_manager.none()
    permission_map = {"GET": "project.view", "POST": "project.member.manage"}
    pagination_class = None

    @extend_schema(responses=s.MemberOutput(many=True), tags=["org"], summary="Project members")
    def get(self, request, project_id):
        project = get_project(request.user, project_id)
        return _members_response(User.objects.filter(project_memberships__project=project).order_by("first_name"))

    @extend_schema(
        request=s.UserIdsInput, responses={201: s.MemberOutput(many=True)}, tags=["org"], summary="Add project members"
    )
    def post(self, request, project_id):
        project = get_project(request.user, project_id)
        data = s.UserIdsInput(data=request.data)
        data.is_valid(raise_exception=True)
        services.add_project_members(actor=request.user, project=project, user_ids=data.validated_data["user_ids"])
        users = User.objects.filter(project_memberships__project=project).order_by("first_name")
        return Response(s.MemberOutput(users, many=True).data, status=status.HTTP_201_CREATED)


class ProjectMemberDetailView(TenantAPIView):
    queryset = Project._base_manager.none()
    permission_map = {"DELETE": "project.member.manage"}

    @extend_schema(responses={204: None}, tags=["org"], summary="Remove a project member")
    def delete(self, request, project_id, user_id):
        services.remove_project_member(
            actor=request.user, project=get_project(request.user, project_id), user_id=user_id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Directory, employee teams ---------------------------------------------------------


class DirectoryView(TenantAPIView):
    """Lightweight list of colleagues for pickers and @mentions."""

    pagination_class = PageNumberPagination
    permission_map = {"GET": "employee.view"}
    filter_backends = LIST_FILTERS
    search_fields = ["first_name", "last_name", "email", "job_title"]
    ordering = ["first_name", "last_name"]

    def get_queryset(self):
        if schema_generation(self):
            return User._base_manager.none()
        qs = User.objects.filter(company_id=self.request.user.company_id).exclude(status=User.Status.DEACTIVATED)
        return policy.scope_queryset(self.request.user, "employee.view", qs)

    @extend_schema(responses=s.DirectoryOutput(many=True), tags=["org"], summary="Employee directory")
    def get(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(s.DirectoryOutput(page, many=True).data)


class EmployeeTeamsView(TenantAPIView):
    queryset = User._base_manager.none()
    permission_map = {"PUT": "employee.assign_team"}

    @extend_schema(
        request=EmployeeTeamsInput, responses=s.TeamOutput(many=True), tags=["hr"], summary="Set an employee's teams"
    )
    def put(self, request, user_id):
        target = get_employee(request.user, user_id)
        if not policy.can(request.user, "employee.view_private", target):
            raise NotFound()
        data = EmployeeTeamsInput(data=request.data)
        data.is_valid(raise_exception=True)
        teams = services.set_employee_teams(actor=request.user, target=target, team_ids=data.validated_data["team_ids"])
        return Response(s.TeamOutput(teams, many=True).data)


# --- Holidays and leave ---------------------------------------------------------------------


class HolidayListView(TenantAPIView):
    permission_map = {"GET": "employee.view", "POST": "holiday.manage"}
    pagination_class = None

    def get_queryset(self):
        if schema_generation(self):
            return Holiday._base_manager.none()
        qs = Holiday.objects.all()
        year = self.request.query_params.get("year")
        return qs.filter(date__year=int(year)) if year and year.isdigit() else qs

    @extend_schema(
        parameters=[OpenApiParameter("year", int)],
        responses=s.HolidaySerializer(many=True),
        tags=["hr"],
        summary="Company holidays",
    )
    def get(self, request):
        return Response(s.HolidaySerializer(self.get_queryset(), many=True).data)

    @extend_schema(
        request=s.HolidaySerializer, responses={201: s.HolidaySerializer}, tags=["hr"], summary="Add a holiday"
    )
    def post(self, request):
        data = s.HolidaySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        holiday = services.create_holiday(actor=request.user, **data.validated_data)
        return Response(s.HolidaySerializer(holiday).data, status=status.HTTP_201_CREATED)


class HolidayDetailView(TenantAPIView):
    queryset = Holiday._base_manager.none()
    permission_map = {"DELETE": "holiday.manage"}

    @extend_schema(responses={204: None}, tags=["hr"], summary="Remove a holiday")
    def delete(self, request, holiday_id):
        holiday = Holiday.objects.filter(pk=holiday_id).first()
        if holiday is None:
            raise NotFound()
        services.delete_holiday(actor=request.user, holiday=holiday)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeaveFilter(django_filters.FilterSet):
    user = django_filters.UUIDFilter(field_name="user_id")
    date_from = django_filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="date", lookup_expr="lte")
    kind = django_filters.ChoiceFilter(choices=LeaveDay.Kind.choices)

    class Meta:
        model = LeaveDay
        fields = ["user", "date_from", "date_to", "kind"]


class LeaveListView(TenantAPIView):
    pagination_class = PageNumberPagination
    permission_map = {"GET": "leave.view", "POST": "leave.manage"}
    filter_backends = LIST_FILTERS
    filterset_class = LeaveFilter
    ordering = ["date"]

    def get_queryset(self):
        if schema_generation(self):
            return LeaveDay._base_manager.none()
        return policy.scope_queryset(self.request.user, "leave.view", LeaveDay.objects.select_related("user"))

    @extend_schema(responses=s.LeaveOutput(many=True), tags=["hr"], summary="Leave records")
    def get(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(s.LeaveOutput(page, many=True).data)

    @extend_schema(request=s.LeaveInput, responses={201: s.LeaveOutput}, tags=["hr"], summary="Record leave")
    def post(self, request):
        data = s.LeaveInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        user = _company_user(request.user, values.pop("user_id"), "user_id")
        leave = services.record_leave(actor=request.user, user=user, data=values)
        return Response(s.LeaveOutput(leave).data, status=status.HTTP_201_CREATED)


class LeaveDetailView(TenantAPIView):
    queryset = LeaveDay._base_manager.none()
    permission_map = {"DELETE": "leave.manage"}

    @extend_schema(responses={204: None}, tags=["hr"], summary="Remove a leave record")
    def delete(self, request, leave_id):
        leave = LeaveDay.objects.filter(pk=leave_id).select_related("user").first()
        if leave is None or not policy.can(request.user, "leave.view", leave):
            raise NotFound()
        services.delete_leave(actor=request.user, leave=leave)
        return Response(status=status.HTTP_204_NO_CONTENT)
