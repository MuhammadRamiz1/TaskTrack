import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import Role
from apps.accounts.permissions import Capability, Scope, has_capability, scope_for

User = get_user_model()
pytestmark = pytest.mark.django_db


def make(role, email=None):
    return User.objects.create_user(email or f"{role}@example.com", "pw12345!", first_name=role.title(), role=role)


def test_email_is_normalised_and_unique_case_insensitively():
    User.objects.create_user("Ali@Example.COM", "pw", first_name="Ali")
    assert User.objects.get().email == "ali@example.com"
    with pytest.raises(Exception):
        User.objects.create_user("ALI@example.com", "pw", first_name="Ali2")


def test_superuser_is_admin():
    user = User.objects.create_superuser("root@example.com", "pw", first_name="Root")
    assert user.role == Role.ADMIN and user.is_staff and user.is_superuser


def test_default_timezone_and_schedule():
    user = make(Role.MEMBER)
    assert user.timezone == "Asia/Karachi"
    assert user.working_days == [0, 1, 2, 3, 4]


def test_user_cannot_manage_self():
    from django.core.exceptions import ValidationError

    user = make(Role.MANAGER)
    user.manager = user
    with pytest.raises(ValidationError):
        user.full_clean(exclude=["password"])


def test_permission_matrix_scopes():
    admin, mgr, member, viewer = (make(r) for r in (Role.ADMIN, Role.MANAGER, Role.MEMBER, Role.VIEWER))
    assert scope_for(admin, Capability.MANAGE_USERS) is Scope.ALL
    assert not has_capability(mgr, Capability.MANAGE_USERS)
    assert scope_for(mgr, Capability.APPROVE_TIMESHEET) is Scope.TEAM
    assert not has_capability(member, Capability.APPROVE_TIMESHEET)
    assert scope_for(member, Capability.VIEW_TIME) is Scope.OWN
    assert scope_for(viewer, Capability.VIEW_TIME) is Scope.ALL
    assert not has_capability(viewer, Capability.CREATE_TASK)


def test_inactive_user_has_no_capabilities():
    admin = make(Role.ADMIN)
    admin.is_active = False
    assert not has_capability(admin, Capability.MANAGE_USERS)
