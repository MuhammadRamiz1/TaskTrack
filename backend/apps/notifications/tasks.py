from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.common.tasks import TenantTask, send_templated_email

ENTITY_PATHS = {"task": "/tasks/{id}", "timesheet": "/timesheets/{id}", "reportexport": "/reports"}


@shared_task(name="notifications.send_email", base=TenantTask, bind=True)
def send_notification_email(self, notification_id: str, *, company_id: str) -> bool:
    from .models import Notification

    n = Notification.objects.select_related("recipient").filter(pk=notification_id, emailed_at__isnull=True).first()
    if n is None or not n.recipient.is_active:
        return False
    path = ENTITY_PATHS.get(n.entity_type, "/notifications").format(id=n.entity_id)
    send_templated_email(  # run inline: we already are in the worker
        template="notification",
        to=n.recipient.email,
        context={
            "first_name": n.recipient.first_name,
            "title": n.title,
            "body": n.body,
            "link": f"{settings.WEB_ORIGIN}{path}",
        },
    )
    Notification.objects.filter(pk=n.pk).update(emailed_at=timezone.now())
    return True


@shared_task(name="notifications.purge_old")
def purge_old_notifications(days: int = 180) -> int:
    from apps.common import tenancy

    from .models import Notification

    with tenancy.platform_context():
        return Notification.objects.filter(created_at__lt=timezone.now() - timedelta(days=days)).delete()[0]
