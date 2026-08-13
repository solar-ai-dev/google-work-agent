"""Prompt registry loading for workflow nodes."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from google_work_agent.ports import PromptReference

DEFAULT_INPUT_SCHEMA_VERSION = "agent-node-input-v0.1"
DEFAULT_OUTPUT_SCHEMA_VERSION = "agent-node-output-v0.1"
RUNTIME_ACTIVE_STATUS = "RUNTIME_ACTIVE"

_MANIFEST_FILENAME_PATTERN = re.compile(r"^prompt-manifest-v(\d+)\.(\d+)\.(\d+)\.json$")
_REPO_ROOT = Path(__file__).resolve().parents[4]


class InactivePromptArtifactError(RuntimeError):
    """Raised when a prompt slot exists but is not approved for product runtime."""


def default_prompt_manifest_path() -> Path:
    return discover_canonical_prompt_manifest_path(
        Path(__file__).resolve().parents[4] / "prompts" / "agent"
    )


def discover_canonical_prompt_manifest_path(prompts_agent_dir: Path) -> Path:
    """Select the single current prompt manifest from ``prompts/agent``.

    Mirrors ``adapters.persistence.migration.discover_migrations``: the
    prompt bundle is a versioned, directory-discovered artifact (see
    ``prompts/agent/README.md``'s "Current: ..." pointer) rather than one
    filename hardcoded into the runtime, so this keeps tracking whichever
    ``prompt-manifest-vX.Y.Z.json`` the prompt pack currently ships without
    a code change every time the bundle version is bumped.
    """

    if not prompts_agent_dir.exists() or not prompts_agent_dir.is_dir():
        raise FileNotFoundError(f"prompt manifest directory is not available: {prompts_agent_dir}")

    candidates: list[tuple[tuple[int, int, int], Path]] = []
    for path in sorted(prompts_agent_dir.iterdir()):
        if not path.is_file():
            continue
        match = _MANIFEST_FILENAME_PATTERN.match(path.name)
        if match is None:
            continue
        version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        candidates.append((version, path))

    if not candidates:
        raise FileNotFoundError(
            f"no prompt-manifest-vX.Y.Z.json file found in: {prompts_agent_dir}"
        )

    highest_version = max(version for version, _path in candidates)
    matching_paths = [path for version, path in candidates if version == highest_version]
    if len(matching_paths) > 1:
        raise ValueError(
            f"ambiguous canonical prompt manifest, multiple files share version "
            f"{highest_version}: {sorted(path.name for path in matching_paths)}"
        )
    return matching_paths[0]


def load_prompt_reference(prompt_id: str, manifest_path: Path | None = None) -> PromptReference:
    return _load_prompt_reference(prompt_id, manifest_path, enforce_runtime_active=True)


def load_prompt_reference_for_evaluation(prompt_id: str, manifest_path: Path) -> PromptReference:
    """Load a prompt's reference for Gate evaluation, regardless of activation_status.

    Used only by the offline Node DEV/Node HOLDOUT/Safety Gate runner
    (``experiments/runner/r84_gate_runner.py``), which must read a slot's
    real assembled content before it has been promoted past ``DRAFT``.
    Production consumers must keep using ``load_prompt_reference``, which
    still enforces ``RUNTIME_ACTIVE`` via ``_require_runtime_active`` below
    and is completely unaffected by this function's existence.
    """

    return _load_prompt_reference(prompt_id, manifest_path, enforce_runtime_active=False)


def _load_prompt_reference(
    prompt_id: str,
    manifest_path: Path | None,
    *,
    enforce_runtime_active: bool,
) -> PromptReference:
    path = manifest_path or default_prompt_manifest_path()
    payload = _load_manifest_payload(path)
    if "slots" in payload:
        return _load_slot_prompt_reference(
            prompt_id, payload, enforce_runtime_active=enforce_runtime_active
        )
    if "prompt_manifest" in payload:
        return _load_legacy_prompt_reference(
            prompt_id, payload, enforce_runtime_active=enforce_runtime_active
        )
    raise ValueError("prompt manifest must contain slots or prompt_manifest")


@lru_cache(maxsize=8)
def _load_manifest_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prompt manifest must be an object")
    return payload


def _load_slot_prompt_reference(
    prompt_id: str,
    payload: dict[str, object],
    *,
    enforce_runtime_active: bool,
) -> PromptReference:
    slots = payload.get("slots")
    if not isinstance(slots, list):
        raise ValueError("prompt manifest slots must be a list")
    for slot_value in slots:
        slot = _require_mapping(slot_value, "$.slots[]")
        slot_id = _required_string(slot, "slot_id")
        if slot_id != prompt_id:
            continue
        if enforce_runtime_active:
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
    *,
    enforce_runtime_active: bool,
) -> PromptReference:
    manifest = payload.get("prompt_manifest")
    if not isinstance(manifest, list):
        raise ValueError("prompt manifest must contain prompt_manifest list")
    for item_value in manifest:
        item = _require_mapping(item_value, "$.prompt_manifest[]")
        if item.get("prompt_id") != prompt_id:
            continue
        if enforce_runtime_active:
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


def resolve_instruction_text(prompt_id: str, manifest_path: Path | None = None) -> str:
    """Resolve one slot's assembled prompt instruction text, content only.

    This must be called only at the LLM-call boundary (see
    ``OllamaStructuredLLMProvider.invoke_structured``), immediately before
    dispatch, and the caller must keep the result as a local variable --
    never attach it to ``PromptReference`` or any object that flows into
    ``AgentLocalStateV1``/trace_context/LangGraph checkpoints, since those
    are persisted (docs/00-CODE-AGENT-START-HERE.md section 4 forbids
    storing full Prompt/Completion text in Trace).

    Activation status is not re-checked here: by the time production code
    reaches this call, ``prompt_ref`` was already produced by
    ``load_prompt_reference``, which enforces ``RUNTIME_ACTIVE``. The offline
    Gate runner calls this directly against DRAFT slots by design.
    """

    path = manifest_path or default_prompt_manifest_path()
    payload = _load_manifest_payload(path)
    slot = _find_slot(prompt_id, payload)
    return _read_instruction_text(slot, prompt_id)


def _find_slot(prompt_id: str, payload: dict[str, object]) -> dict[str, object]:
    if "slots" in payload:
        slots = payload.get("slots")
        if not isinstance(slots, list):
            raise ValueError("prompt manifest slots must be a list")
        for slot_value in slots:
            slot = _require_mapping(slot_value, "$.slots[]")
            if (
                _optional_string(slot.get("prompt_id")) == prompt_id
                or slot.get("slot_id") == prompt_id
            ):
                return slot
        raise LookupError(f"{prompt_id} prompt is missing from manifest")
    if "prompt_manifest" in payload:
        manifest = payload.get("prompt_manifest")
        if not isinstance(manifest, list):
            raise ValueError("prompt manifest must contain prompt_manifest list")
        for item_value in manifest:
            item = _require_mapping(item_value, "$.prompt_manifest[]")
            if item.get("prompt_id") == prompt_id:
                return item
        raise LookupError(f"{prompt_id} prompt is missing from manifest")
    raise ValueError("prompt manifest must contain slots or prompt_manifest")


def _read_instruction_text(slot: dict[str, object], prompt_id: str) -> str:
    """Load and hash-verify one slot's assembled prompt instruction text.

    ``assembled_path``/``assembled_hash`` are the manifest's own documented
    fields for exactly this; nothing previously read them, so every real LLM
    call carried only prompt_ref metadata and structured input JSON, with no
    task instructions at all.
    """

    assembled_path = _optional_string(slot.get("assembled_path"))
    if assembled_path is None:
        return ""
    full_path = _REPO_ROOT / assembled_path
    try:
        raw = full_path.read_bytes()
    except OSError as error:
        raise ValueError(
            f"{prompt_id} assembled prompt file is missing: {assembled_path}"
        ) from error
    expected_hash = _optional_string(slot.get("assembled_hash")) or _optional_string(
        slot.get("content_hash")
    )
    if expected_hash is not None and hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError(f"{prompt_id} assembled prompt content hash mismatch")
    return raw.decode("utf-8")


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
