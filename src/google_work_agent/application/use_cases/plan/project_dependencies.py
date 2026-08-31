"""Project the persisted Plan dependency relation in one bounded pass."""

from google_work_agent.ports.persistence.plan_repository import PlanBundle


def project_dependency_ids(bundle: PlanBundle) -> dict[str, tuple[str, ...]]:
    projected: dict[str, list[str]] = {action.id: [] for action in bundle.actions}
    for dependency in bundle.dependencies:
        projected.setdefault(dependency.action_id, []).append(dependency.depends_on_action_id)
    return {
        action_id: tuple(sorted(dependency_ids)) for action_id, dependency_ids in projected.items()
    }
