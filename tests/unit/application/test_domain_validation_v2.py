from __future__ import annotations

from google_work_agent.application.workflows.domain_validation_v2 import (
    build_domain_validation_output_from_v2,
)


class _ResourceReader:
    def __init__(self, resources):
        self._resources = dict(resources)

    def resolve_resource_identity(self, *, run_id: str, resource_handle: str):
        assert run_id == "run-1"
        return self._resources.get(resource_handle)


def _plan_meta():
    return {
        "artifact_id": "plan-1",
        "revision": 1,
        "based_on": [{"artifact_id": "analysis-1", "revision": 1}],
    }


def _review(*, plan_revision: int = 1):
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


def _evidence(resource_handle: str = "task:t1"):
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


def _reader():
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


def _task_update_plan():
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


def _task_create_plan():
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


def _call(plan, *, review=None, evidence=None, reader=None, analysis=None, receipts=()):
    return build_domain_validation_output_from_v2(
        run_id="run-1",
        planning_result=plan,
        plan_review=review or _review(),
        work_analysis_result=analysis,
        evidence_drafts=evidence or _evidence(),
        policy_confirmation_receipts=receipts,
        resource_identity_reader=reader or _reader(),
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
    analysis = {
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
        "policy_confirmation_receipt_refs": [
            {"artifact_id": "receipt-artifact-1", "revision": 1}
        ],
        "action_necessity": "REQUIRED",
    }
    declined_receipt = {
        "schema_version": 1,
        "meta": {
            "artifact_id": "receipt-artifact-1",
            "revision": 1,
            "based_on": [],
        },
        "confirmation_receipt_id": "receipt-1",
        "interrupt_id": "interrupt-1",
        "confirmation_kind": "DUPLICATE_OVERRIDE",
        "decision": "DECLINED",
        "decision_context_hash": "hash",
        "affected_route_ids": ["r1"],
        "affected_resource_refs": [],
    }

    result = _call(
        _task_create_plan(),
        analysis=analysis,
        receipts=[declined_receipt],
    )

    assert result["result"] == "BLOCK"
    assert result["reason_codes"] == ["WORK_ANALYSIS_INVALID"]
