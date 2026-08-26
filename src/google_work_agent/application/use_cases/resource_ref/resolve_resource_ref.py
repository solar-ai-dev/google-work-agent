"""Resolve one canonical ResourceRef through its repository boundary."""

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ResolveResourceRefQuery:
    resource_ref_id: str


@dataclass(frozen=True, slots=True)
class ResolveResourceRefResult:
    resource_ref: ResourceRefRecord | None


class ResolveResourceRefHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: ResolveResourceRefQuery) -> ResolveResourceRefResult:
        with self._unit_of_work_factory() as unit_of_work:
            return ResolveResourceRefResult(unit_of_work.resource_refs.get(query.resource_ref_id))
