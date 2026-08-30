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
        "source_fetch_plans": [],
        "acquisition_result": None,
        "context_result": None,
        "analysis_result": None,
        "answer_draft": None,
        "plan_draft": None,
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


def test_derive_finalize_intent_prefers_persisted_finalize_handoff_after_checkpoint() -> None:
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


def test_derive_finalize_intent_keeps_technical_failure_in_persisted_handoff() -> None:
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


def test_derive_finalize_intent_completes_answer_only_review_pass_from_state_only() -> None:
    intent = derive_finalize_intent(
        state=_checkpoint_roundtrip(
            _state(
                workflow_phase="PLAN_REVIEW",
                answer_draft={
                    "schema_version": 1,
                    "status": "ANSWER_ONLY",
                    "answer": "Done",
                    "evidence_refs": [],
                    "resource_refs": [],
                    "reason_codes": [],
                    "confirmation": None,
                    "blockers": [],
                    "llm_provider_result": {},
                },
                plan_review={
                    "schema_version": 1,
                    "status": "PASS",
                    "summary": "Looks good",
                    "issues": [],
                    "reason_codes": [],
                    "evidence_refs": [],
                    "resource_refs": [],
                    "confirmation": None,
                    "blockers": [],
                    "additional_acquisition_request": None,
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


def test_derive_finalize_intent_fails_acquisition_from_state_only() -> None:
    intent = derive_finalize_intent(
        state=_checkpoint_roundtrip(
            _state(
                workflow_phase="API_ACQUISITION",
                acquisition_result={
                    "schema_version": 1,
                    "status": "FAILED",
                    "resource_handles": [],
                    "source_summaries": [
                        {
                            "schema_version": 1,
                            "source": "GMAIL",
                            "status": "FAILED",
                            "required": True,
                            "error_code": "QUERY_PROVIDER_FAILED",
                            "resource_count": 0,
                            "resource_handles": [],
                            "resources": [],
                        }
                    ],
                    "missing_slots": ["GMAIL:QUERY_PROVIDER_FAILED"],
                    "remaining_budget": {"sources": 2, "pages": 2, "candidates": 20, "details": 10},
                },
            )
        )
    )

    assert intent == {
        "schema_version": 1,
        "intent": "FAILED",
        "reason_code": "QUERY_PROVIDER_FAILED",
        "result_kind": None,
    }


def test_derive_finalize_intent_returns_none_for_auth_boundary() -> None:
    intent = derive_finalize_intent(
        state=_state(
            workflow_phase="API_ACQUISITION",
            acquisition_result={
                "schema_version": 1,
                "status": "AUTH_REQUIRED",
                "resource_handles": [],
                "source_summaries": [],
                "missing_slots": ["GMAIL:AUTH_EXPIRED"],
                "remaining_budget": {"sources": 2, "pages": 2, "candidates": 20, "details": 10},
            },
        )
    )

    assert intent is None


def test_derive_finalize_intent_does_not_use_trace_context_as_terminal_authority() -> None:
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
