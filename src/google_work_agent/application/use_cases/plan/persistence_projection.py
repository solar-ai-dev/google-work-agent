"""Plan-owner persistence projections shared by Application and workflow adapters."""

from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.ports.persistence.plan_repository import PlanRepository


def current_plan_tuple(repository: PlanRepository, run_id: str) -> tuple[PlanRecord, ...]:
    current = repository.get_current(run_id)
    return () if current is None else (current,)


def load_plan_record(repository: PlanRepository, plan_id: str) -> PlanRecord | None:
    bundle = repository.load_bundle(plan_id)
    return None if bundle is None else bundle.plan
