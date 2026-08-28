from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from tests.support.canonical_prompt_runtime import (
    activate_prompt_slot,
    copy_prompt_runtime_artifacts,
)

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_SLOT_IDS,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    InactivePromptArtifactError,
    PromptRegistry,
    PromptRegistryError,
    PromptSelectionKey,
    default_prompt_manifest_path,
    load_prompt_reference,
)


def test_prompt_registry_loads_exact_canonical_slot_set() -> None:
    registry = PromptRegistry()

    assert registry.slot_ids == REQUIRED_PROMPT_SLOT_IDS
    assert default_prompt_manifest_path().name == "prompt_manifest.json"


def test_prompt_registry_rejects_draft_product_selection() -> None:
    registry = PromptRegistry()

    with pytest.raises(InactivePromptArtifactError, match="DRAFT"):
        registry.lookup_by_id("planning.compose_answer")


def test_prompt_registry_selects_only_gate_complete_active_slot(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    activate_prompt_slot(manifest_path, "planning.compose_answer")
    registry = PromptRegistry(manifest_path, contract_path)

    prompt_ref = registry.lookup(
        PromptSelectionKey(
            agent_role="planning",
            subgraph_name="planning",
            node_name="compose_answer",
            node_state="INITIAL",
            purpose="compose_answer",
            input_schema_version=1,
            output_schema_version=1,
        )
    )

    assert prompt_ref.prompt_id == "planning.compose_answer"


def test_runtime_active_label_without_gate_evidence_fails_closed(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slot = next(
        slot
        for slot in cast(list[dict[str, object]], manifest["slots"])
        if slot["prompt_slot_id"] == "planning.compose_answer"
    )
    slot["activation_status"] = "RUNTIME_ACTIVE"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry = PromptRegistry(manifest_path, contract_path)

    with pytest.raises(InactivePromptArtifactError, match="activation-gate complete"):
        registry.lookup_by_id("planning.compose_answer")


def test_prompt_registry_rejects_source_hash_drift(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    source = manifest_path.parent / "sources" / "planning.compose_answer.md"
    source.write_text(source.read_text(encoding="utf-8") + "drift", encoding="utf-8")

    with pytest.raises(PromptRegistryError, match="source hash mismatch"):
        PromptRegistry(manifest_path, contract_path)


def test_predecessor_caller_slot_keeps_product_runtime_inactive() -> None:
    with pytest.raises(InactivePromptArtifactError, match="not represented"):
        load_prompt_reference("request_understanding.classify")


def test_prompt_registry_rejects_duplicate_json_field(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            '"schema_version": 1,',
            '"schema_version": 1, "schema_version": 1,',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PromptRegistryError, match="duplicate JSON field"):
        PromptRegistry(manifest_path, contract_path)
