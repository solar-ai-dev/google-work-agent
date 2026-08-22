"""Compatibility checks for the legacy READ application facade."""

import google_work_agent.application.read_only as read_only
from google_work_agent.application.read_execution import ExecuteReadActionService
from google_work_agent.application.read_lifecycle import (
    ClaimReadActionService,
    CompleteReadActionService,
    FailReadActionService,
    FinalizeReadActionService,
)
from google_work_agent.application.read_plan import (
    PublishReadOnlyPlanService,
    SaveReadOnlyPlanService,
)


def test_read_only_facade_preserves_service_identities() -> None:
    assert read_only.SaveReadOnlyPlanService is SaveReadOnlyPlanService
    assert read_only.PublishReadOnlyPlanService is PublishReadOnlyPlanService
    assert read_only.ClaimReadActionService is ClaimReadActionService
    assert read_only.CompleteReadActionService is CompleteReadActionService
    assert read_only.FinalizeReadActionService is FinalizeReadActionService
    assert read_only.FailReadActionService is FailReadActionService
    assert read_only.ExecuteReadActionService is ExecuteReadActionService
