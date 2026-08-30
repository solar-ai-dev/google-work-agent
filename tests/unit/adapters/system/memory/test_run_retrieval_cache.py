from __future__ import annotations

import pytest

from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCacheEntryV1


def _entry(
    *,
    handle: str = "read-1",
    run_id: str = "run-1",
    route_id: str = "route-1",
    query_hash: str = "q" * 64,
    token: str | None = "opaque-provider-token",
    exhausted: bool = False,
) -> RunRetrievalCacheEntryV1:
    return RunRetrievalCacheEntryV1(
        schema_version=1,
        read_result_handle=handle,
        run_id=run_id,
        route_id=route_id,
        query_identity_hash=query_hash,
        read_result=ConnectorReadResultV1(
            schema_version=1,
            tool_id="gmail_search_threads",
            request_id="request-1",
            output={"items": []},
            next_page_token=token,
            total_count=0,
        ),
        continuation_exhausted=exhausted,
    )


def test_resolve_statuses_are_closed_and_do_not_disclose_cross_run_entries() -> None:
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(_entry())

    found = cache.resolve_read_result("read-1", "run-1", "route-1", "q" * 64)
    assert found.status == "FOUND"
    assert found.entry is not None
    assert found.entry.read_result.next_page_token == "opaque-provider-token"

    for arguments, expected in (
        (("missing", "run-1", "route-1", "q" * 64), "MISSING"),
        (("read-1", "run-2", "route-1", "q" * 64), "CROSS_RUN"),
        (("read-1", "run-1", "route-2", "q" * 64), "BINDING_MISMATCH"),
        (("read-1", "run-1", "route-1", "x" * 64), "BINDING_MISMATCH"),
    ):
        resolved = cache.resolve_read_result(*arguments)
        assert resolved.status == expected
        assert resolved.entry is None


def test_exhausted_entry_remains_a_valid_bound_result() -> None:
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(_entry(token=None, exhausted=True))

    resolved = cache.resolve_read_result("read-1", "run-1", "route-1", "q" * 64)

    assert resolved.status == "EXHAUSTED"
    assert resolved.entry is not None


def test_conflicting_handle_fails_closed_and_discard_is_run_scoped() -> None:
    cache = InMemoryRunRetrievalCache()
    cache.put_read_result(_entry())
    cache.put_read_result(_entry(handle="read-2", run_id="run-2"))

    with pytest.raises(ValueError, match="conflicting read result handle"):
        cache.put_read_result(_entry(route_id="route-conflict"))

    cache.discard_run("run-1")

    assert cache.resolve_read_result("read-1", "run-1", "route-1", "q" * 64).status == "MISSING"
    assert cache.resolve_read_result("read-2", "run-2", "route-1", "q" * 64).status == "FOUND"
