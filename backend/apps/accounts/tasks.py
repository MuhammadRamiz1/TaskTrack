from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.common import tenancy


@shared_task(name="accounts.purge_expired_tokens")
def purge_expired_tokens() -> dict:
    """Delete invite/reset tokens and sessions that expired more than 30 days ago."""
    from .models import InviteToken, PasswordResetToken, UserSession

    cutoff = timezone.now() - timedelta(days=30)
    with tenancy.platform_context():
        stale = Q(expires_at__lt=cutoff)
        counts = {
            "invites": InviteToken.objects.filter(stale).delete()[0],
            "resets": PasswordResetToken.objects.filter(stale).delete()[0],
            "sessions": UserSession.objects.filter(stale | Q(revoked_at__lt=cutoff)).delete()[0],
        }
    return counts
