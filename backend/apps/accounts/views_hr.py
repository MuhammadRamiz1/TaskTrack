"""/api/v1/hr/ endpoints: employee lifecycle, invites, passwords, roles."""

import django_filters
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.common.exceptions import InvalidInput, NotFound
from apps.common.pagination import PageNumberPagination
from apps.common.views import LIST_FILTERS, TenantAPIView, schema_generation
from apps.rbac import policy
from apps.rbac import services as rbac_services
from apps.rbac.models import Role, UserRole

from . import serializers as s
from .models import InviteToken, User
from .services import employee_import, employees, invites

VIEW = "employee.view_private"


class EmployeeFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=User.Status.choices)
    role = django_filters.CharFilter(method="filter_role", help_text="Role key, e.g. MANAGER")
    manager = django_filters.UUIDFilter(field_name="manager_id")

    class Meta:
        model = User
        fields = ["status", "role", "manager"]

    def filter_role(self, qs, name, value):
        return qs.filter(user_roles__role__key=value).distinct()


def employee_queryset(actor):
    qs = (
        User.objects.filter(company_id=actor.company_id)
        .select_related("manager")
        .prefetch_related(
            Prefetch("user_roles", queryset=UserRole.objects.select_related("role")),
            Prefetch("invites", queryset=InviteToken.objects.order_by("-created_at")),
        )
    )
    return policy.scope_queryset(actor, VIEW, qs)


def get_employee(actor, user_id) -> User:
    """Any employee of the actor's company; services decide visibility (404) and rights (403)."""
    user = User.objects.filter(pk=user_id, company_id=actor.company_id).select_related("company", "manager").first()
    if user is None:
        raise NotFound()
    return user


class _EmployeeView(TenantAPIView):
    queryset = User._base_manager.none()  # schema hint only; real querysets come from the policy layer

    def employee(self, request, user_id) -> User:
        target = get_employee(request.user, user_id)
        if not policy.can(request.user, VIEW, target):
            raise NotFound()
        return target

    def output(self, user_id):
        return s.EmployeeOutput(employee_queryset(self.request.user).get(pk=user_id)).data


class EmployeeListView(_EmployeeView):
    pagination_class = PageNumberPagination
    filter_backends = LIST_FILTERS
    permission_map = {"GET": VIEW, "POST": "employee.create"}
    filterset_class = EmployeeFilter
    search_fields = ["first_name", "last_name", "email", "job_title"]
    ordering_fields = ["first_name", "last_name", "email", "created_at", "status"]
    ordering = ["first_name", "last_name"]

    def get_queryset(self):
        if schema_generation(self):
            return User._base_manager.none()
        return employee_queryset(self.request.user)

    @extend_schema(responses=s.EmployeeOutput(many=True), tags=["hr"], summary="List employees")
    def get(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(s.EmployeeOutput(page, many=True).data)

    @extend_schema(
        request=s.EmployeeCreateInput,
        responses={201: s.EmployeeOutput},
        tags=["hr"],
        summary="Create an employee (status INVITED) and optionally send the invite",
    )
    def post(self, request):
        data = s.EmployeeCreateInput(data=request.data)
        data.is_valid(raise_exception=True)
        user = employees.create(actor=request.user, data=data.validated_data)
        return Response(self.output(user.pk), status=status.HTTP_201_CREATED)


def _upload(request):
    upload = request.FILES.get("file")
    if upload is None:
        raise InvalidInput(details={"file": ["Attach a .xlsx or .csv file in the 'file' field."]})
    return upload


class EmployeeImportPreviewView(_EmployeeView):
    permission_map = {"POST": "employee.create"}

    @extend_schema(
        request={"multipart/form-data": s.EmployeeImportInput},
        responses=s.EmployeeImportOutput,
        tags=["hr"],
        summary="Check an employee sheet without creating anyone",
    )
    def post(self, request):
        result = employee_import.preview(actor=request.user, uploaded=_upload(request))
        return Response(s.EmployeeImportOutput(result).data)


class EmployeeImportView(_EmployeeView):
    permission_map = {"POST": "employee.create"}

    @extend_schema(
        request={"multipart/form-data": s.EmployeeImportInput},
        responses=s.EmployeeImportOutput,
        tags=["hr"],
        summary="Create employees from a sheet and email each an invite link",
    )
    def post(self, request):
        result = employee_import.run(actor=request.user, uploaded=_upload(request))
        return Response(s.EmployeeImportOutput(result).data)


class EmployeeDetailView(_EmployeeView):
    permission_map = {"GET": VIEW, "PATCH": "employee.update"}

    @extend_schema(responses=s.EmployeeOutput, tags=["hr"], summary="Employee details")
    def get(self, request, user_id):
        self.employee(request, user_id)
        return Response(self.output(user_id))

    @extend_schema(
        request=s.EmployeeUpdateInput,
        responses=s.EmployeeOutput,
        tags=["hr"],
        summary="Edit an employee's profile or manager",
    )
    def patch(self, request, user_id):
        target = self.employee(request, user_id)
        data = s.EmployeeUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        employees.update(actor=request.user, target=target, data=data.validated_data)
        return Response(self.output(user_id))


class EmployeeInviteView(_EmployeeView):
    permission_map = {"GET": "employee.invite", "POST": "employee.invite", "DELETE": "employee.invite"}

    @extend_schema(responses=s.InviteStatusOutput, tags=["hr"], summary="Invite link status")
    def get(self, request, user_id):
        target = self.employee(request, user_id)
        policy.require(request.user, "employee.invite", target, view_code=VIEW)
        return Response(s.InviteStatusOutput(invites.status_of(target)).data)

    @extend_schema(
        request=None,
        responses={201: s.InviteStatusOutput},
        tags=["hr"],
        summary="Create or resend the invite link (older links are revoked)",
    )
    def post(self, request, user_id):
        target = self.employee(request, user_id)
        employees.send_invite(actor=request.user, target=target)
        return Response(s.InviteStatusOutput(invites.status_of(target)).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None}, tags=["hr"], summary="Revoke the open invite link")
    def delete(self, request, user_id):
        target = self.employee(request, user_id)
        employees.revoke_invite(actor=request.user, target=target)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmployeeResetLinkView(_EmployeeView):
    permission_map = {"POST": "employee.reset_password"}

    @extend_schema(
        request=None,
        responses={202: s.DetailOutput},
        tags=["hr"],
        summary="Email a password reset link and sign the employee out everywhere",
    )
    def post(self, request, user_id):
        employees.send_reset_link(actor=request.user, target=self.employee(request, user_id))
        return Response({"detail": "Reset link sent."}, status=status.HTTP_202_ACCEPTED)


