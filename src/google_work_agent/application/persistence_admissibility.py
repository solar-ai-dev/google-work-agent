"""Application admission checks required before connector-bound persistence."""

from google_work_agent.domain.resource_ref.model import ResourceRef
from google_work_agent.ports.connector.migration_contracts.tool_registry import (
    ConnectorToolCatalog,
    build_p0_tool_catalog,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


def upsert_registered_resource_ref(
    unit_of_work: UnitOfWork,
    resource_ref: ResourceRef,
    *,
    catalog: ConnectorToolCatalog | None = None,
) -> ResourceRef:
    authority = catalog or build_p0_tool_catalog()
    authority.registry_for(resource_ref.connector_id)
    return unit_of_work.resource_refs.upsert_bound_ref(resource_ref)
