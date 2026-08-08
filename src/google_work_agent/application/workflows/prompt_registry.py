"""Prompt registry loading for workflow nodes."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from google_work_agent.ports import PromptReference

DEFAULT_INPUT_SCHEMA_VERSION = "agent-node-input-v0.1"
DEFAULT_OUTPUT_SCHEMA_VERSION = "agent-node-output-v0.1"


def default_prompt_manifest_path() -> Path:
    return Path(__file__).resolve().parents[4] / "prompts" / "agent" / "prompt-manifest-v0.7.json"


def load_prompt_reference(prompt_id: str, manifest_path: Path | None = None) -> PromptReference:
    path = manifest_path or default_prompt_manifest_path()
    payload = _load_manifest_payload(path)
    if "slots" in payload:
        return _load_slot_prompt_reference(prompt_id, payload)
    if "prompt_manifest" in payload:
        return _load_legacy_prompt_reference(prompt_id, payload)
    raise ValueError("prompt manifest must contain slots or prompt_manifest")


@lru_cache(maxsize=8)
def _load_manifest_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prompt manifest must be an object")
    return payload


def _load_slot_prompt_reference(prompt_id: str, payload: dict[str, object]) -> PromptReference:
    slots = payload.get("slots")
    if not isinstance(slots, list):
        raise ValueError("prompt manifest slots must be a list")
    for slot_value in slots:
        slot = _require_mapping(slot_value, "$.slots[]")
        if slot.get("slot_id") != prompt_id:
            continue
        subgraph_name, node_name = _split_prompt_id(prompt_id)
        return PromptReference(
            prompt_bundle_version=_required_string(payload, "prompt_bundle_version"),
            prompt_id=prompt_id,
            prompt_version=_required_string(slot, "version"),
            content_hash=_required_string(slot, "content_hash"),
            agent_role=_required_string(slot, "agent_role"),
            subgraph_name=subgraph_name,
            node_name=node_name,
            node_state="BASELINE",
            purpose=_required_string(slot, "purpose"),
            input_schema_version=_schema_version(slot.get("input_schema")),
            output_schema_version=_schema_version(slot.get("output_schema")),
        )
    raise LookupError(f"{prompt_id} prompt is missing from manifest")


def _load_legacy_prompt_reference(
    prompt_id: str,
    payload: dict[str, object],
) -> PromptReference:
    manifest = payload.get("prompt_manifest")
    if not isinstance(manifest, list):
        raise ValueError("prompt manifest must contain prompt_manifest list")
    for item_value in manifest:
        item = _require_mapping(item_value, "$.prompt_manifest[]")
        if item.get("prompt_id") != prompt_id:
            continue
        return PromptReference(
            prompt_bundle_version=_required_active_string(item, "prompt_bundle_version"),
            prompt_id=_required_active_string(item, "prompt_id"),
            prompt_version=_required_active_string(item, "prompt_version"),
            content_hash=_required_active_string(item, "content_hash"),
            agent_role=_required_active_string(item, "agent_role"),
            subgraph_name=_required_active_string(item, "subgraph_name"),
            node_name=_required_active_string(item, "node_name"),
            node_state=_required_active_string(item, "node_state"),
            purpose=_required_active_string(item, "purpose"),
            input_schema_version=_required_active_string(item, "input_schema_version"),
            output_schema_version=_required_active_string(item, "output_schema_version"),
        )
    raise LookupError(f"{prompt_id} prompt is missing from manifest")


def _split_prompt_id(prompt_id: str) -> tuple[str, str]:
    if "." not in prompt_id:
        raise ValueError(f"prompt_id must contain subgraph and node name: {prompt_id}")
    subgraph_name, node_name = prompt_id.split(".", 1)
    return subgraph_name, node_name


def _schema_version(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return DEFAULT_INPUT_SCHEMA_VERSION


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{path} keys must be strings")
        result[key] = item
    return result


def _required_string(item: dict[str, object], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"prompt manifest field is required: {field}")
    return value


def _required_active_string(item: dict[str, object], field: str) -> str:
    value = _required_string(item, field)
    if value == "TBD":
        raise ValueError(f"prompt manifest field is not runtime-active: {field}")
    return value
