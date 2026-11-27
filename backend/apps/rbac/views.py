from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

from apps.common.exceptions import NotFound
from apps.common.views import TenantAPIView

from . import serializers as s
from . import services
from .catalogue import Scope
from .models import Permission, Role


def _role(role_id) -> Role:
    role = Role.objects.annotate(holders=Count("user_roles")).filter(pk=role_id).first()
    if role is None:
        raise NotFound()
    return role


class PermissionCatalogueView(TenantAPIView):
    queryset = Permission.objects.none()  # schema hint only; never evaluated
    permission_map = {"GET": "role.manage"}
    pagination_class = None

    @extend_schema(responses=s.PermissionOutput(many=True), tags=["company"], summary="Permission catalogue")
    def get(self, request):
        perms = Permission.objects.exclude(allowed_scopes=[Scope.PLATFORM.value])
        return Response(s.PermissionOutput(perms, many=True).data)


class RoleListView(TenantAPIView):
    queryset = Role._base_manager.none()  # schema hint only; never evaluated
    permission_map = {"GET": "role.manage", "POST": "role.manage"}
    pagination_class = None

    @extend_schema(responses=s.RoleOutput(many=True), tags=["company"], summary="Company roles")
    def get(self, request):
        roles = Role.objects.annotate(holders=Count("user_roles")).order_by("-rank", "name")
        return Response(s.RoleOutput(roles, many=True).data)

    @extend_schema(
        request=s.RoleCreateInput, responses={201: s.RoleOutput}, tags=["company"], summary="Create a custom role"
    )
    def post(self, request):
        data = s.RoleCreateInput(data=request.data)
        data.is_valid(raise_exception=True)
        role = services.create_role(
            actor=request.user,
            name=data.validated_data["name"],
            description=data.validated_data["description"],
            rank=data.validated_data["rank"],
            grants=data.validated_data["permissions"],
        )
        return Response(s.RoleOutput(_role(role.pk)).data, status=status.HTTP_201_CREATED)


class RoleDetailView(TenantAPIView):
    queryset = Role._base_manager.none()  # schema hint only; never evaluated
    permission_map = {"GET": "role.manage", "PATCH": "role.manage", "DELETE": "role.manage"}

    @extend_schema(responses=s.RoleOutput, tags=["company"], summary="Role details")
    def get(self, request, role_id):
        return Response(s.RoleOutput(_role(role_id)).data)

    @extend_schema(request=s.RoleUpdateInput, responses=s.RoleOutput, tags=["company"], summary="Edit a role")
    def patch(self, request, role_id):
        role = _role(role_id)
        data = s.RoleUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        services.update_role(actor=request.user, role=role, data=data.validated_data)
        return Response(s.RoleOutput(_role(role_id)).data)

    @extend_schema(responses={204: None}, tags=["company"], summary="Delete a custom role")
    def delete(self, request, role_id):
        services.delete_role(actor=request.user, role=_role(role_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class RolePermissionsView(TenantAPIView):
    queryset = Role._base_manager.none()  # schema hint only; never evaluated
    permission_map = {"PUT": "role.manage"}

    @extend_schema(
        request=s.RolePermissionsInput, responses=s.RoleOutput, tags=["company"], summary="Replace a role's permissions"
    )
    def put(self, request, role_id):
        role = _role(role_id)
        data = s.RolePermissionsInput(data=request.data)
        data.is_valid(raise_exception=True)
        services.set_role_permissions(actor=request.user, role=role, grants=data.validated_data["permissions"])
        return Response(s.RoleOutput(_role(role_id)).data)


class GrantableRolesView(TenantAPIView):
    queryset = Role._base_manager.none()  # schema hint only; never evaluated
    permission_map = {"GET": "employee.assign_role"}
    pagination_class = None

    @extend_schema(responses=s.RoleOutput(many=True), tags=["hr"], summary="Roles you can grant")
    def get(self, request):
        return Response(s.RoleOutput(services.grantable_roles(request.user), many=True).data)
