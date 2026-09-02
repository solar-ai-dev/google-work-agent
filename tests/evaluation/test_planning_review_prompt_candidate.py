from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_ROOT = ROOT / "evaluation/prompt_candidates/planning-review-sllm-decomposition-v0.9.2"
MANIFEST = CANDIDATE_ROOT / "prompt-manifest-v0.9.2-candidate.json"
CONTRACT = CANDIDATE_ROOT / "contracts/prompt-runtime-input-contract-v3.json"


def test_planning_review__prompt_candidate__is_fail_closed() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["activation_status"] != "RUNTIME_ACTIVE"
    assert manifest["discovery_status"] == "CANDIDATE_NOT_RUNTIME_SELECTED"


def test_review_recheck__identity_is__coherent_and_unique() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    slot_ids = {slot["slot_id"] for slot in manifest["slots"]}
    assert "review.recheck_affected_dimensions" in slot_ids
    assert "review.recheck_affected_findings" not in slot_ids
    assert "review.recheck_affected_dimensions" in contract["slots"]
    assert "review.recheck_affected_findings" not in contract["slots"]
    slot = next(
        slot
        for slot in manifest["slots"]
        if slot["slot_id"] == "review.recheck_affected_dimensions"
    )
    assert slot["prompt_id"] == "review.recheck_affected_dimensions"
    assert slot["node_name"] == "recheck_affected_dimensions"
    assert slot["assembled_path"].endswith("review.recheck_affected_dimensions.md")


def test_planning_has__no_dependency__prompt_slot() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    slot_ids = {slot["slot_id"] for slot in manifest["slots"]}
    assert "planning.compose_dependencies" not in slot_ids
    assert "planning.generate_dependencies" not in slot_ids
    assert "planning.build_dependencies" not in slot_ids


def test_migrated_candidate__repository_paths_resolve_under__evaluation_owner() -> None:
    manifests = [
        json.loads((CANDIDATE_ROOT / name).read_text(encoding="utf-8"))
        for name in ("prompt-manifest-v0.9.1.json", "prompt-manifest-v0.9.2-candidate.json")
    ]
    referenced = {
        manifests[0]["runtime_input_contract"],
        manifests[1]["base_runtime_manifest"],
        manifests[1]["runtime_input_contract"],
    }
    for manifest in manifests:
        for slot in manifest["slots"]:
            referenced.update(slot["files"])
            referenced.add(slot["assembled_path"])

    assert all(path.startswith("evaluation/prompt_candidates/") for path in referenced)
    assert all((ROOT / path).is_file() for path in referenced)
