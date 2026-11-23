"""Account emails. Always enqueued with transaction.on_commit so nothing is sent for a
rolled-back change. Raw tokens travel only inside the email link."""

from django.conf import settings
from django.db import transaction

from apps.common.tasks import send_templated_email


def _send(template: str, user, **context) -> None:
    payload = {
        "template": template,
        "to": user.email,
        "context": {
            "first_name": user.first_name,
            "company_name": user.company.name if user.company_id else "TaskTrack",
            **context,
        },
    }
    transaction.on_commit(lambda: send_templated_email.delay(**payload))


def invite(user, raw_token: str, expires_at, invited_by_name: str) -> None:
    _send(
        "invite",
        user,
        link=f"{settings.WEB_ORIGIN}/accept-invite/{raw_token}",
        expires_at=expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        invited_by=invited_by_name,
    )


def password_reset(user, raw_token: str, expires_at, by_hr: bool) -> None:
    _send(
        "password_reset",
        user,
        link=f"{settings.WEB_ORIGIN}/reset-password/{raw_token}",
        expires_at=expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        by_hr=by_hr,
    )


def password_changed(user, how: str) -> None:
    _send("password_changed", user, how=how)


def temporary_password_set(user) -> None:
    _send("temporary_password", user, login_link=f"{settings.WEB_ORIGIN}/login")


def account_locked(user, minutes: int) -> None:
    _send("account_locked", user, minutes=minutes, reset_link=f"{settings.WEB_ORIGIN}/forgot-password")


def account_deactivated(user) -> None:
    _send("account_deactivated", user)
