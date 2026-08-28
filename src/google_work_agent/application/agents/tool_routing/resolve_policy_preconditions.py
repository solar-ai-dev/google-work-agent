from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ScopeExpansionRequiredV1,
)
from google_work_agent.application.orchestration.contracts import PolicyConfirmationReceiptV1
from google_work_agent.application.orchestration.scope_expansion import ScopeExpansionResolver


@dataclass(frozen=True, slots=True)
class PolicyPreconditionResolutionV1:
    candidate: SemanticRouteCandidate
    workflow_signal: ScopeExpansionRequiredV1 | None


def resolve_policy_preconditions(
    *,
    request_intent: RequestIntentV2,
    candidate: SemanticRouteCandidate,
    policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1] = (),
    current_interrupt_id: str | None = None,
    scope_expansion: ScopeExpansionResolver | None = None,
) -> PolicyPreconditionResolutionV1:
    """Resolve mandatory policy READ resources without changing any OUT route.

    An out-of-scope READ is never materialized until the Application-owned
    confirmation receipt for the current interrupt validates successfully.
    """

    required_reads = _required_reads(candidate)
    resolver = scope_expansion or ScopeExpansionResolver()
    out_of_scope = resolver.out_of_scope_reads(
        request_intent=request_intent,
        required_reads=required_reads,
        category_of=coarse_resource_category,
    )
    if out_of_scope:
        required_resource_types = tuple(sorted({read[1] for read in out_of_scope}))
        reason_codes = tuple(sorted({read[2] for read in out_of_scope}))
        approval = resolver.find_valid_approval(
            request_intent=request_intent,
            required_resource_types=required_resource_types,
            reason_codes=reason_codes,
            receipts=policy_confirmation_receipts,
            current_interrupt_id=current_interrupt_id,
        )
        if approval is None:
            return PolicyPreconditionResolutionV1(
                candidate=candidate,
                workflow_signal={
                    "schema_version": 1,
                    "kind": "SCOPE_EXPANSION_REQUIRED",
                    "reason_codes": list(reason_codes),
                    "required_resource_types": list(required_resource_types),
                },
            )
    return PolicyPreconditionResolutionV1(
        candidate=_merge_required_reads(candidate, required_reads=required_reads),
        workflow_signal=None,
    )


def _required_reads(
    candidate: SemanticRouteCandidate,
) -> tuple[tuple[str, str, str], ...]:
    required: set[tuple[str, str, str]] = set()
    for resource_type, effect in candidate.output_pairs:
        key = (resource_type, effect.value)
        if key == ("TASK", "CREATE"):
            required.update(
                {
                    ("", "TASK", "POLICY_TASK_DUPLICATE_CHECK"),
                    ("", "TASK_LIST", "POLICY_TASK_DUPLICATE_CHECK"),
                }
            )
        elif key == ("CALENDAR_EVENT", "CREATE"):
            required.update(
                {
                    (
                        "",
                        "CALENDAR",
                        "POLICY_CALENDAR_CONFLICT_CHECK",
                    ),
                    (
                        "",
                        "CALENDAR_EVENT",
                        "POLICY_CALENDAR_CONFLICT_CHECK",
                    ),
                    (
                        "",
                        "CALENDAR_FREEBUSY",
                        "POLICY_CALENDAR_CONFLICT_CHECK",
                    ),
                }
            )
    return tuple(sorted(required))


def _merge_required_reads(
    candidate: SemanticRouteCandidate,
    *,
    required_reads: Sequence[tuple[str, str, str]],
) -> SemanticRouteCandidate:
    input_resources = set(candidate.input_resource_types)
    reason_codes = dict(candidate.input_reason_codes)
    for _connector_id, resource_type, reason_code in required_reads:
        input_resources.add(resource_type)
        reason_codes[resource_type] = reason_code
    return SemanticRouteCandidate(
        input_resource_types=tuple(sorted(input_resources)),
        output_pairs=candidate.output_pairs,
        output_mode=candidate.output_mode,
        analysis_requirement=candidate.analysis_requirement,
        input_reason_codes=tuple(sorted(reason_codes.items())),
    )


__all__ = ["PolicyPreconditionResolutionV1", "resolve_policy_preconditions"]
