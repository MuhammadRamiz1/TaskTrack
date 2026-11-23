"""JWT issuance. Access tokens live in browser memory; refresh tokens in an httpOnly cookie.

Access claims:  sub, cid (company or null), sv (session_version), sid (UserSession),
                imp (ImpersonationSession, optional), scp ("mfa_enrol" when the company
                enforces 2FA and the user has not enrolled).
Refresh claims: sub, cid, sid, jti. The session stores the current jti; presenting an
                older jti means the token was stolen and replayed, so the session is revoked.
"""

from datetime import timedelta

from django.conf import settings
from django.core import signing
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

MFA_SALT = "tasktrack.mfa-challenge"


def _cid(user) -> str | None:
    return str(user.company_id) if user.company_id else None


def needs_mfa_enrolment(user) -> bool:
    return bool(user.company_id and user.company.enforce_2fa and not user.totp_enabled)


def issue_access(user, session=None, *, impersonation=None) -> str:
    token = AccessToken()
    token["sub"] = str(user.pk)
    token["cid"] = _cid(user)
    token["sv"] = user.session_version
    token["sid"] = str(session.pk) if session else None
    if impersonation is not None:
        token["imp"] = str(impersonation.pk)
        token.set_exp(lifetime=timedelta(minutes=settings.IMPERSONATION_MINUTES))
    elif needs_mfa_enrolment(user):
        token["scp"] = "mfa_enrol"
    return str(token)


def issue_refresh(user, session) -> tuple[str, str]:
    """Returns (raw token, jti)."""
    token = RefreshToken()
    token["sub"] = str(user.pk)
    token["cid"] = _cid(user)
    token["sid"] = str(session.pk)
    return str(token), token["jti"]


def refresh_lifetime() -> timedelta:
    return settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]


def issue_mfa_challenge(user) -> str:
    return signing.dumps({"uid": str(user.pk), "cid": _cid(user), "sv": user.session_version}, salt=MFA_SALT)


def read_mfa_challenge(raw: str) -> dict | None:
    try:
        return signing.loads(raw, salt=MFA_SALT, max_age=settings.MFA_TOKEN_SECONDS)
    except signing.BadSignature:
        return None
