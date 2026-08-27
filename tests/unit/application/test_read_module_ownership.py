"""Compatibility checks for the legacy READ application facade."""

import google_work_agent.application.read_only as read_only
from google_work_agent.application.read_execution import ExecuteReadActionService
from google_work_agent.application.read_plan import (
    SaveReadOnlyPlanService,
)
from google_work_agent.application.use_cases.action.claim_read_action import ClaimReadActionHandler
from google_work_agent.application.use_cases.action.complete_read_action import (
    CompleteReadActionHandler,
)
from google_work_agent.application.use_cases.action.fail_read_action import FailReadActionHandler
from google_work_agent.application.use_cases.action.finalize_read_action import (
    FinalizeReadActionHandler,
)
from google_work_agent.application.use_cases.plan.publish_read_only_plan import (
    PublishReadOnlyPlanHandler,
)


def test_read_only_facade_preserves_service_identities() -> None:
    assert read_only.SaveReadOnlyPlanService is SaveReadOnlyPlanService
    assert read_only.PublishReadOnlyPlanHandler is PublishReadOnlyPlanHandler
    assert read_only.ClaimReadActionHandler is ClaimReadActionHandler
    assert read_only.CompleteReadActionHandler is CompleteReadActionHandler
    assert read_only.FinalizeReadActionHandler is FinalizeReadActionHandler
    assert read_only.FailReadActionHandler is FailReadActionHandler
    assert read_only.ExecuteReadActionService is ExecuteReadActionService
