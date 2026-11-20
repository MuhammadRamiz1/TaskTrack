import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import AuditLog, ImmutableError
from apps.audit.services import diff_instances, log_action

pytestmark = pytest.mark.django_db


def test_log_action_records_actor_and_target():
    user = get_user_model().objects.create_user("a@example.com", "pw", first_name="A")
    entry = log_action(user, AuditLog.Action.CREATE, user, changes={"role": {"old": None, "new": "member"}})
    assert entry.actor_email == "a@example.com"
    assert entry.object_id == str(user.pk)
    assert entry.content_type.model == "user"


def test_entries_are_immutable():
    entry = log_action(None, AuditLog.Action.OTHER, object_repr="system job")
    entry.object_repr = "tampered"
    with pytest.raises(ImmutableError):
        entry.save()
    with pytest.raises(ImmutableError):
        entry.delete()
    with pytest.raises(ImmutableError):
        AuditLog.objects.all().delete()
    with pytest.raises(ImmutableError):
        AuditLog.objects.all().update(object_repr="x")


def test_diff_instances_reports_changed_fields_only():
    User = get_user_model()
    old = User(email="a@example.com", first_name="A", role="member")
    new = User(id=old.id, email="a@example.com", first_name="A", role="manager")
    diff = diff_instances(old, new, fields=["email", "role"])
    assert diff == {"role": {"old": "member", "new": "manager"}}
