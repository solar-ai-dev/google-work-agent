"""Application admission checks required before connector-bound persistence."""

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import (
    SignedToolRegistry,
)
from google_work_agent.domain.resource_ref.model import ResourceRef
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


def upsert_registered_resource_ref(
    unit_of_work: UnitOfWork,
    resource_ref: ResourceRef,
    *,
    catalog: SignedToolRegistry | None = None,
) -> ResourceRef:
    authority = catalog or load_signed_tool_registry()
    if not any(entry.connector_id == resource_ref.connector_id for entry in authority.entries):
        raise LookupError(f"connector not registered: {resource_ref.connector_id}")
    return unit_of_work.resource_refs.upsert_bound_ref(resource_ref)
