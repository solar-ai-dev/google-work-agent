"""C2-B: ScopeExpansionResolver + PolicyConfirmationReceiptV1 unit tests.

Covers the deterministic scope-comparison and receipt-provenance logic in
isolation from LangGraph/Registry/LLM machinery -- see
``test_tool_route_confirmation.py`` for the full nested-checkpoint
integration proof.
"""

from __future__ import annotations

from typing import Literal, cast

from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.orchestration.handoff_contracts import RequestIntentV2
from google_work_agent.application.orchestration.scope_expansion import (
    ScopeExpansionResolver,
    build_policy_confirmation_receipt,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)

_TASK_READS = (
    ("google_workspace", "TASK", "POLICY_TASK_DUPLICATE_CHECK"),
    ("google_workspace", "TASK_LIST", "POLICY_TASK_DUPLICATE_CHECK"),
)
_CALENDAR_READS = (
    ("google_workspace", "CALENDAR", "POLICY_CALENDAR_CONFLICT_CHECK"),
    ("google_workspace", "CALENDAR_EVENT", "POLICY_CALENDAR_CONFLICT_CHECK"),
    ("google_workspace", "CALENDAR_FREEBUSY", "POLICY_CALENDAR_CONFLICT_CHECK"),
)


def _request_intent(
    *, constraints: list[dict[str, object]] | None = None, revision: int = 1
) -> RequestIntentV2:
    return cast(
        RequestIntentV2,
        {
            "schema_version": 2,
            "meta": {"artifact_id": "intent-1", "revision": revision, "based_on": []},
            "goal": "Create a task.",
            "completion_conditions": ["Task created."],
            "constraints": constraints or [],
            "ambiguity": {
                "requires_confirmation": False,
                "reason_codes": [],
                "missing_fields": [],
            },
            "requested_effect_hints": ["CREATE"],
            "requested_resource_hints": ["TASK"],
            "analysis_requirement": "REQUIRED",
        },
    )


def test_out_of_scope_reads_empty_when_no_scope_constraints() -> None:
    resolver = ScopeExpansionResolver()
    out_of_scope = resolver.out_of_scope_reads(
        request_intent=_request_intent(),
        required_reads=_TASK_READS,
        category_of=coarse_resource_category,
    )
    assert out_of_scope == ()


def test_out_of_scope_reads_flags_forbidden_task_source() -> None:
    resolver = ScopeExpansionResolver()
    out_of_scope = resolver.out_of_scope_reads(
        request_intent=_request_intent(
            constraints=[{"kind": "SCOPE", "field": "forbidden_sources", "value": ["TASK"]}]
        ),
        required_reads=_TASK_READS,
        category_of=coarse_resource_category,
    )
    assert set(out_of_scope) == set(_TASK_READS)


def test_out_of_scope_reads_flags_forbidden_calendar_source() -> None:
    resolver = ScopeExpansionResolver()
    out_of_scope = resolver.out_of_scope_reads(
        request_intent=_request_intent(
            constraints=[{"kind": "SCOPE", "field": "forbidden_sources", "value": ["CALENDAR"]}]
        ),
        required_reads=_CALENDAR_READS,
        category_of=coarse_resource_category,
    )
    assert set(out_of_scope) == set(_CALENDAR_READS)


def test_out_of_scope_reads_flags_required_sources_allowlist_excluding_category() -> None:
    resolver = ScopeExpansionResolver()
    out_of_scope = resolver.out_of_scope_reads(
        request_intent=_request_intent(
            constraints=[{"kind": "SCOPE", "field": "required_sources", "value": ["EMAIL"]}]
        ),
        required_reads=_TASK_READS,
        category_of=coarse_resource_category,
    )
    assert set(out_of_scope) == set(_TASK_READS)


def test_out_of_scope_reads_allows_when_category_is_in_required_sources_allowlist() -> None:
    resolver = ScopeExpansionResolver()
    out_of_scope = resolver.out_of_scope_reads(
        request_intent=_request_intent(
            constraints=[{"kind": "SCOPE", "field": "required_sources", "value": ["TASK"]}]
        ),
        required_reads=_TASK_READS,
        category_of=coarse_resource_category,
    )
    assert out_of_scope == ()


def test_out_of_scope_reads_ignores_resource_kind_constraints() -> None:
    """RESOURCE-kind constraints carry selected resource ids, not a source
    scope declaration (see retrieval_ranking.py._selected_resource_ids) --
    they must not be misread as a SCOPE restriction."""
    resolver = ScopeExpansionResolver()
    out_of_scope = resolver.out_of_scope_reads(
        request_intent=_request_intent(
            constraints=[{"kind": "RESOURCE", "field": "selected_resource_ids", "value": ["x"]}]
        ),
        required_reads=_TASK_READS,
        category_of=coarse_resource_category,
    )
    assert out_of_scope == ()


def _build_receipt(
    *,
    request_intent: RequestIntentV2,
    interrupt_id: str = "interrupt-1",
    decision: Literal["APPROVED", "DECLINED"] = "APPROVED",
) -> PolicyConfirmationReceiptV1:
    counter = iter(["receipt-artifact-1", "receipt-id-1"])
    return build_policy_confirmation_receipt(
        id_factory=lambda: next(counter),
        interrupt_id=interrupt_id,
        decision=decision,
        request_intent=request_intent,
        required_resource_types=("TASK", "TASK_LIST"),
        reason_codes=("POLICY_TASK_DUPLICATE_CHECK",),
        affected_route_ids=["TASK:CREATE"],
    )


