"""Login, refresh, logout and two-step (TOTP) login."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

import structlog
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.services import record
from apps.common import tenancy
from apps.common.exceptions import DomainError

from .. import emails, tokens
from ..models import User, UserSession
from . import mfa, sessions

logger = structlog.get_logger(__name__)
_DUMMY_HASH = make_password("timing-equaliser-not-a-password")


class AuthFailed(DomainError):
    status_code = 401
    code = "invalid_credentials"
    message = "Invalid email or password."


class SessionInvalid(DomainError):
    status_code = 401
    code = "session_revoked"
    message = "Your session has ended. Please sign in again."


@dataclass(frozen=True)
class LoginOutcome:
    ok: bool
    tokens: sessions.IssuedTokens | None = None
    user: User | None = None
    mfa_token: str | None = None

    @property
    def mfa_required(self) -> bool:
        return self.mfa_token is not None


FAILED = LoginOutcome(ok=False)


def _lockout_minutes(lockout_count: int) -> int:
    return min(settings.LOGIN_LOCKOUT_BASE_MINUTES * (2**lockout_count), settings.LOGIN_LOCKOUT_MAX_MINUTES)


def _register_failure(user: User, reason: str) -> None:
    user.failed_login_count += 1
    fields = ["failed_login_count"]
    if user.failed_login_count >= settings.LOGIN_MAX_FAILURES:
        minutes = _lockout_minutes(user.lockout_count)
        user.locked_until = timezone.now() + timedelta(minutes=minutes)
        user.lockout_count += 1
        user.failed_login_count = 0
        fields += ["locked_until", "lockout_count"]
        record(actor=user, action="auth.account_locked", entity=user, new_value={"minutes": minutes})
        emails.account_locked(user, minutes)
    user.save(update_fields=fields)
    record(actor=user, action="auth.login_failed", entity=user, new_value={"reason": reason})


def login(email: str, password: str) -> LoginOutcome:
    """Never raises for bad credentials: failures are recorded and FAILED returned,
    so the failure counter is committed (an exception would roll it back)."""
    email = (email or "").strip().lower()
    with tenancy.auth_lookup_context():
        row = User.objects.filter(email=email).values("pk", "company_id").first()
    if row is None:
        check_password(password, _DUMMY_HASH)  # equalise timing for unknown emails
        logger.info("auth.login_failed", reason="unknown_email")
        return FAILED

    with tenancy.context_for_company(row["company_id"]):
        user = User.objects.select_for_update(of=("self",)).select_related("company").get(pk=row["pk"])
        if user.is_locked():
            record(actor=user, action="auth.login_failed", entity=user, new_value={"reason": "locked"})
            return FAILED
        if not user.check_password(password):
            _register_failure(user, "bad_password")
            return FAILED
        if not user.is_active:
            record(actor=user, action="auth.login_failed", entity=user, new_value={"reason": "inactive"})
            return FAILED
        if user.company_id and not user.company.is_active:
            record(actor=user, action="auth.login_failed", entity=user, new_value={"reason": "company_suspended"})
            return FAILED

        user.failed_login_count = 0
        user.lockout_count = 0
        user.locked_until = None
        user.last_login = timezone.now()
        user.save(update_fields=["failed_login_count", "lockout_count", "locked_until", "last_login"])

        if user.totp_enabled:
            record(actor=user, action="auth.mfa_challenge", entity=user)
            return LoginOutcome(ok=True, user=user, mfa_token=tokens.issue_mfa_challenge(user))

        issued = sessions.start_session(user)
        record(actor=user, action="auth.login", entity=user, new_value={"session_id": issued.session.pk})
        return LoginOutcome(ok=True, tokens=issued, user=user)


def verify_mfa_login(mfa_token: str, code: str) -> LoginOutcome:
    claims = tokens.read_mfa_challenge(mfa_token or "")
    if claims is None:
        return FAILED
    company_id = uuid.UUID(claims["cid"]) if claims.get("cid") else None
    with tenancy.context_for_company(company_id):
        user = User.objects.select_for_update(of=("self",)).select_related("company").filter(pk=claims["uid"]).first()
        if user is None or not user.is_active or user.session_version != claims["sv"] or user.is_locked():
            return FAILED
        if not mfa.verify_code_or_recovery(user, code):
            _register_failure(user, "bad_mfa_code")
            return FAILED
        user.failed_login_count = 0
        user.save(update_fields=["failed_login_count"])
        issued = sessions.start_session(user)
        record(actor=user, action="auth.login", entity=user, new_value={"session_id": issued.session.pk, "mfa": True})
        return LoginOutcome(ok=True, tokens=issued, user=user)


def _decode_refresh(raw: str) -> RefreshToken:
    try:
        return RefreshToken(raw)
    except TokenError as exc:
        raise SessionInvalid() from exc


@dataclass(frozen=True)
class RefreshOutcome:
    tokens: sessions.IssuedTokens | None = None
    user: User | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.tokens is not None


def refresh(raw: str) -> RefreshOutcome:
    """Rotate the refresh token. Failures are returned (not raised) so that the
    revocation written on token reuse is committed."""
    token = _decode_refresh(raw or "")
    company_id = uuid.UUID(token["cid"]) if token.get("cid") else None
    with tenancy.context_for_company(company_id):
        session = UserSession.objects.select_for_update().filter(pk=token.get("sid"), user_id=token.get("sub")).first()
        if session is None or not session.is_active:
            return RefreshOutcome(reason="session_revoked")
        if session.refresh_jti != token["jti"]:
            # An already-rotated refresh token was replayed: treat as theft.
            sessions.revoke(session, "refresh_reuse")
            record(
                actor=None,
                action="auth.refresh_reuse_detected",
                entity=session,
                company_id=session.company_id,
                new_value={"user_id": session.user_id},
            )
            return RefreshOutcome(reason="reuse_detected")
        user = User.objects.select_related("company").get(pk=session.user_id)
        if not user.is_active or (user.company_id and not user.company.is_active):
            sessions.revoke(session, "account_inactive")
            return RefreshOutcome(reason="account_inactive")
        return RefreshOutcome(tokens=sessions.rotate(session, user), user=user)


def logout(raw: str | None) -> None:
    if not raw:
        return
    try:
        token = RefreshToken(raw)
    except TokenError:
        return
    company_id = uuid.UUID(token["cid"]) if token.get("cid") else None
    with tenancy.context_for_company(company_id):
        session = UserSession.objects.filter(pk=token.get("sid"), user_id=token.get("sub")).first()
        if session and session.is_active and session.refresh_jti == token["jti"]:
            sessions.revoke(session, "logout")
            record(actor=session.user, action="auth.logout", entity=session, company_id=session.company_id)


def logout_everywhere(user: User) -> int:
    count = sessions.end_all_sessions(user, "logout_all")
    record(actor=user, action="auth.logout_all", entity=user, new_value={"sessions_revoked": count})
    return count
