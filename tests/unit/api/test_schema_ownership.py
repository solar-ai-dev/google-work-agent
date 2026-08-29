"""Repository-architecture checks for canonical API schema ownership."""

from pathlib import Path

from google_work_agent.api.schemas.actions.approve_action import ApproveActionRequestV2
from google_work_agent.api.schemas.actions.modify_action import ModifyActionRequestV2
from google_work_agent.api.schemas.actions.prepare_retry_action import PrepareRetryRequestV2
from google_work_agent.api.schemas.actions.reject_action import RejectActionRequestV2
from google_work_agent.api.schemas.attachments.stage_attachment import StageAttachmentRequest
from google_work_agent.api.schemas.conversations.create_conversation import (
    CreateConversationRequest,
)
from google_work_agent.api.schemas.events.get_events import EventEnvelope
from google_work_agent.api.schemas.health_checks.get_liveness import LiveResponse
from google_work_agent.api.schemas.health_checks.get_readiness import ReadyResponse
from google_work_agent.api.schemas.resources.list_resources import ResourceListResponse
from google_work_agent.api.schemas.runs.cancel_run import CancelRunRequestV2
from google_work_agent.api.schemas.runs.confirm_run import ConfirmationResponseV1
from google_work_agent.api.schemas.runs.recovery import (
    ActionRecoveryTargetV1,
    RecoveryUiProjectionV1,
    RunRecoveryTargetV1,
)
from google_work_agent.api.schemas.runs.resolve_recovery import ResolveRecoveryRequestV1
from google_work_agent.api.schemas.runs.resume_run import ResumeRunRequestV2
from google_work_agent.api.schemas.runs.start_run import StartRunRequest
from google_work_agent.api.schemas.runtime_summaries.get_runtime_summary import (
    RuntimeSummaryResponse,
)
from google_work_agent.api.schemas.settings.update_settings import PatchSettingsRequest


def test_action_transport_contracts_live_in_operation_modules() -> None:
    assert ApproveActionRequestV2.__module__.endswith(".actions.approve_action")
    assert ModifyActionRequestV2.__module__.endswith(".actions.modify_action")
    assert RejectActionRequestV2.__module__.endswith(".actions.reject_action")
    assert PrepareRetryRequestV2.__module__.endswith(".actions.prepare_retry_action")


def test_run_transport_contracts_live_in_operation_modules() -> None:
    assert StartRunRequest.__module__.endswith(".runs.start_run")
    assert ConfirmationResponseV1.__module__.endswith(".runs.confirm_run")
    assert ResumeRunRequestV2.__module__.endswith(".runs.resume_run")
    assert CancelRunRequestV2.__module__.endswith(".runs.cancel_run")
    assert ResolveRecoveryRequestV1.__module__.endswith(".runs.resolve_recovery")
    assert RunRecoveryTargetV1.__module__.endswith(".runs.recovery")
    assert ActionRecoveryTargetV1.__module__.endswith(".runs.recovery")
    assert RecoveryUiProjectionV1.__module__.endswith(".runs.recovery")


def test_other_plural_resource_contracts_live_in_operation_modules() -> None:
    assert StageAttachmentRequest.__module__.endswith(".attachments.stage_attachment")
    assert CreateConversationRequest.__module__.endswith(".conversations.create_conversation")
    assert EventEnvelope.__module__.endswith(".events.get_events")
    assert ResourceListResponse.__module__.endswith(".resources.list_resources")
    assert PatchSettingsRequest.__module__.endswith(".settings.update_settings")
    assert RuntimeSummaryResponse.__module__.endswith(".runtime_summaries.get_runtime_summary")
    assert LiveResponse.__module__.endswith(".health_checks.get_liveness")
    assert ReadyResponse.__module__.endswith(".health_checks.get_readiness")


def test_retired_broad_plural_resource_schema_modules_are_absent() -> None:
    api_root = Path(__file__).resolve().parents[3] / "src" / "google_work_agent" / "api" / "schemas"
    for filename in (
        "actions.py",
        "attachments.py",
        "conversations.py",
        "events.py",
        "resources.py",
        "runs.py",
        "settings.py",
        "runtime.py",
    ):
        assert not (api_root / filename).exists()
