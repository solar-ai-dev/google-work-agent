"""Memory-only Run Retrieval Cache for read results and raw source snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from threading import Lock

from google_work_agent.ports import ResourceSnapshot


class ReadResultContinuationError(ValueError):
    """A read-result handle is invalid before any connector read occurs."""


@dataclass(frozen=True, slots=True)
class DetailTargetCacheEntry:
    run_id: str
    route_id: str
    resource_handle: str
    source: str
    resource_type: str
    resource_id: str
    parent_resource_id: str | None
    detail_tool_id: str


@dataclass(frozen=True, slots=True)
class ReadResultCacheEntry:
    run_id: str
    route_id: str
    query_hash: str
    next_page_token: str | None
    exhausted: bool
    result_handles: tuple[str, ...]
    result_count: int
    # Raw provider source belongs only to this run-memory cache.  It must
    # never be projected by bounded_summary() or copied into LangGraph state.
    snapshots: tuple[ResourceSnapshot, ...] = ()

    @property
    def page_state_hash(self) -> str | None:
        if self.next_page_token is None:
            return None
        return sha256(self.next_page_token.encode()).hexdigest()


class RunScopedReadResultCache:
    """Run-owned raw read boundary; only opaque handles leave this cache."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._by_run: dict[str, dict[str, ReadResultCacheEntry]] = {}
        self._detail_targets: dict[str, dict[str, DetailTargetCacheEntry]] = {}
        self._completed_details: set[tuple[str, str, str]] = set()

    def put(self, *, handle: str, entry: ReadResultCacheEntry) -> None:
        with self._lock:
            entries = self._by_run.setdefault(entry.run_id, {})
            existing = entries.get(handle)
            if existing is not None and existing != entry:
                raise ReadResultContinuationError("conflicting read result handle")
            entries[handle] = entry

    def attach_snapshots(
        self,
        *,
        run_id: str,
        handle: str,
        snapshots: tuple[ResourceSnapshot, ...],
    ) -> None:
        """Attach raw snapshots to an already-published read-result entry."""
        with self._lock:
            entries = self._by_run.get(run_id, {})
            entry = entries.get(handle)
            if entry is None:
                raise ReadResultContinuationError("unknown or cross-run read result handle")
            self._validate_snapshot_binding(entry=entry, snapshots=snapshots)
            _reject_binary_snapshot_payloads(snapshots)
            if entry.snapshots and entry.snapshots != snapshots:
                raise ReadResultContinuationError("conflicting raw snapshot publication")
            entries[handle] = replace(entry, snapshots=snapshots)

    def attach_snapshots_for_result(
        self,
        *,
        run_id: str,
        result_handles: tuple[str, ...],
        snapshots: tuple[ResourceSnapshot, ...],
    ) -> str:
        """Bind raw snapshots to the newest matching unpublished read entry.

        Legacy acquisition returns only resource handles, not its local
        read-result handle.  This compatibility bridge stays entirely inside
        the cache boundary and never creates a second handle authority.
        """
        with self._lock:
            entries = self._by_run.get(run_id, {})
            for handle, entry in reversed(tuple(entries.items())):
                if entry.result_handles != result_handles or entry.snapshots:
                    continue
                self._validate_snapshot_binding(entry=entry, snapshots=snapshots)
                _reject_binary_snapshot_payloads(snapshots)
                entries[handle] = replace(entry, snapshots=snapshots)
                return handle
        raise ReadResultContinuationError("matching run-scoped read result handle not found")

    def resolve_snapshots(self, *, run_id: str, handle: str) -> tuple[ResourceSnapshot, ...]:
        with self._lock:
            entry = self._by_run.get(run_id, {}).get(handle)
            if entry is None:
                raise ReadResultContinuationError("unknown or cross-run read result handle")
            if not entry.snapshots and entry.result_count:
                raise ReadResultContinuationError("raw snapshots were not materialized")
            return entry.snapshots

    def resolve_resource_snapshot(
        self, *, run_id: str, resource_handle: str
    ) -> ResourceSnapshot:
        """Resolve one resource only inside the owning Run, fail closed otherwise."""
        with self._lock:
            for entry in reversed(tuple(self._by_run.get(run_id, {}).values())):
                for snapshot in entry.snapshots:
                    if _resource_handle(snapshot) == resource_handle:
                        return snapshot
        raise ReadResultContinuationError("unknown or cross-run resource snapshot handle")

    def resolve_next_page(
        self,
        *,
        run_id: str,
        handle: str,
        route_id: str,
        query_hash: str,
    ) -> str:
        with self._lock:
            entry = self._by_run.get(run_id, {}).get(handle)
            if entry is None:
                raise ReadResultContinuationError("unknown or cross-run read result handle")
            if entry.route_id != route_id or entry.query_hash != query_hash:
                raise ReadResultContinuationError("read result continuation binding mismatch")
            if entry.exhausted or entry.next_page_token is None:
                raise ReadResultContinuationError("read result continuation is exhausted")
            return entry.next_page_token

    def discard_run(self, *, run_id: str) -> None:
        with self._lock:
            self._by_run.pop(run_id, None)
            self._detail_targets.pop(run_id, None)
            self._completed_details = {
                item for item in self._completed_details if item[0] != run_id
            }

    def register_detail_target(self, *, entry: DetailTargetCacheEntry) -> None:
        with self._lock:
            targets = self._detail_targets.setdefault(entry.run_id, {})
            existing = targets.get(entry.resource_handle)
            if existing is not None and existing != entry:
                raise ReadResultContinuationError("conflicting detail target binding")
            targets[entry.resource_handle] = entry

    def resolve_detail_target(
        self, *, run_id: str, route_id: str, resource_handle: str
    ) -> DetailTargetCacheEntry:
        with self._lock:
            entry = self._detail_targets.get(run_id, {}).get(resource_handle)
            if entry is None or entry.route_id != route_id:
                raise ReadResultContinuationError(
                    "unknown, cross-run, or wrong-route detail target"
                )
            if (run_id, route_id, resource_handle) in self._completed_details:
                raise ReadResultContinuationError("duplicate detail fetch")
            return entry

    def mark_detail_complete(self, *, run_id: str, route_id: str, resource_handle: str) -> None:
        with self._lock:
            self._completed_details.add((run_id, route_id, resource_handle))

    def latest_handle(self, *, run_id: str, route_id: str, query_hash: str) -> str | None:
        """Return an opaque local handle, never a provider continuation."""
        with self._lock:
            for handle, entry in reversed(tuple(self._by_run.get(run_id, {}).items())):
                if entry.route_id == route_id and entry.query_hash == query_hash:
                    return handle
        return None

    def bounded_summary(self, *, run_id: str, handle: str) -> dict[str, object]:
        with self._lock:
            entry = self._by_run.get(run_id, {}).get(handle)
            if entry is None:
                raise ReadResultContinuationError("unknown or cross-run read result handle")
            return {
                "has_next_page": entry.next_page_token is not None and not entry.exhausted,
                "exhausted": entry.exhausted,
                "result_count": entry.result_count,
                "result_handles": list(entry.result_handles),
                "page_state_hash": entry.page_state_hash,
            }

    @staticmethod
    def _validate_snapshot_binding(
        *, entry: ReadResultCacheEntry, snapshots: tuple[ResourceSnapshot, ...]
    ) -> None:
        handles = tuple(_resource_handle(snapshot) for snapshot in snapshots)
        if handles != entry.result_handles or len(snapshots) != entry.result_count:
            raise ReadResultContinuationError("raw snapshot/read-result binding mismatch")


def _resource_handle(snapshot: ResourceSnapshot) -> str:
    return f"{snapshot.resource_type.value}:{snapshot.resource_id}"


def _reject_binary_snapshot_payloads(snapshots: tuple[ResourceSnapshot, ...]) -> None:
    for snapshot in snapshots:
        if _contains_binary(snapshot.payload):
            raise ReadResultContinuationError(
                "attachment/binary bytes are outside the Run Retrieval Cache contract"
            )


def _contains_binary(value: object) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return True
    if isinstance(value, dict):
        return any(_contains_binary(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_binary(item) for item in value)
    return False
