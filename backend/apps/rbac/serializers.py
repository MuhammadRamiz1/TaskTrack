from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .catalogue import Scope
from .models import Permission, Role

TENANT_SCOPES = [s.value for s in Scope if s != Scope.PLATFORM]


class PermissionOutput(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["code", "module", "description", "allowed_scopes"]


class GrantSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=80)
    scope = serializers.ChoiceField(choices=TENANT_SCOPES)


class RoleGrantOutput(serializers.Serializer):
    code = serializers.CharField()
    scope = serializers.CharField()


class RoleOutput(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    holders = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Role
        fields = ["id", "key", "name", "description", "rank", "is_system", "permissions", "holders"]

    @extend_schema_field(RoleGrantOutput(many=True))
    def get_permissions(self, role) -> list[dict]:
        return [{"code": g.permission.code, "scope": g.scope} for g in role.grants.select_related("permission")]


class RoleCreateInput(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    description = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    rank = serializers.IntegerField(min_value=1, max_value=99)
    permissions = GrantSerializer(many=True)


class RoleUpdateInput(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False)
    description = serializers.CharField(max_length=200, required=False, allow_blank=True)
    rank = serializers.IntegerField(min_value=1, max_value=99, required=False)


class RolePermissionsInput(serializers.Serializer):
    permissions = GrantSerializer(many=True)
