from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path
from typing import cast

from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
)


def copy_prompt_runtime_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    source_dir = default_prompt_manifest_path().parent
    target_dir = tmp_path / "prompt_runtime"
    shutil.copytree(source_dir, target_dir)
    return target_dir / "prompt_manifest.json", target_dir / "prompt_runtime_input_contract_v1.json"


def activate_prompt_slot(manifest_path: Path, prompt_slot_id: str) -> None:
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slots = cast(list[dict[str, object]], manifest["slots"])
    for slot in slots:
        if slot["prompt_slot_id"] != prompt_slot_id:
            continue
        slot.update(
            {
                "activation_status": "RUNTIME_ACTIVE",
                "node_dev_pass": True,
                "node_holdout_pass": True,
                "safety_gate_pass": True,
                "manifest_approved": True,
                "activation_evidence": _activation_evidence(
                    manifest_path=manifest_path,
                    slot=slot,
                ),
            }
        )
        break
    else:
        raise ValueError(f"unknown Prompt slot: {prompt_slot_id}")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def deactivate_prompt_slot(manifest_path: Path, prompt_slot_id: str) -> None:
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slots = cast(list[dict[str, object]], manifest["slots"])
    for slot in slots:
        if slot["prompt_slot_id"] != prompt_slot_id:
            continue
        slot.update(
            {
                "activation_status": "DRAFT",
                "node_dev_pass": False,
                "node_holdout_pass": False,
                "safety_gate_pass": False,
                "manifest_approved": False,
                "activation_evidence": None,
            }
        )
        break
    else:
        raise ValueError(f"unknown Prompt slot: {prompt_slot_id}")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def activate_all_prompt_slots(manifest_path: Path) -> None:
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    slots = cast(list[dict[str, object]], manifest["slots"])
    for slot in slots:
        slot.update(
            {
                "activation_status": "RUNTIME_ACTIVE",
                "node_dev_pass": True,
                "node_holdout_pass": True,
                "safety_gate_pass": True,
                "manifest_approved": True,
                "activation_evidence": _activation_evidence(
                    manifest_path=manifest_path,
                    slot=slot,
                ),
            }
        )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _activation_evidence(
    *,
    manifest_path: Path,
    slot: dict[str, object],
) -> dict[str, object]:
    prompt_slot_id = str(slot["prompt_slot_id"])
    evidence_dir = manifest_path.parent / "activation-evidence" / prompt_slot_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, object]] = {}
    for artifact_name in (
        "dataset",
        "grader",
        "node_dev_result",
        "node_holdout_result",
        "safety_gate_result",
        "manifest_approval",
    ):
        artifact_path = evidence_dir / f"{artifact_name}.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "prompt_slot_id": prompt_slot_id,
                    "artifact_kind": artifact_name,
                    "passed": True,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        content = artifact_path.read_bytes()
        artifacts[artifact_name] = {
            "path": artifact_path.relative_to(manifest_path.parent).as_posix(),
            "sha256": sha256(content).hexdigest(),
            "result": "PASS",
        }
    return {
        "schema_version": 1,
        "target_model_id": "test-provider/test-model",
        "target_model_artifact_sha256": sha256(b"test-model-artifact").hexdigest(),
        "prompt_source_sha256": slot["content_hash"],
        "input_schema_version": slot["input_schema_version"],
        "output_schema_version": slot["output_schema_version"],
        "dataset": artifacts["dataset"],
        "grader": artifacts["grader"],
        "grader_version": "test-grader-v1",
        "node_dev_result": artifacts["node_dev_result"],
        "node_holdout_result": artifacts["node_holdout_result"],
        "safety_gate_result": artifacts["safety_gate_result"],
        "manifest_approval": artifacts["manifest_approval"],
        "executed_at_utc": "2026-09-03T00:00:00Z",
    }
