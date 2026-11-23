"""Cross-tenant matrix generated from the URL resolver.

For every tenant endpoint with an object id in its path, a COMPANY_ADMIN of company A
(who holds every company permission) calls every method with company B's ids. Each call
must return 404 and leave company B untouched. A meta check fails when a new path
parameter appears that this matrix does not know how to fill, so new endpoints cannot
skip the check.
"""

import re

import pytest
from django.urls import get_resolver

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.common.views import PlatformAPIView, PublicAPIView
from apps.rbac.models import UserRole
from apps.tasks.models import Task
from tests import factories as f

PARAM = re.compile(r"<(?:\w+:)?(\w+)>")
STRING_TOKEN_PARAMS = {"token"}  # bearer secrets, not tenant ids


def _routes():
    out = []

    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns, prefix + str(p.pattern))
                continue
            view = getattr(p.callback, "view_class", None)
            route = prefix + str(p.pattern)
            if view is None or not route.startswith("api/v1/") or issubclass(view, (PublicAPIView,)):
                continue
            out.append((route, view, p.name))

    walk(get_resolver().url_patterns)
    return out


ROUTES = _routes()
TENANT_ROUTES_WITH_IDS = [
    (route, view, name) for route, view, name in ROUTES if PARAM.search(route) and not issubclass(view, PlatformAPIView)
]
PLATFORM_ROUTES = [(route, view, name) for route, view, name in ROUTES if issubclass(view, PlatformAPIView)]


@pytest.fixture
def world(company_a, company_b):
    attacker = f.make_user(company_a, "COMPANY_ADMIN", email="attacker@acme.test")
    victim = f.make_user(company_b, "TEAM_MEMBER", email="victim@globex.test")
    victim_session = f.client_for(victim).session_obj
    entry = record(actor=victim, action="test.seed", entity=victim)
    world_b = _company_b_objects(company_b, victim)
    ids = {
        **world_b,
        "user_id": victim.pk,
        "user_role_id": UserRole.objects.get(user=victim).pk,
        "role_id": f.role(company_b, "TEAM_LEAD").pk,
        "session_id": victim_session.pk,
        "entry_id": entry.pk,
    }
    return attacker, victim, ids


