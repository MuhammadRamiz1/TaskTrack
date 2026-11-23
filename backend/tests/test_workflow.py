"""State machine: every default rule, role checks, comment rules, dependencies, locking."""

import pytest

from apps.audit.models import AuditLog
from apps.tasks.models import Status, StatusTransitionRule, Task, TaskActivity, TaskAssignee
from apps.tasks.workflow import DirectStatusWrite, transition_task
from apps.tasks.workflow_defaults import DEFAULT_RULES
from tests import factories as f


def move(client, task, to, comment="", version=None):
    body = {"to_status": to, "comment": comment}
    if version is not None:
        body["version"] = version
    return client.post(f"/api/v1/tasks/{task.pk}/transition/", body, format="json")


@pytest.fixture
def task(world):
    return f.make_task(world.project, world.manager, assignees=[world.member], title="Build login page")


def test_defaults_seeded_per_company(company_a, company_b):
    for company in (company_a, company_b):
        assert StatusTransitionRule.objects.filter(company=company).count() == len(DEFAULT_RULES)


def test_assignment_moves_backlog_to_assigned(world):
    task = f.make_task(world.project, world.manager)
    assert task.status == Status.BACKLOG
    f.client_for(world.manager).post(
        f"/api/v1/tasks/{task.pk}/assignees/", {"user_ids": [str(world.member.pk)]}, format="json"
    )
    task.refresh_from_db()
    assert task.status == Status.ASSIGNED
    assert TaskAssignee.objects.get(task=task).task_status == Status.ASSIGNED


def test_member_happy_path_and_blocked(world, task):
    member = f.client_for(world.member)
    started = move(member, task, "IN_PROGRESS")
    assert started.status_code == 200 and started.json()["status"] == "IN_PROGRESS"
    no_reason = move(member, task, "BLOCKED")
    assert no_reason.status_code == 400 and no_reason.json()["error"]["code"] == "comment_required"
    blocked = move(member, task, "BLOCKED", "Waiting for the API keys")
    assert blocked.json()["blocked_reason"] == "Waiting for the API keys"
    assert move(member, task, "IN_PROGRESS").status_code == 403  # only leads/managers unblock
    unblocked = move(f.client_for(world.lead), task, "IN_PROGRESS")
    assert unblocked.status_code == 200 and unblocked.json()["blocked_reason"] == ""
    # BACKLOG->ASSIGNED on creation, then the three manual changes above.
    assert TaskActivity.objects.filter(task=task, verb="status_changed").count() == 4
    assert AuditLog.objects.filter(action="task.transition", entity_id=str(task.pk)).count() == 4


def test_allowed_transitions_reflect_role(world, task):
    member = {t["to_status"] for t in f.client_for(world.member).get(f"/api/v1/tasks/{task.pk}/transitions/").json()}
    manager = {t["to_status"] for t in f.client_for(world.manager).get(f"/api/v1/tasks/{task.pk}/transitions/").json()}
    assert member == {"IN_PROGRESS", "BLOCKED"}
    assert manager == {"IN_PROGRESS", "BLOCKED", "CANCELLED"}


def test_invalid_transition_lists_allowed(world, task):
    response = move(f.client_for(world.manager), task, "COMPLETED")
    assert response.status_code == 409 and response.json()["error"]["code"] == "invalid_transition"
    assert "IN_PROGRESS" in response.json()["error"]["details"]["allowed"]


def test_review_triggers_not_available_manually(world, task):
    manager = f.client_for(world.manager)
    move(manager, task, "IN_PROGRESS")
    assert move(manager, task, "IN_REVIEW").status_code == 409  # only through submit-for-review


def test_member_cannot_move_unassigned_task(world):
    other = f.make_task(world.project, world.manager, assignees=[world.member2])
    assert move(f.client_for(world.member), other, "IN_PROGRESS").status_code == 404  # not visible at all


def test_on_hold_and_cancel_require_comment(world, task):
    manager = f.client_for(world.manager)
    move(manager, task, "IN_PROGRESS")
    assert move(manager, task, "ON_HOLD").status_code == 400
    assert move(manager, task, "ON_HOLD", "Client paused").status_code == 200
    assert move(manager, task, "CANCELLED", "Descoped").json()["is_read_only"] is True
    assert (
        f.client_for(world.manager)
        .patch(f"/api/v1/tasks/{task.pk}/", {"title": "x", "version": 99}, format="json")
        .json()["error"]["code"]
        == "task_locked"
    )
    restored = move(manager, task, "BACKLOG", "Back in scope")
    assert restored.status_code == 200


def test_dependencies_block_start(world, task):
    manager = f.client_for(world.manager)
    blocker = f.make_task(world.project, world.manager, title="Design")
    manager.post(f"/api/v1/tasks/{task.pk}/dependencies/", {"blocked_by_id": str(blocker.pk)}, format="json")
    response = move(f.client_for(world.member), task, "IN_PROGRESS")
    assert response.status_code == 409 and response.json()["error"]["code"] == "dependency_blocked"
    assert response.json()["error"]["details"]["blocked_by"] == [blocker.key]
    manager.post(f"/api/v1/tasks/{blocker.pk}/transition/", {"to_status": "CANCELLED", "comment": "n/a"}, format="json")
    assert move(f.client_for(world.member), task, "IN_PROGRESS").status_code == 200


