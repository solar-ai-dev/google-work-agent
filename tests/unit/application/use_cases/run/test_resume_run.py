"""Regression tests for canonical persisted Run resume authority."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from google_work_agent.application.use_cases.run.resume_run import (
    ResumeRunCommand,
    ResumeRunHandler,
)
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import Run as RunRecord
from google_work_agent.domain.run.model import RunStatus
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
    RunExecutionAcceptedV1,
)


class _Sink:
    def __init__(self) -> None:
        self.items = []

    def add(self, item) -> None:
        self.items.append(item)


class _Receipts:
    def __init__(self) -> None:
        self.items = {}

    def get_by_command_id(self, command_id):
        return self.items.get(command_id)

    def add_received(
        self, *, command_id, command_type, request_hash, aggregate_type, aggregate_id, created_at_ms
    ):
        self.items[command_id] = CommandReceiptRecord(
            command_id,
            command_type,
            request_hash,
            aggregate_type,
            aggregate_id,
            CommandReceiptStatus.RECEIVED,
            None,
            None,
            None,
            None,
            created_at_ms,
            None,
        )

    def finish_json(
        self, *, command_id, applied, result_code, result_version, response_json, completed_at_ms
    ):
        old = self.items[command_id]
        self.items[command_id] = CommandReceiptRecord(
            old.command_id,
            old.command_type,
            old.request_hash,
            old.aggregate_type,
            old.aggregate_id,
            CommandReceiptStatus.APPLIED if applied else CommandReceiptStatus.REJECTED,
            result_code,
            result_version,
            None,
            response_json,
            old.created_at_ms,
            completed_at_ms,
        )


class _Runs:
    def __init__(self, status: RunStatus, version: int = 4) -> None:
        self.record = RunRecord("run-1", "conv-1", status, version, 1, None)
        self.calls = []

    def get(self, run_id):
        return self.record if run_id == self.record.id else None

    def update_if_version_and_status(self, run_id, expected_version, expected_statuses, values):
        if (
            run_id != self.record.id
            or expected_version != self.record.version
            or self.record.status not in expected_statuses
        ):
            return None
        target = RunStatus(values["status"])
        if self.record.status is RunStatus.REAUTH_REQUIRED:
            name = "resume_after_reauth"
        elif target is RunStatus.RECOVERY_REQUIRED:
            name = "require_recovery"
        elif self.record.status is RunStatus.RECOVERY_REQUIRED:
            name = "resolve_recovery"
        else:
            name = "resume_confirmation"
        self.calls.append(name)
        self.record = RunRecord(
            self.record.id,
            self.record.conversation_id,
            target,
            int(values["version"]),
            self.record.started_at_ms,
            values.get("finished_at_ms"),
        )
        return self.record

    def _move(self, name, target):
        self.calls.append(name)
        self.record = RunRecord(
            self.record.id,
            self.record.conversation_id,
            target,
            self.record.version + 1,
            self.record.started_at_ms,
            None,
        )
        return CommandResult(
            True, ResultCode.TRANSITION_APPLIED, target, self.record.version, (), None
        )

    def resume_confirmation(self, run_id, *, expected_version, resume_status, finished_at_ms=None):
        return self._move("resume_confirmation", resume_status)

    def resume_after_reauth(self, run_id, *, expected_version, resume_status, finished_at_ms=None):
        return self._move("resume_after_reauth", resume_status)

    def require_recovery(self, run_id, *, expected_version, finished_at_ms=None):
        return self._move("require_recovery", RunStatus.RECOVERY_REQUIRED)

    def resolve_recovery(
        self,
        run_id,
        *,
        expected_version,
        recovery_next_status,
        finished_at_ms=None,
        validated_recovery_target=False,
    ):
        del validated_recovery_target
        return self._move("resolve_recovery", recovery_next_status)


class _RecoveryContexts:
    def __init__(self) -> None:
        self.current: dict | None = None
        self.stored: list[dict] = []

    def load_current_context(self, run_id):
        return self.current

    def store_context(self, context):
        self.stored.append(context)
        self.current = context
        return context

    def clear_context(self, run_id, expected_version):
        assert self.current is not None
        assert self.current["run_id"] == run_id
        assert self.current["version"] == expected_version
        self.current = None


class _Uow:
    def __init__(self, status, action_statuses=()):
        self.runs = _Runs(status)
        self.command_receipts = _Receipts()
        self.traces = _Sink()
        self.audits = _Sink()
        self.recovery_contexts = _RecoveryContexts()
        self.commits = 0
        plan = SimpleNamespace(id="plan-1", revision_no=1, created_at_ms=1)
        self.plans = SimpleNamespace(list_by_run=lambda run_id: [plan] if action_statuses else [])
        self.actions = SimpleNamespace(
            list_by_plan=lambda plan_id: [SimpleNamespace(status=item) for item in action_statuses]
        )
        target = MainControlResumeTargetV2("MAIN_CONTROL", "PREFLIGHT", "SIX_ROLE_BASELINE", "v1")
        self.checkpoints = SimpleNamespace(
            load_workflow_binding=lambda run_id: WorkflowBindingV1(
                1, "thread-1", run_id, "thread-1", "SIX_ROLE_BASELINE", "v1", "AUTO", 1
            ),
            load_same_run_checkpoint=lambda run_id, thread_id: GraphCheckpointEnvelopeV1(
                1,
                "checkpoint-1",
                1,
                run_id,
                thread_id,
                "SIX_ROLE_BASELINE",
                "v1",
                "RUN",
                target,
                None,
                None,
                None,
                None,
                (),
                1,
                b"checkpoint",
            ),
        )
        self.workflow_handoffs = _Handoffs()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


@dataclass
class _Harness:
    uow: _Uow
    authority: dict[str, object] | None
    enqueues: list[dict[str, object]]

    def handler(self):
        return ResumeRunHandler(
            unit_of_work_factory=lambda: self.uow,
            now_ms=lambda: 100,
            resolve_resume_authority=lambda **kwargs: self.authority,
            id_generator=SimpleNamespace(next_id=lambda: "handoff-1"),
            resume_target_registry=SimpleNamespace(validate=lambda target: None),
            schedule_run_execution=lambda command: (
                self.enqueues.append({"handoff_id": command.handoff_id})
                or RunExecutionAcceptedV1(1, True, "ACCEPTED")
            ),
        )


class _Handoffs:
    def __init__(self) -> None:
        self.items = {}
        self.stages = []

    def stage_pending(self, stage):
        self.stages.append(stage)
        handoff = SimpleNamespace(handoff_id=stage.handoff_id)
        self.items[stage.trigger_command_id] = handoff
        return handoff

    def get_by_trigger_command_id(self, trigger_command_id):
        return self.items.get(trigger_command_id)


def _command(
    kind: str, *, command_id: str = "cmd-1", request_hash: str = "hash-1", version: int = 4
):
    return ResumeRunCommand(command_id, request_hash, "run-1", version, kind, "v1")


def _reauth_authority(
    status: str = "WAITING_APPROVAL", target: str = "action_execution"
) -> dict[str, object]:
    return {"resume_status": status, "continuation_target": target}


def test_generic_resume_rejects_confirmation_without_mutation_or_enqueue() -> None:
    h = _Harness(
        _Uow(RunStatus.WAITING_CONFIRMATION),
        {"resume_status": "PLANNING", "interrupt_id": "int-1"},
        [],
    )
    result = h.handler()(
        _command("CONFIRMATION"), request_id="req", resume_payload={"interrupt_id": "int-1"}
    )
    assert not result.applied and result.result_code == ResultCode.STATE_CONFLICT.value
    assert h.uow.runs.calls == [] and h.enqueues == []
    assert h.uow.commits == 1


def test_reauth_resume_applies_safe_checkpoint_transition_and_server_target() -> None:
    h = _Harness(_Uow(RunStatus.REAUTH_REQUIRED), _reauth_authority(), [])
    result = h.handler()(_command("REAUTH_COMPLETED"), request_id="req")
    assert result.applied and result.run_status == "WAITING_APPROVAL" and result.run_version == 5
    assert h.uow.runs.calls == ["resume_after_reauth"] and len(h.enqueues) == 1
    assert h.uow.workflow_handoffs.stages[0].execution.resume_target.stage_id == "PREFLIGHT"
    assert h.uow.workflow_handoffs.stages[0].control_kind == "NONE"


def test_reauth_dispatched_write_facts_fail_safe_to_recovery_without_runtime_resume() -> None:
    for action_status in ("EXECUTING", "UNKNOWN_RESULT", "EXECUTED"):
        h = _Harness(_Uow(RunStatus.REAUTH_REQUIRED, (action_status,)), _reauth_authority(), [])
        result = h.handler()(_command("REAUTH_COMPLETED"), request_id="req")
        assert (
            result.applied and result.run_status == "RECOVERY_REQUIRED" and result.run_version == 6
        )
        assert h.uow.runs.calls == ["resume_after_reauth", "require_recovery"]
        assert h.uow.commits == 1 and h.enqueues == []
        assert not hasattr(h.uow, "execution_attempts") and not hasattr(h.uow, "approvals")
        assert len(h.uow.recovery_contexts.stored) == 1
        context = h.uow.recovery_contexts.stored[0]
        assert context["reason"] == "CHECKPOINT_MISMATCH"
        assert context["scope"] == "RUN"
        assert context["version"] == 0
        assert [item.event_type for item in h.uow.audits.items] == [
            "RECOVERY_REQUIRED",
            "RUN_RESUMED",
        ]


def test_reauth_recovery_checkpoint_restores_domain_truth_without_runtime_recovery_selection() -> (
    None
):
    h = _Harness(_Uow(RunStatus.REAUTH_REQUIRED), {"resume_status": "RECOVERY_REQUIRED"}, [])
    result = h.handler()(_command("REAUTH_COMPLETED"), request_id="req")
    assert result.applied and result.run_status == "RECOVERY_REQUIRED" and result.run_version == 5
    assert h.uow.runs.calls == ["resume_after_reauth"]
    assert h.uow.commits == 1 and h.enqueues == []


def test_recovery_recheck_moves_to_verifying_without_new_attempt_or_approval() -> None:
    h = _Harness(_Uow(RunStatus.RECOVERY_REQUIRED), None, [])
    h.uow.recovery_contexts.current = {
        "run_id": "run-1",
        "reason": "VERIFICATION_MISMATCH",
        "pre_recovery_status": "VERIFYING",
        "version": 0,
    }
    result = h.handler()(_command("RECOVERY_RECHECK"), request_id="req")
    assert result.applied and result.run_status == "VERIFYING"
    assert h.uow.runs.calls == ["resolve_recovery"] and len(h.enqueues) == 1
    assert not hasattr(h.uow, "execution_attempts") and not hasattr(h.uow, "approvals")


def test_terminal_blocked_safe_checkpoint_resume_is_rejected_without_enqueue() -> None:
    h = _Harness(_Uow(RunStatus.BLOCKED), None, [])
    result = h.handler()(_command("SAFE_CHECKPOINT_RESUME"), request_id="req")
    assert not result.applied and result.result_code == ResultCode.STATE_CONFLICT.value
    assert result.run_status == "BLOCKED" and result.run_version == 4
    assert h.uow.runs.calls == [] and h.enqueues == [] and h.uow.commits == 1
    assert h.uow.command_receipts.items["cmd-1"].status is CommandReceiptStatus.REJECTED


def test_safe_checkpoint_resume_fails_closed_when_no_canonical_ordinary_state_is_registered() -> (
    None
):
    h = _Harness(_Uow(RunStatus.PLANNING), None, [])
    result = h.handler()(_command("SAFE_CHECKPOINT_RESUME"), request_id="req")
    assert not result.applied and result.result_code == ResultCode.STATE_CONFLICT.value
    assert h.uow.runs.calls == [] and h.enqueues == []


def test_invalid_status_does_not_transition_or_enqueue() -> None:
    h = _Harness(
        _Uow(RunStatus.ANALYZING), {"resume_status": "PLANNING", "interrupt_id": "int-1"}, []
    )
    result = h.handler()(
        _command("CONFIRMATION"), request_id="req", resume_payload={"interrupt_id": "int-1"}
    )
    assert not result.applied and result.result_code == ResultCode.STATE_CONFLICT.value
    assert h.uow.runs.calls == [] and h.enqueues == []


def test_invalid_resume_kind_does_not_transition_or_enqueue() -> None:
    h = _Harness(_Uow(RunStatus.BLOCKED), None, [])
    result = h.handler()(_command("NOT_REGISTERED"), request_id="req")
    assert not result.applied and result.result_code == ResultCode.STATE_CONFLICT.value
    assert h.uow.runs.calls == [] and h.enqueues == []


def test_confirmation_interrupt_must_match_persisted_checkpoint_authority() -> None:
    h = _Harness(
        _Uow(RunStatus.WAITING_CONFIRMATION),
        {"resume_status": "PLANNING", "interrupt_id": "int-1"},
        [],
    )
    result = h.handler()(
        _command("CONFIRMATION"), request_id="req", resume_payload={"interrupt_id": "wrong"}
    )
    assert not result.applied and result.result_code == ResultCode.STATE_CONFLICT.value
    assert h.uow.runs.calls == [] and h.enqueues == []


def test_same_hash_replay_returns_prior_result_without_second_mutation_or_enqueue() -> None:
    h = _Harness(_Uow(RunStatus.REAUTH_REQUIRED), _reauth_authority(), [])
    handler = h.handler()
    command = _command("REAUTH_COMPLETED")
    first = handler(command, request_id="req")
    second = handler(command, request_id="req")
    assert first.applied and second.applied and second.request_replayed
    assert h.uow.runs.calls == ["resume_after_reauth"] and len(h.enqueues) == 1


def test_hash_mismatch_is_conflict_with_zero_second_mutation_and_enqueue() -> None:
    h = _Harness(_Uow(RunStatus.REAUTH_REQUIRED), _reauth_authority(), [])
    handler = h.handler()
    first = handler(_command("REAUTH_COMPLETED"), request_id="req")
    second = handler(_command("REAUTH_COMPLETED", request_hash="different"), request_id="req")
    assert (
        first.applied
        and not second.applied
        and second.result_code == ResultCode.DUPLICATE_COMMAND.value
    )
    assert h.uow.runs.calls == ["resume_after_reauth"] and len(h.enqueues) == 1