def test_find_valid_approval_accepts_matching_receipt() -> None:
    resolver = ScopeExpansionResolver()
    request_intent = _request_intent()
    receipt = _build_receipt(request_intent=request_intent)
    approval = resolver.find_valid_approval(
        request_intent=request_intent,
        required_resource_types=("TASK", "TASK_LIST"),
        reason_codes=("POLICY_TASK_DUPLICATE_CHECK",),
        receipts=[receipt],
        current_interrupt_id="interrupt-1",
    )
    assert approval == receipt


def test_find_valid_approval_rejects_declined_receipt() -> None:
    resolver = ScopeExpansionResolver()
    request_intent = _request_intent()
    receipt = _build_receipt(request_intent=request_intent, decision="DECLINED")
    approval = resolver.find_valid_approval(
        request_intent=request_intent,
        required_resource_types=("TASK", "TASK_LIST"),
        reason_codes=("POLICY_TASK_DUPLICATE_CHECK",),
        receipts=[receipt],
        current_interrupt_id="interrupt-1",
    )
    assert approval is None


def test_find_valid_approval_rejects_wrong_interrupt_id() -> None:
    """A receipt built for a different interrupt occurrence (foreign/replayed)
    must never unlock a scope expansion it was not built for."""
    resolver = ScopeExpansionResolver()
    request_intent = _request_intent()
    receipt = _build_receipt(request_intent=request_intent, interrupt_id="interrupt-OTHER")
    approval = resolver.find_valid_approval(
        request_intent=request_intent,
        required_resource_types=("TASK", "TASK_LIST"),
        reason_codes=("POLICY_TASK_DUPLICATE_CHECK",),
        receipts=[receipt],
        current_interrupt_id="interrupt-1",
    )
    assert approval is None


def test_find_valid_approval_rejects_when_no_current_interrupt() -> None:
    """Receipts are not standing credentials: a fresh (round-1) route()
    attempt with no just-resolved interrupt never reuses an older receipt,
    even if its content would otherwise match."""
    resolver = ScopeExpansionResolver()
    request_intent = _request_intent()
    receipt = _build_receipt(request_intent=request_intent)
    approval = resolver.find_valid_approval(
        request_intent=request_intent,
        required_resource_types=("TASK", "TASK_LIST"),
        reason_codes=("POLICY_TASK_DUPLICATE_CHECK",),
        receipts=[receipt],
        current_interrupt_id=None,
    )
    assert approval is None


def test_find_valid_approval_rejects_stale_request_intent_revision() -> None:
    resolver = ScopeExpansionResolver()
    original_intent = _request_intent(revision=1)
    receipt = _build_receipt(request_intent=original_intent)
    revised_intent = _request_intent(revision=2)
    approval = resolver.find_valid_approval(
        request_intent=revised_intent,
        required_resource_types=("TASK", "TASK_LIST"),
        reason_codes=("POLICY_TASK_DUPLICATE_CHECK",),
        receipts=[receipt],
        current_interrupt_id="interrupt-1",
    )
    assert approval is None


def test_find_valid_approval_rejects_tampered_decision_context_hash() -> None:
    resolver = ScopeExpansionResolver()
    request_intent = _request_intent()
    receipt = dict(_build_receipt(request_intent=request_intent))
    receipt["decision_context_hash"] = "forged-hash-value"
    approval = resolver.find_valid_approval(
        request_intent=request_intent,
        required_resource_types=("TASK", "TASK_LIST"),
        reason_codes=("POLICY_TASK_DUPLICATE_CHECK",),
        receipts=[cast(PolicyConfirmationReceiptV1, receipt)],
        current_interrupt_id="interrupt-1",
    )
    assert approval is None


def test_find_valid_approval_rejects_receipt_for_different_resource_types() -> None:
    """A CALENDAR-scope receipt must never unlock a TASK scope expansion,
    even with the same interrupt id and request-intent revision."""
    resolver = ScopeExpansionResolver()
    request_intent = _request_intent()
    counter = iter(["artifact", "receipt-id"])
    calendar_receipt = build_policy_confirmation_receipt(
        id_factory=lambda: next(counter),
        interrupt_id="interrupt-1",
        decision="APPROVED",
        request_intent=request_intent,
        required_resource_types=("CALENDAR", "CALENDAR_EVENT", "CALENDAR_FREEBUSY"),
        reason_codes=("POLICY_CALENDAR_CONFLICT_CHECK",),
        affected_route_ids=["CALENDAR_EVENT:CREATE"],
    )
    approval = resolver.find_valid_approval(
        request_intent=request_intent,
        required_resource_types=("TASK", "TASK_LIST"),
        reason_codes=("POLICY_TASK_DUPLICATE_CHECK",),
        receipts=[calendar_receipt],
        current_interrupt_id="interrupt-1",
    )
    assert approval is None


def test_build_policy_confirmation_receipt_has_required_minimum_fields() -> None:
    request_intent = _request_intent()
    receipt = _build_receipt(request_intent=request_intent)
    assert receipt["schema_version"] == 1
    assert receipt["confirmation_kind"] == "SCOPE_EXPANSION"
    assert receipt["decision"] == "APPROVED"
    assert receipt["semantic_owner_id"] == "TOOL_ROUTE"
    assert receipt["meta"]["artifact_id"] == "receipt-artifact-1"
    assert receipt["interrupt_id"] == "interrupt-1"
    assert receipt["affected_route_ids"] == ["TASK:CREATE"]
    assert receipt["affected_resource_refs"] == ["TASK", "TASK_LIST"]
    assert receipt["meta"]["based_on"] == [{"artifact_id": "intent-1", "revision": 1}]
