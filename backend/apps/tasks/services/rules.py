"""Company administration of status transition rules."""

from apps.audit.services import record
from apps.common.exceptions import InvalidInput
from apps.rbac import policy
from apps.rbac.models import Role

from ..models import StatusTransitionRule, Trigger
from ..workflow_defaults import COMMENT_ALWAYS_REQUIRED, seed_rules


def update_rule(*, actor, rule: StatusTransitionRule, data: dict) -> StatusTransitionRule:
    policy.require(actor, "workflow.manage")
    if rule.trigger == Trigger.SYSTEM:
        raise InvalidInput("System rules cannot be edited.", code="system_rule")
    if rule.is_locked and data.get("is_active") is False:
        raise InvalidInput(details={"is_active": ["Core rules cannot be disabled."]})
    if (rule.from_status, rule.to_status) in COMMENT_ALWAYS_REQUIRED and data.get("requires_comment") is False:
        raise InvalidInput(details={"requires_comment": ["This change always requires a comment."]})
    if "allowed_roles" in data:
        known = set(Role.objects.filter(company_id=actor.company_id).values_list("key", flat=True))
        unknown = set(data["allowed_roles"]) - known
        if unknown:
            raise InvalidInput(details={"allowed_roles": [f"Unknown roles: {', '.join(sorted(unknown))}."]})
    old = {k: getattr(rule, k) for k in data}
    for key, value in data.items():
        setattr(rule, key, value)
    rule.save()
    record(actor=actor, action="workflow.rule.updated", entity=rule, old_value=old, new_value=data)
    return rule


def reset_rules(*, actor) -> int:
    policy.require(actor, "workflow.manage")
    StatusTransitionRule.objects.filter(company_id=actor.company_id).delete()
    count = seed_rules(actor.company_id)
    record(actor=actor, action="workflow.rules.reset", entity_type="statustransitionrule", new_value={"rules": count})
    return count
