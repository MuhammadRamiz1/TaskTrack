"""Default status transition rules seeded for every company (docs/architecture/04-task-lifecycle.md 4.3)."""

from .models import Status as S  # noqa: N817 - short aliases keep the rule table readable
from .models import Trigger as T  # noqa: N817

CA, MG, TL, TM = "COMPANY_ADMIN", "MANAGER", "TEAM_LEAD", "TEAM_MEMBER"
CANCELLABLE = [S.BACKLOG, S.ASSIGNED, S.IN_PROGRESS, S.ON_HOLD, S.BLOCKED]


def _rule(frm, to, trigger, roles, *, comment=False, reviewer=False, locked=False):
    return {
        "from_status": frm,
        "to_status": to,
        "trigger": trigger,
        "allowed_roles": roles,
        "requires_comment": comment,
        "requires_reviewer": reviewer,
        "is_locked": locked,
    }


DEFAULT_RULES = [
    _rule(S.BACKLOG, S.ASSIGNED, T.ASSIGN, [CA, MG, TL], locked=True),
    _rule(S.ASSIGNED, S.BACKLOG, T.SYSTEM, [], locked=True),
    _rule(S.ASSIGNED, S.IN_PROGRESS, T.MANUAL, [CA, MG, TL, TM]),
    _rule(S.ASSIGNED, S.IN_PROGRESS, T.TIMER, [CA, MG, TL, TM]),
    _rule(S.IN_PROGRESS, S.IN_REVIEW, T.SUBMIT, [MG, TL, TM], reviewer=True, locked=True),
    _rule(S.IN_REVIEW, S.COMPLETED, T.APPROVE, [CA, MG, TL], reviewer=True, locked=True),
    _rule(S.IN_REVIEW, S.IN_PROGRESS, T.REQUEST_CHANGES, [CA, MG, TL], comment=True, reviewer=True, locked=True),
    _rule(S.IN_PROGRESS, S.ON_HOLD, T.MANUAL, [CA, MG, TL], comment=True),
    _rule(S.ON_HOLD, S.IN_PROGRESS, T.MANUAL, [CA, MG, TL]),
    _rule(S.ASSIGNED, S.BLOCKED, T.MANUAL, [CA, MG, TL, TM], comment=True, locked=True),
    _rule(S.IN_PROGRESS, S.BLOCKED, T.MANUAL, [CA, MG, TL, TM], comment=True, locked=True),
    _rule(S.BLOCKED, S.IN_PROGRESS, T.MANUAL, [CA, MG, TL]),
    _rule(S.BLOCKED, S.ASSIGNED, T.MANUAL, [CA, MG, TL]),
    _rule(S.COMPLETED, S.REOPENED, T.MANUAL, [CA, MG], comment=True, locked=True),
    _rule(S.REOPENED, S.IN_PROGRESS, T.MANUAL, [CA, MG, TL, TM]),
    _rule(S.REOPENED, S.IN_PROGRESS, T.TIMER, [CA, MG, TL, TM]),
    *[_rule(frm, S.CANCELLED, T.MANUAL, [CA, MG], comment=True) for frm in CANCELLABLE],
    _rule(S.CANCELLED, S.BACKLOG, T.MANUAL, [CA, MG], comment=True),
]

#: Rules whose requires_comment may never be switched off (BLOCKED reason, reopen reason,
#: change requests). Companies can still edit roles on unlocked rules.
COMMENT_ALWAYS_REQUIRED = {
    (S.ASSIGNED, S.BLOCKED),
    (S.IN_PROGRESS, S.BLOCKED),
    (S.COMPLETED, S.REOPENED),
    (S.IN_REVIEW, S.IN_PROGRESS),
}


def seed_rules(company_id, RuleModel=None) -> int:  # noqa: N803 - model class (historical in migrations)
    if RuleModel is None:
        from .models import StatusTransitionRule as RuleModel
    created = 0
    for rule in DEFAULT_RULES:
        _, was_created = RuleModel.objects.update_or_create(
            company_id=company_id,
            from_status=rule["from_status"],
            to_status=rule["to_status"],
            trigger=rule["trigger"],
            defaults={**rule, "is_active": True},
        )
        created += was_created
    return created
