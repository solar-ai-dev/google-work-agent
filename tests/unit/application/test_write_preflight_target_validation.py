from __future__ import annotations

import pytest

from google_work_agent.application.write_preflight import validate_preflight_target
from google_work_agent.domain import PolicyViolationError
from google_work_agent.ports import (
    ResourceRefRecord,
    ResourceSnapshot,
    ResourceSource,
    ResourceType,
    StoredResourceType,
)


def _snapshot(
    *,
    resource_type: ResourceType = ResourceType.TASK,
    resource_id: str = "task-1",
    parent_id: str | None = "list-1",
    version: str = "v2",
) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id="fixture-1",
        resource_type=resource_type,
        resource_id=resource_id,
        parent_id=parent_id,
        related_resource_ids=(),
        version=version,
        recovery_fingerprint=None,
        payload={},
    )


def _ref(
    *,
    resource_id: str = "task-1",
    parent_id: str | None = "list-1",
    version_token: str | None = "v2",
) -> ResourceRefRecord:
    return ResourceRefRecord(
        id="ref-1",
        run_id="run-1",
        source=ResourceSource.TASKS,
        resource_type=StoredResourceType.TASK,
        resource_id=resource_id,
        parent_resource_id=parent_id,
        canonical_url=None,
        title=None,
        event_time_ms=None,
        version_token=version_token,
        metadata_json="{}",
        captured_at_ms=1,
    )


def test_update_target_requires_persisted_reference() -> None:
    with pytest.raises(PolicyViolationError, match="persisted target reference"):
        validate_preflight_target(
            snapshot=_snapshot(),
            target_ref=None,
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target_requires_persisted_version() -> None:
    with pytest.raises(PolicyViolationError, match="persisted target version"):
        validate_preflight_target(
            snapshot=_snapshot(),
            target_ref=_ref(version_token=None),
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target_rejects_version_drift() -> None:
    with pytest.raises(PolicyViolationError, match="version mismatch"):
        validate_preflight_target(
            snapshot=_snapshot(version="v3"),
            target_ref=_ref(version_token="v2"),
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target_rejects_identity_drift() -> None:
    with pytest.raises(PolicyViolationError, match="identity mismatch"):
        validate_preflight_target(
            snapshot=_snapshot(resource_id="task-2"),
            target_ref=_ref(resource_id="task-1"),
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target_rejects_parent_drift() -> None:
    with pytest.raises(PolicyViolationError, match="parent mismatch"):
        validate_preflight_target(
            snapshot=_snapshot(parent_id="list-2"),
            target_ref=_ref(parent_id="list-1"),
            expected_resource_type=ResourceType.TASK,
            expected_parent_id="list-1",
            require_target_ref=True,
            require_version_token=True,
        )


def test_update_target_accepts_same_identity_and_version() -> None:
    validate_preflight_target(
        snapshot=_snapshot(),
        target_ref=_ref(),
        expected_resource_type=ResourceType.TASK,
        expected_parent_id="list-1",
        require_target_ref=True,
        require_version_token=True,
    )
