"""Persist one internally validated connector-bound ResourceRef."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports.models import ResourceRefRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class PersistResourceRefCommand:
    resource_ref: ResourceRefRecord


@dataclass(frozen=True, slots=True)
class PersistResourceRefResult:
    resource_ref: ResourceRefRecord


class PersistResourceRefHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, command: PersistResourceRefCommand) -> PersistResourceRefResult:
        with self._unit_of_work_factory() as unit_of_work:
            persisted = unit_of_work.resource_refs.upsert_bound_ref(command.resource_ref)
            unit_of_work.commit()
        return PersistResourceRefResult(persisted)
