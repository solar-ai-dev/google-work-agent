from __future__ import annotations

import json
import shutil
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
            }
        )
        break
    else:
        raise ValueError(f"unknown Prompt slot: {prompt_slot_id}")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
