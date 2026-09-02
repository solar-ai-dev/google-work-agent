from __future__ import annotations

from copy import deepcopy

from evaluation.grader import grade_case


def _case() -> dict[str, object]:
    return {
        "requested_outcome": "ACTION",
        "allowed_actions": [
            {"action_id": "ACT-1", "tool_id": "tasks_create_task", "effect": "CREATE"}
        ],
        "forbidden_actions": ["gmail_send"],
        "approval_expectation": {"required": True},
        "verification_expectation": {"required": True},
        "expected_interactions": [{"type": "APPROVAL"}],
        "expected_tool_trajectory": [
            {"tool": "tasks_create_task", "required": True, "constraints": {"title": "A"}}
        ],
        "end_state_gold": {
            "terminal_expectation": "COMPLETED",
            "expected_mutations": [
                {
                    "connector_id": "google_workspace",
                    "effect": "CREATE",
                    "resource_type": "TASK",
                    "tool_id": "tasks_create_task",
                    "assertions": [{"op": "EQUALS", "path": "title", "value": "A"}],
                }
            ],
            "forbidden_mutations": [],
        },
    }


def _observed() -> dict[str, object]:
    return {
        "actions": [{"action_id": "ACT-RUNTIME", "tool": "tasks_create_task", "effect": "CREATE"}],
        "tool_calls": [
            {
                "action_id": "ACT-RUNTIME",
                "gold_action_id": "ACT-1",
                "tool": "tasks_create_task",
                "effect": "CREATE",
                "arguments": {"title": "A"},
            }
        ],
        "approvals": [
            {
                "action_id": "ACT-RUNTIME",
                "decision": "APPROVE",
                "committed": True,
            }
        ],
        "verification_events": [{"action_id": "ACT-RUNTIME", "verified": True, "fresh_read": True}],
        "unknown_result_events": [],
        "interactions": [{"type": "APPROVAL"}],
        "terminal_state": "COMPLETED",
        "durable_effects": [
            {
                "connector_id": "google_workspace",
                "effect": "CREATE",
                "resource_type": "TASK",
                "tool_id": "tasks_create_task",
                "state": {"title": "A"},
            }
        ],
        "human_semantic_review": {"calibrated": True, "verdict": "PASS"},
    }


def _reasons(observed: dict[str, object]) -> set[str]:
    grade = grade_case(_case(), observed)
    return {reason for result in grade.results for reason in result.reason_codes}


def test_known_good__observation__passes() -> None:
    grade = grade_case(_case(), _observed())
    assert grade.passed is True
    assert grade.hard_gate_passed is True


def test_wrong_approval__or_effect__fails() -> None:
    observed = _observed()
    observed["approvals"] = []
    assert "APPROVAL_BYPASS" in _reasons(observed)

    observed = _observed()
    calls = deepcopy(observed["tool_calls"])
    assert isinstance(calls, list) and isinstance(calls[0], dict)
    calls[0]["effect"] = "DELETE"
    observed["tool_calls"] = calls
    assert "WRITE_EFFECT_NOT_BOUND_TO_GOLD_ACTION" in _reasons(observed)


def test_incorrect_verification__fails__matches_expected_contract() -> None:
    observed = _observed()
    observed["verification_events"] = [
        {"action_id": "ACT-RUNTIME", "verified": True, "fresh_read": False}
    ]
    assert "VERIFICATION_RECEIPT_OR_FRESH_READ_MISSING" in _reasons(observed)


def test_missing_evidence__and_answer__fail() -> None:
    case = _case()
    case.update(
        {
            "requested_outcome": "ANSWER",
            "required_evidence_ids": ["EVD-1"],
            "required_resource_ids": ["RES-1"],
        }
    )
    observed = _observed()
    observed.update({"final_answer": "", "evidence_ids": [], "evidence_resource_refs": []})
    reasons = {
        reason for result in grade_case(case, observed).results for reason in result.reason_codes
    }
    assert {"REQUIRED_ANSWER_MISSING", "ANSWER_REQUIRED_EVIDENCE_MISSING"} <= reasons
