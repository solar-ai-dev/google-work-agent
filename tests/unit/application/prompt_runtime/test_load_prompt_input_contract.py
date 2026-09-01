from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_SLOT_IDS,
    PromptRuntimeInputContractError,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    default_prompt_input_contract_path,
    load_prompt_input_contract,
)


def _payload() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(default_prompt_input_contract_path().read_text(encoding="utf-8")),
    )


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "prompt_runtime_input_contract_v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_prompt_input_contract_closes_exact_slot_set() -> None:
    contract = load_prompt_input_contract()

    assert contract.schema_version == 1
    assert contract.slot_ids == REQUIRED_PROMPT_SLOT_IDS


def test_sufficiency_contract_matches_the_live_typed_projection() -> None:
    contract = load_prompt_input_contract()

    contract.validate_projection(
        "retrieval.assess_sufficiency",
        {
            "request_intent": {},
            "selected_evidence": [],
            "source_statuses": [],
            "budget_state": {
                "additional_rounds_used": 0,
                "additional_rounds_remaining": 2,
            },
        },
    )


def test_load_prompt_input_contract_rejects_schema_version(tmp_path: Path) -> None:
    payload = _payload()
    payload["schema_version"] = 2

    with pytest.raises(PromptRuntimeInputContractError, match="schema version"):
        load_prompt_input_contract(_write(tmp_path, payload))


def test_load_prompt_input_contract_rejects_missing_unknown_and_duplicate_slots(
    tmp_path: Path,
) -> None:
    payload = _payload()
    entries = cast(list[dict[str, object]], payload["entries"])
    removed = entries.pop()
    with pytest.raises(PromptRuntimeInputContractError, match="slot set mismatch"):
        load_prompt_input_contract(_write(tmp_path, payload))

    entries.append(removed)
    entries.append({**removed, "prompt_slot_id": "unknown.slot"})
    with pytest.raises(PromptRuntimeInputContractError, match="slot set mismatch"):
        load_prompt_input_contract(_write(tmp_path, payload))

    entries.pop()
    entries.append(dict(removed))
    with pytest.raises(PromptRuntimeInputContractError, match="duplicate"):
        load_prompt_input_contract(_write(tmp_path, payload))


def test_load_prompt_input_contract_rejects_duplicate_json_field(tmp_path: Path) -> None:
    path = tmp_path / "prompt_runtime_input_contract_v1.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")

    with pytest.raises(PromptRuntimeInputContractError, match="duplicate JSON field"):
        load_prompt_input_contract(path)
