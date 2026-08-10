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