def test_dependency_enforcement_is_configurable(world, task, company_a):
    company_a.enforce_dependencies = False
    company_a.save()
    blocker = f.make_task(world.project, world.manager)
    f.client_for(world.manager).post(
        f"/api/v1/tasks/{task.pk}/dependencies/", {"blocked_by_id": str(blocker.pk)}, format="json"
    )
    assert move(f.client_for(world.member), task, "IN_PROGRESS").status_code == 200


def test_version_conflict(world, task):
    response = move(f.client_for(world.member), task, "IN_PROGRESS", version=task.version + 5)
    assert response.status_code == 409 and response.json()["error"]["code"] == "version_conflict"


def test_completed_task_reopen_flow(world, task):
    """COMPLETED is reachable only via review approval (Phase 4); simulate it with the
    APPROVE trigger and check the lock and the reopen path."""
    manager = f.client_for(world.manager)
    move(manager, task, "IN_PROGRESS")
    transition_task(actor=world.manager, task_id=task.pk, to_status=Status.IN_REVIEW, trigger="SUBMIT")
    transition_task(actor=world.manager, task_id=task.pk, to_status=Status.COMPLETED, trigger="APPROVE")
    task.refresh_from_db()
    assert task.locked_at and task.completed_at and task.is_read_only
    assert manager.post(f"/api/v1/tasks/{task.pk}/comments/", {"body": "late"}, format="json").status_code == 409
    assert (
        f.client_for(world.member)
        .post(f"/api/v1/tasks/{task.pk}/reopen/", {"comment": "bug"}, format="json")
        .status_code
        == 403
    )
    assert manager.post(f"/api/v1/tasks/{task.pk}/reopen/", {}, format="json").status_code == 400
    reopened = manager.post(f"/api/v1/tasks/{task.pk}/reopen/", {"comment": "Regression found"}, format="json")
    assert reopened.json()["status"] == "REOPENED" and reopened.json()["locked_at"] is None
    assert move(f.client_for(world.member), task, "IN_PROGRESS").status_code == 200


def test_direct_status_write_is_forbidden(world, task):
    task.status = Status.COMPLETED
    with pytest.raises(DirectStatusWrite):
        task.save()
    with pytest.raises(DirectStatusWrite):
        Task(
            company=task.company,
            project=task.project,
            number=999,
            title="x",
            created_by=world.manager,
            status=Status.IN_PROGRESS,
        ).save()


class TestRuleAdministration:
    def test_hr_can_change_roles_on_unlocked_rule(self, world):
        rule = StatusTransitionRule.objects.get(
            from_status="ON_HOLD", to_status="IN_PROGRESS", company=world.team.company
        )
        client = f.client_for(world.hr)
        response = client.patch(
            f"/api/v1/company/workflow/rules/{rule.pk}/",
            {"allowed_roles": ["COMPANY_ADMIN", "MANAGER", "TEAM_LEAD", "TEAM_MEMBER"]},
            format="json",
        )
        assert response.status_code == 200 and "TEAM_MEMBER" in response.json()["allowed_roles"]
        assert (
            client.patch(
                f"/api/v1/company/workflow/rules/{rule.pk}/", {"allowed_roles": ["GHOST"]}, format="json"
            ).status_code
            == 400
        )

    def test_core_rules_protected(self, world):
        company = world.team.company
        locked = StatusTransitionRule.objects.get(company=company, from_status="IN_PROGRESS", to_status="BLOCKED")
        client = f.client_for(world.admin)
        assert (
            client.patch(
                f"/api/v1/company/workflow/rules/{locked.pk}/", {"is_active": False}, format="json"
            ).status_code
            == 400
        )
        assert (
            client.patch(
                f"/api/v1/company/workflow/rules/{locked.pk}/", {"requires_comment": False}, format="json"
            ).status_code
            == 400
        )

    def test_disabling_a_rule_blocks_the_transition_and_reset_restores(self, world, task):
        rule = StatusTransitionRule.objects.get(
            company=world.team.company, from_status="ASSIGNED", to_status="IN_PROGRESS", trigger="MANUAL"
        )
        admin = f.client_for(world.admin)
        admin.patch(f"/api/v1/company/workflow/rules/{rule.pk}/", {"is_active": False}, format="json")
        assert move(f.client_for(world.member), task, "IN_PROGRESS").status_code == 409
        assert admin.post("/api/v1/company/workflow/rules/reset/").json()["count"] == len(DEFAULT_RULES)
        assert move(f.client_for(world.member), task, "IN_PROGRESS").status_code == 200

    def test_member_reads_rules_but_cannot_edit(self, world):
        client = f.client_for(world.member)
        rules = client.get("/api/v1/company/workflow/rules/").json()
        assert len(rules) == len(DEFAULT_RULES)
        assert (
            client.patch(
                f"/api/v1/company/workflow/rules/{rules[0]['id']}/", {"is_active": False}, format="json"
            ).status_code
            == 403
        )
