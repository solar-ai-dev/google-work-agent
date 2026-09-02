from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation.prompt_candidate import (
    PromptCandidateError,
    load_prompt_candidate,
    materialize_prompt_candidate,
)

from google_work_agent.application.prompt_runtime.prompt_registry import (
    InactivePromptArtifactError,
    PromptRegistry,
)

ROOT = Path(__file__).parents[2]
CANDIDATE = (
    ROOT / "evaluation/prompt_candidates/mcp-tool-use-2026-v1/candidate.json"
)
ACTIVE_PROMPT_ROOT = ROOT / "src/google_work_agent/application/prompt_runtime"


def test_mcp_candidate_has__exact_current_slots_hashes_and_draft__lifecycle() -> None:
    bundle = load_prompt_candidate(CANDIDATE, repository_root=ROOT)
    active_manifest = json.loads(
        (ACTIVE_PROMPT_ROOT / "prompt_manifest.json").read_text(encoding="utf-8")
    )
    active_slot_ids = {slot["prompt_slot_id"] for slot in active_manifest["slots"]}

    assert bundle.candidate_id == "mcp-tool-use-research-2026-v1"
    assert len(bundle.source_hashes) == 21
    assert set(bundle.source_hashes) == active_slot_ids
    assert bundle.payload["status"] == "DRAFT"
    assert bundle.payload["activation_evidence"] == {
        "node_dev_pass": False,
        "node_holdout_pass": False,
        "safety_gate_pass": False,
        "manifest_approved": False,
    }


def test_materialization_is__deterministic_evaluation_loadable_and_product_inactive(
    tmp_path: Path,
) -> None:
    first = materialize_prompt_candidate(
        candidate_path=CANDIDATE,
        repository_root=ROOT,
        output_dir=tmp_path / "first",
    )
    second = materialize_prompt_candidate(
        candidate_path=CANDIDATE,
        repository_root=ROOT,
        output_dir=tmp_path / "second",
    )
    first_files = {
        path.relative_to(first.output_dir): path.read_bytes()
        for path in first.output_dir.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second.output_dir): path.read_bytes()
        for path in second.output_dir.rglob("*")
        if path.is_file()
    }
    manifest = json.loads(first.prompt_manifest_path.read_text(encoding="utf-8"))
    registry = PromptRegistry(first.prompt_manifest_path, first.input_contract_path)

    assert first_files == second_files
    assert first.prompt_manifest_hash == second.prompt_manifest_hash
    assert len(manifest["slots"]) == 21
    assert all(slot["activation_status"] == "DRAFT" for slot in manifest["slots"])
    assert all(slot["activation_evidence"] is None for slot in manifest["slots"])
    for slot in manifest["slots"]:
        registry.lookup_for_evaluation(slot["prompt_slot_id"])
        with pytest.raises(InactivePromptArtifactError):
            registry.lookup_for_product_release(slot["prompt_slot_id"])


def test_materializer_refuses__candidate_or_product_source__overwrite(tmp_path: Path) -> None:
    with pytest.raises(PromptCandidateError, match="cannot overwrite"):
        materialize_prompt_candidate(
            candidate_path=CANDIDATE,
            repository_root=ROOT,
            output_dir=ACTIVE_PROMPT_ROOT,
        )
    with pytest.raises(PromptCandidateError, match="cannot overwrite"):
        materialize_prompt_candidate(
            candidate_path=CANDIDATE,
            repository_root=ROOT,
            output_dir=CANDIDATE.parent / "generated",
        )


def test_candidate_hash_tampering_is_rejected(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    payload = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    payload["base_prompt_manifest"] = str(
        (ACTIVE_PROMPT_ROOT / "prompt_manifest.json").relative_to(ROOT)
    ).replace("\\", "/")
    payload["base_input_contract"] = str(
        (ACTIVE_PROMPT_ROOT / "prompt_runtime_input_contract_v1.json").relative_to(ROOT)
    ).replace("\\", "/")
    payload["candidate_bundle_hash"] = "0" * 64
    (candidate_dir / "candidate.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PromptCandidateError, match="source hash mismatch|bundle hash mismatch"):
        load_prompt_candidate(candidate_dir / "candidate.json", repository_root=ROOT)
