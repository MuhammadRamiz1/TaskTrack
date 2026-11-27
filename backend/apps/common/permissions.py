from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission


class _Denied(PermissionDenied):
    def __init__(self, message, code):
        super().__init__(detail=message, code=code)


class AccountStatePermission(BasePermission):
    """Restrictions that depend on the account or token state, not on RBAC."""

    def has_permission(self, request, view):
        user = request.user
        if not user:
            return True  # IsAuthenticated reports the 401
        if getattr(request, "impersonation", None) and request.method not in SAFE_METHODS:
            if not getattr(view, "allow_unsafe_during_impersonation", False):
                raise _Denied("Impersonation sessions are read-only.", "impersonation_read_only")
        token = request.auth or {}
        if token.get("scp") == "mfa_enrol" and not getattr(view, "allow_mfa_enrolment", False):
            raise _Denied(
                "Your company requires two-factor authentication. Set it up to continue.", "mfa_enrolment_required"
            )
        if user.must_change_password and not getattr(view, "allow_password_change_required", False):
            raise _Denied("You must change your password before continuing.", "password_change_required")
        return True


class IsCompanyUser(BasePermission):
    message = "This endpoint is for company users."

    def has_permission(self, request, view):
        return bool(request.user and request.user.company_id)


class IsPlatformAdmin(BasePermission):
    message = "This endpoint is for platform administrators."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_platform_admin and not getattr(request, "impersonation", None))
