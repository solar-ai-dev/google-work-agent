from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from google_work_agent.application.workflows.prompt_registry import (
    discover_canonical_prompt_manifest_path,
)


def canonical_prompt_manifest_path() -> Path:
    return discover_canonical_prompt_manifest_path(
        Path(__file__).resolve().parents[2] / "prompts" / "agent"
    )


def write_runtime_active_manifest(
    tmp_path: Path,
    *,
    prompt_ids: Iterable[str],
) -> Path:
    manifest = json.loads(canonical_prompt_manifest_path().read_text(encoding="utf-8"))
    requested = set(prompt_ids)
    activated: set[str] = set()
    slots = manifest.get("slots")
    if not isinstance(slots, list):
        raise ValueError("canonical prompt manifest must contain slots")
    for slot in slots:
        if not isinstance(slot, dict):
            raise ValueError("canonical prompt slot must be an object")
        slot_id = slot.get("slot_id")
        if slot_id in requested:
            slot["activation_status"] = "RUNTIME_ACTIVE"
            activated.add(str(slot_id))
    missing = sorted(requested - activated)
    if missing:
        raise ValueError(f"prompt slots not found in canonical manifest: {missing}")
    path = tmp_path / "prompt-manifest-runtime-active.json"
    path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return path


def write_manifest_with_overrides(
    tmp_path: Path,
    *,
    active_prompt_ids: Iterable[str] = (),
    draft_prompt_ids: Iterable[str] = (),
) -> Path:
    """Force distinct slot groups to RUNTIME_ACTIVE and DRAFT in one fixture.

    Combines what ``write_runtime_active_manifest``/``write_draft_manifest``
    do separately, for tests that need one group active and a different
    group deterministically DRAFT in the same manifest (e.g. proving a
    graph_profile's construction ignores another profile's prompts).
    """
    manifest = json.loads(canonical_prompt_manifest_path().read_text(encoding="utf-8"))
    active = set(active_prompt_ids)
    draft = set(draft_prompt_ids)
    overlap = active & draft
    if overlap:
        raise ValueError(f"prompt slots requested as both active and draft: {sorted(overlap)}")
    seen_active: set[str] = set()
    seen_draft: set[str] = set()
    slots = manifest.get("slots")
    if not isinstance(slots, list):
        raise ValueError("canonical prompt manifest must contain slots")
    for slot in slots:
        if not isinstance(slot, dict):
            raise ValueError("canonical prompt slot must be an object")
        slot_id = slot.get("slot_id")
        if slot_id in active:
            slot["activation_status"] = "RUNTIME_ACTIVE"
            seen_active.add(str(slot_id))
        elif slot_id in draft:
            slot["activation_status"] = "DRAFT"
            seen_draft.add(str(slot_id))
    missing = sorted((active - seen_active) | (draft - seen_draft))
    if missing:
        raise ValueError(f"prompt slots not found in canonical manifest: {missing}")
    path = tmp_path / "prompt-manifest-overrides.json"
    path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return path


def write_draft_manifest(
    tmp_path: Path,
    *,
    prompt_ids: Iterable[str],
) -> Path:
    """Force the given slots to DRAFT in an isolated manifest copy.

    Tests asserting "an inactive prompt is rejected" must not depend on
    which slots happen to be DRAFT in the real canonical manifest right
    now -- that status legitimately changes over time as R8.4 Gates
    promote slots for real (see ``experiments/runner/r84_gate_runner.py``).
    Forcing DRAFT here keeps the rejection behavior under test
    deterministic regardless of the canonical manifest's current state.
    """
    manifest = json.loads(canonical_prompt_manifest_path().read_text(encoding="utf-8"))
    requested = set(prompt_ids)
    drafted: set[str] = set()
    slots = manifest.get("slots")
    if not isinstance(slots, list):
        raise ValueError("canonical prompt manifest must contain slots")
    for slot in slots:
        if not isinstance(slot, dict):
            raise ValueError("canonical prompt slot must be an object")
        slot_id = slot.get("slot_id")
        if slot_id in requested:
            slot["activation_status"] = "DRAFT"
            drafted.add(str(slot_id))
    missing = sorted(requested - drafted)
    if missing:
        raise ValueError(f"prompt slots not found in canonical manifest: {missing}")
    path = tmp_path / "prompt-manifest-draft.json"
    path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return path
