"""Create notifications from domain events, honouring each user's preferences."""

from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.common.exceptions import InvalidInput, NotFound

from . import events
from .models import Notification, NotificationPreference


def _preferences(user_ids: set, event_type: str) -> dict:
    rows = NotificationPreference.objects.filter(user_id__in=user_ids, event_type=event_type)
    return {r.user_id: (r.in_app, r.email) for r in rows}


def notify(*, recipients: Iterable, actor, event_type: str, title: str, body: str = "", entity=None) -> int:
    """One notification per distinct active recipient, never to the actor themselves.
    Email is sent after the transaction commits, from the Celery worker."""
    users, seen = [], set()
    for user in recipients:
        if user is None or user.pk in seen or (actor is not None and user.pk == actor.pk) or not user.is_active:
            continue
        seen.add(user.pk)
        users.append(user)
    if not users:
        return 0
    prefs = _preferences(seen, event_type)
    default = events.defaults(event_type)
    rows, to_email = [], []
    for user in users:
        in_app, email = prefs.get(user.pk, default)
        if not (in_app or email):
            continue
        n = Notification(
            company_id=user.company_id,
            recipient=user,
            actor=actor,
            event_type=event_type,
            title=title[:200],
            body=body,
            entity_type=entity._meta.model_name if entity is not None else "",
            entity_id=entity.pk if entity is not None else None,
            show_in_app=in_app,
        )
        rows.append(n)
        if email:
            to_email.append(n)
    Notification.objects.bulk_create(rows)
    if to_email:
        from .tasks import send_notification_email

        jobs = [(n.pk, n.company_id) for n in to_email]
        transaction.on_commit(lambda: [send_notification_email.delay(str(pk), company_id=str(cid)) for pk, cid in jobs])
    return len(rows)


def inbox(user):
    return Notification.objects.filter(recipient=user, show_in_app=True)


def mark_read(*, actor, notification_id) -> Notification:
    n = inbox(actor).filter(pk=notification_id).first()
    if n is None:
        raise NotFound()
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at", "updated_at"])
        record(actor=actor, action="notification.read", entity=n)
    return n


def mark_all_read(*, actor) -> int:
    count = inbox(actor).filter(read_at__isnull=True).update(read_at=timezone.now())
    record(actor=actor, action="notification.read_all", entity=actor, new_value={"count": count})
    return count


def preferences_for(user) -> list[dict]:
    stored = {p.event_type: p for p in NotificationPreference.objects.filter(user=user)}
    result = []
    for event_type, meta in events.EVENTS.items():
        pref = stored.get(event_type)
        result.append(
            {
                "event_type": event_type,
                "label": meta["label"],
                "in_app": pref.in_app if pref else meta["in_app"],
                "email": pref.email if pref else meta["email"],
            }
        )
    return result


def set_preferences(*, actor, items: list[dict]) -> list[dict]:
    unknown = {i["event_type"] for i in items} - set(events.EVENTS)
    if unknown:
        raise InvalidInput(details={"preferences": [f"Unknown events: {', '.join(sorted(unknown))}."]})
    before = {p["event_type"]: (p["in_app"], p["email"]) for p in preferences_for(actor)}
    for item in items:
        NotificationPreference.objects.update_or_create(
            user=actor,
            event_type=item["event_type"],
            defaults={"company_id": actor.company_id, "in_app": item["in_app"], "email": item["email"]},
        )
    after = preferences_for(actor)
    changed = {
        p["event_type"]: [p["in_app"], p["email"]]
        for p in after
        if before[p["event_type"]] != (p["in_app"], p["email"])
    }
    if changed:
        record(actor=actor, action="notification.preferences_updated", entity=actor, new_value=changed)
    return after
