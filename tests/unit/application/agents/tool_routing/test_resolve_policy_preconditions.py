from __future__ import annotations

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintV1,
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.resolve_policy_preconditions import (
    resolve_policy_preconditions,
)
from google_work_agent.domain.action.model import EffectType


def _intent(*, forbidden_sources: list[str] | None = None) -> RequestIntentV2:
    constraints: list[ConstraintV1] = []
    if forbidden_sources is not None:
        constraints.append(
            {"kind": "SCOPE", "field": "forbidden_sources", "value": forbidden_sources}
        )
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "create work",
        "completion_conditions": ["created"],
        "constraints": constraints,
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }


def _candidate(resource_type: str) -> SemanticRouteCandidate:
    return SemanticRouteCandidate(
        input_resource_types=(),
        output_pairs=((resource_type, EffectType.CREATE),),
        output_mode="ACTION",
        analysis_requirement="REQUIRED",
    )


def test_task_create_adds_only_mandatory_duplicate_check_resources() -> None:
    result = resolve_policy_preconditions(
        request_intent=_intent(),
        candidate=_candidate("TASK"),
    )

    assert result.workflow_signal is None
    assert set(result.candidate.input_resource_types) == {"TASK", "TASK_LIST"}
    assert set(result.candidate.input_reason_codes) == {
        ("TASK", "POLICY_TASK_DUPLICATE_CHECK"),
        ("TASK_LIST", "POLICY_TASK_DUPLICATE_CHECK"),
    }
    assert result.candidate.output_pairs == _candidate("TASK").output_pairs


def test_calendar_create_adds_event_freebusy_and_calendar_resources() -> None:
    result = resolve_policy_preconditions(
        request_intent=_intent(),
        candidate=_candidate("CALENDAR_EVENT"),
    )

    assert result.workflow_signal is None
    assert set(result.candidate.input_resource_types) == {
        "CALENDAR",
        "CALENDAR_EVENT",
        "CALENDAR_FREEBUSY",
    }


def test_out_of_scope_policy_reads_are_not_materialized_before_confirmation() -> None:
    original = _candidate("TASK")
    result = resolve_policy_preconditions(
        request_intent=_intent(forbidden_sources=["TASK"]),
        candidate=original,
    )

    assert result.candidate is original
    assert result.candidate.input_resource_types == ()
    assert result.workflow_signal == {
        "schema_version": 1,
        "kind": "SCOPE_EXPANSION_REQUIRED",
        "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
        "required_resource_types": ["TASK", "TASK_LIST"],
    }
