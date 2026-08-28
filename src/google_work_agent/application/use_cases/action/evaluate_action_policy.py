"""Compute deterministic product-policy disposition without mutation or I/O."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class EvaluateActionPolicyQueryV1:
    effect: Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
    required_scopes_granted: bool
    target_is_user_selected: bool
    duplicate_blocked: bool = False
    calendar_conflict_blocked: bool = False
    feasibility_blocked: bool = False


@dataclass(frozen=True, slots=True)
class ActionPolicyEvaluationResultV1:
    disposition: Literal["ALLOW", "REQUIRE_APPROVAL", "BLOCK"]
    reason_codes: tuple[str, ...]


class EvaluateActionPolicyHandler:
    def __call__(self, query: EvaluateActionPolicyQueryV1) -> ActionPolicyEvaluationResultV1:
        reasons: list[str] = []
        if not query.required_scopes_granted:
            reasons.append("REQUIRED_SCOPE_MISSING")
        if query.effect != "READ" and not query.target_is_user_selected:
            reasons.append("TARGET_NOT_USER_SELECTED")
        if query.duplicate_blocked:
            reasons.append("DUPLICATE_BLOCKED")
        if query.calendar_conflict_blocked:
            reasons.append("CALENDAR_CONFLICT_BLOCKED")
        if query.feasibility_blocked:
            reasons.append("FEASIBILITY_BLOCKED")
        if reasons:
            return ActionPolicyEvaluationResultV1("BLOCK", tuple(reasons))
        if query.effect == "READ":
            return ActionPolicyEvaluationResultV1("ALLOW", ())
        return ActionPolicyEvaluationResultV1("REQUIRE_APPROVAL", ("WRITE_APPROVAL_REQUIRED",))


__all__ = [
    "ActionPolicyEvaluationResultV1",
    "EvaluateActionPolicyHandler",
    "EvaluateActionPolicyQueryV1",
]
