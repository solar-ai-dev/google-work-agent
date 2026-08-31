from google_work_agent.application.use_cases.plan.project_dependencies import (
    project_dependency_ids,
)
from google_work_agent.domain.action.model import ActionDependency
from google_work_agent.ports.persistence.plan_repository import PlanBundle


def test_projects_dependencies_in_one_pass() -> None:
    bundle = object.__new__(PlanBundle)
    object.__setattr__(bundle, "plan", object())
    object.__setattr__(bundle, "actions", ())
    object.__setattr__(bundle, "dependencies", (ActionDependency("b", "a"),))
    object.__setattr__(bundle, "evidence", ())
    object.__setattr__(bundle, "action_evidence", ())

    assert project_dependency_ids(bundle) == {"b": ("a",)}
