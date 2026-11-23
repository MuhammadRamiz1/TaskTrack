"""A realistic company for task tests: one team with a lead, a manager who owns a
project, two members, and an outsider in another team."""

from dataclasses import dataclass

import pytest

from apps.accounts.models import User
from apps.org.models import Project, Team
from tests import factories as f


@dataclass
class World:
    admin: User
    hr: User
    manager: User
    lead: User
    member: User
    member2: User
    outsider: User
    team: Team
    other_team: Team
    project: Project
    other_project: Project


@pytest.fixture
def world(company_a) -> World:
    admin = f.make_user(company_a, "COMPANY_ADMIN", first_name="Ada")
    hr = f.make_user(company_a, "HR", first_name="Hana")
    manager = f.make_user(company_a, "MANAGER", first_name="Max")
    lead = f.make_user(company_a, "TEAM_MEMBER", first_name="Lea")
    member = f.make_user(company_a, "TEAM_MEMBER", first_name="Mo")
    member2 = f.make_user(company_a, "TEAM_MEMBER", first_name="Mia")
    outsider = f.make_user(company_a, "TEAM_MEMBER", first_name="Otto")
    team = f.make_team(company_a, "Web", members=[manager, member, member2], lead=lead)
    other_team = f.make_team(company_a, "Ops", members=[outsider])
    project = f.make_project(team, key="WEB", members=[member], owner=manager)
    other_project = f.make_project(other_team, key="OPS", members=[outsider], owner=admin)
    return World(admin, hr, manager, lead, member, member2, outsider, team, other_team, project, other_project)
