import uuid
from datetime import timedelta

import structlog
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.common import request_context, tenancy

from .models import ImpersonationSession, User, UserSession

TOUCH_INTERVAL = timedelta(minutes=1)


def _fail(message: str, code: str):
    raise AuthenticationFailed(message, code=code)


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        _fail("Invalid token.", "token_invalid")


class JWTAuthentication(BaseAuthentication):
    """Bearer access token -> user, with the tenant context taken from the token.

    The tenant context is activated *before* the user is loaded, so Postgres RLS
    independently confirms the user belongs to the company named in the token.
    """

    def authenticate_header(self, request):
        return 'Bearer realm="api"'

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header:
            return None
        scheme, _, raw = header.partition(" ")
        if scheme != "Bearer" or not raw:
            _fail("Invalid authorization header.", "token_invalid")
        try:
            token = AccessToken(raw.strip())
        except TokenError as exc:
            expired = "expired" in str(exc).lower()
            _fail("Token expired." if expired else "Invalid token.", "token_expired" if expired else "token_invalid")

        company_id = _uuid(token.get("cid"))
        user_id = _uuid(token.get("sub"))
        imp_id = _uuid(token.get("imp"))

        impersonation = None
        impersonator = None
        if imp_id:
            # The super admin row is only visible in platform context.
            tenancy.activate(tenancy.TenantState(tenancy.Mode.PLATFORM))
            impersonation = ImpersonationSession.objects.filter(pk=imp_id).select_related("super_admin").first()
            if (
                impersonation is None
                or not impersonation.is_active
                or impersonation.target_user_id != user_id
                or impersonation.company_id != company_id
                or not impersonation.super_admin.is_active
            ):
                _fail("Impersonation session has ended.", "session_revoked")
            impersonator = impersonation.super_admin

        tenancy.activate(tenancy.state_for_company(company_id))
        user = User.objects.select_related("company").filter(pk=user_id).first()
        if user is None or user.company_id != company_id or not user.is_active:
            _fail("Invalid token.", "token_invalid")
        if token.get("sv") != user.session_version:
            _fail("Your session has ended. Please sign in again.", "session_revoked")
        if user.company_id and not user.company.is_active:
            raise PermissionDenied("This company account is suspended.", code="company_suspended")

        if impersonation is None:
            session_id = _uuid(token.get("sid"))
            session = UserSession.objects.filter(pk=session_id, user_id=user.pk).first() if session_id else None
            if session is None or not session.is_active:
                _fail("Your session has ended. Please sign in again.", "session_revoked")
            now = timezone.now()
            if now - session.last_used_at > TOUCH_INTERVAL:
                UserSession.objects.filter(pk=session.pk).update(last_used_at=now)
            request.session_id = session.pk
        else:
            request.impersonation = impersonation
            request._impersonator = impersonator
            request_context.update(impersonator_id=str(impersonator.pk))

        structlog.contextvars.bind_contextvars(user_id=str(user.pk), company_id=str(company_id or ""))
        return user, token
