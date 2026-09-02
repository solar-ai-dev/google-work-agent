"""Materialize one DRAFT prompt candidate into the Product PromptRegistry file layout."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def _load_object(path: Path) -> dict[str, Any]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(f"expected JSON object: {path}")
    return decoded


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(*, candidate_dir: Path, repository_root: Path, output_dir: Path) -> None:
    candidate_dir = candidate_dir.resolve()
    repository_root = repository_root.resolve()
    output_dir = output_dir.resolve()

    candidate = _load_object(candidate_dir / "candidate.json")
    if candidate.get("schema_version") != 1 or candidate.get("status") != "DRAFT":
        raise ValueError("candidate must be a schema-v1 DRAFT")
    if output_dir == candidate_dir or output_dir == (
        repository_root / "src/google_work_agent/application/prompt_runtime"
    ).resolve():
        raise ValueError("candidate materialization must not overwrite source or active prompts")

    base_manifest_path = repository_root / str(candidate["base_prompt_manifest"])
    base_contract_path = repository_root / str(candidate["base_input_contract"])
    base_manifest = _load_object(base_manifest_path)
    candidate_sources = candidate.get("sources")
    if not isinstance(candidate_sources, dict):
        raise ValueError("candidate sources must be an object")

    base_slots = base_manifest.get("slots")
    if not isinstance(base_slots, list):
        raise ValueError("base prompt manifest slots must be a list")
    base_slot_ids = {
        slot.get("prompt_slot_id")
        for slot in base_slots
        if isinstance(slot, dict) and isinstance(slot.get("prompt_slot_id"), str)
    }
    if base_slot_ids != set(candidate_sources):
        missing = sorted(base_slot_ids - set(candidate_sources))
        extra = sorted(set(candidate_sources) - base_slot_ids)
        raise ValueError(f"candidate slot set mismatch: missing={missing}, extra={extra}")

    output_sources = output_dir / "sources"
    output_sources.mkdir(parents=True, exist_ok=True)
    materialized_slots: list[dict[str, Any]] = []
    evidence = candidate.get("activation_evidence")
    if not isinstance(evidence, dict) or any(
        evidence.get(field) is not False
        for field in (
            "node_dev_pass",
            "node_holdout_pass",
            "safety_gate_pass",
            "manifest_approved",
        )
    ):
        raise ValueError("DRAFT candidate activation evidence must remain false")

    for raw_slot in base_slots:
        if not isinstance(raw_slot, dict):
            raise ValueError("base prompt slot must be an object")
        slot_id = raw_slot.get("prompt_slot_id")
        if not isinstance(slot_id, str):
            raise ValueError("base prompt slot id is invalid")
        candidate_entry = candidate_sources[slot_id]
        if not isinstance(candidate_entry, dict):
            raise ValueError(f"candidate source entry is invalid: {slot_id}")
        relative_source = candidate_entry.get("source")
        expected_hash = candidate_entry.get("content_hash")
        if not isinstance(relative_source, str) or not relative_source.startswith("sources/"):
            raise ValueError(f"candidate source path is invalid: {slot_id}")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise ValueError(f"candidate source hash is invalid: {slot_id}")
        source_path = (candidate_dir / relative_source).resolve()
        try:
            source_path.relative_to(candidate_dir)
        except ValueError as error:
            raise ValueError(f"candidate source escaped candidate directory: {slot_id}") from error
        if not source_path.is_file() or _sha256(source_path) != expected_hash:
            raise ValueError(f"candidate source hash mismatch: {slot_id}")
        destination = output_dir / relative_source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)

        materialized = dict(raw_slot)
        materialized.update(
            {
                "prompt_version": candidate["candidate_prompt_version"],
                "content_hash": expected_hash,
                "activation_status": "DRAFT",
                "node_dev_pass": False,
                "node_holdout_pass": False,
                "safety_gate_pass": False,
                "manifest_approved": False,
                "source": relative_source,
            }
        )
        materialized_slots.append(materialized)

    output_manifest = dict(base_manifest)
    output_manifest["prompt_bundle_version"] = candidate["candidate_id"]
    output_manifest["slots"] = materialized_slots
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "prompt_manifest.json").write_text(
        json.dumps(output_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copyfile(
        base_contract_path,
        output_dir / "prompt_runtime_input_contract_v1.json",
    )

    # Re-read the generated manifest and prove every recorded content hash.
    generated = _load_object(output_dir / "prompt_manifest.json")
    for slot in generated["slots"]:
        if _sha256(output_dir / slot["source"]) != slot["content_hash"]:
            raise RuntimeError(f"generated prompt hash mismatch: {slot['prompt_slot_id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path)
    args = parser.parse_args()

    candidate_dir = Path(__file__).resolve().parent
    repository_root = (
        args.repository_root.resolve()
        if args.repository_root is not None
        else candidate_dir.parents[2]
    )
    materialize(
        candidate_dir=candidate_dir,
        repository_root=repository_root,
        output_dir=args.output,
    )


if __name__ == "__main__":
    main()
