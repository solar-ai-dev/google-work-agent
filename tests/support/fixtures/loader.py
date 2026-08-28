"""Deterministic product fixture loader."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)


class FixtureLoaderError(RuntimeError):
    """Raised when a fixture manifest or resource file is invalid."""


@dataclass(frozen=True, slots=True)
class ProductFixtureManifest:
    """Loaded fixture manifest metadata."""

    snapshot_id: str
    resource_paths: tuple[str, ...]
    fault_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProductFixtureSnapshot:
    """Immutable loaded fixture snapshot."""

    manifest: ProductFixtureManifest
    resources: tuple[ResourceSnapshot, ...]
    faults: tuple[dict[str, object], ...]


class ProductFixtureSnapshotLoader:
    """Load UTF-8 product fixtures from a manifest."""

    SUPPORTED_RESOURCE_TYPES = frozenset(resource_type.value for resource_type in ResourceType)

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def load_snapshot(self, manifest_path: str | Path) -> ProductFixtureSnapshot:
        """Load one fixture snapshot from a manifest."""

        manifest_file = self._resolve_under_root(Path(manifest_path))
        manifest_payload = self._load_json_file(manifest_file)
        snapshot_id = self._require_non_empty_string(manifest_payload, "snapshot_id")
        resources_payload = self._require_list(manifest_payload, "resources")
        faults_payload = manifest_payload.get("faults", [])
        if not isinstance(faults_payload, list):
            raise FixtureLoaderError("manifest faults must be a list")

        resource_paths = tuple(self._require_manifest_path(item) for item in resources_payload)
        fault_paths = tuple(self._require_manifest_path(item) for item in faults_payload)

        resources = tuple(
            self._load_resource(snapshot_id=snapshot_id, relative_path=path)
            for path in resource_paths
        )
        self._validate_unique_resource_ids(resources)
        self._validate_relations(resources)

        faults = tuple(self._load_fault(relative_path=path) for path in fault_paths)
        manifest = ProductFixtureManifest(
            snapshot_id=snapshot_id,
            resource_paths=tuple(sorted(resource_paths)),
            fault_paths=tuple(sorted(fault_paths)),
        )
        return ProductFixtureSnapshot(
            manifest=manifest,
            resources=tuple(
                sorted(resources, key=lambda item: (item.resource_type.value, item.resource_id))
            ),
            faults=tuple(deepcopy(fault) for fault in faults),
        )

    def _load_resource(self, *, snapshot_id: str, relative_path: str) -> ResourceSnapshot:
        payload = self._load_json_file(self._resolve_under_root(Path(relative_path)))
        resource_type_value = self._require_non_empty_string(payload, "resource_type")
        if resource_type_value not in self.SUPPORTED_RESOURCE_TYPES:
            raise FixtureLoaderError(f"unsupported resource_type: {resource_type_value}")

        related_ids_payload = payload.get("related_resource_ids", [])
        if not isinstance(related_ids_payload, list):
            raise FixtureLoaderError("related_resource_ids must be a list")

        record_payload = payload.get("payload")
        if not isinstance(record_payload, dict):
            raise FixtureLoaderError("resource payload must be an object")

        return ResourceSnapshot(
            fixture_snapshot_id=snapshot_id,
            resource_type=ResourceType(resource_type_value),
            resource_id=self._require_non_empty_string(payload, "resource_id"),
            parent_id=self._optional_string(payload, "parent_id"),
            related_resource_ids=tuple(sorted(self._require_string_list(related_ids_payload))),
            version=self._require_non_empty_string(payload, "version"),
            recovery_fingerprint=self._optional_string(payload, "recovery_fingerprint"),
            payload=deepcopy(record_payload),
        )

    def _load_fault(self, *, relative_path: str) -> dict[str, object]:
        payload = self._load_json_file(self._resolve_under_root(Path(relative_path)))
        if "fault_name" not in payload:
            raise FixtureLoaderError("fault payload must include fault_name")
        return deepcopy(payload)

    def _validate_unique_resource_ids(self, resources: tuple[ResourceSnapshot, ...]) -> None:
        seen: set[tuple[ResourceType, str]] = set()
        for resource in resources:
            key = (resource.resource_type, resource.resource_id)
            if key in seen:
                resource_key = f"{resource.resource_type.value}/{resource.resource_id}"
                raise FixtureLoaderError(f"duplicate resource id detected: {resource_key}")
            seen.add(key)

    def _validate_relations(self, resources: tuple[ResourceSnapshot, ...]) -> None:
        resource_ids = {resource.resource_id for resource in resources}
        for resource in resources:
            if resource.parent_id is not None and resource.parent_id not in resource_ids:
                raise FixtureLoaderError(f"missing parent relation: {resource.parent_id}")
            for related_id in resource.related_resource_ids:
                if related_id not in resource_ids:
                    raise FixtureLoaderError(f"missing related resource relation: {related_id}")

    def _load_json_file(self, path: Path) -> dict[str, object]:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise FixtureLoaderError(f"fixture must be UTF-8: {path}") from error
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise FixtureLoaderError(f"invalid JSON fixture: {path}") from error
        if not isinstance(payload, dict):
            raise FixtureLoaderError(f"fixture root must be an object: {path}")
        return payload

    def _resolve_under_root(self, relative_path: Path) -> Path:
        if relative_path.is_absolute():
            raise FixtureLoaderError("absolute fixture paths are not allowed")
        resolved = (self._root / relative_path).resolve()
        if self._root not in resolved.parents and resolved != self._root:
            raise FixtureLoaderError("path traversal outside fixture root is not allowed")
        return resolved

    def _require_manifest_path(self, item: object) -> str:
        if not isinstance(item, dict):
            raise FixtureLoaderError("manifest entry must be an object")
        value = item.get("path")
        if not isinstance(value, str) or not value.strip():
            raise FixtureLoaderError("manifest entry path must be a non-empty string")
        return value

    def _require_non_empty_string(self, payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise FixtureLoaderError(f"{key} must be a non-empty string")
        return value

    def _optional_string(self, payload: dict[str, object], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise FixtureLoaderError(f"{key} must be a non-empty string when present")
        return value

    def _require_list(self, payload: dict[str, object], key: str) -> list[object]:
        value = payload.get(key)
        if not isinstance(value, list):
            raise FixtureLoaderError(f"{key} must be a list")
        return value

    def _require_string_list(self, values: list[object]) -> list[str]:
        result: list[str] = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise FixtureLoaderError("related_resource_ids entries must be non-empty strings")
            result.append(value)
        return result
