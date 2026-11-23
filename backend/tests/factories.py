"""Test data builders. Tests run in PLATFORM context (see conftest), so these may write
rows for any company; API requests then run in the context their token proves."""

import itertools

import factory
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import sessions
from apps.companies.models import Company, Plan
from apps.rbac.catalogue import RoleKey
from apps.rbac.models import Role, UserRole
from apps.rbac.services import provision_company_roles

PASSWORD = "Str0ng!Passw0rd#2026"
_seq = itertools.count(1)


class PlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Plan
        django_get_or_create = ("code",)

    code = "business"
    name = "Business"
    max_users = 100


class CompanyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Company
        skip_postgeneration_save = True

    name = factory.Sequence(lambda n: f"Company {n}")
    slug = factory.Sequence(lambda n: f"company-{n}")
    plan = factory.SubFactory(PlanFactory)

    @factory.post_generation
    def roles(obj, create, extracted, **kwargs):  # noqa: N805
        if create:
            from apps.tasks.workflow_defaults import seed_rules

            provision_company_roles(obj)
            seed_rules(obj.pk)


def role(company: Company, key: str) -> Role:
    return Role.objects.get(company=company, key=key)


def make_user(
    company: Company | None, *roles: str, status: str = User.Status.ACTIVE, password: str = PASSWORD, **fields
) -> User:
    n = next(_seq)
    fields.setdefault("email", f"user{n}@{(company.slug if company else 'platform')}.test")
    fields.setdefault("first_name", f"User{n}")
    fields.setdefault("last_name", "Test")
    if company is None:
        return User.objects.create_superuser(password=password, **fields)
    user = User.objects.create_user(
        company=company, status=status, password=password if status == "ACTIVE" else None, **fields
    )
    for key in roles or (RoleKey.TEAM_MEMBER,):
        UserRole.objects.create(company=company, user=user, role=role(company, key))
    return user


def client_for(user: User | None) -> APIClient:
    from tests.conftest import AuditCheckingClient

    client = AuditCheckingClient()
    if user is not None:
        issued = sessions.start_session(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.access}")
        client.session_obj = issued.session
        client.refresh_token = issued.refresh
    return client


def make_team(company: Company, name: str | None = None, members=(), lead: User | None = None):
    from apps.org.models import Team, TeamMember

    team = Team.objects.create(company=company, name=name or f"Team {next(_seq)}")
    for user in {*members, *([lead] if lead else [])}:
        TeamMember.objects.create(company=company, team=team, user=user)
    if lead:
        team.lead = lead
        team.save()
        UserRole.objects.get_or_create(company=company, user=lead, role=role(company, RoleKey.TEAM_LEAD), team=team)
    return team


def make_project(team, key: str | None = None, members=(), owner: User | None = None):
    from apps.org.models import Project, ProjectMember

    project = Project.objects.create(
        company_id=team.company_id,
        team=team,
        key=key or f"P{next(_seq)}",
        name=f"Project {key or ''}".strip(),
        owner=owner,
    )
    for user in {*members, *([owner] if owner else [])}:
        ProjectMember.objects.create(company_id=team.company_id, project=project, user=user)
    return project


def make_task(project, creator: User, assignees=(), **fields):
    """Create a task through the services, as ``creator`` (needs task.create)."""
    from apps.tasks.services.tasks import create_task

    data = {"project": project, "title": fields.pop("title", f"Task {next(_seq)}"), **fields}
    if assignees:
        data["assignee_ids"] = [u.pk for u in assignees]
    return create_task(actor=creator, data=data)
