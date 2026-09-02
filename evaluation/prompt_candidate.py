"""Validate and materialize offline DRAFT Prompt candidate artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_CANDIDATE_FIELDS = {
    "schema_version",
    "candidate_id",
    "candidate_version",
    "status",
    "base_product_sha",
    "base_prompt_bundle_version",
    "base_prompt_manifest",
    "base_input_contract",
    "candidate_prompt_version",
    "prompt_slot_count",
    "activation_evidence",
    "sources",
    "research_basis",
    "research_basis_sha256",
    "candidate_bundle_hash",
}
_SOURCE_FIELDS = {"source", "content_hash"}
_ACTIVATION_FIELDS = {
    "node_dev_pass",
    "node_holdout_pass",
    "safety_gate_pass",
    "manifest_approved",
}


class PromptCandidateError(ValueError):
    """Raised when an offline Prompt candidate is malformed or stale."""


@dataclass(frozen=True, slots=True)
class PromptCandidateBundle:
    candidate_dir: Path
    candidate_id: str
    candidate_version: str
    base_product_sha: str
    base_prompt_bundle_version: str
    base_prompt_manifest: Path
    base_input_contract: Path
    candidate_prompt_version: str
    source_hashes: dict[str, str]
    candidate_bundle_hash: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class MaterializedPromptCandidate:
    output_dir: Path
    prompt_manifest_path: Path
    input_contract_path: Path
    prompt_manifest_hash: str
    candidate_bundle_hash: str


def load_prompt_candidate(candidate_path: Path, *, repository_root: Path) -> PromptCandidateBundle:
    """Load one exact DRAFT candidate without importing Product runtime code."""

    root = repository_root.resolve()
    manifest_path = (
        candidate_path / "candidate.json" if candidate_path.is_dir() else candidate_path
    ).resolve()
    candidate_dir = manifest_path.parent
    payload = _load_object(manifest_path)
    _require_exact_fields(payload, _CANDIDATE_FIELDS, "PromptCandidateV1")
    if payload.get("schema_version") != 1 or payload.get("status") != "DRAFT":
        raise PromptCandidateError("candidate must be a schema-v1 DRAFT")

    candidate_id = _required_string(payload, "candidate_id")
    candidate_version = _required_string(payload, "candidate_version")
    base_product_sha = _required_sha256_or_git_sha(payload, "base_product_sha", length=40)
    base_prompt_bundle_version = _required_string(payload, "base_prompt_bundle_version")
    candidate_prompt_version = _required_string(payload, "candidate_prompt_version")
    prompt_slot_count = _required_int(payload, "prompt_slot_count")
    if prompt_slot_count != 21:
        raise PromptCandidateError("prompt_slot_count must be exactly 21")

    activation = _required_object(payload, "activation_evidence")
    _require_exact_fields(activation, _ACTIVATION_FIELDS, "activation_evidence")
    if any(activation[field] is not False for field in sorted(_ACTIVATION_FIELDS)):
        raise PromptCandidateError("DRAFT activation evidence must remain false")

    base_prompt_manifest = _repository_path(
        root, _required_string(payload, "base_prompt_manifest"), "base_prompt_manifest"
    )
    base_input_contract = _repository_path(
        root, _required_string(payload, "base_input_contract"), "base_input_contract"
    )
    sources = _required_object(payload, "sources")
    if len(sources) != prompt_slot_count:
        raise PromptCandidateError("candidate source count must equal prompt_slot_count")
    source_hashes: dict[str, str] = {}
    for slot_id, value in sources.items():
        if not isinstance(value, dict):
            raise PromptCandidateError(f"candidate source entry must be an object: {slot_id}")
        entry = cast(dict[str, object], value)
        _require_exact_fields(entry, _SOURCE_FIELDS, f"sources.{slot_id}")
        relative = _required_string(entry, "source")
        if not relative.startswith("sources/"):
            raise PromptCandidateError(f"candidate source must live under sources/: {slot_id}")
        source_path = _child_path(candidate_dir, relative, f"sources.{slot_id}.source")
        expected_hash = _required_sha256_or_git_sha(entry, "content_hash", length=64)
        if not source_path.is_file() or file_sha256(source_path) != expected_hash:
            raise PromptCandidateError(f"candidate source hash mismatch: {slot_id}")
        source_hashes[slot_id] = expected_hash

    research_path = _child_path(
        candidate_dir, _required_string(payload, "research_basis"), "research_basis"
    )
    research_hash = _required_sha256_or_git_sha(payload, "research_basis_sha256", length=64)
    if not research_path.is_file() or file_sha256(research_path) != research_hash:
        raise PromptCandidateError("research basis hash mismatch")

    expected_bundle_hash = _required_sha256_or_git_sha(payload, "candidate_bundle_hash", length=64)
    actual_bundle_hash = calculate_candidate_bundle_hash(payload)
    if actual_bundle_hash != expected_bundle_hash:
        raise PromptCandidateError("candidate bundle hash mismatch")

    return PromptCandidateBundle(
        candidate_dir=candidate_dir,
        candidate_id=candidate_id,
        candidate_version=candidate_version,
        base_product_sha=base_product_sha,
        base_prompt_bundle_version=base_prompt_bundle_version,
        base_prompt_manifest=base_prompt_manifest,
        base_input_contract=base_input_contract,
        candidate_prompt_version=candidate_prompt_version,
        source_hashes=source_hashes,
        candidate_bundle_hash=actual_bundle_hash,
        payload=payload,
    )


def materialize_prompt_candidate(
    *, candidate_path: Path, repository_root: Path, output_dir: Path
) -> MaterializedPromptCandidate:
    """Overlay candidate text on current Product-owned slot metadata."""

    bundle = load_prompt_candidate(candidate_path, repository_root=repository_root)
    destination_root = output_dir.resolve()
    active_prompt_root = bundle.base_prompt_manifest.parent.resolve()
    if _is_within(destination_root, bundle.candidate_dir) or _is_within(
        destination_root, active_prompt_root
    ):
        raise PromptCandidateError("candidate materialization cannot overwrite source artifacts")
    if destination_root.exists() and any(destination_root.iterdir()):
        raise PromptCandidateError("materialization output must be absent or empty")

    base_manifest = _load_object(bundle.base_prompt_manifest)
    base_contract = _load_object(bundle.base_input_contract)
    if base_manifest.get("prompt_bundle_version") != bundle.base_prompt_bundle_version:
        raise PromptCandidateError("base Prompt bundle version mismatch")
    base_slots = _required_object_list(base_manifest, "slots")
    contract_entries = _required_object_list(base_contract, "entries")
    base_by_id = _unique_by_string_key(base_slots, "prompt_slot_id", "base Prompt slots")
    contract_by_id = _unique_by_string_key(
        contract_entries, "prompt_slot_id", "Prompt input contract"
    )
    if set(base_by_id) != set(bundle.source_hashes) or set(contract_by_id) != set(base_by_id):
        raise PromptCandidateError("candidate, manifest, and input contract slot sets differ")

    candidate_sources = _required_object(bundle.payload, "sources")
    materialized_slots: list[dict[str, object]] = []
    sources_root = destination_root / "sources"
    sources_root.mkdir(parents=True, exist_ok=True)
    for raw_slot in base_slots:
        slot_id = _required_string(raw_slot, "prompt_slot_id")
        contract = contract_by_id[slot_id]
        for field in ("runtime_node_id", "input_schema_version", "output_schema_version"):
            if raw_slot.get(field) != contract.get(field):
                raise PromptCandidateError(f"current Prompt contract mismatch: {slot_id}.{field}")
        candidate_entry = cast(dict[str, object], candidate_sources[slot_id])
        relative_source = _required_string(candidate_entry, "source")
        source_path = _child_path(bundle.candidate_dir, relative_source, slot_id)
        target = _child_path(destination_root, relative_source, slot_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)

        materialized = dict(raw_slot)
        materialized.update(
            {
                "prompt_version": bundle.candidate_prompt_version,
                "content_hash": bundle.source_hashes[slot_id],
                "activation_status": "DRAFT",
                "node_dev_pass": False,
                "node_holdout_pass": False,
                "safety_gate_pass": False,
                "manifest_approved": False,
                "activation_evidence": None,
                "source": relative_source,
            }
        )
        materialized_slots.append(materialized)

    output_manifest = dict(base_manifest)
    output_manifest["prompt_bundle_version"] = bundle.candidate_id
    output_manifest["slots"] = materialized_slots
    prompt_manifest_path = destination_root / "prompt_manifest.json"
    prompt_manifest_path.write_text(
        json.dumps(output_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    input_contract_path = destination_root / "prompt_runtime_input_contract_v1.json"
    shutil.copyfile(bundle.base_input_contract, input_contract_path)
    for slot in materialized_slots:
        slot_id = _required_string(slot, "prompt_slot_id")
        source_path = _child_path(destination_root, _required_string(slot, "source"), slot_id)
        if file_sha256(source_path) != slot["content_hash"]:
            raise PromptCandidateError(f"materialized source hash mismatch: {slot_id}")

    return MaterializedPromptCandidate(
        output_dir=destination_root,
        prompt_manifest_path=prompt_manifest_path,
        input_contract_path=input_contract_path,
        prompt_manifest_hash=file_sha256(prompt_manifest_path),
        candidate_bundle_hash=bundle.candidate_bundle_hash,
    )


def calculate_candidate_bundle_hash(payload: dict[str, object]) -> str:
    """Hash candidate metadata and source identities without self-reference."""

    material = {key: value for key, value in payload.items() if key != "candidate_bundle_hash"}
    encoded = json.dumps(
        material, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise PromptCandidateError(f"cannot hash artifact: {path}") from error


def _load_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PromptCandidateError(f"cannot load JSON object: {path}") from error
    if not isinstance(value, dict):
        raise PromptCandidateError(f"expected JSON object: {path}")
    return cast(dict[str, object], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PromptCandidateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_exact_fields(payload: dict[str, object], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise PromptCandidateError(
            f"{label} fields mismatch: missing={sorted(expected - set(payload))}, "
            f"extra={sorted(set(payload) - expected)}"
        )


def _required_object(payload: dict[str, object], field: str) -> dict[str, object]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise PromptCandidateError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _required_object_list(payload: dict[str, object], field: str) -> list[dict[str, object]]:
    value = payload.get(field)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PromptCandidateError(f"{field} must be an object array")
    return cast(list[dict[str, object]], value)


def _required_string(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise PromptCandidateError(f"{field} must be a non-empty string")
    return value


def _required_int(payload: dict[str, object], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PromptCandidateError(f"{field} must be an integer")
    return value


def _required_sha256_or_git_sha(payload: dict[str, object], field: str, *, length: int) -> str:
    value = _required_string(payload, field)
    if len(value) != length or any(character not in "0123456789abcdef" for character in value):
        raise PromptCandidateError(f"{field} must be a lowercase {length}-character hex digest")
    return value


def _repository_path(root: Path, relative: str, label: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise PromptCandidateError(f"{label} must be repository-relative")
    return _child_path(root, relative, label)


def _child_path(parent: Path, relative: str, label: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise PromptCandidateError(f"{label} must be relative")
    resolved = (parent / path).resolve()
    if not _is_within(resolved, parent.resolve()):
        raise PromptCandidateError(f"{label} escapes its owner directory")
    return resolved


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _unique_by_string_key(
    rows: list[dict[str, object]], field: str, label: str
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        key = _required_string(row, field)
        if key in result:
            raise PromptCandidateError(f"duplicate {label} identifier: {key}")
        result[key] = row
    return result


__all__ = [
    "MaterializedPromptCandidate",
    "PromptCandidateBundle",
    "PromptCandidateError",
    "calculate_candidate_bundle_hash",
    "file_sha256",
    "load_prompt_candidate",
    "materialize_prompt_candidate",
]
