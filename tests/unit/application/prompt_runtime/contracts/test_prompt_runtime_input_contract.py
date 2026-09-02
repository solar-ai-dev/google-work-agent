from __future__ import annotations

import pytest

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    PromptRuntimeInputContractEntryV1,
    PromptRuntimeInputContractError,
    PromptRuntimeInputContractV1,
)


def _contract() -> PromptRuntimeInputContractV1:
    return PromptRuntimeInputContractV1(
        schema_version=1,
        entries=(
            PromptRuntimeInputContractEntryV1(
                prompt_slot_id="planning.compose_answer",
                runtime_node_id="planning.compose_answer",
                input_schema_version=1,
                required_root_fields=("answer_outline",),
                optional_root_fields=("work_analysis",),
                output_schema_version=1,
            ),
        ),
        forbidden_input_fields=frozenset({"conversation_history", "gold"}),
    )


def test_prompt_runtime__input_contract_accepts__only_declared_projection() -> None:
    _contract().validate_projection(
        "planning.compose_answer", {"answer_outline": {}, "work_analysis": None}
    )


def test_prompt_runtime_input__contract_rejects_missing__and_unknown_fields() -> None:
    with pytest.raises(PromptRuntimeInputContractError, match="missing required"):
        _contract().validate_projection("planning.compose_answer", {})
    with pytest.raises(PromptRuntimeInputContractError, match="unknown Product Prompt"):
        _contract().validate_projection(
            "planning.compose_answer", {"answer_outline": {}, "legacy_context": {}}
        )


def test_prompt_runtime__input_contract_rejects__forbidden_nested_fields() -> None:
    with pytest.raises(PromptRuntimeInputContractError, match="conversation_history"):
        _contract().validate_projection(
            "planning.compose_answer",
            {"answer_outline": {"conversation_history": ["hidden"]}},
        )


def test_prompt_runtime__input_contract__rejects_duplicate_slot() -> None:
    entry = _contract().entries[0]
    with pytest.raises(PromptRuntimeInputContractError, match="duplicate"):
        PromptRuntimeInputContractV1(
            schema_version=1,
            entries=(entry, entry),
            forbidden_input_fields=frozenset(),
        )
