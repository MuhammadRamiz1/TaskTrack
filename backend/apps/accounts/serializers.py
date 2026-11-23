from django.contrib.auth.password_validation import password_validators_help_texts
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.rbac import policy
from apps.rbac.catalogue import RoleKey

from .models import User, UserSession, validate_timezone

PASSWORD_HELP = " ".join(password_validators_help_texts())


def _password_field(**kwargs):
    return serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128, style={"input_type": "password"}, **kwargs
    )


# --- Auth inputs ------------------------------------------------------------------


class LoginInput(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = _password_field()


class MfaVerifyInput(serializers.Serializer):
    mfa_token = serializers.CharField(max_length=512)
    code = serializers.CharField(max_length=32)


class InviteAcceptInput(serializers.Serializer):
    token = serializers.CharField(max_length=128)
    password = _password_field(help_text=PASSWORD_HELP)


class ForgotPasswordInput(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class ResetPasswordInput(serializers.Serializer):
    token = serializers.CharField(max_length=128)
    new_password = _password_field(help_text=PASSWORD_HELP)


class ChangePasswordInput(serializers.Serializer):
    current_password = _password_field()
    new_password = _password_field(help_text=PASSWORD_HELP)


class MfaCodeInput(serializers.Serializer):
    code = serializers.CharField(max_length=32)


class MfaDisableInput(serializers.Serializer):
    password = _password_field()
    code = serializers.CharField(max_length=32)


class ProfileUpdateInput(serializers.Serializer):
    first_name = serializers.CharField(max_length=100, required=False)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    job_title = serializers.CharField(max_length=120, required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=64, required=False, validators=[validate_timezone])


# --- Auth outputs -------------------------------------------------------------------


class CompanyBrief(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    enforce_2fa = serializers.BooleanField()
    timezone = serializers.CharField()


class RoleBrief(serializers.Serializer):
    id = serializers.UUIDField(source="role.id")
    key = serializers.CharField(source="role.key")
    name = serializers.CharField(source="role.name")
    user_role_id = serializers.UUIDField(source="id")
    team_id = serializers.UUIDField(allow_null=True)
    project_id = serializers.UUIDField(allow_null=True)


class ImpersonationInfo(serializers.Serializer):
    id = serializers.UUIDField()
    expires_at = serializers.DateTimeField()
    super_admin_email = serializers.EmailField()


class MeOutput(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    job_title = serializers.CharField()
    timezone = serializers.CharField()
    status = serializers.CharField()
    is_platform_admin = serializers.BooleanField()
    must_change_password = serializers.BooleanField()
    totp_enabled = serializers.BooleanField()
    company = CompanyBrief(allow_null=True)
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    impersonation = serializers.SerializerMethodField()
    mfa_enrolment_required = serializers.SerializerMethodField()

    @extend_schema_field(RoleBrief(many=True))
    def get_roles(self, user) -> list[dict]:
        if user.is_platform_admin:
            return [
                {
                    "id": None,
                    "key": RoleKey.SUPER_ADMIN,
                    "name": "Super Admin",
                    "user_role_id": None,
                    "team_id": None,
                    "project_id": None,
                }
            ]
        return RoleBrief(user.user_roles.select_related("role").order_by("-role__rank"), many=True).data

    def get_permissions(self, user) -> dict[str, list[str]]:
        return policy.permissions_for(user)

    @extend_schema_field(ImpersonationInfo(allow_null=True))
    def get_impersonation(self, user) -> dict | None:
        imp = self.context.get("impersonation")
        if imp is None:
            return None
        return {"id": str(imp.pk), "expires_at": imp.expires_at, "super_admin_email": imp.super_admin.email}

    def get_mfa_enrolment_required(self, user) -> bool:
        from .tokens import needs_mfa_enrolment

        return needs_mfa_enrolment(user)


class AccessOutput(serializers.Serializer):
    access = serializers.CharField()
    user = MeOutput()


class LoginOutput(serializers.Serializer):
    mfa_required = serializers.BooleanField()
    mfa_token = serializers.CharField(required=False)
    access = serializers.CharField(required=False)
    user = MeOutput(required=False)


class SessionOutput(serializers.ModelSerializer):
    current = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = ["id", "user_agent", "ip", "created_at", "last_used_at", "expires_at", "current"]

    def get_current(self, obj) -> bool:
        return obj.pk == self.context.get("current_session_id")


class InviteInfoOutput(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField()
    company_name = serializers.CharField()
    expires_at = serializers.DateTimeField()


class ResetInfoOutput(serializers.Serializer):
    email = serializers.EmailField()
    expires_at = serializers.DateTimeField()


class MfaSetupOutput(serializers.Serializer):
    secret = serializers.CharField()
    otpauth_uri = serializers.CharField()


class RecoveryCodesOutput(serializers.Serializer):
    recovery_codes = serializers.ListField(child=serializers.CharField())


class DetailOutput(serializers.Serializer):
    detail = serializers.CharField()


# --- HR -------------------------------------------------------------------------------


class InviteStatusOutput(serializers.Serializer):
    state = serializers.ChoiceField(choices=["none", "pending", "expired", "used", "revoked"])
    expires_at = serializers.DateTimeField(allow_null=True)
    send_count = serializers.IntegerField()
    last_sent_at = serializers.DateTimeField(allow_null=True)


class UserBrief(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "full_name"]


class TeamRef(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class EmployeeOutput(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    manager = UserBrief(allow_null=True)
    roles = serializers.SerializerMethodField()
    invite = serializers.SerializerMethodField()
    teams = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "job_title",
            "timezone",
            "status",
            "manager",
            "roles",
            "teams",
            "invite",
            "must_change_password",
            "totp_enabled",
            "last_login",
            "activated_at",
            "deactivated_at",
            "created_at",
        ]

    @extend_schema_field(RoleBrief(many=True))
    def get_roles(self, user) -> list[dict]:
        return RoleBrief(sorted(user.user_roles.all(), key=lambda ur: -ur.role.rank), many=True).data

    @extend_schema_field(TeamRef(many=True))
    def get_teams(self, user) -> list[dict]:
        return TeamRef([m.team for m in user.team_memberships.all()], many=True).data

    @extend_schema_field(InviteStatusOutput)
    def get_invite(self, user) -> dict:
        invites = sorted(user.invites.all(), key=lambda i: i.created_at, reverse=True)
        if not invites:
            return {"state": "none", "expires_at": None, "send_count": 0, "last_sent_at": None}
        latest = invites[0]
        return {
            "state": "pending" if latest.state == "valid" else latest.state,
            "expires_at": latest.expires_at,
            "send_count": latest.send_count,
            "last_sent_at": latest.created_at,
        }


class EmployeeCreateInput(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    job_title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    timezone = serializers.CharField(max_length=64, required=False, validators=[validate_timezone])
    manager_id = serializers.UUIDField(required=False, allow_null=True)
    role_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=10)
    send_invite = serializers.BooleanField(default=True)


class EmployeeUpdateInput(serializers.Serializer):
    first_name = serializers.CharField(max_length=100, required=False)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    job_title = serializers.CharField(max_length=120, required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=64, required=False, validators=[validate_timezone])
    manager_id = serializers.UUIDField(required=False, allow_null=True)


class TemporaryPasswordInput(serializers.Serializer):
    password = _password_field(help_text=PASSWORD_HELP)


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class DeactivationOutput(serializers.Serializer):
    sessions_revoked = serializers.IntegerField()
    tasks_flagged = serializers.IntegerField(required=False)
    timers_stopped = serializers.IntegerField(required=False)


class GrantRoleInput(serializers.Serializer):
    role_id = serializers.UUIDField()
    team_id = serializers.UUIDField(required=False, allow_null=True, help_text="Bind the role to one team.")
    project_id = serializers.UUIDField(required=False, allow_null=True, help_text="Bind the role to one project.")


class EmployeeTeamsInput(serializers.Serializer):
    team_ids = serializers.ListField(child=serializers.UUIDField(), max_length=50)


class UserRoleOutput(serializers.Serializer):
    user_role_id = serializers.UUIDField(source="id")
    role_id = serializers.UUIDField(source="role.id")
    key = serializers.CharField(source="role.key")
    name = serializers.CharField(source="role.name")
    rank = serializers.IntegerField(source="role.rank")
    team_id = serializers.UUIDField(allow_null=True)
    project_id = serializers.UUIDField(allow_null=True)
    granted_at = serializers.DateTimeField(source="created_at")


# --- Platform ---------------------------------------------------------------------------


class CompanyAdminInput(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    job_title = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=[RoleKey.HR.value, RoleKey.COMPANY_ADMIN.value], default=RoleKey.HR.value)


class PlatformUserOutput(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "status", "roles", "last_login"]

    def get_roles(self, user) -> list[str]:
        return sorted({ur.role.name for ur in user.user_roles.all()})


class ImpersonationInput(serializers.Serializer):
    user_id = serializers.UUIDField()
    reason = serializers.CharField(min_length=10, max_length=500)


class ImpersonationOutput(serializers.Serializer):
    id = serializers.UUIDField()
    access = serializers.CharField()
    expires_at = serializers.DateTimeField()
    target_user = UserBrief()
    company_id = serializers.UUIDField()
