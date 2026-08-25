"""ResourceRef persistence boundary."""

from typing import Protocol

from google_work_agent.ports.models import ResourceRefRecord


class ResourceRefRepository(Protocol):
    def upsert_bound_ref(self, record: ResourceRefRecord) -> ResourceRefRecord: ...

    def get(self, resource_ref_id: str) -> ResourceRefRecord | None: ...

    def list_for_run_bounded(self, run_id: str, *, limit: int) -> tuple[ResourceRefRecord, ...]: ...
