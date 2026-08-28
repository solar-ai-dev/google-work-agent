from __future__ import annotations

from json import dumps

import pytest

from google_work_agent.application.orchestration.handoff_contracts import AcquisitionResultV1
from google_work_agent.application.orchestration.retrieval_data_boundary import (
    hydrate_acquisition_for_segmentation,
    sanitize_acquisition_result,
)
from google_work_agent.application.orchestration.retrieval_read_cache import (
    ReadResultCacheEntry,
    ReadResultContinuationError,
    RunScopedReadResultCache,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)


def test_raw_snapshot_is_cache_owned_and_checkpoint_projection_is_bounded() -> None:
    sentinel = "RAW_PROVIDER_PRIVATE_BODY_unit_7f"
    continuation = "RAW_PROVIDER_CONTINUATION_unit_91"
    snapshot = _snapshot(sentinel)
    cache = RunScopedReadResultCache()
    cache.put(
        handle="read-1",
        entry=ReadResultCacheEntry(
            run_id="run-a",
            route_id="route-task",
            query_hash="query-hash",
            next_page_token=continuation,
            exhausted=False,
            result_handles=("task:task-1",),
            result_count=1,
        ),
    )
    cache.attach_snapshots(run_id="run-a", handle="read-1", snapshots=(snapshot,))

    raw_result = _acquisition_result(snapshot)
    safe_result = sanitize_acquisition_result(raw_result)

    assert sentinel not in dumps(safe_result, sort_keys=True)
    assert continuation not in dumps(cache.bounded_summary(run_id="run-a", handle="read-1"))
    assert cache.resolve_snapshots(run_id="run-a", handle="read-1")[0].payload["notes"] == sentinel
    assert (
        cache.resolve_next_page(
            run_id="run-a",
            handle="read-1",
            route_id="route-task",
            query_hash="query-hash",
        )
        == continuation
    )

    hydrated = hydrate_acquisition_for_segmentation(
        run_id="run-a",
        result=safe_result,
        read_result_cache=cache,
    )
    resource = hydrated["source_summaries"][0]["resources"][0]
    assert resource["payload"]["notes"] == sentinel


def test_raw_snapshot_resolution_is_run_scoped_and_terminal_discarded() -> None:
    cache = RunScopedReadResultCache()
    snapshot = _snapshot("private")
    cache.put(
        handle="read-a",
        entry=ReadResultCacheEntry(
            run_id="run-a",
            route_id="route-task",
            query_hash="query-hash",
            next_page_token=None,
            exhausted=True,
            result_handles=("task:task-1",),
            result_count=1,
            snapshots=(snapshot,),
        ),
    )

    with pytest.raises(ReadResultContinuationError, match="cross-run"):
        cache.resolve_resource_snapshot(run_id="run-b", resource_handle="task:task-1")
    with pytest.raises(ReadResultContinuationError, match="cross-run"):
        cache.resolve_snapshots(run_id="run-b", handle="read-a")

    cache.discard_run(run_id="run-a")

    with pytest.raises(ReadResultContinuationError):
        cache.resolve_resource_snapshot(run_id="run-a", resource_handle="task:task-1")
    with pytest.raises(ReadResultContinuationError):
        cache.resolve_snapshots(run_id="run-a", handle="read-a")


def test_run_cache_rejects_attachment_or_binary_bytes() -> None:
    cache = RunScopedReadResultCache()
    snapshot = ResourceSnapshot(
        fixture_snapshot_id="fixture",
        resource_type=ResourceType.GMAIL_MESSAGE,
        resource_id="message-1",
        parent_id="thread-1",
        related_resource_ids=(),
        version="v1",
        recovery_fingerprint=None,
        payload={"body": "safe text", "attachment_bytes": b"raw-binary"},
    )
    cache.put(
        handle="read-binary",
        entry=ReadResultCacheEntry(
            run_id="run-a",
            route_id="route-mail",
            query_hash="query-hash",
            next_page_token=None,
            exhausted=True,
            result_handles=("gmail_message:message-1",),
            result_count=1,
        ),
    )

    with pytest.raises(ReadResultContinuationError, match="binary bytes"):
        cache.attach_snapshots(run_id="run-a", handle="read-binary", snapshots=(snapshot,))


def test_bounded_projection_drops_raw_body_notes_binary_token_and_provider_blob() -> None:
    snapshot = ResourceSnapshot(
        fixture_snapshot_id="fixture",
        resource_type=ResourceType.TASK,
        resource_id="task-1",
        parent_id="list-1",
        related_resource_ids=(),
        version="v1",
        recovery_fingerprint=None,
        payload={
            "title": "Follow up",
            "status": "needsAction",
            "due": "2026-08-22",
            "notes": "RAW_NOTES",
            "body": "RAW_BODY",
            "attachment_bytes": b"RAW_BYTES",
            "page_token": "RAW_TOKEN",
            "provider_response": {"secret": "RAW_PROVIDER"},
        },
    )

    safe = sanitize_acquisition_result(_acquisition_result(snapshot))
    resource = safe["source_summaries"][0]["resources"][0]

    assert resource["payload"] == {
        "title": "Follow up",
        "status": "needsAction",
        "due": "2026-08-22",
    }
    serialized = repr(safe)
    for forbidden in ("RAW_NOTES", "RAW_BODY", "RAW_BYTES", "RAW_TOKEN", "RAW_PROVIDER"):
        assert forbidden not in serialized


def _snapshot(notes: str) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id="fixture",
        resource_type=ResourceType.TASK,
        resource_id="task-1",
        parent_id="list-1",
        related_resource_ids=(),
        version="v1",
        recovery_fingerprint=None,
        payload={
            "title": "Follow up",
            "status": "needsAction",
            "due": "2026-08-22",
            "notes": notes,
        },
    )


def _acquisition_result(snapshot: ResourceSnapshot) -> AcquisitionResultV1:
    resource_handle = f"{snapshot.resource_type.value}:{snapshot.resource_id}"
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "resource_handles": [resource_handle],
        "source_summaries": [
            {
                "schema_version": 1,
                "source": "TASKS",
                "status": "COMPLETE",
                "required": True,
                "reason_codes": ["TEST"],
                "resource_count": 1,
                "resource_handles": [resource_handle],
                "resources": [
                    {
                        "resource_handle": resource_handle,
                        "resource_type": snapshot.resource_type.value,
                        "resource_id": snapshot.resource_id,
                        "parent_id": snapshot.parent_id,
                        "version": snapshot.version,
                        "related_resource_ids": [],
                        "payload": dict(snapshot.payload),
                    }
                ],
            }
        ],
        "missing_slots": [],
        "remaining_budget": {"sources": 1, "pages": 1, "candidates": 1, "details": 1},
    }
