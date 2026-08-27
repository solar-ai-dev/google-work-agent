"""In-memory implementation of the canonical Run Retrieval Cache."""

from threading import Lock
from typing import Literal

from google_work_agent.ports.system.run_retrieval_cache_port import (
    RunRetrievalCacheEntryV1,
    RunRetrievalCacheResolveResultV1,
)


class InMemoryRunRetrievalCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: dict[str, RunRetrievalCacheEntryV1] = {}

    def put_read_result(self, entry: RunRetrievalCacheEntryV1) -> str:
        if not entry.read_result_handle:
            raise ValueError("read_result_handle is required")
        with self._lock:
            existing = self._entries.get(entry.read_result_handle)
            if existing is not None and existing != entry:
                raise ValueError("conflicting read result handle")
            self._entries[entry.read_result_handle] = entry
        return entry.read_result_handle

    def resolve_read_result(
        self,
        read_result_handle: str,
        run_id: str,
        route_id: str,
        query_identity_hash: str,
    ) -> RunRetrievalCacheResolveResultV1:
        with self._lock:
            entry = self._entries.get(read_result_handle)
        if entry is None:
            return _result("MISSING", None)
        if entry.run_id != run_id:
            return _result("CROSS_RUN", None)
        if entry.route_id != route_id or entry.query_identity_hash != query_identity_hash:
            return _result("BINDING_MISMATCH", None)
        if entry.continuation_exhausted:
            return _result("EXHAUSTED", entry)
        return _result("FOUND", entry)

    def discard_run(self, run_id: str) -> None:
        with self._lock:
            self._entries = {
                handle: entry for handle, entry in self._entries.items() if entry.run_id != run_id
            }


def _result(
    status: Literal["FOUND", "MISSING", "CROSS_RUN", "BINDING_MISMATCH", "EXHAUSTED"],
    entry: RunRetrievalCacheEntryV1 | None,
) -> RunRetrievalCacheResolveResultV1:
    return RunRetrievalCacheResolveResultV1(
        schema_version=1,
        status=status,
        entry=entry,
    )


__all__ = ["InMemoryRunRetrievalCache"]
