from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.prompt_manifests import (
    canonical_prompt_manifest_path,
    write_runtime_active_manifest,
)

from google_work_agent.application.workflows.contracts import PROMPT_SELECTION_KEY_FIELDS
from google_work_agent.application.workflows.prompt_registry import (
    InactivePromptArtifactError,
    default_prompt_manifest_path,
    load_prompt_reference,
)


def test_default_prompt_manifest_path_uses_canonical_r83_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GOOGLE_WORK_AGENT_PROMPT_MANIFEST_PATH",
        str(Path("C:/tmp/arbitrary-manifest.json")),
    )

    assert default_prompt_manifest_path() == canonical_prompt_manifest_path()
    assert default_prompt_manifest_path().name == "prompt-manifest-v0.8.2.json"


def test_load_prompt_reference_succeeds_for_runtime_active_slot(tmp_path: Path) -> None:
    manifest_path = write_runtime_active_manifest(
        tmp_path,
        prompt_ids={"planning.revise_plan"},
    )

    prompt_ref = load_prompt_reference("planning.revise_plan", manifest_path)

    assert prompt_ref.prompt_id == "planning.revise_plan"
    assert prompt_ref.node_state == "SEMANTIC_REVISION"
    assert prompt_ref.input_schema_version == "v1"
    assert prompt_ref.output_schema_version == "v1"


def test_load_prompt_reference_distinguishes_missing_from_inactive_artifact() -> None:
    with pytest.raises(InactivePromptArtifactError, match="planning.revise_plan"):
        load_prompt_reference("planning.revise_plan", canonical_prompt_manifest_path())

    with pytest.raises(LookupError, match="planning.missing_slot"):
        load_prompt_reference("planning.missing_slot", canonical_prompt_manifest_path())


def test_prompt_selection_key_excludes_failure_reason_code() -> None:
    assert "failure_reason_code" not in PROMPT_SELECTION_KEY_FIELDS


def test_legacy_slot_format_uses_runtime_activation_boundary(tmp_path: Path) -> None:
    manifest_path = tmp_path / "legacy-prompt-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "prompt_bundle_version": "0.7.0-r7",
                "activation_policy": "legacy",
                "slots": [
                    {
                        "slot_id": "analysis.analyze",
                        "agent_role": "work_analysis",
                        "purpose": "analyze",
                        "version": "0.4.0-r7",
                        "activation_status": "DRAFT",
                        "files": [],
                        "failure_reason_codes": [],
                        "input_schema": "legacy-input",
                        "output_schema": "legacy-output",
                        "content_hash": "hash",
                        "assembled_path": "legacy.md",
                        "assembled_hash": "hash",
                    }
                ],
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(InactivePromptArtifactError, match="analysis.analyze"):
        load_prompt_reference("analysis.analyze", manifest_path)
