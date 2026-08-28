import pytest

from google_work_agent.application.orchestration.retrieval_read_cache import (
    DetailTargetCacheEntry,
    ReadResultCacheEntry,
    ReadResultContinuationError,
    RunScopedReadResultCache,
)


def test_next_page_requires_matching_run_route_query_and_live_continuation() -> None:
    cache = RunScopedReadResultCache()
    cache.put(
        handle="read-1",
        entry=ReadResultCacheEntry(
            run_id="run-1",
            route_id="route-1",
            query_hash="query-1",
            next_page_token="raw-token",
            exhausted=False,
            result_handles=("gmail_thread:1",),
            result_count=1,
        ),
    )

    assert (
        cache.resolve_next_page(
            run_id="run-1", handle="read-1", route_id="route-1", query_hash="query-1"
        )
        == "raw-token"
    )
    for run_id, route_id, query_hash in (
        ("other-run", "route-1", "query-1"),
        ("run-1", "other-route", "query-1"),
        ("run-1", "route-1", "other-query"),
    ):
        with pytest.raises(ReadResultContinuationError):
            cache.resolve_next_page(
                run_id=run_id, handle="read-1", route_id=route_id, query_hash=query_hash
            )


def test_exhausted_or_discarded_read_result_never_yields_raw_continuation() -> None:
    cache = RunScopedReadResultCache()
    cache.put(
        handle="read-1",
        entry=ReadResultCacheEntry("run-1", "route-1", "query-1", None, True, (), 0),
    )
    with pytest.raises(ReadResultContinuationError):
        cache.resolve_next_page(
            run_id="run-1", handle="read-1", route_id="route-1", query_hash="query-1"
        )


def test_detail_target_is_route_bound_and_only_completes_after_explicit_publication() -> None:
    cache = RunScopedReadResultCache()
    target = DetailTargetCacheEntry(
        run_id="run-1",
        route_id="route-1",
        resource_handle="gmail_thread:1",
        source="GMAIL",
        resource_type="GMAIL_THREAD",
        resource_id="thread-1",
        parent_resource_id=None,
        detail_tool_id="gmail_get_thread",
    )
    cache.register_detail_target(entry=target)

    assert (
        cache.resolve_detail_target(
            run_id="run-1", route_id="route-1", resource_handle="gmail_thread:1"
        )
        == target
    )
    with pytest.raises(ReadResultContinuationError):
        cache.resolve_detail_target(
            run_id="run-1", route_id="wrong-route", resource_handle="gmail_thread:1"
        )

    cache.mark_detail_complete(run_id="run-1", route_id="route-1", resource_handle="gmail_thread:1")
    with pytest.raises(ReadResultContinuationError, match="duplicate"):
        cache.resolve_detail_target(
            run_id="run-1", route_id="route-1", resource_handle="gmail_thread:1"
        )
    cache.discard_run(run_id="run-1")
    with pytest.raises(ReadResultContinuationError):
        cache.resolve_next_page(
            run_id="run-1", handle="read-1", route_id="route-1", query_hash="query-1"
        )
