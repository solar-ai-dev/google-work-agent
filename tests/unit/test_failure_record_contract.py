from __future__ import annotations

import json
from pathlib import Path

import pytest

from google_work_agent.application.orchestration.failure_record import (
    FAILURE_RECORD_FIELDS,
    FailureRecordValidationError,
    build_failure_record_v1,
    validate_failure_record_v1,
)
from tests.support.legacy_prompt_input_contract import (
    PromptInputContractError,
    PromptRuntimeInputContractValidator,
)


def _record() -> dict[str, object]:
    return build_failure_record_v1(
        failure_reason_code="TOOL_SELECTION_INVALID",
        failure_origin="LLM_OUTPUT",
        detected_by="RUNTIME_DOMAIN_VALIDATOR",
        runtime_disposition="RETRYABLE",
        experiment_disposition="RUN_REVISION",
        affected_field_paths=["$.selected_tool_id"],
        evidence_refs=[],
        failure_context_ids=["issue-1"],
    )


def test_failure_record_builder_emits_exact_canonical_schema() -> None:
    record = _record()
    assert set(record) == FAILURE_RECORD_FIELDS
    assert record["schema_version"] == 1
    assert record["failure_origin"] == "LLM_OUTPUT"
    assert record["detected_by"] == "RUNTIME_DOMAIN_VALIDATOR"
    assert record["affected_field_paths"] == ["$.selected_tool_id"]
    assert "affected_fields" not in record
    assert "allowed_change_scope" not in record
    assert "validation_errors" not in record


def test_failure_record_validator_rejects_bespoke_nested_field() -> None:
    invalid = {**_record(), "validation_errors": ["bad"]}
    with pytest.raises(FailureRecordValidationError, match="exact schema mismatch"):
        validate_failure_record_v1(invalid)


def test_prompt_input_guard_validates_nested_failure_record_exactly(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prompt_dir = repo / "prompts" / "agent"
    contract_dir = prompt_dir / "contracts"
    contract_dir.mkdir(parents=True)
    manifest_path = prompt_dir / "prompt-manifest-v1.json"
    contract_path = contract_dir / "runtime-input-v1.json"
    manifest_path.write_text(
        json.dumps({"runtime_input_contract": "prompts/agent/contracts/runtime-input-v1.json"}),
        encoding="utf-8",
    )
    contract_path.write_text(
        json.dumps(
            {
                "forbidden_runtime_fields": [],
                "slots": {
                    "retrieval.plan_query.revise": {
                        "allowed_root_fields": [
                            "base_projection",
                            "candidate_output",
                            "failure_record",
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    validator = PromptRuntimeInputContractValidator(manifest_path=manifest_path)
    valid_input = {
        "base_projection": {},
        "candidate_output": {},
        "failure_record": _record(),
    }
    validator.validate(
        prompt_id="retrieval.plan_query.revise",
        prompt_input=valid_input,
    )

    invalid_input = {
        **valid_input,
        "failure_record": {**_record(), "review_issue_ids": ["issue-1"]},
    }
    with pytest.raises(PromptInputContractError, match="failure_record is invalid"):
        validator.validate(
            prompt_id="retrieval.plan_query.revise",
            prompt_input=invalid_input,
        )
