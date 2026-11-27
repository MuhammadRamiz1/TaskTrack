"""Kanban board: per-card allowed moves."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.tasks.models import Status
from tests import factories as f

BOARD = "/api/v1/tasks/board/"
T = "/api/v1/tasks/"


def board(client, world):
    res = client.get(BOARD, {"project": str(world.project.pk)})
    assert res.status_code == 200, res.content
    return res.json()


def moves(client, world, task, *, hidden_ok=False) -> dict[str, str]:
    for column in board(client, world)["columns"]:
        for card in column["tasks"]:
            if card["id"] == str(task.pk):
                return {m["to_status"]: m["action"] for m in card["allowed_moves"]}
    assert hidden_ok, "task not on board"
    return {}


def to_progress(world, task):
    res = f.client_for(world.member).post(f"{T}{task.pk}/transition/", {"to_status": "IN_PROGRESS"}, format="json")
    assert res.status_code == 200, res.content


def submit(world, task):
    res = f.client_for(world.member).post(f"{T}{task.pk}/review/submit/", {"note": "done"}, format="json")
    assert res.status_code == 201, res.content


def test_backlog_card_offers_assign_to_manager_only(world):
    task = f.make_task(world.project, world.manager)
    assert moves(f.client_for(world.manager), world, task) == {"ASSIGNED": "assign", "CANCELLED": "transition"}
    assert moves(f.client_for(world.member), world, task, hidden_ok=True) == {}  # cannot see it


def test_assigned_card_for_member(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    assert moves(f.client_for(world.member), world, task) == {
        "IN_PROGRESS": "transition",
        "BLOCKED": "transition",
    }


def test_in_progress_card_submit_only_for_assignee(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    to_progress(world, task)
    assert moves(f.client_for(world.member), world, task)["IN_REVIEW"] == "submit"
    assert "IN_REVIEW" not in moves(f.client_for(world.lead), world, task, hidden_ok=True)


def test_submit_allowed_when_creator_is_fallback_reviewer(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    assert task.reviewer_id is None
    to_progress(world, task)
    assert moves(f.client_for(world.member), world, task)["IN_REVIEW"] == "submit"


def test_in_review_card_offers_decisions_to_reviewer(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    to_progress(world, task)
    submit(world, task)
    manager = f.client_for(world.manager)
    assert moves(manager, world, task) == {"COMPLETED": "approve", "IN_PROGRESS": "request_changes"}
    card = next(c for col in board(manager, world)["columns"] for c in col["tasks"] if c["id"] == str(task.pk))
    required = {m["to_status"]: m["requires_comment"] for m in card["allowed_moves"]}
    assert required["IN_PROGRESS"] is True
    assert moves(f.client_for(world.member), world, task) == {}


def test_self_review_blocks_approve_move(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    to_progress(world, task)
    submit(world, task)
    task.refresh_from_db()
    from apps.tasks.models import TaskAssignee

    TaskAssignee.objects.create(company_id=task.company_id, task=task, user=world.manager)
    result = moves(f.client_for(world.manager), world, task)
    assert "COMPLETED" not in result and "IN_PROGRESS" not in result


def test_completed_task_moves_by_role(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    to_progress(world, task)
    submit(world, task)
    f.client_for(world.manager).post(f"{T}{task.pk}/review/approve/", {}, format="json")
    task.refresh_from_db()
    assert task.status == Status.COMPLETED
    for user in (world.admin, world.manager):
        assert moves(f.client_for(user), world, task) == {"REOPENED": "transition"}
    manager = f.client_for(world.manager)
    card = next(c for col in board(manager, world)["columns"] for c in col["tasks"] if c["id"] == str(task.pk))
    assert card["allowed_moves"][0]["requires_comment"] is True
    assert moves(f.client_for(world.member), world, task) == {}


def _populate(world, n):
    """n backlog, n assigned, n in-progress and n in-review tasks."""
    member = f.client_for(world.member)
    for _ in range(n):
        f.make_task(world.project, world.manager)
        f.make_task(world.project, world.manager, assignees=[world.member])
        for review in (False, True):
            task = f.make_task(world.project, world.manager, assignees=[world.member])
            to_progress(world, task)
            if review:
                assert member.post(f"{T}{task.pk}/review/submit/", {}, format="json").status_code == 201


@pytest.mark.parametrize("who", ["admin", "manager", "lead", "member"])
def test_board_query_count_is_constant(world, who):
    client = f.client_for(getattr(world, who))

    def count():
        with CaptureQueriesContext(connection) as ctx:
            assert client.get(BOARD, {"project": str(world.project.pk)}).status_code == 200
        return len(ctx)

    _populate(world, 1)
    small = count()
    _populate(world, 4)
    assert count() == small


def _depend(world, task):
    from apps.tasks.models import TaskDependency

    blocker = f.make_task(world.project, world.manager)
    TaskDependency.objects.create(company_id=task.company_id, task=task, blocked_by=blocker)


def test_no_review_move_with_open_required_checklist_item(world):
    from apps.tasks.models import ChecklistItem, TaskChecklist

    task = f.make_task(world.project, world.manager, assignees=[world.member])
    to_progress(world, task)
    checklist = TaskChecklist.objects.create(company_id=task.company_id, task=task, title="DoD")
    item = ChecklistItem.objects.create(company_id=task.company_id, checklist=checklist, text="Tests", is_required=True)
    assert "IN_REVIEW" not in moves(f.client_for(world.member), world, task)
    item.is_done = True
    item.save()
    assert moves(f.client_for(world.member), world, task)["IN_REVIEW"] == "submit"


def test_optional_checklist_item_does_not_hide_review_move(world):
    from apps.tasks.models import ChecklistItem, TaskChecklist

    task = f.make_task(world.project, world.manager, assignees=[world.member])
    to_progress(world, task)
    checklist = TaskChecklist.objects.create(company_id=task.company_id, task=task, title="DoD")
    ChecklistItem.objects.create(company_id=task.company_id, checklist=checklist, text="Nice")
    assert moves(f.client_for(world.member), world, task)["IN_REVIEW"] == "submit"


def test_no_progress_move_with_open_blockers_when_enforced(world):
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    _depend(world, task)
    assert "IN_PROGRESS" not in moves(f.client_for(world.member), world, task)


def test_progress_move_offered_with_blockers_when_not_enforced(world, company_a):
    company_a.enforce_dependencies = False
    company_a.save()
    task = f.make_task(world.project, world.manager, assignees=[world.member])
    _depend(world, task)
    assert moves(f.client_for(world.member), world, task)["IN_PROGRESS"] == "transition"


def test_card_carries_checklist_comment_and_attachment_counts(world):
    from apps.tasks.models import ChecklistItem, TaskAttachment, TaskChecklist, TaskComment

    task = f.make_task(world.project, world.manager)
    cid = task.company_id
    checklist = TaskChecklist.objects.create(company_id=cid, task=task, title="Steps")
    for i, done in enumerate([True, True, False]):
        ChecklistItem.objects.create(company_id=cid, checklist=checklist, text=f"step {i}", is_done=done)
    TaskComment.objects.create(company_id=cid, task=task, author=world.manager, body="hi")
    TaskComment.objects.create(
        company_id=cid, task=task, author=world.manager, body="gone", deleted_at="2026-01-01T00:00Z"
    )
    for state in (TaskAttachment.State.ACTIVE, TaskAttachment.State.DELETED):
        TaskAttachment.objects.create(
            company_id=cid,
            task=task,
            storage_key="k",
            filename="a.txt",
            content_type="text/plain",
            size_bytes=1,
            sha256="0" * 64,
            status=state,
        )
    other = f.make_task(world.project, world.manager)

    cards = {c["id"]: c for col in board(f.client_for(world.manager), world)["columns"] for c in col["tasks"]}
    counts = lambda c: (c["checklist_done"], c["checklist_total"], c["comment_count"], c["attachment_count"])  # noqa: E731
    assert counts(cards[str(task.pk)]) == (2, 3, 1, 1)
    assert counts(cards[str(other.pk)]) == (0, 0, 0, 0)