class EmployeeTemporaryPasswordView(_EmployeeView):
    permission_map = {"POST": "employee.reset_password"}

    @extend_schema(
        request=s.TemporaryPasswordInput,
        responses={200: s.DetailOutput},
        tags=["hr"],
        summary="Set a temporary password (must be changed at next sign-in)",
    )
    def post(self, request, user_id):
        target = self.employee(request, user_id)
        data = s.TemporaryPasswordInput(data=request.data)
        data.is_valid(raise_exception=True)
        employees.set_temporary_password(actor=request.user, target=target, password=data.validated_data["password"])
        return Response({"detail": "Temporary password set. The employee must change it at next sign-in."})


class EmployeeDeactivateView(_EmployeeView):
    permission_map = {"POST": "employee.deactivate"}

    @extend_schema(request=s.ReasonInput, responses=s.DeactivationOutput, tags=["hr"], summary="Deactivate")
    def post(self, request, user_id):
        target = self.employee(request, user_id)
        data = s.ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(employees.deactivate(actor=request.user, target=target, reason=data.validated_data["reason"]))


class EmployeeOffboardView(_EmployeeView):
    permission_map = {"POST": "employee.deactivate"}

    @extend_schema(
        request=s.ReasonInput,
        responses=s.DeactivationOutput,
        tags=["hr"],
        summary="Offboard: deactivate, revoke sessions, flag open work for reassignment",
    )
    def post(self, request, user_id):
        target = self.employee(request, user_id)
        data = s.ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(employees.offboard(actor=request.user, target=target, reason=data.validated_data["reason"]))


class EmployeeReactivateView(_EmployeeView):
    permission_map = {"POST": "employee.deactivate"}

    @extend_schema(request=None, responses=s.EmployeeOutput, tags=["hr"], summary="Reactivate")
    def post(self, request, user_id):
        employees.reactivate(actor=request.user, target=self.employee(request, user_id))
        return Response(self.output(user_id))


class EmployeeRevokeSessionsView(_EmployeeView):
    permission_map = {"POST": "employee.deactivate"}

    @extend_schema(request=None, responses=s.DeactivationOutput, tags=["hr"], summary="Sign out of all devices")
    def post(self, request, user_id):
        count = employees.revoke_sessions(actor=request.user, target=self.employee(request, user_id))
        return Response({"sessions_revoked": count})


class EmployeeRolesView(_EmployeeView):
    permission_map = {"GET": VIEW, "POST": "employee.assign_role"}

    def _roles(self, target):
        return UserRole.objects.filter(user=target).select_related("role").order_by("-role__rank")

    @extend_schema(responses=s.UserRoleOutput(many=True), tags=["hr"], summary="Roles held by an employee")
    def get(self, request, user_id):
        target = self.employee(request, user_id)
        return Response(s.UserRoleOutput(self._roles(target), many=True).data)

    @extend_schema(
        request=s.GrantRoleInput, responses={201: s.UserRoleOutput(many=True)}, tags=["hr"], summary="Grant a role"
    )
    def post(self, request, user_id):
        target = self.employee(request, user_id)
        data = s.GrantRoleInput(data=request.data)
        data.is_valid(raise_exception=True)
        from apps.org.models import Project, Team

        role = Role.objects.filter(pk=data.validated_data["role_id"]).first()
        if role is None:
            raise InvalidInput(details={"role_id": ["Unknown role."]})
        team = project = None
        if data.validated_data.get("team_id"):
            team = Team.objects.filter(pk=data.validated_data["team_id"]).first()
            if team is None:
                raise InvalidInput(details={"team_id": ["Unknown team."]})
        if data.validated_data.get("project_id"):
            project = Project.objects.filter(pk=data.validated_data["project_id"]).first()
            if project is None:
                raise InvalidInput(details={"project_id": ["Unknown project."]})
        rbac_services.grant(actor=request.user, user=target, role=role, team=team, project=project)
        return Response(s.UserRoleOutput(self._roles(target), many=True).data, status=status.HTTP_201_CREATED)


class EmployeeRoleDetailView(_EmployeeView):
    permission_map = {"DELETE": "employee.assign_role"}

    @extend_schema(responses={204: None}, tags=["hr"], summary="Revoke a role")
    def delete(self, request, user_id, user_role_id):
        target = self.employee(request, user_id)
        user_role = UserRole.objects.filter(pk=user_role_id, user=target).select_related("role", "user").first()
        if user_role is None:
            raise NotFound()
        rbac_services.revoke(actor=request.user, user_role=user_role)
        return Response(status=status.HTTP_204_NO_CONTENT)
