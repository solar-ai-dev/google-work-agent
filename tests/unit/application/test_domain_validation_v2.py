from __future__ import annotations

from collections.abc import Sequence
from inspect import Parameter, signature
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.main.validate_planning_output import (
    CanonicalDomainValidationService,
    PolicyOverrideProvenanceDependency,
    build_domain_validation_output_from_v2,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.action.validate_action_arguments import (
    ValidateActionArgumentsHandler,
)


class _ResourceReader:
    def __init__(self, resources: dict[str, dict[str, object]]) -> None:
        self._resources = dict(resources)

    def resolve_resource_identity(
        self, *, run_id: str, resource_handle: str
    ) -> dict[str, object] | None:
        assert run_id == "run-1"
        return self._resources.get(resource_handle)


def _plan_meta() -> dict[str, Any]:
    return {
        "artifact_id": "plan-1",
        "revision": 1,
        "based_on": [{"artifact_id": "analysis-1", "revision": 1}],
    }


def _review(*, plan_revision: int = 1) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": "review-1",
            "revision": 1,
            "based_on": [{"artifact_id": "plan-1", "revision": plan_revision}],
        },
        "status": "PASS",
        "summary": "ok",
    }


def _evidence(resource_handle: str = "task:t1") -> list[dict[str, Any]]:
    return [
        {
            "schema_version": 1,
            "evidence_id": "ev-1",
            "resource_handle": resource_handle,
            "segment_id": "seg-1",
            "kind": "CONTEXT",
            "excerpt": "submit report",
            "locator": None,
            "reason_codes": ["SUPPORTS"],
        }
    ]


def _reader() -> _ResourceReader:
    return _ResourceReader(
        {
            "task:t1": {
                "resource_handle": "task:t1",
                "resource_type": "task",
                "resource_id": "t1",
                "parent_id": "list-1",
            }
        }
    )


def _task_update_plan() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "meta": _plan_meta(),
        "actions": [
            {
                "action_id": "a1",
                "route_id": "r1",
                "tool_id": "tasks_update_task",
                "effect": "UPDATE",
                "arguments": {
                    "task_list_id": "list-1",
                    "task_id": "t1",
                    "payload": {"status": "completed"},
                },
                "evidence_refs": ["ev-1"],
                "depends_on_action_ids": [],
            }
        ],
    }


def _task_create_plan() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "meta": _plan_meta(),
        "actions": [
            {
                "action_id": "a1",
                "route_id": "r1",
                "tool_id": "tasks_create_task",
                "effect": "CREATE",
                "arguments": {
                    "task_list_id": "list-1",
                    "payload": {"title": "new task"},
                },
                "evidence_refs": ["ev-1"],
                "depends_on_action_ids": [],
            }
        ],
    }


def _analysis(
    *,
    action_necessity: str = "REQUIRED",
    receipt_refs: Sequence[object] = (),
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": "analysis-1",
            "revision": 1,
            "based_on": [{"artifact_id": "retrieval-1", "revision": 1}],
        },
        "work_facts": [],
        "relations": [],
        "ambiguities": [],
        "risks": [],
        "evidence_refs": ["ev-1"],
        "policy_confirmation_receipt_refs": list(receipt_refs),
        "action_necessity": action_necessity,
        "action_necessity_reason": "requested write" if action_necessity == "REQUIRED" else None,
    }


def _receipt(*, decision: str = "APPROVED") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": "receipt-artifact-1",
            "revision": 1,
            "based_on": [],
        },
        "interrupt_id": "interrupt-1",
        "confirmation_kind": "DUPLICATE_OVERRIDE",
        "decision": decision,
        "semantic_owner_id": "WORK_ANALYSIS",
        "decision_context_hash": "hash",
        "affected_route_ids": ["r1"],
        "affected_resource_refs": [],
    }


def _call(
    plan: Any,
    *,
    review: Any = None,
    evidence: Any = None,
    reader: Any = None,
    analysis: Any = None,
    receipts: Any = (),
) -> Any:
    return build_domain_validation_output_from_v2(
        run_id="run-1",
        planning_result=plan,
        plan_review=cast(Any, review or _review()),
        work_analysis_result=analysis,
        evidence_drafts=cast(Any, evidence or _evidence()),
        policy_confirmation_receipts=receipts,
        resource_identity_reader=cast(Any, reader or _reader()),
        tool_registry=load_signed_tool_registry(),
        validate_action_arguments=ValidateActionArgumentsHandler(),
    )


def test_valid_task_update_requires_approval() -> None:
    result = _call(_task_update_plan())
    assert result["result"] == "REQUIRE_APPROVAL"


def test_update_blocks_when_evidence_is_not_tied_to_exact_current_run_target() -> None:
    result = _call(
        _task_update_plan(),
        evidence=_evidence("task:other"),
        reader=_ResourceReader({}),
    )
    assert result["result"] == "BLOCK"
    assert result["reason_codes"] == ["PLAN_DRAFT_INVALID"]


def test_create_requires_evidence_but_not_existing_target() -> None:
    result = _call(_task_create_plan(), reader=_ResourceReader({}))
    assert result["result"] == "REQUIRE_APPROVAL"


def test_invalid_tool_effect_pair_blocks() -> None:
    plan = _task_create_plan()
    plan["actions"][0]["effect"] = "DELETE"

    result = _call(plan)

    assert result["result"] == "BLOCK"
    assert result["reason_codes"] == ["PLAN_DRAFT_INVALID"]


def test_stale_review_cannot_authorize_current_plan() -> None:
    result = _call(_task_create_plan(), review=_review(plan_revision=2))

    assert result["result"] == "BLOCK"
    assert result["reason_codes"] == ["PLAN_REVIEW_INVALID"]


def test_work_analysis_receipt_ref_must_resolve_to_approved_receipt() -> None:
    analysis = _analysis(receipt_refs=[{"artifact_id": "receipt-artifact-1", "revision": 1}])

    result = _call(
        _task_create_plan(),
        analysis=analysis,
        receipts=[_receipt(decision="DECLINED")],
    )

    assert result["result"] == "BLOCK"
    assert result["reason_codes"] == ["WORK_ANALYSIS_INVALID"]


def test_not_required_analysis_with_action_fails_closed_on_override_provenance_dependency() -> None:
    analysis = _analysis(
        action_necessity="NOT_REQUIRED",
        receipt_refs=[{"artifact_id": "receipt-artifact-1", "revision": 1}],
    )

    with pytest.raises(
        PolicyOverrideProvenanceDependency,
        match="POLICY_OVERRIDE_PROVENANCE_DEPENDENCY",
    ):
        _call(
            _task_create_plan(),
            analysis=analysis,
            receipts=[_receipt(decision="APPROVED")],
        )


def test_registry_authority_must_be_explicitly_injected() -> None:
    service_parameter = signature(CanonicalDomainValidationService).parameters["tool_registry"]
    helper_parameter = signature(build_domain_validation_output_from_v2).parameters["tool_registry"]

    assert service_parameter.default is Parameter.empty
    assert helper_parameter.default is Parameter.empty
