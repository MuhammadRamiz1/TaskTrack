"""Invite links: 256-bit random, SHA-256 stored, single use, expiring, revocable, resendable."""

from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.services import record
from apps.common import tenancy
from apps.common.exceptions import Conflict, Forbidden, Gone, InvalidInput
from apps.common.security import new_url_token, sha256_hex

from .. import emails
from ..models import InviteToken, User
from . import sessions

LINK_INVALID_MESSAGE = "This link is no longer valid. Ask HR for a new link."


def _open_invites(user: User):
    return InviteToken.objects.filter(user=user, used_at__isnull=True, revoked_at__isnull=True)


def issue(*, actor: User | None, user: User) -> InviteToken:
    """Create (or re-send) the invite for an INVITED user. Older open links are revoked."""
    if user.status != User.Status.INVITED:
        raise Conflict("This account is already active or deactivated.", code="invite_not_applicable")
    company = user.company
    if not company.is_active:
        raise Forbidden("The company account is suspended.", code="company_suspended")
    now = timezone.now()
    previous = list(_open_invites(user).select_for_update())
    send_count = 1 + max((p.send_count for p in previous), default=0)
    _open_invites(user).update(revoked_at=now)

    raw = new_url_token()
    invite = InviteToken.objects.create(
        company_id=user.company_id,
        user=user,
        token_hash=sha256_hex(raw),
        expires_at=now + timedelta(hours=company.invite_expiry_hours),
        created_by=actor,
        send_count=send_count,
    )
    record(
        actor=actor,
        action="invite.resent" if previous else "invite.created",
        entity=user,
        company_id=user.company_id,
        new_value={"invite_id": invite.pk, "expires_at": invite.expires_at},
    )
    emails.invite(user, raw, invite.expires_at, actor.full_name if actor else "TaskTrack")
    return invite


def revoke(*, actor: User, user: User) -> int:
    count = _open_invites(user).update(revoked_at=timezone.now())
    if count == 0:
        raise Conflict("There is no open invite link for this employee.", code="no_open_invite")
    record(actor=actor, action="invite.revoked", entity=user, new_value={"revoked": count})
    return count


def status_of(user: User) -> dict:
    latest = InviteToken.objects.filter(user=user).order_by("-created_at").first()
    if latest is None:
        return {"state": "none", "expires_at": None, "send_count": 0, "last_sent_at": None}
    state = "pending" if latest.state == "valid" else latest.state
    return {
        "state": state,
        "expires_at": latest.expires_at,
        "send_count": latest.send_count,
        "last_sent_at": latest.created_at,
    }


def _find(raw: str) -> dict:
    with tenancy.auth_lookup_context():
        row = InviteToken.objects.filter(token_hash=sha256_hex(raw or "")).values("pk", "company_id").first()
    if row is None:
        raise Gone(LINK_INVALID_MESSAGE, code="link_invalid")
    return row


def _raise_if_unusable(invite: InviteToken) -> None:
    state = invite.state
    if state != "valid" or invite.user.status != User.Status.INVITED:
        raise Gone(LINK_INVALID_MESSAGE, code="link_used" if state == "valid" else f"link_{state}")
    if not invite.company.is_active:
        raise Forbidden("The company account is suspended.", code="company_suspended")


def describe(raw: str) -> dict:
    row = _find(raw)
    with tenancy.tenant_context(row["company_id"]):
        invite = InviteToken.objects.select_related("user", "company").get(pk=row["pk"])
        _raise_if_unusable(invite)
        return {
            "email": invite.user.email,
            "first_name": invite.user.first_name,
            "company_name": invite.company.name,
            "expires_at": invite.expires_at,
        }


def accept(raw: str, password: str) -> tuple[User, sessions.IssuedTokens]:
    row = _find(raw)
    with tenancy.tenant_context(row["company_id"]):
        invite = InviteToken.objects.select_for_update(of=("self",)).select_related("user", "company").get(pk=row["pk"])
        _raise_if_unusable(invite)
        user = User.objects.select_for_update(of=("self",)).select_related("company").get(pk=invite.user_id)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise InvalidInput(details={"password": exc.messages}) from exc

        now = timezone.now()
        user.set_password(password)
        user.status = User.Status.ACTIVE
        user.activated_at = now
        user.password_changed_at = now
        user.must_change_password = False
        user.save()
        invite.used_at = now
        invite.save(update_fields=["used_at", "updated_at"])
        _open_invites(user).update(revoked_at=now)
        record(actor=user, action="invite.accepted", entity=user, new_value={"invite_id": invite.pk})
        issued = sessions.start_session(user)
        record(
            actor=user, action="auth.login", entity=user, new_value={"session_id": issued.session.pk, "via": "invite"}
        )
        return user, issued
