from __future__ import annotations

from typing import cast

from google_work_agent.application.use_cases.run.complete_write_run import (
    CompleteWriteRunCommand,
    CompleteWriteRunHandler,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.conversation.model import Conversation as ConversationRecord
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import Run as RunRecord
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports import UnitOfWork


class _Receipts:
    def __init__(self) -> None:
        self.finished = 0

    def get_by_command_id(self, _command_id: str):
        return None

    def reserve_or_replay(self, **_kwargs: object) -> None:
        return None

    def store_result(self, **_kwargs: object) -> None:
        self.finished += 1


class _Runs:
    def __init__(self, run: RunRecord) -> None:
        self.run = run
        self.complete_calls = 0

    def get(self, _run_id: str) -> RunRecord:
        return self.run

    def update_if_version_and_status(self, *_args: object, **_kwargs: object):
        self.complete_calls += 1
        raise AssertionError("Run completion must not execute when aggregate guard fails")


class _Plans:
    def __init__(self, plan: PlanRecord) -> None:
        self.plan = plan
        self.complete_calls = 0

    def get_current(self, _run_id: str) -> PlanRecord:
        return self.plan

    def complete(self, _plan_id: str) -> None:
        self.complete_calls += 1


class _Actions:
    def __init__(self, action: ActionRecord) -> None:
        self.action = action

    def list_for_plan(self, _plan_id: str) -> tuple[ActionRecord, ...]:
        return (self.action,)


class _CancelIntents:
    def has_durable_intent(self, _run_id: str) -> bool:
        return False


class _EmptyHistory:
    def list_for_action(self, _action_id: str) -> tuple[object, ...]:
        return ()


class _Conversations:
    def __init__(self, conversation: ConversationRecord) -> None:
        self.conversation = conversation

    def get(self, _conversation_id: str) -> ConversationRecord:
        return self.conversation


class _Uow:
    def __init__(self) -> None:
        self.command_receipts = _Receipts()
        self.cancel_intents = _CancelIntents()
        self.approval_history = _EmptyHistory()
        self.runs = _Runs(
            RunRecord(
                id="run-1",
                conversation_id="conversation-1",
                status=RunStatusV1.VERIFYING,
                version=7,
                started_at_ms=1,
                finished_at_ms=None,
            )
        )
        self.plans = _Plans(
            PlanRecord(
                id="plan-1",
                run_id="run-1",
                revision_no=1,
                status=PlanStatusV1.WAITING_APPROVAL,
                summary_text="write",
                created_at_ms=1,
            )
        )
        self.actions = _Actions(
            ActionRecord(
                id="action-1",
                plan_id="plan-1",
                connector_id="google_workspace",
                position=0,
                tool_name="tasks_create_task",
                effect_type="CREATE",
                approval_requirement="REQUIRED",
                verification_policy="GET_COMPARE",
                recovery_policy="RESOURCE_SEARCH",
                target_resource_ref_id=None,
                status=ActionStatusV1.MISMATCH.value,
                arguments_json="{}",
                arguments_hash="hash",
                expected_json="{}",
                risk={},
                version=4,
                created_at_ms=1,
                updated_at_ms=2,
            )
        )
        self.conversations = _Conversations(
            ConversationRecord(
                id="conversation-1",
                account_id="acct-1",
                title="test",
                created_at_ms=1,
                updated_at_ms=1,
            )
        )
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


def test_complete_write_run_mismatch_guard_has_zero_run_and_plan_completion_mutations() -> None:
    uow = _Uow()
    service = CompleteWriteRunHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, uow),
        now_ms=lambda: 100,
        message_id_factory=lambda: "message-1",
    )

    response = service(
        CompleteWriteRunCommand(
            command_id="complete-1",
            request_hash="request-hash",
            run_id="run-1",
            expected_version=7,
        )
    )

    assert response.applied is False
    assert response.run_status == RunStatusV1.VERIFYING.value
    assert response.run_version == 7
    assert "MISMATCH" in cast(str, response.conflict_detail)
    assert uow.runs.complete_calls == 0
    assert uow.plans.complete_calls == 0
    assert uow.command_receipts.finished == 1
    assert uow.commits == 1
