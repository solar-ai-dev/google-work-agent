"""Persist one internally validated connector-bound ResourceRef."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class PersistResourceRefCommand:
    resource_ref: ResourceRefRecord


@dataclass(frozen=True, slots=True)
class PersistResourceRefResult:
    resource_ref: ResourceRefRecord


class PersistResourceRefHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        tool_registry: SignedToolRegistry,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._tool_registry = tool_registry

    def __call__(self, command: PersistResourceRefCommand) -> PersistResourceRefResult:
        with self._unit_of_work_factory() as unit_of_work:
            result = self.apply_in_unit_of_work(unit_of_work, command)
            unit_of_work.commit()
        return result

    def apply_in_unit_of_work(
        self,
        unit_of_work: UnitOfWork,
        command: PersistResourceRefCommand,
    ) -> PersistResourceRefResult:
        return PersistResourceRefResult(
            persist_registered_resource_ref(
                unit_of_work,
                command.resource_ref,
                catalog=self._tool_registry,
            )
        )


def persist_registered_resource_ref(
    unit_of_work: UnitOfWork,
    resource_ref: ResourceRefRecord,
    *,
    catalog: SignedToolRegistry,
) -> ResourceRefRecord:
    """Shared same-UoW primitive owned by the exact persistence capability."""
    if not any(
        entry.connector_id == resource_ref.connector_id
        and entry.resource_type == resource_ref.resource_type
        for entry in catalog.entries
    ):
        raise LookupError(
            "connector/resource type is not registered: "
            f"{resource_ref.connector_id}/{resource_ref.resource_type}"
        )
    return unit_of_work.resource_refs.upsert_bound_ref(resource_ref)


__all__ = [
    "PersistResourceRefCommand",
    "PersistResourceRefHandler",
    "PersistResourceRefResult",
    "persist_registered_resource_ref",
]
