"""Prompt registry loading for workflow nodes."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from google_work_agent.ports import PromptReference

DEFAULT_INPUT_SCHEMA_VERSION = "agent-node-input-v0.1"
DEFAULT_OUTPUT_SCHEMA_VERSION = "agent-node-output-v0.1"
RUNTIME_ACTIVE_STATUS = "RUNTIME_ACTIVE"


class InactivePromptArtifactError(RuntimeError):
    """Raised when a prompt slot exists but is not approved for product runtime."""


def default_prompt_manifest_path() -> Path:
    return Path(__file__).resolve().parents[4] / "prompts" / "agent" / "prompt-manifest-v0.8.2.json"


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
        slot_id = _required_string(slot, "slot_id")
        if slot_id != prompt_id:
            continue
        _require_runtime_active(slot, prompt_id)
        manifest_prompt_id = _optional_string(slot.get("prompt_id")) or slot_id
        subgraph_name = _optional_string(slot.get("subgraph_name"))
        node_name = _optional_string(slot.get("node_name"))
        if subgraph_name is None or node_name is None:
            subgraph_name, node_name = _split_prompt_id(manifest_prompt_id)
        return PromptReference(
            prompt_bundle_version=_required_string(payload, "prompt_bundle_version"),
            prompt_id=manifest_prompt_id,
            prompt_version=_optional_string(slot.get("prompt_version"))
            or _required_string(slot, "version"),
            content_hash=_required_string(slot, "content_hash"),
            agent_role=_required_string(slot, "agent_role"),
            subgraph_name=subgraph_name,
            node_name=node_name,
            node_state=_optional_string(slot.get("node_state")) or "BASELINE",
            purpose=_required_string(slot, "purpose"),
            input_schema_version=_optional_string(slot.get("input_schema_version"))
            or DEFAULT_INPUT_SCHEMA_VERSION,
            output_schema_version=_optional_string(slot.get("output_schema_version"))
            or DEFAULT_OUTPUT_SCHEMA_VERSION,
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
        _require_runtime_active(item, prompt_id)
        subgraph_name, node_name = _split_prompt_id(prompt_id)
        return PromptReference(
            prompt_bundle_version=_required_string(item, "prompt_bundle_version"),
            prompt_id=_required_string(item, "prompt_id"),
            prompt_version=_required_string(item, "prompt_version"),
            content_hash=_required_string(item, "content_hash"),
            agent_role=_required_string(item, "agent_role"),
            subgraph_name=_optional_string(item.get("subgraph_name")) or subgraph_name,
            node_name=_optional_string(item.get("node_name")) or node_name,
            node_state=_optional_string(item.get("node_state")) or "BASELINE",
            purpose=_required_string(item, "purpose"),
            input_schema_version=_optional_string(item.get("input_schema_version"))
            or DEFAULT_INPUT_SCHEMA_VERSION,
            output_schema_version=_optional_string(item.get("output_schema_version"))
            or DEFAULT_OUTPUT_SCHEMA_VERSION,
        )
    raise LookupError(f"{prompt_id} prompt is missing from manifest")


def _split_prompt_id(prompt_id: str) -> tuple[str, str]:
    if "." not in prompt_id:
        raise ValueError(f"prompt_id must contain subgraph and node name: {prompt_id}")
    subgraph_name, node_name = prompt_id.split(".", 1)
    return subgraph_name, node_name


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


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _require_runtime_active(item: dict[str, object], prompt_id: str) -> None:
    activation_status = _required_string(item, "activation_status")
    if activation_status != RUNTIME_ACTIVE_STATUS:
        raise InactivePromptArtifactError(
            f"{prompt_id} prompt exists but is not runtime-active: {activation_status}"
        )
