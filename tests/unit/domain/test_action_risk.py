import pytest

from google_work_agent.application.write_plan_contracts import WriteActionDraft
from google_work_agent.domain import InvariantViolationError, canonicalize_action_risk


def _draft(action_id: str) -> WriteActionDraft:
    return WriteActionDraft(
        action_id=action_id,
        position=1,
        connector_id="google_workspace",
        tool_name="tasks_create_task",
        arguments={},
        expected={},
        evidence_ids=(),
    )


def test_write_action_draft_risk_defaults_are_not_shared() -> None:
    first = _draft("action-1")
    second = _draft("action-2")

    first.risk["test"] = True

    assert second.risk == {}


@pytest.mark.parametrize("risk", [[], "warning", {"score": float("nan")}])
def test_action_risk_accepts_only_finite_json_objects(risk: object) -> None:
    with pytest.raises(InvariantViolationError):
        canonicalize_action_risk(risk)
