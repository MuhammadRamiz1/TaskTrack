"""Task review workflow (separate from timesheet approval)."""

import pytest

from apps.audit.models import AuditLog
from apps.notifications.models import Notification
from apps.reviews.models import TaskReview
from apps.tasks.models import Status
from tests import factories as f

T = "/api/v1/tasks/"


@pytest.fixture
def task(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member], title="Checkout flow")
    f.client_for(world.member).post(f"{T}{task.pk}/transition/", {"to_status": "IN_PROGRESS"}, format="json")
    return task


def submit(client, task, note=""):
    return client.post(f"{T}{task.pk}/review/submit/", {"note": note}, format="json")


def test_full_cycle_with_rounds_and_history(world, task):
    member, manager = f.client_for(world.member), f.client_for(world.manager)

    first = submit(member, task, "Ready")
    assert first.status_code == 201 and first.json()["round"] == 1
    assert first.json()["reviewer"]["id"] == str(world.manager.pk)  # default reviewer: creator
    task.refresh_from_db()
    assert task.status == Status.IN_REVIEW
    assert Notification.objects.filter(recipient=world.manager, event_type="review.requested").exists()

    frozen = manager.patch(f"{T}{task.pk}/", {"title": "x", "version": task.version}, format="json")
    assert frozen.status_code == 409 and frozen.json()["error"]["code"] == "task_in_review"
    assert member.post(f"{T}{task.pk}/comments/", {"body": "fyi"}, format="json").status_code == 201

    no_comment = manager.post(f"{T}{task.pk}/review/request-changes/", {}, format="json")
    assert no_comment.status_code == 400 and no_comment.json()["error"]["code"] == "comment_required"
    changes = manager.post(f"{T}{task.pk}/review/request-changes/", {"comment": "Add input validation"}, format="json")
    assert changes.json()["decision"] == "CHANGES_REQUESTED"
    task.refresh_from_db()
    assert task.status == Status.IN_PROGRESS
    assert Notification.objects.filter(recipient=world.member, event_type="review.changes_requested").exists()

    assert submit(member, task, "Validation added").json()["round"] == 2
    approved = manager.post(f"{T}{task.pk}/review/approve/", {"comment": "Great work"}, format="json")
    assert approved.json()["decision"] == "APPROVED"
    task.refresh_from_db()
    assert task.status == Status.COMPLETED and task.locked_at is not None

    history = member.get(f"{T}{task.pk}/reviews/").json()
    assert [(h["round"], h["decision"]) for h in history] == [(1, "CHANGES_REQUESTED"), (2, "APPROVED")]
    assert history[0]["comment"] == "Add input validation"
    actions = set(AuditLog.objects.filter(entity_type="taskreview").values_list("action", flat=True))
    assert actions == {"review.submitted", "review.changes_requested", "review.approved"}


def test_approved_task_is_read_only_until_reopened(world, task):
    member, manager = f.client_for(world.member), f.client_for(world.manager)
    submit(member, task)
    manager.post(f"{T}{task.pk}/review/approve/", {}, format="json")
    for call in (
        lambda: member.post(f"{T}{task.pk}/comments/", {"body": "late"}, format="json"),
        lambda: manager.post(f"{T}{task.pk}/checklists/", {"title": "x"}, format="json"),
        lambda: member.post(f"{T}{task.pk}/transition/", {"to_status": "IN_PROGRESS"}, format="json"),
    ):
        assert call().status_code == 409
    manager.post(f"{T}{task.pk}/reopen/", {"comment": "Bug in production"}, format="json")
    member.post(f"{T}{task.pk}/transition/", {"to_status": "IN_PROGRESS"}, format="json")
    assert submit(member, task).json()["round"] == 2  # history is kept, the next round opens


def test_required_checklist_blocks_submission(world, task):
    manager, member = f.client_for(world.manager), f.client_for(world.member)
    checklist = manager.post(f"{T}{task.pk}/checklists/", {"title": "DoD"}, format="json").json()
    item = manager.post(
        f"{T}{task.pk}/checklists/{checklist['id']}/items/", {"text": "Tests", "is_required": True}, format="json"
    ).json()
    manager.post(f"{T}{task.pk}/checklists/{checklist['id']}/items/", {"text": "Nice to have"}, format="json")
    blocked = submit(member, task)
    assert blocked.status_code == 400 and blocked.json()["error"]["code"] == "checklist_incomplete"
    assert blocked.json()["error"]["details"]["open_required_items"] == 1
    member.patch(f"{T}{task.pk}/checklist-items/{item['id']}/", {"is_done": True}, format="json")
    assert submit(member, task).status_code == 201


def test_only_assignee_submits_and_only_in_progress(world, task):
    assert submit(f.client_for(world.manager), task).status_code == 403  # not an assignee
    backlog = f.make_task(world.project, world.manager, assignees=[world.member])
    assert submit(f.client_for(world.member), backlog).status_code == 409  # still ASSIGNED
    member = f.client_for(world.member)
    submit(member, task)
    assert submit(member, task).status_code == 409


def test_only_the_reviewer_decides(world, task, company_a):
    submit(f.client_for(world.member), task)
    other_manager = f.make_user(company_a, "MANAGER")
    f.make_project(world.team, key="WEB2", owner=other_manager)
    world.project.memberships.create(company=company_a, user=other_manager)
    response = f.client_for(other_manager).post(f"{T}{task.pk}/review/approve/", {}, format="json")
    assert response.status_code == 403 and response.json()["error"]["code"] == "not_reviewer"
    assert f.client_for(world.member).post(f"{T}{task.pk}/review/approve/", {}, format="json").status_code == 403
    assert f.client_for(world.admin).post(f"{T}{task.pk}/review/approve/", {}, format="json").status_code == 200


def test_explicit_reviewer_and_self_review_block(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member, world.manager], reviewer=world.manager)
    member = f.client_for(world.member)
    member.post(f"{T}{task.pk}/transition/", {"to_status": "IN_PROGRESS"}, format="json")
    submit(member, task)
    blocked = f.client_for(world.manager).post(f"{T}{task.pk}/review/approve/", {}, format="json")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "self_review"


def test_team_lead_reviews_only_when_granted(world, task):
    from apps.rbac.models import Permission, RolePermission

    task.reviewer = world.lead
    task.save(update_fields=["reviewer"])
    submit(f.client_for(world.member), task)
    lead = f.client_for(world.lead)
    assert lead.post(f"{T}{task.pk}/review/approve/", {}, format="json").status_code == 403
    RolePermission.objects.create(
        role=f.role(world.team.company, "TEAM_LEAD"),
        permission=Permission.objects.get(code="review.decide"),
        scope="TEAM",
    )
    assert lead.post(f"{T}{task.pk}/review/approve/", {}, format="json").status_code == 200


def test_review_queue(world, task):
    submit(f.client_for(world.member), task)
    queue = f.client_for(world.manager).get("/api/v1/reviews/queue/").json()["results"]
    assert [q["task"]["id"] for q in queue] == [str(task.pk)]
    assert f.client_for(world.member).get("/api/v1/reviews/queue/").status_code == 403


def test_one_pending_review_enforced_by_database(world, task):
    from django.db import IntegrityError, transaction

    submit(f.client_for(world.member), task)
    with pytest.raises(IntegrityError), transaction.atomic():
        TaskReview.objects.create(
            company=task.company, task=task, round=99, submitted_by=world.member, reviewer=world.manager
        )
