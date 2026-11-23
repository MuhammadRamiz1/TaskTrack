"""Base views. Every API view in the project inherits from one of these (a test enforces it).

* ``PublicAPIView``     - no authentication (login, invite accept, password reset).
* ``AuthenticatedAPIView`` - any signed-in user (own profile, sessions, 2FA).
* ``TenantAPIView``     - company users only; super admins get 403 (they reach tenant
                          data only through impersonation).
* ``PlatformAPIView``   - super admins only.

Each resets the DB tenant settings before authentication runs, so the only context a
request can have is the one its token proves.
"""

import structlog
from django.db import connection
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from . import tenancy
from .permissions import AccountStatePermission, IsCompanyUser, IsPlatformAdmin

security_log = structlog.get_logger("tasktrack.security")

#: Filtering, search and ordering for list endpoints.
LIST_FILTERS = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)


def schema_generation(view) -> bool:
    """True while drf-spectacular introspects the view (no real request or user)."""
    return getattr(view, "swagger_fake_view", False)


class _ContextResetMixin:
    #: Extra permission classes appended after the base ones.
    extra_permission_classes: tuple = ()
    #: Allowed while ``must_change_password`` is set.
    allow_password_change_required = False
    #: Allowed with an MFA-enrolment-only token.
    allow_mfa_enrolment = False
    #: Allowed for read-only impersonation sessions when the method is unsafe.
    allow_unsafe_during_impersonation = False

    base_permission_classes: tuple = ()
    #: When True, ``permission_map[method]`` must name a policy permission the user holds.
    enforce_policy = False
    #: {"GET": "employee.view_private", "POST": "employee.create", ...}
    permission_map: dict[str, str] = {}

    def initial(self, request, *args, **kwargs):
        tenancy.activate(tenancy.NO_CONTEXT)
        super().initial(request, *args, **kwargs)

    def get_permissions(self):
        classes = [*self.base_permission_classes, *self.permission_classes, *self.extra_permission_classes]
        if self.enforce_policy:
            from apps.rbac.permissions import PolicyPermission  # rbac depends on common, not the reverse

            classes.append(PolicyPermission)
        return [cls() for cls in classes]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        imp = getattr(request, "impersonation", None)
        if imp is not None and connection.needs_rollback:
            # The request failed and its transaction will roll back, so an audit row
            # written now would be lost. Nothing was changed; keep a security log line.
            security_log.warning(
                "impersonation.request_failed",
                impersonation_id=str(imp.id),
                method=request.method,
                path=request.path,
                status=response.status_code,
            )
        elif imp is not None:
            from apps.audit.services import record

            record(
                actor=getattr(request, "_impersonator", None),
                action="impersonation.request",
                entity_type="impersonation_session",
                entity_id=imp.id,
                new_value={"method": request.method, "path": request.path, "status": response.status_code},
                company_id=imp.company_id,
            )
        response["Cache-Control"] = "no-store"
        return response


class PublicAPIView(_ContextResetMixin, APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)


class AuthenticatedAPIView(_ContextResetMixin, APIView):
    base_permission_classes = (IsAuthenticated, AccountStatePermission)
    permission_classes = ()


class TenantAPIView(_ContextResetMixin, generics.GenericAPIView):
    base_permission_classes = (IsAuthenticated, AccountStatePermission, IsCompanyUser)
    permission_classes = ()
    enforce_policy = True
    pagination_class = None  # list views opt in with PageNumberPagination / CursorPagination


class PlatformAPIView(_ContextResetMixin, generics.GenericAPIView):
    base_permission_classes = (IsAuthenticated, AccountStatePermission, IsPlatformAdmin)
    permission_classes = ()
    enforce_policy = True
    pagination_class = None


BASE_VIEW_CLASSES = (PublicAPIView, AuthenticatedAPIView, TenantAPIView, PlatformAPIView)
