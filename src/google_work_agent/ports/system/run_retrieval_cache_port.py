"""Run-scoped retrieval continuation cache boundary."""

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1


@dataclass(frozen=True, slots=True)
class RunRetrievalCacheEntryV1:
    schema_version: Literal[1]
    read_result_handle: str
    run_id: str
    route_id: str
    query_identity_hash: str
    read_result: ConnectorReadResultV1
    continuation_exhausted: bool


@dataclass(frozen=True, slots=True)
class RunRetrievalCacheResolveResultV1:
    schema_version: Literal[1]
    status: Literal["FOUND", "MISSING", "CROSS_RUN", "BINDING_MISMATCH", "EXHAUSTED"]
    entry: RunRetrievalCacheEntryV1 | None


class RunRetrievalCachePort(Protocol):
    def put_read_result(self, entry: RunRetrievalCacheEntryV1) -> str: ...

    def resolve_read_result(
        self,
        read_result_handle: str,
        run_id: str,
        route_id: str,
        query_identity_hash: str,
    ) -> RunRetrievalCacheResolveResultV1: ...

    def discard_run(self, run_id: str) -> None: ...


__all__ = [
    "RunRetrievalCacheEntryV1",
    "RunRetrievalCachePort",
    "RunRetrievalCacheResolveResultV1",
]
