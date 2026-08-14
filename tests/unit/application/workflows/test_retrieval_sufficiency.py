"""Tests for retrieval.assess_sufficiency's own Canonical output contract and
SS19.2 deterministic close-out Guard (docs/05-context-retrieval.md SS19.1,
SS19.2)."""

from __future__ import annotations

import pytest

from google_work_agent.application.workflows import MAX_ADDITIONAL_ACQUISITIONS
from google_work_agent.application.workflows.context_segmentation import (
    ContextRetrievalValidationError,
)
from google_work_agent.application.workflows.contracts import RunBudgetV1
from google_work_agent.application.workflows.handoff_contracts import (
    ActionEffectValue,
    RequestIntentV2,
    SufficiencyIssueV2,
    SufficiencyResultV2,
)
from google_work_agent.application.workflows.retrieval_sufficiency import (
    enforce_sufficiency_guard,
    missing_information_projection,
    validate_sufficiency_result_v2,
)


def _intent(*, effects: list[ActionEffectValue] | None = None) -> RequestIntentV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "goal",
        "completion_conditions": [],
        "constraints": [],
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        "requested_effect_hints": effects or ["READ"],
        "requested_resource_hints": [],
        "analysis_requirement": "NONE",
    }


def _run_budget(*, used: int) -> RunBudgetV1:
    return {
        "schema_version": 1,
        "profile": "NORMAL",
        "llm_calls_used": 0,
        "additional_acquisitions_used": used,
        "planning_revisions_used": 0,
        "last_rechecked_planning_revision": 0,
        "semantic_revision_signatures_used": [],
    }


def _issue(**overrides: object) -> SufficiencyIssueV2:
    base: SufficiencyIssueV2 = {
        "slot": "date_range",
        "issue_type": "MISSING",
        "required": True,
        "resolution_source": "GOOGLE",
        "safety_critical": False,
        "reason_codes": ["ambiguous date"],
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def test_validate_sufficiency_result_v2_rejects_legacy_candidate_issue_shape() -> None:
    """The PHASE 7.5 Candidate schema originally reused
    MissingInformationV1's {code,description,required_for} shape for
    issues[] by mistake -- that shape must never validate as a
    SufficiencyResultV2 issue again."""
    with pytest.raises(ContextRetrievalValidationError):
        validate_sufficiency_result_v2(
            {
                "schema_version": 2,
                "status": "NEEDS_MORE_DATA",
                "issues": [
                    {
                        "code": "date_range",
                        "description": "ambiguous date",
                        "required_for": "RETRIEVAL",
                    }
                ],
            }
        )


def test_validate_sufficiency_result_v2_accepts_canonical_issue_shape() -> None:
    result = validate_sufficiency_result_v2(
        {
            "schema_version": 2,
            "status": "NEEDS_MORE_DATA",
            "issues": [_issue()],
        }
    )

    assert result["issues"] == [_issue()]


@pytest.mark.parametrize(
    ("resolution_source", "safety_critical", "expected_status"),
    [
        ("POLICY", False, "BLOCKED"),
        ("GOOGLE", True, "BLOCKED"),
        ("USER", False, "NEEDS_CONFIRMATION"),
        ("ROUTE", False, "ROUTE_RECONSIDERATION_REQUIRED"),
        ("GOOGLE", False, "NEEDS_MORE_DATA"),
    ],
)
def test_enforce_sufficiency_guard_follows_ss19_2_precedence(
    resolution_source: str,
    safety_critical: bool,
    expected_status: str,
) -> None:
    """The LLM's proposed status ("SUFFICIENT") is deliberately wrong here --
    the deterministic Guard must override it regardless of LLM confidence."""
    sufficiency_result: SufficiencyResultV2 = {
        "schema_version": 2,
        "status": "SUFFICIENT",
        "issues": [_issue(resolution_source=resolution_source, safety_critical=safety_critical)],
    }

    enforced = enforce_sufficiency_guard(
        sufficiency_result,
        request_intent=_intent(),
        retry_budget=_run_budget(used=0),
        evidence_supported_partial_possible=True,
    )

    assert enforced["status"] == expected_status
    assert enforced["issues"] == sufficiency_result["issues"]


def test_enforce_sufficiency_guard_agrees_when_llm_status_already_matches() -> None:
    sufficiency_result: SufficiencyResultV2 = {
        "schema_version": 2,
        "status": "BLOCKED",
        "issues": [_issue(resolution_source="POLICY", safety_critical=True)],
    }

    enforced = enforce_sufficiency_guard(
        sufficiency_result,
        request_intent=_intent(),
        retry_budget=_run_budget(used=0),
        evidence_supported_partial_possible=True,
    )

    assert enforced is sufficiency_result


def test_enforce_sufficiency_guard_partial_requires_exhausted_budget_read_only_and_evidence() -> (
    None
):
    sufficiency_result: SufficiencyResultV2 = {
        "schema_version": 2,
        "status": "SUFFICIENT",
        "issues": [],
    }

    enforced = enforce_sufficiency_guard(
        sufficiency_result,
        request_intent=_intent(),
        retry_budget=_run_budget(used=MAX_ADDITIONAL_ACQUISITIONS),
        evidence_supported_partial_possible=True,
    )

    assert enforced["status"] == "PARTIAL"


def test_enforce_sufficiency_guard_available_budget_stays_sufficient_with_no_issues() -> None:
    sufficiency_result: SufficiencyResultV2 = {
        "schema_version": 2,
        "status": "PARTIAL",
        "issues": [],
    }

    enforced = enforce_sufficiency_guard(
        sufficiency_result,
        request_intent=_intent(),
        retry_budget=_run_budget(used=0),
        evidence_supported_partial_possible=True,
    )

    assert enforced["status"] == "SUFFICIENT"


def test_enforce_sufficiency_guard_write_effect_missing_data_never_becomes_partial() -> None:
    """docs/05-context-retrieval.md SS19.2 item 6: Write-required data
    shortage resolves to NEEDS_CONFIRMATION or BLOCKED, never PARTIAL --
    PARTIAL is reserved for read-only budget-exhausted-with-usable-evidence
    runs."""
    sufficiency_result: SufficiencyResultV2 = {
        "schema_version": 2,
        "status": "PARTIAL",
        "issues": [_issue(resolution_source="GOOGLE")],
    }

    enforced = enforce_sufficiency_guard(
        sufficiency_result,
        request_intent=_intent(effects=["SEND"]),
        retry_budget=_run_budget(used=MAX_ADDITIONAL_ACQUISITIONS),
        evidence_supported_partial_possible=True,
    )

    assert enforced["status"] != "PARTIAL"
    assert enforced["status"] == "BLOCKED"


def test_missing_information_projection_is_a_distinct_parent_facing_shape() -> None:
    """SufficiencyIssue (Retrieval-internal Guard input) and
    MissingInformationV1 (Parent RetrievalResultV1 handoff, docs/06-agent-
    workflow.md SS3.3) are never the same type -- this is the deterministic
    projection boundary between them."""
    issues = [
        _issue(slot="date_range", resolution_source="USER", reason_codes=["ambiguous date"]),
        _issue(slot="calendar_route", resolution_source="ROUTE", reason_codes=[]),
    ]

    projected = missing_information_projection(issues)

    assert projected == [
        {
            "code": "date_range",
            "description": "ambiguous date",
            "required_for": "USER_CONFIRMATION",
        },
        {"code": "calendar_route", "description": "calendar_route", "required_for": "RETRIEVAL"},
    ]
