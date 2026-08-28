from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.legacy_prompt_input_contract import (
    PromptInputContractError,
    PromptRuntimeInputContractValidator,
)

from google_work_agent.application.orchestration.failure_record import (
    build_failure_record_v1,
)


def _manifest(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "prompts" / "agent"
    contracts_dir = agent_dir / "contracts"
    contracts_dir.mkdir(parents=True)
    manifest_path = agent_dir / "prompt-manifest-v1.0.0.json"
    contract_path = contracts_dir / "prompt-runtime-input-contract-v1.json"
    manifest_path.write_text(
        json.dumps(
            {
                "runtime_input_contract": (
                    "prompts/agent/contracts/prompt-runtime-input-contract-v1.json"
                )
            }
        ),
        encoding="utf-8",
    )
    contract_path.write_text(
        json.dumps(
            {
                "forbidden_runtime_fields": ["interrupt_id", "checkpoint_metadata"],
                "slots": {
                    "planning.compose_answer": {
                        "allowed_root_fields": [
                            "user_request",
                            "request_intent",
                            "work_analysis",
                            "evidence",
                            "confirmation_response",
                        ]
                    },
                    "planning.compose_answer.repair": {
                        "allowed_root_fields": [
                            "base_projection",
                            "candidate_output",
                            "failure_record",
                        ]
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_accepts_declared_product_prompt_projection(tmp_path: Path) -> None:
    validator = PromptRuntimeInputContractValidator(_manifest(tmp_path))

    validator.validate(
        prompt_id="planning.compose_answer",
        prompt_input={
            "user_request": "summarize",
            "request_intent": {},
            "work_analysis": {},
            "evidence": [],
        },
    )


def test_rejects_undeclared_root_field(tmp_path: Path) -> None:
    validator = PromptRuntimeInputContractValidator(_manifest(tmp_path))

    with pytest.raises(PromptInputContractError, match="undeclared root fields"):
        validator.validate(
            prompt_id="planning.compose_answer",
            prompt_input={
                "user_request": "summarize",
                "request_intent": {},
                "work_analysis": {},
                "evidence": [],
                "legacy_context_result": {},
            },
        )


def test_rejects_forbidden_field_at_any_depth(tmp_path: Path) -> None:
    validator = PromptRuntimeInputContractValidator(_manifest(tmp_path))

    with pytest.raises(PromptInputContractError, match="forbidden runtime fields"):
        validator.validate(
            prompt_id="planning.compose_answer",
            prompt_input={
                "user_request": "summarize",
                "request_intent": {"meta": {"checkpoint_metadata": "must-not-leak"}},
                "work_analysis": {},
                "evidence": [],
            },
        )


def test_repair_slot_accepts_only_bounded_envelope(tmp_path: Path) -> None:
    validator = PromptRuntimeInputContractValidator(_manifest(tmp_path))

    validator.validate(
        prompt_id="planning.compose_answer.repair",
        prompt_input={
            "base_projection": {"user_request": "summarize"},
            "candidate_output": {"answer": "draft"},
            "failure_record": build_failure_record_v1(
                failure_reason_code="OUTPUT_SCHEMA_INVALID",
                failure_origin="LLM_OUTPUT",
                detected_by="RUNTIME_SCHEMA_VALIDATOR",
                runtime_disposition="RETRYABLE",
                experiment_disposition="RUN_REPAIR",
            ),
        },
    )

    with pytest.raises(PromptInputContractError, match="undeclared root fields"):
        validator.validate(
            prompt_id="planning.compose_answer.repair",
            prompt_input={
                "base_projection": {},
                "candidate_output": {},
                "failure_record": {},
                "validator_errors": ["raw error"],
            },
        )


def test_missing_slot_fails_closed(tmp_path: Path) -> None:
    validator = PromptRuntimeInputContractValidator(_manifest(tmp_path))

    with pytest.raises(PromptInputContractError, match="must be an object"):
        validator.validate(prompt_id="unknown.slot", prompt_input={})