def _company_b_objects(company_b, victim) -> dict:
    """One of every tenant object in company B, keyed by URL parameter name."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.org.models import Holiday, LeaveDay
    from apps.tasks.models import StatusTransitionRule
    from apps.tasks.services import attachments, details

    manager = f.make_user(company_b, "COMPANY_ADMIN", email="boss@globex.test")
    team = f.make_team(company_b, "Globex Team", members=[victim, manager])
    project = f.make_project(team, key="GLX", members=[victim, manager], owner=manager)
    task = f.make_task(project, manager, assignees=[victim], title="Secret plan")
    other = f.make_task(project, manager, title="Other")
    checklist = details.add_checklist(actor=manager, task_id=task.pk, title="Steps")
    item = details.add_item(actor=manager, checklist=checklist, text="Step 1")
    dependency = details.add_dependency(actor=manager, task_id=task.pk, blocked_by_id=other.pk)
    comment = details.add_comment(actor=manager, task_id=task.pk, body="confidential")
    attachment = attachments.upload(
        actor=manager, task_id=task.pk, uploaded_file=SimpleUploadedFile("plan.txt", b"top secret", "text/plain")
    )
    from datetime import timedelta

    from django.utils import timezone

    from apps.timetracking.services import create_manual

    began = timezone.now() - timedelta(hours=2)
    entry = create_manual(actor=victim, task_id=task.pk, started_at=began, ended_at=began + timedelta(minutes=30))
    from datetime import time

    from apps.notifications.models import Notification
    from apps.reports.models import ReportExport, ScheduledReport

    export = ReportExport.objects.create(
        company=company_b,
        requested_by=manager,
        report_type="time",
        format="csv",
        filters={"date_from": "2026-01-01", "date_to": "2026-01-31"},
    )
    schedule = ScheduledReport.objects.create(
        company=company_b,
        owner=manager,
        name="B weekly",
        report_type="time",
        frequency="WEEKLY",
        send_at=time(8, 0),
        next_run_at=timezone.now(),
    )
    return {
        "notification_id": Notification.objects.filter(recipient=victim).first().pk,
        "export_id": export.pk,
        "schedule_id": schedule.pk,
        "entry_id": entry.pk,
        "timesheet_id": entry.timesheet_id,
        "team_id": team.pk,
        "project_id": project.pk,
        "task_id": task.pk,
        "key": f"GLX-{task.number}",
        "checklist_id": checklist.pk,
        "item_id": item.pk,
        "dependency_id": dependency.pk,
        "comment_id": comment.pk,
        "attachment_id": attachment.pk,
        "holiday_id": Holiday.objects.create(company=company_b, date="2026-12-25", name="Xmas").pk,
        "leave_id": LeaveDay.objects.create(company=company_b, user=victim, date="2026-12-24").pk,
        "rule_id": StatusTransitionRule.objects.filter(company=company_b).first().pk,
    }


def _fill(route, ids):
    return "/" + PARAM.sub(lambda m: str(ids[m.group(1)]), route)


def test_matrix_knows_every_path_parameter(world):
    _, _, ids = world
    unknown = {p for route, *_ in TENANT_ROUTES_WITH_IDS for p in PARAM.findall(route)} - set(ids)
    assert not unknown - STRING_TOKEN_PARAMS, f"Add ids for new path parameters: {unknown}"
    assert len(TENANT_ROUTES_WITH_IDS) >= 10


@pytest.mark.parametrize(("route", "view", "name"), TENANT_ROUTES_WITH_IDS, ids=[r[2] for r in TENANT_ROUTES_WITH_IDS])
def test_company_a_cannot_touch_company_b(world, company_b, route, view, name):
    attacker, victim, ids = world
    client = f.client_for(attacker)
    url = _fill(route, ids)
    audit_before = AuditLog.objects.filter(company_id=company_b.pk).count()
    snapshot_before = User.objects.filter(pk=victim.pk).values().get()
    task_before = Task.with_deleted.filter(pk=ids["task_id"]).values().get()
    payload = {
        "reason": "x",
        "role_id": str(ids["role_id"]),
        "password": "Temp-Passw0rd-2026!",
        "first_name": "pwned",
        "title": "pwned",
        "version": 1,
        "to_status": "CANCELLED",
        "comment": "x",
        "body": "x",
        "user_ids": [str(ids["user_id"])],
        "text": "x",
        "is_done": True,
        "blocked_by_id": str(ids["task_id"]),
        "team_ids": [],
        "from_user_id": str(ids["user_id"]),
        "to_user_id": str(ids["user_id"]),
    }
    for method in ("get", "post", "put", "patch", "delete"):
        if not hasattr(view, method):
            continue
        response = getattr(client, method)(url, payload, format="json")
        assert response.status_code == 404, f"{method.upper()} {url} -> {response.status_code} {response.content!r}"
    assert AuditLog.objects.filter(company_id=company_b.pk).count() == audit_before
    assert User.objects.filter(pk=victim.pk).values().get() == snapshot_before
    assert Task.with_deleted.filter(pk=ids["task_id"]).values().get() == task_before
    assert UserRole.objects.filter(user=victim).count() == 1


def test_lists_never_include_other_tenant(world, company_b):
    attacker, victim, _ = world
    client = f.client_for(attacker)
    employees = client.get("/api/v1/hr/employees/?page_size=100").json()["results"]
    assert victim.email not in {e["email"] for e in employees}
    assert client.get(f"/api/v1/hr/employees/?search={victim.email}").json()["count"] == 0
    audit = client.get("/api/v1/audit/?page_size=100").json()["results"]
    assert all(e["company_id"] != str(company_b.pk) for e in audit)
    roles = client.get("/api/v1/company/roles/").json()
    assert all(r["id"] != str(f.role(company_b, "TEAM_LEAD").pk) for r in roles)
    assert client.get("/api/v1/company/settings/").json()["id"] != str(company_b.pk)


@pytest.mark.parametrize(("route", "view", "name"), PLATFORM_ROUTES, ids=[r[2] for r in PLATFORM_ROUTES])
def test_company_users_get_403_on_platform_routes(world, route, view, name, company_b):
    attacker, _, _ = world
    client = f.client_for(attacker)
    url = "/" + PARAM.sub(lambda m: str(company_b.pk), route)
    for method in ("get", "post", "put", "patch", "delete"):
        if hasattr(view, method):
            assert getattr(client, method)(url, {}, format="json").status_code == 403


def test_token_from_one_company_cannot_be_replayed_against_another(world, company_b):
    """A token's company claim is checked against the user row under RLS."""
    from rest_framework_simplejwt.tokens import AccessToken

    attacker, victim, _ = world
    client = f.client_for(attacker)
    raw = client._credentials["HTTP_AUTHORIZATION"].split()[1]
    forged = AccessToken(raw)
    forged["cid"] = str(company_b.pk)  # re-signed with the server key would still not match the user
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {forged}")
    assert client.get("/api/v1/auth/me/").status_code == 401
