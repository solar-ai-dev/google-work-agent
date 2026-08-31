"""Single Product Prompt registration, source, and activation authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT,
    REQUIRED_PROMPT_SLOT_IDS,
    PromptRuntimeInputContractV1,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    default_prompt_input_contract_path,
    load_prompt_input_contract,
)
from google_work_agent.ports.llm import PromptReference

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_MANIFEST_PATH = _PACKAGE_DIR / "prompt_manifest.json"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST_FILENAME_PATTERN = re.compile(r"^prompt-manifest-v(\d+)\.(\d+)\.(\d+)\.json$")
_ACTIVATION_STATUSES: Final = frozenset(
    {"DRAFT", "DEV_VALIDATED", "HOLDOUT_VALIDATED", "RUNTIME_ACTIVE", "RETIRED"}
)
_MANIFEST_ROOT_FIELDS: Final = {
    "schema_version",
    "prompt_bundle_version",
    "activation_policy",
    "slots",
}
_MANIFEST_SLOT_FIELDS: Final = {
    "prompt_slot_id",
    "prompt_id",
    "runtime_node_id",
    "prompt_version",
    "content_hash",
    "activation_status",
    "node_dev_pass",
    "node_holdout_pass",
    "safety_gate_pass",
    "manifest_approved",
    "agent_role",
    "subgraph_name",
    "node_name",
    "node_state",
    "purpose",
    "input_schema_version",
    "output_schema_version",
    "source",
}


class PromptRegistryError(ValueError):
    """Raised when Prompt runtime artifacts are structurally inconsistent."""


class InactivePromptArtifactError(RuntimeError):
    """Raised when an unvalidated Prompt is selected by Product runtime."""


@dataclass(frozen=True, slots=True)
class PromptSelectionKey:
    agent_role: str
    subgraph_name: str
    node_name: str
    node_state: str
    purpose: str
    input_schema_version: int
    output_schema_version: int


@dataclass(frozen=True, slots=True)
class _PromptManifestEntry:
    prompt_slot_id: str
    prompt_id: str
    runtime_node_id: str
    prompt_version: str
    content_hash: str
    activation_status: str
    node_dev_pass: bool
    node_holdout_pass: bool
    safety_gate_pass: bool
    manifest_approved: bool
    selection_key: PromptSelectionKey
    source_path: Path

    @property
    def activation_evidence_complete(self) -> bool:
        return all(
            (
                self.node_dev_pass,
                self.node_holdout_pass,
                self.safety_gate_pass,
                self.manifest_approved,
            )
        )


class PromptRegistry:
    """Validate and select the exact Canonical Product Prompt artifact set."""

    def __init__(
        self,
        manifest_path: Path | None = None,
        input_contract_path: Path | None = None,
    ) -> None:
        self._manifest_path = (manifest_path or _DEFAULT_MANIFEST_PATH).resolve()
        self._input_contract_path = (
            input_contract_path or default_prompt_input_contract_path()
        ).resolve()
        payload = _load_json_object(self._manifest_path, "prompt manifest")
        _require_exact_fields(payload, _MANIFEST_ROOT_FIELDS, "prompt manifest")
        if _require_int(payload.get("schema_version"), "schema_version") != 1:
            raise PromptRegistryError("prompt manifest schema_version must be 1")
        self._prompt_bundle_version = _require_string(
            payload.get("prompt_bundle_version"), "prompt_bundle_version"
        )
        _require_string(payload.get("activation_policy"), "activation_policy")
        raw_slots = payload.get("slots")
        if not isinstance(raw_slots, list):
            raise PromptRegistryError("prompt manifest slots must be an array")

        by_id: dict[str, _PromptManifestEntry] = {}
        by_key: dict[PromptSelectionKey, _PromptManifestEntry] = {}
        for index, raw_slot in enumerate(raw_slots):
            item = _require_object(raw_slot, f"slots[{index}]")
            _require_exact_fields(item, _MANIFEST_SLOT_FIELDS, f"slots[{index}]")
            entry = self._parse_entry(item, index)
            if entry.prompt_slot_id in by_id:
                raise PromptRegistryError(f"duplicate prompt manifest slot: {entry.prompt_slot_id}")
            if entry.selection_key in by_key:
                raise PromptRegistryError(f"duplicate Prompt selection key: {entry.selection_key}")
            by_id[entry.prompt_slot_id] = entry
            by_key[entry.selection_key] = entry

        slot_ids = frozenset(by_id)
        if slot_ids != REQUIRED_PROMPT_SLOT_IDS:
            _raise_set_mismatch("manifest", REQUIRED_PROMPT_SLOT_IDS, slot_ids)
        source_slot_ids = self._validate_sources(by_id)
        self._input_contract = load_prompt_input_contract(
            self._input_contract_path,
            manifest_slot_ids=slot_ids,
            source_slot_ids=source_slot_ids,
        )
        self._by_id = by_id
        self._by_key = by_key

    @property
    def slot_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    @property
    def input_contract(self) -> PromptRuntimeInputContractV1:
        return self._input_contract

    def lookup(self, selection_key: PromptSelectionKey) -> PromptReference:
        try:
            entry = self._by_key[selection_key]
        except KeyError as error:
            raise LookupError(f"Prompt selection key is not registered: {selection_key}") from error
        return self._to_runtime_reference(entry)

    def lookup_by_id(self, prompt_slot_id: str) -> PromptReference:
        return self._to_runtime_reference(self._entry(prompt_slot_id))

    def lookup_for_evaluation(self, prompt_slot_id: str) -> PromptReference:
        """Expose a DRAFT reference only to offline activation-gate evaluation."""

        return self._to_reference(self._entry(prompt_slot_id))

    def source_text(self, prompt_slot_id: str) -> str:
        entry = self._entry(prompt_slot_id)
        return _read_verified_source(entry)

    def _entry(self, prompt_slot_id: str) -> _PromptManifestEntry:
        try:
            return self._by_id[prompt_slot_id]
        except KeyError as error:
            raise LookupError(f"Prompt slot is not registered: {prompt_slot_id}") from error

    def _to_runtime_reference(self, entry: _PromptManifestEntry) -> PromptReference:
        if entry.activation_status != "RUNTIME_ACTIVE" or not entry.activation_evidence_complete:
            raise InactivePromptArtifactError(
                f"{entry.prompt_slot_id} exists but is not activation-gate complete: "
                f"{entry.activation_status}"
            )
        return self._to_reference(entry)

    def _to_reference(self, entry: _PromptManifestEntry) -> PromptReference:
        key = entry.selection_key
        return PromptReference(
            prompt_bundle_version=self._prompt_bundle_version,
            prompt_id=entry.prompt_id,
            prompt_version=entry.prompt_version,
            content_hash=entry.content_hash,
            agent_role=key.agent_role,
            subgraph_name=key.subgraph_name,
            node_name=key.node_name,
            node_state=key.node_state,
            purpose=key.purpose,
            input_schema_version=str(key.input_schema_version),
            output_schema_version=str(key.output_schema_version),
        )

    def _parse_entry(self, item: dict[str, object], index: int) -> _PromptManifestEntry:
        prefix = f"slots[{index}]"
        prompt_slot_id = _require_string(item.get("prompt_slot_id"), f"{prefix}.prompt_slot_id")
        prompt_id = _require_string(item.get("prompt_id"), f"{prefix}.prompt_id")
        if prompt_id != prompt_slot_id:
            raise PromptRegistryError(f"prompt_id must equal prompt_slot_id: {prompt_slot_id}")
        expected_runtime_node = REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT.get(prompt_slot_id)
        runtime_node_id = _require_string(item.get("runtime_node_id"), f"{prefix}.runtime_node_id")
        if expected_runtime_node is not None and runtime_node_id != expected_runtime_node:
            raise PromptRegistryError(
                f"runtime node mismatch for {prompt_slot_id}: {runtime_node_id}"
            )
        activation_status = _require_string(
            item.get("activation_status"), f"{prefix}.activation_status"
        )
        if activation_status not in _ACTIVATION_STATUSES:
            raise PromptRegistryError(
                f"unknown activation status for {prompt_slot_id}: {activation_status}"
            )
        source = _require_string(item.get("source"), f"{prefix}.source")
        expected_source = f"sources/{prompt_slot_id}.md"
        if source != expected_source:
            raise PromptRegistryError(
                f"source path mismatch for {prompt_slot_id}: {source!r} != {expected_source!r}"
            )
        entry = _PromptManifestEntry(
            prompt_slot_id=prompt_slot_id,
            prompt_id=prompt_id,
            runtime_node_id=runtime_node_id,
            prompt_version=_require_string(item.get("prompt_version"), f"{prefix}.prompt_version"),
            content_hash=_require_sha256(item.get("content_hash"), f"{prefix}.content_hash"),
            activation_status=activation_status,
            node_dev_pass=_require_bool(item.get("node_dev_pass"), f"{prefix}.node_dev_pass"),
            node_holdout_pass=_require_bool(
                item.get("node_holdout_pass"), f"{prefix}.node_holdout_pass"
            ),
            safety_gate_pass=_require_bool(
                item.get("safety_gate_pass"), f"{prefix}.safety_gate_pass"
            ),
            manifest_approved=_require_bool(
                item.get("manifest_approved"), f"{prefix}.manifest_approved"
            ),
            selection_key=PromptSelectionKey(
                agent_role=_require_string(item.get("agent_role"), f"{prefix}.agent_role"),
                subgraph_name=_require_string(item.get("subgraph_name"), f"{prefix}.subgraph_name"),
                node_name=_require_string(item.get("node_name"), f"{prefix}.node_name"),
                node_state=_require_string(item.get("node_state"), f"{prefix}.node_state"),
                purpose=_require_string(item.get("purpose"), f"{prefix}.purpose"),
                input_schema_version=_require_int(
                    item.get("input_schema_version"), f"{prefix}.input_schema_version"
                ),
                output_schema_version=_require_int(
                    item.get("output_schema_version"), f"{prefix}.output_schema_version"
                ),
            ),
            source_path=(self._manifest_path.parent / source).resolve(),
        )
        _validate_activation_lifecycle(entry)
        return entry

    def _validate_sources(self, entries: dict[str, _PromptManifestEntry]) -> frozenset[str]:
        source_dir = self._manifest_path.parent / "sources"
        actual_files = {path.name for path in source_dir.glob("*.md") if path.is_file()}
        expected_files = {f"{prompt_slot_id}.md" for prompt_slot_id in REQUIRED_PROMPT_SLOT_IDS}
        if actual_files != expected_files:
            raise PromptRegistryError(
                "Prompt source file set mismatch; "
                f"missing={sorted(expected_files - actual_files)}, "
                f"extra={sorted(actual_files - expected_files)}"
            )
        for entry in entries.values():
            _read_verified_source(entry)
        return frozenset(path.removesuffix(".md") for path in actual_files)


def default_prompt_manifest_path() -> Path:
    return _DEFAULT_MANIFEST_PATH


def _canonical_registry(manifest_path: Path, contract_path: Path) -> PromptRegistry:
    return PromptRegistry(manifest_path, contract_path)


def load_prompt_reference(prompt_id: str, manifest_path: Path | None = None) -> PromptReference:
    path = (manifest_path or _DEFAULT_MANIFEST_PATH).resolve()
    payload = _load_json_object(path, "prompt manifest")
    if _is_canonical_manifest(payload):
        contract_path = (
            path.parent / "prompt_runtime_input_contract_v1.json"
            if path.parent != _PACKAGE_DIR
            else default_prompt_input_contract_path()
        )
        try:
            return _canonical_registry(path, contract_path.resolve()).lookup_by_id(prompt_id)
        except LookupError as error:
            # Broad predecessor callers are migrated by the successor Agent slices.
            # Until then, an unrepresented caller slot makes Product runtime inactive;
            # it must not turn launcher construction into an uncaught error.
            raise InactivePromptArtifactError(
                f"{prompt_id} is not represented by the Canonical Prompt runtime"
            ) from error
    return _load_migration_prompt_reference(prompt_id, payload, enforce_runtime_active=True)


def load_prompt_reference_for_evaluation(prompt_id: str, manifest_path: Path) -> PromptReference:
    path = manifest_path.resolve()
    payload = _load_json_object(path, "prompt manifest")
    if _is_canonical_manifest(payload):
        contract_path = (
            path.parent / "prompt_runtime_input_contract_v1.json"
            if path.parent != _PACKAGE_DIR
            else default_prompt_input_contract_path()
        )
        return _canonical_registry(path, contract_path.resolve()).lookup_for_evaluation(prompt_id)
    return _load_migration_prompt_reference(prompt_id, payload, enforce_runtime_active=False)


def discover_canonical_prompt_manifest_path(prompts_agent_dir: Path) -> Path:
    """Migration-only discovery for the versioned predecessor Prompt packs."""

    if not prompts_agent_dir.is_dir():
        raise FileNotFoundError(f"prompt manifest directory is not available: {prompts_agent_dir}")
    candidates: list[tuple[tuple[int, int, int], Path]] = []
    for path in sorted(prompts_agent_dir.iterdir()):
        match = _MANIFEST_FILENAME_PATTERN.match(path.name) if path.is_file() else None
        if match is not None:
            version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            candidates.append((version, path))
    if not candidates:
        raise FileNotFoundError(
            f"no prompt-manifest-vX.Y.Z.json file found in: {prompts_agent_dir}"
        )
    highest = max(version for version, _ in candidates)
    matches = [path for version, path in candidates if version == highest]
    if len(matches) != 1:
        raise PromptRegistryError(f"ambiguous migration prompt manifest version: {highest}")
    return matches[0]


def _is_canonical_manifest(payload: dict[str, object]) -> bool:
    slots = payload.get("slots")
    return bool(
        isinstance(slots, list)
        and slots
        and isinstance(slots[0], dict)
        and "prompt_slot_id" in slots[0]
    )


def _load_migration_prompt_reference(
    prompt_id: str,
    payload: dict[str, object],
    *,
    enforce_runtime_active: bool,
) -> PromptReference:
    slot = _find_migration_slot(prompt_id, payload)
    if (
        enforce_runtime_active
        and _require_string(slot.get("activation_status"), "activation_status") != "RUNTIME_ACTIVE"
    ):
        raise InactivePromptArtifactError(
            f"{prompt_id} prompt exists but is not runtime-active: {slot.get('activation_status')}"
        )
    manifest_prompt_id = _optional_string(slot.get("prompt_id")) or prompt_id
    subgraph_name = _optional_string(slot.get("subgraph_name"))
    node_name = _optional_string(slot.get("node_name"))
    if subgraph_name is None or node_name is None:
        subgraph_name, node_name = _split_prompt_id(manifest_prompt_id)
    return PromptReference(
        prompt_bundle_version=_require_string(
            payload.get("prompt_bundle_version") or slot.get("prompt_bundle_version"),
            "prompt_bundle_version",
        ),
        prompt_id=manifest_prompt_id,
        prompt_version=_optional_string(slot.get("prompt_version"))
        or _require_string(slot.get("version"), "version"),
        content_hash=_require_string(slot.get("content_hash"), "content_hash"),
        agent_role=_require_string(slot.get("agent_role"), "agent_role"),
        subgraph_name=subgraph_name,
        node_name=node_name,
        node_state=_optional_string(slot.get("node_state")) or "BASELINE",
        purpose=_require_string(slot.get("purpose"), "purpose"),
        input_schema_version=_optional_string(slot.get("input_schema_version"))
        or "agent-node-input-v0.1",
        output_schema_version=_optional_string(slot.get("output_schema_version"))
        or "agent-node-output-v0.1",
    )


def _find_migration_slot(prompt_id: str, payload: dict[str, object]) -> dict[str, object]:
    raw_slots = payload.get("slots", payload.get("prompt_manifest"))
    if not isinstance(raw_slots, list):
        raise PromptRegistryError("migration prompt manifest must contain a slot list")
    for index, raw_slot in enumerate(raw_slots):
        slot = _require_object(raw_slot, f"slots[{index}]")
        if slot.get("slot_id") == prompt_id or slot.get("prompt_id") == prompt_id:
            return slot
    raise LookupError(f"{prompt_id} prompt is missing from manifest")


def _read_verified_source(entry: _PromptManifestEntry) -> str:
    try:
        raw = entry.source_path.read_bytes()
    except OSError as error:
        raise PromptRegistryError(
            f"Prompt source is missing for {entry.prompt_slot_id}: {entry.source_path}"
        ) from error
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != entry.content_hash:
        raise PromptRegistryError(
            f"Prompt source hash mismatch for {entry.prompt_slot_id}: "
            f"{actual_hash} != {entry.content_hash}"
        )
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise PromptRegistryError(
            f"Prompt source is not strict UTF-8: {entry.prompt_slot_id}"
        ) from error


def _validate_activation_lifecycle(entry: _PromptManifestEntry) -> None:
    evidence = (
        entry.node_dev_pass,
        entry.node_holdout_pass,
        entry.safety_gate_pass,
        entry.manifest_approved,
    )
    if entry.node_holdout_pass and not entry.node_dev_pass:
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} HOLDOUT evidence requires DEV evidence"
        )
    if entry.safety_gate_pass and not entry.node_holdout_pass:
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} Safety evidence requires HOLDOUT evidence"
        )
    if entry.manifest_approved and not entry.safety_gate_pass:
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} manifest approval requires Safety evidence"
        )

    status = entry.activation_status
    if status == "DRAFT" and any(evidence):
        raise PromptRegistryError(f"{entry.prompt_slot_id} DRAFT cannot claim release evidence")
    if status == "DEV_VALIDATED" and evidence != (True, False, False, False):
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} DEV_VALIDATED evidence is inconsistent"
        )
    if status == "HOLDOUT_VALIDATED" and (
        not entry.node_dev_pass
        or not entry.node_holdout_pass
        or entry.manifest_approved
    ):
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} HOLDOUT_VALIDATED evidence is inconsistent"
        )
    if status in {"RUNTIME_ACTIVE", "RETIRED"} and not entry.activation_evidence_complete:
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} {status} requires complete release evidence"
        )


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PromptRegistryError(f"{label} contains a duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8", errors="strict"),
            object_pairs_hook=unique_object,
        )
    except PromptRegistryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PromptRegistryError(f"{label} is unreadable: {path}") from error
    return _require_object(payload, label)


def _require_object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PromptRegistryError(f"{path} must be an object")
    return cast(dict[str, object], value)


def _require_exact_fields(value: dict[str, object], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        raise PromptRegistryError(
            f"{path} fields mismatch; missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _require_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptRegistryError(f"{path} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _require_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PromptRegistryError(f"{path} must be an integer")
    return value


def _require_bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise PromptRegistryError(f"{path} must be a boolean")
    return value


def _require_sha256(value: object, path: str) -> str:
    text = _require_string(value, path)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise PromptRegistryError(f"{path} must be a lowercase SHA-256")
    return text


def _split_prompt_id(prompt_id: str) -> tuple[str, str]:
    if "." not in prompt_id:
        raise PromptRegistryError(f"prompt_id must contain a role and operation: {prompt_id}")
    return cast(tuple[str, str], tuple(prompt_id.split(".", 1)))


def _raise_set_mismatch(label: str, expected: frozenset[str], actual: frozenset[str]) -> None:
    raise PromptRegistryError(
        f"{label} slot set mismatch; missing={sorted(expected - actual)}, "
        f"extra={sorted(actual - expected)}"
    )


__all__ = [
    "InactivePromptArtifactError",
    "PromptRegistry",
    "PromptRegistryError",
    "PromptSelectionKey",
    "default_prompt_manifest_path",
    "discover_canonical_prompt_manifest_path",
    "load_prompt_reference",
    "load_prompt_reference_for_evaluation",
]
