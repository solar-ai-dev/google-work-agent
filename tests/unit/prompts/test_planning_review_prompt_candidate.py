from __future__ import annotations

import json
from pathlib import Path

from google_work_agent.application.workflows.prompt_registry import (
    InactivePromptArtifactError,
    load_prompt_reference,
    load_prompt_reference_for_evaluation,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_candidate_manifest_is_materialized_and_fail_closed() -> None:
    root = _repo_root()
    manifest = root / "prompts/agent/prompt-manifest-v0.9.2-candidate.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["prompt_bundle_version"] == "0.9.2-r8.6-sllm-decomposition"
    assert payload["prompt_semantic_bundle_version"] == "semantic-r8.6-v4"
    ids = {slot["slot_id"] for slot in payload["slots"]}
    assert "planning.draft_action_objective_per_output_route" in ids
    assert "review.inspect_goal_and_evidence" in ids
    assert "review.inspect" not in ids
    load_prompt_reference_for_evaluation("planning.compose_answer", manifest)
    try:
        load_prompt_reference("planning.compose_answer", manifest)
    except InactivePromptArtifactError:
        pass
    else:
        raise AssertionError("DRAFT candidate must fail closed")


def test_no_llm_dependency_slot_exists() -> None:
    payload = json.loads(
        (_repo_root() / "prompts/agent/prompt-manifest-v0.9.2-candidate.json").read_text(encoding="utf-8")
    )
    ids = {slot["slot_id"] for slot in payload["slots"]}
    assert "planning.compose_dependencies" not in ids
    assert "planning.generate_dependencies" not in ids
