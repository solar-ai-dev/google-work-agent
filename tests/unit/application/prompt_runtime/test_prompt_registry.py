from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import cast

import pytest
from tests.support.canonical_prompt_runtime import (
    activate_prompt_slot,
    copy_prompt_runtime_artifacts,
)

from google_work_agent.application.prompt_runtime import prompt_registry as prompt_registry_module
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

CANONICAL_ACTIVATION_STATUSES = frozenset(
    {"DRAFT", "DEV_VALIDATED", "HOLDOUT_VALIDATED", "RUNTIME_ACTIVE", "RETIRED"}
)


def test_prompt_registry_loads_exact_canonical_slot_set() -> None:
    registry = PromptRegistry()

    assert registry.slot_ids == REQUIRED_PROMPT_SLOT_IDS
    assert default_prompt_manifest_path().name == "prompt_manifest.json"


def test_prompt_registry_rejects_draft_product_selection() -> None:
    registry = PromptRegistry()

    with pytest.raises(InactivePromptArtifactError, match="DRAFT"):
        registry.lookup_by_id("planning.compose_answer")


def test_request_understanding_prompts_remain_draft_without_release_evidence() -> None:
    registry = PromptRegistry()

    for prompt_id in (
        "request_understanding.identify_goal",
        "request_understanding.detect_ambiguity",
    ):
        with pytest.raises(InactivePromptArtifactError, match="DRAFT"):
            registry.lookup_by_id(prompt_id)

    manifest = cast(
        dict[str, object],
        json.loads(default_prompt_manifest_path().read_text(encoding="utf-8")),
    )
    slots = cast(list[dict[str, object]], manifest["slots"])
    request_slots = [
        slot for slot in slots if str(slot["prompt_slot_id"]).startswith("request_understanding.")
    ]
    assert len(request_slots) == 2
    for slot in request_slots:
        assert slot["activation_status"] == "DRAFT"
        assert all(
            slot[field] is False
            for field in (
                "node_dev_pass",
                "node_holdout_pass",
                "safety_gate_pass",
                "manifest_approved",
            )
        )


def test_prompt_registry_accepts_exact_canonical_activation_status_vocabulary() -> None:
    assert prompt_registry_module._ACTIVATION_STATUSES == CANONICAL_ACTIVATION_STATUSES


def test_prompt_registry_rejects_safety_gate_as_activation_status(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slots = cast(list[dict[str, object]], manifest["slots"])
    slots[0]["activation_status"] = "SAFETY_VALIDATED"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PromptRegistryError, match="unknown activation status"):
        PromptRegistry(manifest_path, contract_path)


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
    with pytest.raises(PromptRegistryError, match="requires complete release evidence"):
        PromptRegistry(manifest_path, contract_path)


@pytest.mark.parametrize(
    ("activation_status", "evidence", "message"),
    [
        ("DRAFT", (True, False, False, False), "DRAFT cannot claim"),
        ("DEV_VALIDATED", (True, True, False, False), "DEV_VALIDATED evidence"),
        ("HOLDOUT_VALIDATED", (False, True, False, False), "HOLDOUT evidence requires DEV"),
        ("HOLDOUT_VALIDATED", (True, True, False, True), "approval requires Safety"),
        ("RETIRED", (True, True, True, False), "requires complete release evidence"),
    ],
)
def test_prompt_registry_rejects_illegal_activation_lifecycle(
    tmp_path: Path,
    activation_status: str,
    evidence: tuple[bool, bool, bool, bool],
    message: str,
) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slot = cast(list[dict[str, object]], manifest["slots"])[0]
    slot["activation_status"] = activation_status
    for field, value in zip(
        ("node_dev_pass", "node_holdout_pass", "safety_gate_pass", "manifest_approved"),
        evidence,
        strict=True,
    ):
        slot[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PromptRegistryError, match=message):
        PromptRegistry(manifest_path, contract_path)


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


def test_all_21_prompt_sources_are_lf_pinned_and_manifest_hash_exact() -> None:
    manifest_path = default_prompt_manifest_path()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_root = manifest_path.parent
    assert len(manifest["slots"]) == 21
    for slot in manifest["slots"]:
        source = source_root / slot["source"]
        payload = source.read_bytes()
        assert b"\r\n" not in payload
        assert hashlib.sha256(payload).hexdigest() == slot["content_hash"]
        attribute = subprocess.run(
            ["git", "check-attr", "eol", "--", str(source)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert attribute.endswith("eol: lf")


def test_crlf_rewrite_is_rejected_instead_of_reusing_stale_evidence(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    source = manifest_path.parent / "sources" / "planning.compose_answer.md"
    source.write_bytes(source.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(PromptRegistryError, match="source hash mismatch"):
        PromptRegistry(manifest_path, contract_path)
