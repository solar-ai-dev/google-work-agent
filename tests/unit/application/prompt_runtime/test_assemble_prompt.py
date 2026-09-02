from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.canonical_prompt_runtime import (
    activate_prompt_slot,
    copy_prompt_runtime_artifacts,
)

from google_work_agent.application.prompt_runtime.assemble_prompt import (
    PromptAssemblyError,
    assemble_prompt,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    EVALUATION,
    PromptRegistry,
)


def _active_registry(tmp_path: Path) -> PromptRegistry:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    activate_prompt_slot(manifest_path, "planning.compose_answer")
    return PromptRegistry(manifest_path, contract_path)


def _projection() -> dict[str, object]:
    return {
        "user_request": "summarize",
        "request_intent": {"goal": "summary"},
        "answer_outline": {"sections": ["summary"]},
        "evidence": [],
    }


def test_assemble_prompt__uses_registered_source__and_allowlisted_projection(
    tmp_path: Path,
) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")

    assembled = assemble_prompt(prompt_ref, _projection(), registry=registry)

    assert assembled.startswith("You are the Planning answer-composition node.")
    assert '"user_request":"summarize"' in assembled


def test_assemble_prompt_rejects__forbidden_previous_run__and_evaluation_fields(
    tmp_path: Path,
) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")

    for field in ("conversation_history", "previous_run_artifacts", "gold", "grader"):
        with pytest.raises(PromptAssemblyError):
            assemble_prompt(
                prompt_ref,
                {**_projection(), "request_intent": {field: "forbidden"}},
                registry=registry,
            )


def test_assemble_prompt_rejects__raw_provider_continuation__and_mcp_arguments(
    tmp_path: Path,
) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")

    for field in ("next_page_token", "provider_continuation", "mcp_arguments"):
        with pytest.raises(PromptAssemblyError):
            assemble_prompt(
                prompt_ref,
                {**_projection(), "request_intent": {field: "forbidden"}},
                registry=registry,
            )


def test_assemble_prompt__adds_bounded__failure_instruction(tmp_path: Path) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")
    failure = build_failure_record_v1(
        failure_reason_code="OUTPUT_SCHEMA_INVALID",
        failure_origin="LLM_OUTPUT",
        detected_by="RUNTIME_SCHEMA_VALIDATOR",
        runtime_disposition="RETRYABLE",
        experiment_disposition="RUN_REPAIR",
        affected_field_paths=["$.answer"],
    )

    assembled = assemble_prompt(
        prompt_ref, _projection(), failure_record=failure, registry=registry
    )

    assert "Bounded failure instruction" in assembled
    assert "OUTPUT_SCHEMA_INVALID" in assembled
    assert "experiment_disposition" not in assembled


def test_evaluation_and_development_scope__use_same__draft_base_source() -> None:
    registry = PromptRegistry()
    prompt_ref = registry.lookup_for_evaluation("planning.compose_answer")

    evaluation_assembled = assemble_prompt(
        prompt_ref,
        _projection(),
        registry=registry,
        execution_scope=EVALUATION,
    )
    development_assembled = assemble_prompt(
        prompt_ref,
        _projection(),
        registry=registry,
        execution_scope=DEVELOPMENT_SMOKE,
    )

    assert evaluation_assembled.startswith("You are the Planning answer-composition node.")
    assert development_assembled == evaluation_assembled


def test_unknown_activation__scope_fails__closed() -> None:
    registry = PromptRegistry()
    prompt_ref = registry.lookup_for_evaluation("planning.compose_answer")

    with pytest.raises(PromptAssemblyError, match="unknown Prompt execution scope"):
        assemble_prompt(
            prompt_ref,
            _projection(),
            registry=registry,
            execution_scope="OTHER",  # type: ignore[arg-type]
        )


def test_development_smoke__does_not_admit__evaluation_only_fields() -> None:
    registry = PromptRegistry()
    prompt_ref = registry.lookup_for_development_smoke("planning.compose_answer")

    for field in ("gold", "grader", "expected_output", "evaluation_id"):
        with pytest.raises(PromptAssemblyError):
            assemble_prompt(
                prompt_ref,
                {**_projection(), field: "forbidden"},
                registry=registry,
                execution_scope=DEVELOPMENT_SMOKE,
            )


def test_repair_envelope__reuses_base_source__and_binds_candidate(tmp_path: Path) -> None:
    registry = _active_registry(tmp_path)
    prompt_ref = registry.lookup_by_id("planning.compose_answer")
    failure = build_failure_record_v1(
        failure_reason_code="OUTPUT_SCHEMA_INVALID",
        failure_origin="LLM_OUTPUT",
        detected_by="RUNTIME_SCHEMA_VALIDATOR",
        runtime_disposition="RETRYABLE",
        experiment_disposition="RUN_REPAIR",
        affected_field_paths=["$.answer"],
    )

    assembled = assemble_prompt(
        prompt_ref,
        {
            "base_projection": _projection(),
            "candidate_output": {"answer": 123},
            "failure_record": failure,
        },
        registry=registry,
    )

    assert "Candidate output to repair" in assembled
    assert '"answer":123' in assembled
    assert "OUTPUT_SCHEMA_INVALID" in assembled
