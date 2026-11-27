"""The audit log reads as plain English for company admins and HR: no action or permission codes."""

import re

from apps.audit.describe import SENTENCES
from tests import factories as f

AUDIT = "/api/v1/audit/"
CODE = re.compile(r"\b[a-z_]+\.[a-z_.]+\b")  # e.g. org.team.members_added, task.delete


def latest(client, **query):
    body = client.get(AUDIT, query)
    assert body.status_code == 200, body.content
    return body.json()["results"][0]


def test_team_members_added_reads_as_a_sentence(world):
    hr = f.client_for(world.hr)
    team = hr.post("/api/v1/org/teams/", {"name": "Mobile"}, format="json").json()
    users = [str(world.member.pk), str(world.member2.pk)]
    assert hr.post(f"/api/v1/org/teams/{team['id']}/members/", {"user_ids": users}, format="json").status_code == 201

    for viewer in (world.admin, world.hr):
        entry = latest(f.client_for(viewer), category="organization")
        names = sorted([world.member.full_name, world.member2.full_name])
        assert entry["summary"] in (
            f"{world.hr.full_name} added {names[0]} and {names[1]} to the team Mobile.",
            f"{world.hr.full_name} added {names[1]} and {names[0]} to the team Mobile.",
        )
        assert not CODE.search(entry["summary"])
        assert entry["changes"] == []


def test_role_permission_changes_show_descriptions_not_codes(world):
    admin = f.client_for(world.admin)
    role = admin.post(
        "/api/v1/company/roles/",
        {"name": "Auditor", "rank": 20, "permissions": [{"code": "audit.view", "scope": "COMPANY"}]},
        format="json",
    ).json()
    admin.put(
        f"/api/v1/company/roles/{role['id']}/permissions/",
        {"permissions": [{"code": "audit.view", "scope": "COMPANY"}, {"code": "task.delete", "scope": "PROJECT"}]},
        format="json",
    )
    entry = latest(admin, category="roles")
    assert entry["summary"] == f"{world.admin.full_name} changed what the role Auditor can do."
    assert entry["changes"] == [{"field": "Delete and restore tasks", "before": "not allowed", "after": "own projects"}]
    for text in [entry["summary"], *(v for c in entry["changes"] for v in c.values())]:
        assert not CODE.search(text), text


def test_task_status_change_uses_labels(world):
    from apps.tasks.models import Status
    from apps.tasks.workflow import transition_task

    task = f.make_task(world.project, world.manager, assignees=[world.member], title="Ship it")
    transition_task(actor=world.member, task_id=task.pk, to_status=Status.IN_PROGRESS)
    entry = latest(f.client_for(world.admin), category="tasks")
    assert entry["summary"] == f"{world.member.full_name} moved {task.key} “Ship it” from Assigned to In progress."


def test_updates_list_changed_fields_in_words(world):
    hr = f.client_for(world.hr)
    team = hr.post("/api/v1/org/teams/", {"name": "Mobile"}, format="json").json()
    hr.patch(f"/api/v1/org/teams/{team['id']}/", {"name": "Mobile apps"}, format="json")
    entry = latest(hr, category="organization")
    assert entry["summary"] == f"{world.hr.full_name} updated the team Mobile apps."
    assert {"field": "Name", "before": "Mobile", "after": "Mobile apps"} in entry["changes"]


def test_every_recorded_action_has_a_sentence():
    import ast
    import pathlib

    actions = set()
    for path in pathlib.Path("apps").rglob("*.py"):
        if "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "record":
                for kw in node.keywords:
                    if kw.arg == "action":
                        actions |= {
                            n.value
                            for n in ast.walk(kw.value)
                            if isinstance(n, ast.Constant) and isinstance(n.value, str)
                        }
    actions.discard("time.timer_")  # f-string prefix; stopped/paused/switched are listed explicitly
    missing = sorted(a for a in actions if "." in a and a not in SENTENCES)
    assert missing == []


def test_unknown_or_malformed_entries_still_read_as_words(world):
    from apps.audit.services import record

    record(actor=world.admin, action="org.team.members_added", entity=world.team, new_value="not a dict")
    record(actor=world.admin, action="org.team.something_new", entity=world.team)
    admin = f.client_for(world.admin)
    results = admin.get(AUDIT, {"category": "organization"}).json()["results"]
    assert results[0]["summary"] == f"{world.admin.full_name} made a change (something new) to a team."
    assert results[1]["summary"] == f"{world.admin.full_name} added nobody to the team Web."
