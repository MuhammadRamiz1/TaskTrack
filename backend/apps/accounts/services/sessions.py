from dataclasses import dataclass

from django.db.models import F
from django.utils import timezone

from apps.common import request_context

from .. import tokens
from ..models import User, UserSession


@dataclass(frozen=True)
class IssuedTokens:
    access: str
    refresh: str
    session: UserSession


def start_session(user: User) -> IssuedTokens:
    meta = request_context.get()
    session = UserSession(
        company_id=user.company_id,
        user=user,
        refresh_jti="",
        user_agent=meta.user_agent,
        ip=meta.ip,
        expires_at=timezone.now() + tokens.refresh_lifetime(),
    )
    session.save()
    refresh, jti = tokens.issue_refresh(user, session)
    UserSession.objects.filter(pk=session.pk).update(refresh_jti=jti)
    session.refresh_jti = jti
    return IssuedTokens(tokens.issue_access(user, session), refresh, session)


def rotate(session: UserSession, user: User) -> IssuedTokens:
    refresh, jti = tokens.issue_refresh(user, session)
    now = timezone.now()
    UserSession.objects.filter(pk=session.pk).update(
        refresh_jti=jti, last_used_at=now, expires_at=now + tokens.refresh_lifetime()
    )
    session.refresh_jti = jti
    return IssuedTokens(tokens.issue_access(user, session), refresh, session)


def revoke(session: UserSession, reason: str) -> None:
    UserSession.objects.filter(pk=session.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoked_reason=reason
    )


def revoke_all(user: User, reason: str, *, except_session_id=None) -> int:
    qs = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    if except_session_id:
        qs = qs.exclude(pk=except_session_id)
    return qs.update(revoked_at=timezone.now(), revoked_reason=reason)


def bump_session_version(user: User) -> None:
    """Invalidate every access token issued to the user (takes effect on the next request)."""
    User.objects.filter(pk=user.pk).update(session_version=F("session_version") + 1)
    user.refresh_from_db(fields=["session_version"])


def end_all_sessions(user: User, reason: str, *, except_session_id=None) -> int:
    count = revoke_all(user, reason, except_session_id=except_session_id)
    bump_session_version(user)
    return count
