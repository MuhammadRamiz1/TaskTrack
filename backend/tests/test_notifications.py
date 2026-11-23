from apps.notifications.models import Notification, NotificationPreference
from tests import factories as f

N = "/api/v1/notifications/"


def assign(world, user):
    return f.make_task(world.project, world.manager, assignees=[user], title="Notify me")


def test_inbox_unread_count_and_read(world):
    assign(world, world.member)
    client = f.client_for(world.member)
    items = client.get(N).json()["results"]
    assert len(items) == 1 and items[0]["event_type"] == "task.assigned" and items[0]["is_read"] is False
    assert client.get(f"{N}unread-count/").json() == {"unread": 1}
    read = client.post(f"{N}{items[0]['id']}/read/")
    assert read.json()["is_read"] is True
    assert client.get(f"{N}?unread=true").json()["results"] == []
    assign(world, world.member)
    assert client.post(f"{N}read-all/").json() == {"count": 1}


def test_cannot_read_someone_elses_notification(world):
    assign(world, world.member)
    other = Notification.objects.get(recipient=world.member)
    assert f.client_for(world.member2).post(f"{N}{other.pk}/read/").status_code == 404


def test_preferences_control_delivery(world, mailbox):
    client = f.client_for(world.member)
    prefs = client.get(f"{N}preferences/").json()
    assigned = next(p for p in prefs if p["event_type"] == "task.assigned")
    assert assigned == {
        "event_type": "task.assigned",
        "label": "A task is assigned to me",
        "in_app": True,
        "email": True,
    }
    with mailbox():
        assign(world, world.member)
    assert mailbox.outbox[-1].to == [world.member.email] and "WEB-" in mailbox.outbox[-1].subject
    assert Notification.objects.filter(recipient=world.member).first().emailed_at is not None

    updated = client.put(
        f"{N}preferences/",
        {"preferences": [{"event_type": "task.assigned", "in_app": False, "email": False}]},
        format="json",
    )
    assert updated.status_code == 200
    sent_before = len(mailbox.outbox)
    with mailbox():
        assign(world, world.member)
    assert len(mailbox.outbox) == sent_before
    assert Notification.objects.filter(recipient=world.member).count() == 1

    client.put(
        f"{N}preferences/",
        {"preferences": [{"event_type": "task.assigned", "in_app": False, "email": True}]},
        format="json",
    )
    with mailbox():
        assign(world, world.member)
    assert len(mailbox.outbox) == sent_before + 1
    assert client.get(f"{N}unread-count/").json()["unread"] == 1  # email-only rows stay out of the inbox
    assert NotificationPreference.objects.filter(user=world.member).count() == 1


def test_unknown_event_rejected(world):
    response = f.client_for(world.member).put(
        f"{N}preferences/", {"preferences": [{"event_type": "nope", "in_app": True, "email": True}]}, format="json"
    )
    assert response.status_code == 400


def test_actor_is_not_notified_about_own_action(world):
    f.make_task(world.project, world.manager, assignees=[world.manager])
    assert not Notification.objects.filter(recipient=world.manager, event_type="task.assigned").exists()
