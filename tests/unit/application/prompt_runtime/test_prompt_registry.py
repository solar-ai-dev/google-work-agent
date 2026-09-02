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
    deactivate_prompt_slot,
)

from google_work_agent.application.prompt_runtime import prompt_registry as prompt_registry_module
from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_SLOT_IDS,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    PRODUCT_RELEASE,
    InactivePromptArtifactError,
    PromptRegistry,
    PromptRegistryError,
    PromptSelectionKey,
    default_prompt_manifest_path,
)

CANONICAL_ACTIVATION_STATUSES = frozenset(
    {"DRAFT", "DEV_VALIDATED", "HOLDOUT_VALIDATED", "RUNTIME_ACTIVE", "RETIRED"}
)


def test_prompt_registry__loads_exact__canonical_slot_set() -> None:
    registry = PromptRegistry()

    assert registry.slot_ids == REQUIRED_PROMPT_SLOT_IDS
    assert default_prompt_manifest_path().name == "prompt_manifest.json"
    assert {
        registry.lookup_for_development_smoke(prompt_slot_id).prompt_id
        for prompt_slot_id in REQUIRED_PROMPT_SLOT_IDS
    } == REQUIRED_PROMPT_SLOT_IDS
    assert registry.product_release_ready is False


def test_prompt_registry__rejects_draft__product_selection(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    deactivate_prompt_slot(manifest_path, "planning.compose_answer")
    registry = PromptRegistry(manifest_path, contract_path)

    with pytest.raises(InactivePromptArtifactError, match="DRAFT"):
        registry.lookup_by_id("planning.compose_answer")


def test_all_baseline__prompts_are_honest__pre_experiment_drafts() -> None:
    registry = PromptRegistry()

    manifest = cast(
        dict[str, object],
        json.loads(default_prompt_manifest_path().read_text(encoding="utf-8")),
    )
    slots = cast(list[dict[str, object]], manifest["slots"])
    assert len(slots) == 21
    for slot in slots:
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
        assert slot["activation_evidence"] is None
        with pytest.raises(InactivePromptArtifactError):
            registry.lookup_for_product_release(cast(str, slot["prompt_slot_id"]))


def test_prompt_registry__accepts_exact_canonical__activation_status_vocabulary() -> None:
    assert prompt_registry_module._ACTIVATION_STATUSES == CANONICAL_ACTIVATION_STATUSES


def test_prompt_registry__rejects_safety_gate__as_activation_status(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slots = cast(list[dict[str, object]], manifest["slots"])
    slots[0]["activation_status"] = "SAFETY_VALIDATED"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PromptRegistryError, match="unknown activation status"):
        PromptRegistry(manifest_path, contract_path)


def test_prompt_registry__selects_only_gate__complete_active_slot(tmp_path: Path) -> None:
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


def test_runtime_active__label_without_gate__evidence_fails_closed(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slot = next(
        slot
        for slot in cast(list[dict[str, object]], manifest["slots"])
        if slot["prompt_slot_id"] == "planning.compose_answer"
    )
    slot["activation_status"] = "RUNTIME_ACTIVE"
    for field in (
        "node_dev_pass",
        "node_holdout_pass",
        "safety_gate_pass",
        "manifest_approved",
    ):
        slot[field] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PromptRegistryError, match="requires complete release evidence"):
        PromptRegistry(manifest_path, contract_path)


def test_runtime_active__flags_without_actual_artifacts__fails_closed(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    activate_prompt_slot(manifest_path, "planning.compose_answer")
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slot = next(
        slot
        for slot in cast(list[dict[str, object]], manifest["slots"])
        if slot["prompt_slot_id"] == "planning.compose_answer"
    )
    slot["activation_evidence"] = None
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PromptRegistryError, match="immutable activation evidence"):
        PromptRegistry(manifest_path, contract_path)


@pytest.mark.parametrize("activation_status", ["DEV_VALIDATED", "HOLDOUT_VALIDATED"])
def test_non_active_validated_prompt__is_rejected__by_product_release(
    tmp_path: Path, activation_status: str
) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slot = cast(list[dict[str, object]], manifest["slots"])[0]
    slot["activation_status"] = activation_status
    slot["node_dev_pass"] = True
    if activation_status == "HOLDOUT_VALIDATED":
        slot["node_holdout_pass"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry = PromptRegistry(manifest_path, contract_path)

    with pytest.raises(InactivePromptArtifactError, match=activation_status):
        registry.lookup_for_product_release(cast(str, slot["prompt_slot_id"]))


def test_retired_prompt__rejects_new__product_and_development_execution(
    tmp_path: Path,
) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    activate_prompt_slot(manifest_path, "planning.compose_answer")
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slot = next(
        slot
        for slot in cast(list[dict[str, object]], manifest["slots"])
        if slot["prompt_slot_id"] == "planning.compose_answer"
    )
    slot["activation_status"] = "RETIRED"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry = PromptRegistry(manifest_path, contract_path)

    with pytest.raises(InactivePromptArtifactError):
        registry.lookup_for_product_release("planning.compose_answer")
    with pytest.raises(InactivePromptArtifactError):
        registry.lookup_for_development_smoke("planning.compose_answer")


def test_execution_scope__is_explicit__without_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GWA_PROMPT_EXECUTION_SCOPE", DEVELOPMENT_SMOKE)
    registry = PromptRegistry()

    with pytest.raises(InactivePromptArtifactError):
        registry.lookup_for_product_release("planning.compose_answer")
    assert PRODUCT_RELEASE == "PRODUCT_RELEASE"


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
def test_prompt_registry__rejects_illegal__activation_lifecycle(
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


def test_prompt_registry__rejects_source__hash_drift(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    source = manifest_path.parent / "sources" / "planning.compose_answer.md"
    source.write_text(source.read_text(encoding="utf-8") + "drift", encoding="utf-8")

    with pytest.raises(PromptRegistryError, match="source hash mismatch"):
        PromptRegistry(manifest_path, contract_path)


def test_prompt_registry__rejects_duplicate__json_field(tmp_path: Path) -> None:
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


def test_all_21_prompt__sources_are_lf_pinned__and_manifest_hash_exact() -> None:
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


def test_crlf_rewrite_is__rejected_instead_of__reusing_stale_evidence(tmp_path: Path) -> None:
    manifest_path, contract_path = copy_prompt_runtime_artifacts(tmp_path)
    source = manifest_path.parent / "sources" / "planning.compose_answer.md"
    source.write_bytes(source.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(PromptRegistryError, match="source hash mismatch"):
        PromptRegistry(manifest_path, contract_path)
