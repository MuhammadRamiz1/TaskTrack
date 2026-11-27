"""Password change, self-service reset and HR-initiated reset."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.services import record
from apps.common import tenancy
from apps.common.exceptions import Conflict, Gone, InvalidInput
from apps.common.security import new_url_token, sha256_hex

from .. import emails, tokens
from ..models import PasswordResetToken, User
from . import sessions

RESET_INVALID_MESSAGE = "This reset link is no longer valid. Request a new one."


def _validate(password: str, user: User, field: str = "password") -> None:
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise InvalidInput(details={field: exc.messages}) from exc


def _set_password(user: User, password: str, *, must_change: bool = False) -> None:
    user.set_password(password)
    user.must_change_password = must_change
    user.password_changed_at = timezone.now()
    user.failed_login_count = 0
    user.locked_until = None
    user.save(
        update_fields=[
            "password",
            "must_change_password",
            "password_changed_at",
            "failed_login_count",
            "locked_until",
            "updated_at",
        ]
    )


def _issue_reset_token(user: User, *, origin: str, actor: User | None) -> PasswordResetToken:
    now = timezone.now()
    PasswordResetToken.objects.filter(user=user, used_at__isnull=True, revoked_at__isnull=True).update(revoked_at=now)
    raw = new_url_token()
    token = PasswordResetToken.objects.create(
        company_id=user.company_id,
        user=user,
        origin=origin,
        created_by=actor,
        token_hash=sha256_hex(raw),
        expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_EXPIRY_MINUTES),
    )
    emails.password_reset(user, raw, token.expires_at, by_hr=origin == PasswordResetToken.Origin.HR)
    return token


# --- Self-service -----------------------------------------------------------------


def change(user: User, current_password: str, new_password: str, current_session_id) -> str:
    """Returns a fresh access token for the current session (all others are revoked)."""
    if not user.check_password(current_password):
        raise InvalidInput(details={"current_password": ["Your current password is incorrect."]})
    if current_password == new_password:
        raise InvalidInput(details={"new_password": ["Choose a password different from the current one."]})
    _validate(new_password, user, "new_password")
    was_temporary = user.must_change_password
    _set_password(user, new_password)
    revoked = sessions.revoke_all(user, "password_changed", except_session_id=current_session_id)
    sessions.bump_session_version(user)
    record(
        actor=user,
        action="password.changed",
        entity=user,
        new_value={"other_sessions_revoked": revoked, "was_temporary": was_temporary},
    )
    emails.password_changed(user, "you changed it")
    current = user.sessions.filter(pk=current_session_id).first() if current_session_id else None
    return tokens.issue_access(user, current)


def request_reset(email: str) -> None:
    """Always succeeds from the caller's view, so accounts cannot be enumerated."""
    with tenancy.auth_lookup_context():
        row = User.objects.filter(email=(email or "").strip().lower()).values("pk", "company_id", "status").first()
    if row is None or row["status"] != User.Status.ACTIVE:
        return
    with tenancy.context_for_company(row["company_id"]):
        user = User.objects.select_for_update(of=("self",)).select_related("company").get(pk=row["pk"])
        if user.company_id and not user.company.is_active:
            return
        token = _issue_reset_token(user, origin=PasswordResetToken.Origin.SELF, actor=None)
        record(actor=user, action="password.reset_requested", entity=user, new_value={"token_id": token.pk})


def _find_reset(raw: str) -> dict:
    with tenancy.auth_lookup_context():
        row = PasswordResetToken.objects.filter(token_hash=sha256_hex(raw or "")).values("pk", "company_id").first()
    if row is None:
        raise Gone(RESET_INVALID_MESSAGE, code="link_invalid")
    return row


def _check_reset(token: PasswordResetToken) -> None:
    if token.state != "valid":
        raise Gone(RESET_INVALID_MESSAGE, code=f"link_{token.state}")
    if not token.user.is_active or (token.user.company_id and not token.user.company.is_active):
        raise Gone(RESET_INVALID_MESSAGE, code="link_invalid")


def describe_reset(raw: str) -> dict:
    row = _find_reset(raw)
    with tenancy.context_for_company(row["company_id"]):
        token = PasswordResetToken.objects.select_related("user", "user__company").get(pk=row["pk"])
        _check_reset(token)
        return {"email": token.user.email, "expires_at": token.expires_at}


def reset(raw: str, new_password: str) -> None:
    row = _find_reset(raw)
    with tenancy.context_for_company(row["company_id"]):
        token = (
            PasswordResetToken.objects.select_for_update(of=("self",))
            .select_related("user", "user__company")
            .get(pk=row["pk"])
        )
        _check_reset(token)
        user = User.objects.select_for_update(of=("self",)).select_related("company").get(pk=token.user_id)
        _validate(new_password, user, "new_password")
        _set_password(user, new_password)
        token.used_at = timezone.now()
        token.save(update_fields=["used_at", "updated_at"])
        revoked = sessions.end_all_sessions(user, "password_reset")
        record(
            actor=user,
            action="password.reset_completed",
            entity=user,
            new_value={"origin": token.origin, "sessions_revoked": revoked},
        )
        emails.password_changed(user, "using a reset link")


# --- HR -------------------------------------------------------------------------
# Callers (accounts.services.employees) enforce policy and rank before calling these.


def hr_send_reset_link(actor: User, target: User) -> PasswordResetToken:
    if target.status != User.Status.ACTIVE:
        raise Conflict(
            "Only active accounts can be reset. Use the invite link for invited employees.", code="account_not_active"
        )
    token = _issue_reset_token(target, origin=PasswordResetToken.Origin.HR, actor=actor)
    revoked = sessions.end_all_sessions(target, "hr_password_reset")
    record(
        actor=actor,
        action="password.hr_reset_link_sent",
        entity=target,
        new_value={"token_id": token.pk, "sessions_revoked": revoked},
    )
    return token


def hr_set_temporary_password(actor: User, target: User, password: str) -> None:
    if target.status != User.Status.ACTIVE:
        raise Conflict("Only active accounts can be given a temporary password.", code="account_not_active")
    _validate(password, target)
    _set_password(target, password, must_change=True)
    revoked = sessions.end_all_sessions(target, "hr_temporary_password")
    record(
        actor=actor,
        action="password.hr_temporary_set",
        entity=target,
        new_value={"must_change_password": True, "sessions_revoked": revoked},
    )
    emails.temporary_password_set(target)
