from __future__ import annotations

import pytest

from google_work_agent.application.orchestration.retrieval_read_cache import (
    ReadResultCacheEntry,
    ReadResultContinuationError,
    RunScopedReadResultCache,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)


def test_same_run_distinct_resource_snapshots_fail_closed() -> None:
    cache = RunScopedReadResultCache()
    snapshot_a = _snapshot("private-a")
    snapshot_b = _snapshot("private-b")

    for read_handle, snapshot in (("read-1", snapshot_a), ("read-2", snapshot_b)):
        cache.put(
            handle=read_handle,
            entry=ReadResultCacheEntry(
                run_id="run-a",
                route_id="route-task",
                query_hash=f"query-{read_handle}",
                next_page_token=None,
                exhausted=True,
                result_handles=("task:task-1",),
                result_count=1,
            ),
        )
        cache.attach_snapshots(
            run_id="run-a",
            handle=read_handle,
            snapshots=(snapshot,),
        )

    with pytest.raises(
        ReadResultContinuationError,
        match="ambiguous same-run resource snapshot handle",
    ):
        cache.resolve_resource_snapshot(
            run_id="run-a",
            resource_handle="task:task-1",
        )


def test_same_run_single_resource_snapshot_still_resolves() -> None:
    cache = RunScopedReadResultCache()
    snapshot = _snapshot("private")
    cache.put(
        handle="read-1",
        entry=ReadResultCacheEntry(
            run_id="run-a",
            route_id="route-task",
            query_hash="query-hash",
            next_page_token=None,
            exhausted=True,
            result_handles=("task:task-1",),
            result_count=1,
        ),
    )
    cache.attach_snapshots(
        run_id="run-a",
        handle="read-1",
        snapshots=(snapshot,),
    )

    assert (
        cache.resolve_resource_snapshot(
            run_id="run-a",
            resource_handle="task:task-1",
        )
        == snapshot
    )


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
