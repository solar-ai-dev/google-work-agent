from copy import deepcopy
from json import dumps, loads
from typing import cast

from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.application.use_cases.run.run_terminal import (
    build_finalize_state_update,
    derive_finalize_intent,
)


def _state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "schema_version": 1,
        "run_id": "run-1",
        "conversation_id": "conversation-1",
        "thread_id": "thread-1",
        "workflow_phase": "REQUEST_ANALYSIS",
        "request_intent": {"goal": {"summary": "Find the task status."}},
        "acquisition_result": None,
        "context_result": None,
        "analysis_result": None,
        "planning_result": None,
        "plan_review": None,
        "approved_plan_id": None,
        "execution_summary": None,
        "verification_summary": None,
        "finalize_intent": None,
        "user_interrupt": None,
        "retry_budget": build_default_run_budget(),
        "prompt_context": {},
        "trace_context": {},
    }
    state.update(overrides)
    return state


def _checkpoint_roundtrip(state: dict[str, object]) -> dict[str, object]:
    decoded: object = loads(dumps(deepcopy(state)))
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise AssertionError("checkpoint state must be a JSON object")
    return cast(dict[str, object], decoded)


def test_derive_finalize_intent__prefers_persisted_finalize__handoff_after_checkpoint() -> None:
    state = _state(
        request_intent=None,
        **build_finalize_state_update(
            intent="BLOCKED",
            reason_code="INTENT_UNSUPPORTED_SCOPE",
        ),
    )

    intent = derive_finalize_intent(state=_checkpoint_roundtrip(state))

    assert intent == {
        "schema_version": 1,
        "intent": "BLOCKED",
        "reason_code": "INTENT_UNSUPPORTED_SCOPE",
        "result_kind": None,
    }


def test_derive_finalize_intent__keeps_technical_failure__in_persisted_handoff() -> None:
    state = _state(
        **build_finalize_state_update(
            intent="FAILED",
            reason_code="OUTPUT_SCHEMA_INVALID",
        ),
    )

    intent = derive_finalize_intent(state=_checkpoint_roundtrip(state))

    assert intent == {
        "schema_version": 1,
        "intent": "FAILED",
        "reason_code": "OUTPUT_SCHEMA_INVALID",
        "result_kind": None,
    }


def test_derive_finalize_intent__completes_current_answer__from_state_only() -> None:
    intent = derive_finalize_intent(
        state=_checkpoint_roundtrip(
            _state(
                workflow_phase="PLAN_REVIEW",
                planning_result={
                    "schema_version": 2,
                    "meta": {"artifact_id": "answer-1", "revision": 1, "based_on": []},
                    "answer": "Done",
                    "evidence_refs": [],
                },
            )
        )
    )

    assert intent == {
        "schema_version": 1,
        "intent": "COMPLETED",
        "reason_code": "ANSWER_ONLY_REVIEW_PASS",
        "result_kind": None,
    }


def test_derive_finalize_intent__does_not_use_trace__context_as_terminal_authority() -> None:
    intent = derive_finalize_intent(
        state=_state(
            workflow_phase="FINALIZE",
            request_intent=None,
            trace_context={
                "request_understanding_result": "INVALID",
                "validator_codes": ["INTENT_UNSUPPORTED_SCOPE"],
            },
        )
    )

    assert intent is None
