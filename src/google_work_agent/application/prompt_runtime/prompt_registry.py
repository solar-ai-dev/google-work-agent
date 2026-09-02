"""Single Product Prompt registration, source, and activation authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT,
    REQUIRED_PROMPT_SLOT_IDS,
    PromptRuntimeInputContractV1,
)
from google_work_agent.application.prompt_runtime.load_prompt_input_contract import (
    default_prompt_input_contract_path,
    load_prompt_input_contract,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_MANIFEST_PATH = _PACKAGE_DIR / "prompt_manifest.json"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_ACTIVATION_STATUSES: Final = frozenset(
    {"DRAFT", "DEV_VALIDATED", "HOLDOUT_VALIDATED", "RUNTIME_ACTIVE", "RETIRED"}
)
PRODUCT_RELEASE: Final = "PRODUCT_RELEASE"
DEVELOPMENT_SMOKE: Final = "DEVELOPMENT_SMOKE"
EVALUATION: Final = "EVALUATION"
SIGNED_PROMPT_BUNDLE_RELATIVE_ROOT: Final = "manifests/prompt"
SIGNED_PROMPT_MANIFEST_RELATIVE_PATH: Final = (
    f"{SIGNED_PROMPT_BUNDLE_RELATIVE_ROOT}/prompt_manifest.json"
)
SIGNED_PROMPT_INPUT_CONTRACT_RELATIVE_PATH: Final = (
    f"{SIGNED_PROMPT_BUNDLE_RELATIVE_ROOT}/prompt_runtime_input_contract_v1.json"
)
PromptExecutionScope = Literal["PRODUCT_RELEASE", "DEVELOPMENT_SMOKE", "EVALUATION"]
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
    "activation_evidence",
    "agent_role",
    "subgraph_name",
    "node_name",
    "node_state",
    "purpose",
    "input_schema_version",
    "output_schema_version",
    "source",
}
_ACTIVATION_EVIDENCE_FIELDS: Final = {
    "schema_version",
    "target_model_id",
    "target_model_artifact_sha256",
    "prompt_source_sha256",
    "input_schema_version",
    "output_schema_version",
    "dataset",
    "grader",
    "grader_version",
    "node_dev_result",
    "node_holdout_result",
    "safety_gate_result",
    "manifest_approval",
    "executed_at_utc",
}
_EVIDENCE_ARTIFACT_FIELDS: Final = {"path", "sha256", "result"}
_RFC3339_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


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
class _ActivationEvidence:
    target_model_id: str
    target_model_artifact_sha256: str
    prompt_source_sha256: str
    input_schema_version: int
    output_schema_version: int
    dataset_path: Path
    grader_path: Path
    grader_version: str
    node_dev_result_path: Path
    node_holdout_result_path: Path
    safety_gate_result_path: Path
    manifest_approval_path: Path
    executed_at_utc: str


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
    activation_evidence: _ActivationEvidence | None
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
        return self._to_product_release_reference(entry)

    def lookup_by_id(self, prompt_slot_id: str) -> PromptReference:
        """Keep the historical lookup name fail-closed for signed Product use."""

        return self.lookup_for_product_release(prompt_slot_id)

    def lookup_for_product_release(self, prompt_slot_id: str) -> PromptReference:
        return self._to_product_release_reference(self._entry(prompt_slot_id))

    def lookup_for_development_smoke(self, prompt_slot_id: str) -> PromptReference:
        entry = self._entry(prompt_slot_id)
        if entry.activation_status == "RETIRED":
            raise InactivePromptArtifactError(
                f"{entry.prompt_slot_id} is retired and cannot start a development execution"
            )
        return self._to_reference(entry)

    def lookup_for_evaluation(self, prompt_slot_id: str) -> PromptReference:
        """Expose a DRAFT reference only to offline activation-gate evaluation."""

        return self._to_reference(self._entry(prompt_slot_id))

    def source_text(self, prompt_slot_id: str) -> str:
        entry = self._entry(prompt_slot_id)
        return _read_verified_source(entry)

    @property
    def product_release_ready(self) -> bool:
        return all(
            entry.activation_status == "RUNTIME_ACTIVE" and entry.activation_evidence_complete
            for entry in self._by_id.values()
        )

    def require_product_release_ready(self) -> None:
        for prompt_slot_id in sorted(self._by_id):
            self.lookup_for_product_release(prompt_slot_id)

    def product_release_bundle_files(self) -> tuple[Path, ...]:
        """Return the exact validated file closure for signed Release materialization."""

        self.require_product_release_ready()
        bundle_root = self._manifest_path.parent
        files = {self._manifest_path, self._input_contract_path}
        for entry in self._by_id.values():
            files.add(entry.source_path)
            evidence = entry.activation_evidence
            if evidence is None:  # guarded by require_product_release_ready()
                raise PromptRegistryError(
                    f"{entry.prompt_slot_id} product release evidence is unavailable"
                )
            files.update(
                {
                    evidence.dataset_path,
                    evidence.grader_path,
                    evidence.node_dev_result_path,
                    evidence.node_holdout_result_path,
                    evidence.safety_gate_result_path,
                    evidence.manifest_approval_path,
                }
            )
        try:
            return tuple(sorted(files, key=lambda path: path.relative_to(bundle_root).as_posix()))
        except ValueError as error:
            raise PromptRegistryError(
                "product release Prompt artifact must stay inside the Prompt bundle"
            ) from error

    def _entry(self, prompt_slot_id: str) -> _PromptManifestEntry:
        try:
            return self._by_id[prompt_slot_id]
        except KeyError as error:
            raise LookupError(f"Prompt slot is not registered: {prompt_slot_id}") from error

    def _to_product_release_reference(self, entry: _PromptManifestEntry) -> PromptReference:
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
            activation_evidence=_parse_activation_evidence(
                item.get("activation_evidence"),
                prefix=prefix,
                manifest_dir=self._manifest_path.parent,
                prompt_slot_id=prompt_slot_id,
                prompt_source_sha256=_require_sha256(
                    item.get("content_hash"), f"{prefix}.content_hash"
                ),
                input_schema_version=_require_int(
                    item.get("input_schema_version"), f"{prefix}.input_schema_version"
                ),
                output_schema_version=_require_int(
                    item.get("output_schema_version"), f"{prefix}.output_schema_version"
                ),
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


def load_prompt_reference(
    prompt_id: str,
    manifest_path: Path | None = None,
    *,
    execution_scope: PromptExecutionScope = PRODUCT_RELEASE,
) -> PromptReference:
    path = (manifest_path or _DEFAULT_MANIFEST_PATH).resolve()
    contract_path = (
        path.parent / "prompt_runtime_input_contract_v1.json"
        if path.parent != _PACKAGE_DIR
        else default_prompt_input_contract_path()
    )
    registry = PromptRegistry(path, contract_path.resolve())
    if execution_scope == PRODUCT_RELEASE:
        return registry.lookup_for_product_release(prompt_id)
    if execution_scope == DEVELOPMENT_SMOKE:
        return registry.lookup_for_development_smoke(prompt_id)
    if execution_scope == EVALUATION:
        return registry.lookup_for_evaluation(prompt_id)
    raise PromptRegistryError(f"unknown Prompt execution scope: {execution_scope}")


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
        raise PromptRegistryError(f"{entry.prompt_slot_id} HOLDOUT evidence requires DEV evidence")
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
    if status not in {"RUNTIME_ACTIVE", "RETIRED"} and entry.activation_evidence is not None:
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} cannot attach release evidence before activation"
        )
    if status == "DEV_VALIDATED" and evidence != (True, False, False, False):
        raise PromptRegistryError(f"{entry.prompt_slot_id} DEV_VALIDATED evidence is inconsistent")
    if status == "HOLDOUT_VALIDATED" and (
        not entry.node_dev_pass or not entry.node_holdout_pass or entry.manifest_approved
    ):
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} HOLDOUT_VALIDATED evidence is inconsistent"
        )
    if status in {"RUNTIME_ACTIVE", "RETIRED"} and not entry.activation_evidence_complete:
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} {status} requires complete release evidence"
        )
    if status in {"RUNTIME_ACTIVE", "RETIRED"} and entry.activation_evidence is None:
        raise PromptRegistryError(
            f"{entry.prompt_slot_id} {status} requires immutable activation evidence"
        )


def _parse_activation_evidence(
    value: object,
    *,
    prefix: str,
    manifest_dir: Path,
    prompt_slot_id: str,
    prompt_source_sha256: str,
    input_schema_version: int,
    output_schema_version: int,
) -> _ActivationEvidence | None:
    if value is None:
        return None
    payload = _require_object(value, f"{prefix}.activation_evidence")
    _require_exact_fields(payload, _ACTIVATION_EVIDENCE_FIELDS, f"{prefix}.activation_evidence")
    evidence_schema_version = _require_int(
        payload.get("schema_version"), f"{prefix}.activation_evidence.schema_version"
    )
    if evidence_schema_version != 1:
        raise PromptRegistryError(f"{prefix}.activation_evidence schema_version must be 1")
    if payload.get("prompt_source_sha256") != prompt_source_sha256:
        raise PromptRegistryError(f"{prefix}.activation_evidence Prompt source hash mismatch")
    if payload.get("input_schema_version") != input_schema_version:
        raise PromptRegistryError(f"{prefix}.activation_evidence input schema mismatch")
    if payload.get("output_schema_version") != output_schema_version:
        raise PromptRegistryError(f"{prefix}.activation_evidence output schema mismatch")
    executed_at_utc = _require_string(
        payload.get("executed_at_utc"), f"{prefix}.activation_evidence.executed_at_utc"
    )
    if _RFC3339_UTC.fullmatch(executed_at_utc) is None:
        raise PromptRegistryError(f"{prefix}.activation_evidence timestamp must be UTC RFC3339")

    artifacts = {
        name: _validate_evidence_artifact(
            payload.get(name),
            path=f"{prefix}.activation_evidence.{name}",
            manifest_dir=manifest_dir,
            prompt_slot_id=prompt_slot_id,
        )
        for name in (
            "dataset",
            "grader",
            "node_dev_result",
            "node_holdout_result",
            "safety_gate_result",
            "manifest_approval",
        )
    }
    return _ActivationEvidence(
        target_model_id=_require_string(
            payload.get("target_model_id"), f"{prefix}.activation_evidence.target_model_id"
        ),
        target_model_artifact_sha256=_require_sha256(
            payload.get("target_model_artifact_sha256"),
            f"{prefix}.activation_evidence.target_model_artifact_sha256",
        ),
        prompt_source_sha256=prompt_source_sha256,
        input_schema_version=input_schema_version,
        output_schema_version=output_schema_version,
        dataset_path=artifacts["dataset"],
        grader_path=artifacts["grader"],
        grader_version=_require_string(
            payload.get("grader_version"), f"{prefix}.activation_evidence.grader_version"
        ),
        node_dev_result_path=artifacts["node_dev_result"],
        node_holdout_result_path=artifacts["node_holdout_result"],
        safety_gate_result_path=artifacts["safety_gate_result"],
        manifest_approval_path=artifacts["manifest_approval"],
        executed_at_utc=executed_at_utc,
    )


def _validate_evidence_artifact(
    value: object,
    *,
    path: str,
    manifest_dir: Path,
    prompt_slot_id: str,
) -> Path:
    payload = _require_object(value, path)
    _require_exact_fields(payload, _EVIDENCE_ARTIFACT_FIELDS, path)
    if payload.get("result") != "PASS":
        raise PromptRegistryError(f"{path}.result must be PASS")
    relative_text = _require_string(payload.get("path"), f"{path}.path")
    relative_path = Path(relative_text)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise PromptRegistryError(f"{path}.path must stay inside the Prompt bundle")
    artifact_path = (manifest_dir / relative_path).resolve()
    try:
        artifact_path.relative_to(manifest_dir.resolve())
        content = artifact_path.read_bytes()
    except (OSError, ValueError) as error:
        raise PromptRegistryError(f"{path} artifact is unavailable") from error
    expected_sha256 = _require_sha256(payload.get("sha256"), f"{path}.sha256")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise PromptRegistryError(f"{path} artifact hash mismatch")
    if prompt_slot_id.encode() not in content:
        raise PromptRegistryError(f"{path} artifact is not bound to {prompt_slot_id}")
    return artifact_path


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


def _raise_set_mismatch(label: str, expected: frozenset[str], actual: frozenset[str]) -> None:
    raise PromptRegistryError(
        f"{label} slot set mismatch; missing={sorted(expected - actual)}, "
        f"extra={sorted(actual - expected)}"
    )


__all__ = [
    "DEVELOPMENT_SMOKE",
    "EVALUATION",
    "InactivePromptArtifactError",
    "PRODUCT_RELEASE",
    "SIGNED_PROMPT_BUNDLE_RELATIVE_ROOT",
    "SIGNED_PROMPT_INPUT_CONTRACT_RELATIVE_PATH",
    "SIGNED_PROMPT_MANIFEST_RELATIVE_PATH",
    "PromptExecutionScope",
    "PromptRegistry",
    "PromptRegistryError",
    "PromptSelectionKey",
    "default_prompt_manifest_path",
    "load_prompt_reference",
]
