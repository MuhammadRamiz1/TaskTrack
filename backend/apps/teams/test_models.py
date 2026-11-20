import datetime

import pytest
from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model

from apps.organizations.models import Organization
from apps.projects.models import Project
from apps.teams.models import Team, TeamMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return Organization.objects.create(name="MobiTising", slug="mobitising")


def test_organization_defaults(org):
    assert org.default_timezone == "Asia/Karachi"
    assert org.currency == "PKR"
    assert org.require_manual_entry_approval is True
    assert org.idle_detection_enabled is False


def test_user_joins_team_once(org):
    user = get_user_model().objects.create_user("m@example.com", "pw", first_name="M")
    team = Team.objects.create(organization=org, name="Content", manager=user)
    TeamMembership.objects.create(team=team, user=user)
    with pytest.raises(IntegrityError), transaction.atomic():
        TeamMembership.objects.create(team=team, user=user)
    assert list(team.members.all()) == [user]


def test_project_code_uppercased_and_unique_per_org(org):
    Project.objects.create(organization=org, name="Website", code="web")
    assert Project.objects.get().code == "WEB"
    with pytest.raises(IntegrityError), transaction.atomic():
        Project.objects.create(organization=org, name="Other", code="Web")


def test_project_end_date_cannot_precede_start(org):
    with pytest.raises(IntegrityError), transaction.atomic():
        Project.objects.create(
            organization=org,
            name="Bad",
            code="BAD",
            start_date=datetime.date(2026, 12, 1),
            end_date=datetime.date(2026, 11, 1),
        )
