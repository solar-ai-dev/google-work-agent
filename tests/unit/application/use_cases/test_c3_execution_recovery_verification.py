from __future__ import annotations

from json import dumps
from types import SimpleNamespace

import pytest

from google_work_agent.application.use_cases.execution_attempt.execute_action import ExecuteActionCommand, ExecuteActionHandler
from google_work_agent.application.use_cases.recovery.recover_create import RecoverCreateCommand, RecoverCreateHandler
from google_work_agent.application.use_cases.recovery.recover_delete import RecoverDeleteCommand, RecoverDeleteHandler
from google_work_agent.application.use_cases.recovery.recover_send import RecoverSendCommand, RecoverSendHandler
from google_work_agent.application.use_cases.recovery.recover_update import RecoverUpdateCommand, RecoverUpdateHandler
from google_work_agent.application.use_cases.verification.verify_action import VerifyActionCommand, VerifyActionHandler
from google_work_agent.application.write_execution_contracts import WriteActionResponse
from google_work_agent.application.write_execution_integrity import CLAIM_TOKEN_VERSION, issue_claim_token
from google_work_agent.application.write_verification_projection import calculate_verification_subset_diff, normalize_actual_verification_projection
from google_work_agent.domain import ActionStatus, ExecutionAttemptStatus, ResultCode, RunStatus, calculate_canonical_json_hash
from google_work_agent.ports import ResourceSnapshot, ResourceType

_SIGNING_SECRET = "c3-signing-secret"
_SERVICE_INSTANCE_ID = "svc-c3"


class _ByIdRepo:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get_by_id(self, value_id: str) -> object | None:
        return self.values.get(value_id)


class _CommandReceipts:
    def __init__(self) -> None:
        self.received: list[str] = []
        self.finished: list[str] = []

    def get_by_command_id(self, _command_id: str) -> None:
        return None

    def add_received(self, *, command_id: str, **_kwargs: object) -> None:
        self.received.append(command_id)

    def finish_json(self, *, command_id: str, **_kwargs: object) -> None:
        self.finished.append(command_id)


class _Sink:
    def __init__(self) -> None:
        self.items: list[object] = []

    def add(self, item: object) -> None:
        self.items.append(item)


class _VerificationRepo:
    def __init__(self) -> None:
        self.items: list[object] = []

    def list_by_attempt(self, _attempt_id: str) -> list[object]:
        return list(self.items)

    def insert(self, item: object) -> None:
        self.items.append(item)


class _Dependencies:
    def list_dependents(self, _action_id: str) -> list[str]:
        return []


class _Actions(_ByIdRepo):
    def __init__(self, values: dict[str, object], verification_status: ActionStatus | None = None) -> None:
        super().__init__(values)
        self.verification_status = verification_status

    def store_verification(self, _action_id: str, **_kwargs: object) -> object:
        return SimpleNamespace(
            applied=True,
            current_status=self.verification_status or ActionStatus.VERIFIED,
            current_version=2,
            next_allowed_commands=(),
        )


class _Runs(_ByIdRepo):
    def __init__(self, values: dict[str, object]) -> None:
        super().__init__(values)
        self.recovery_required = 0

    def set_recovery_required(self, _run_id: str) -> None:
        self.recovery_required += 1


class _Uow:
    def __init__(
        self,
        *,
        action: object,
        attempt: object,
        approval: object | None = None,
        plan: object | None = None,
        run: object | None = None,
        verification_status: ActionStatus | None = None,
    ) -> None:
        self.actions = _Actions({getattr(action, "id"): action}, verification_status)
        self.execution_attempts = _ByIdRepo({getattr(attempt, "id"): attempt})
        self.approvals = _ByIdRepo({} if approval is None else {getattr(approval, "id"): approval})
        self.plans = _ByIdRepo({} if plan is None else {getattr(plan, "id"): plan})
        self.runs = _Runs({} if run is None else {getattr(run, "id"): run})
        self.resource_refs = _ByIdRepo({})
        self.command_receipts = _CommandReceipts()
        self.verifications = _VerificationRepo()
        self.action_dependencies = _Dependencies()
        self.traces = _Sink()
        self.audits = _Sink()
        self.commits = 0

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


class _ExecutionConnector:
    def __init__(self, snapshot: ResourceSnapshot) -> None:
        self.snapshot = snapshot
        self.prepare_calls = 0
        self.execute_calls = 0

    def prepare_write(self, *, arguments: dict[str, object], **_kwargs: object) -> object:
        self.prepare_calls += 1
        return SimpleNamespace(arguments=arguments)

    def execute_write(self, _request: object) -> ResourceSnapshot:
        self.execute_calls += 1
        return self.snapshot


class _RecoveryConnector:
    def __init__(self, *, candidates: list[ResourceSnapshot] | None = None, snapshot: ResourceSnapshot | None = None, absent: bool = False) -> None:
        self.candidates = candidates or []
        self.snapshot = snapshot
        self.absent = absent
        self.search_calls = 0
        self.read_calls = 0
        self.write_calls = 0

    def search_recovery_candidates(self, **_kwargs: object) -> list[ResourceSnapshot]:
        self.search_calls += 1
        return list(self.candidates)

    def fetch_verification_snapshot(self, **_kwargs: object) -> ResourceSnapshot:
        self.read_calls += 1
        if self.absent:
            raise LookupError("absent")
        if self.snapshot is None:
            raise AssertionError("snapshot not configured")
        return self.snapshot

    def execute_write(self, _request: object) -> ResourceSnapshot:
        self.write_calls += 1
        raise AssertionError("recovery/verification must never dispatch a write")


class _VerificationConnector(_RecoveryConnector):
    last_request_id = "mcp-c3"


def _task_snapshot(*, title: str, resource_id: str = "task-1", version: str = "1", extra: dict[str, object] | None = None) -> ResourceSnapshot:
    payload: dict[str, object] = {"title": title, **(extra or {})}
    return ResourceSnapshot(
        fixture_snapshot_id="fixture-c3",
        resource_type=ResourceType.TASK,
        resource_id=resource_id,
        parent_id="list-1",
        related_resource_ids=("list-1",),
        version=version,
        recovery_fingerprint=None,
        payload=payload,
    )


def _execution_fixture(*, attempt_status: ExecutionAttemptStatus = ExecutionAttemptStatus.CLAIMED, run_status: RunStatus = RunStatus.WAITING_APPROVAL) -> tuple[_Uow, str, _ExecutionConnector]:
    arguments = {"task_list_id": "list-1", "payload": {"title": "C3"}}
    arguments_hash = calculate_canonical_json_hash(arguments)
    action = SimpleNamespace(id="action-1", plan_id="plan-1", tool_name="tasks_create_task", arguments_json=dumps(arguments), arguments_hash=arguments_hash)
    approval = SimpleNamespace(id="approval-1", action_id="action-1", recovery_fingerprint="fp-1")
    attempt = SimpleNamespace(id="attempt-1", approval_id="approval-1", status=attempt_status)
    plan = SimpleNamespace(id="plan-1", run_id="run-1")
    run = SimpleNamespace(id="run-1", status=run_status)
    uow = _Uow(action=action, attempt=attempt, approval=approval, plan=plan, run=run)
    connector = _ExecutionConnector(_task_snapshot(title="C3"))
    token = issue_claim_token(
        {
            "version": CLAIM_TOKEN_VERSION,
            "action_id": "action-1",
            "approval_id": "approval-1",
            "attempt_id": "attempt-1",
            "tool_name": "tasks_create_task",
            "arguments_hash": arguments_hash,
            "service_instance_id": _SERVICE_INSTANCE_ID,
            "nonce": "nonce-1",
            "issued_at_ms": 1_000,
            "expires_at_ms": 31_000,
        },
        signing_secret=_SIGNING_SECRET,
    )
    return uow, token, connector


def _execute_handler(uow: _Uow, connector: _ExecutionConnector, now_ms: int = 2_000) -> ExecuteActionHandler:
    return ExecuteActionHandler(
        unit_of_work_factory=lambda: uow,  # type: ignore[arg-type]
        connector_execution=connector,  # type: ignore[arg-type]
        now_ms=lambda: now_ms,
        signing_secret=_SIGNING_SECRET,
        service_instance_id=_SERVICE_INSTANCE_ID,
    )


def test_execute_action_preserves_token_cancel_claim_and_nonce_safety() -> None:
    uow, token, connector = _execution_fixture()
    expired = _execute_handler(uow, connector, 31_000)
    with pytest.raises(PermissionError, match="expired"):
        expired(ExecuteActionCommand("action-1", token))
    assert connector.execute_calls == 0

    cancelled, cancel_token, cancel_connector = _execution_fixture(run_status=RunStatus.CANCEL_REQUESTED)
    with pytest.raises(PermissionError, match="cancellation"):
        _execute_handler(cancelled, cancel_connector)(ExecuteActionCommand("action-1", cancel_token))
    assert cancel_connector.execute_calls == 0

    nonclaimed, nonclaimed_token, nonclaimed_connector = _execution_fixture(attempt_status=ExecutionAttemptStatus.SUCCEEDED)
    with pytest.raises(PermissionError, match="CLAIMED"):
        _execute_handler(nonclaimed, nonclaimed_connector)(ExecuteActionCommand("action-1", nonclaimed_token))
    assert nonclaimed_connector.execute_calls == 0

    fresh, fresh_token, fresh_connector = _execution_fixture()
    handler = _execute_handler(fresh, fresh_connector)
    assert handler(ExecuteActionCommand("action-1", fresh_token)).snapshot.resource_id == "task-1"
    with pytest.raises(PermissionError, match="already been used"):
        handler(ExecuteActionCommand("action-1", fresh_token))
    assert fresh_connector.execute_calls == 1


def _recovery_uow(*, tool_name: str, expected: dict[str, object] | None = None, source: dict[str, object] | None = None, arguments: dict[str, object] | None = None) -> _Uow:
    action = SimpleNamespace(
        id="action-1", plan_id="plan-1", tool_name=tool_name,
        arguments_json=dumps(arguments or {}), expected_json=dumps(expected or {}),
        target_resource_ref_id=None, status=ActionStatus.UNKNOWN_RESULT.value, version=3,
    )
    attempt = SimpleNamespace(id="attempt-1", approval_id="approval-1", status=ExecutionAttemptStatus.UNKNOWN_RESULT)
    approval = SimpleNamespace(id="approval-1", action_id="action-1", recovery_fingerprint="fp-1", source_snapshot_json=dumps(source or {}))
    return _Uow(action=action, attempt=attempt, approval=approval)


def _applied_response(status: str = ActionStatus.EXECUTED.value) -> WriteActionResponse:
    return WriteActionResponse(True, ResultCode.TRANSITION_APPLIED.value, "action-1", status, 4, (), attempt_id="attempt-1")


def test_create_send_and_delete_recovery_never_blind_write() -> None:
    for handler_type, command_type, tool_name in (
        (RecoverCreateHandler, RecoverCreateCommand, "tasks_create_task"),
        (RecoverSendHandler, RecoverSendCommand, "gmail_send"),
    ):
        uow = _recovery_uow(tool_name=tool_name)
        connector = _RecoveryConnector(candidates=[_task_snapshot(title="a"), _task_snapshot(title="b", resource_id="task-2")])
        result = handler_type(
            unit_of_work_factory=lambda uow=uow: uow,  # type: ignore[arg-type]
            connector_execution=connector,  # type: ignore[arg-type]
            recover_existing_result=lambda _command: _applied_response(),
        )(command_type("cmd", "hash", "action-1", "attempt-1", 3, 1))
        assert result.result_code == ResultCode.RECOVERY_REQUIRED.value
        assert connector.write_calls == 0

    delete_uow = _recovery_uow(tool_name="tasks_delete_task", arguments={"task_id": "task-1", "task_list_id": "list-1"})
    present_connector = _RecoveryConnector(snapshot=_task_snapshot(title="present"))
    present = RecoverDeleteHandler(
        unit_of_work_factory=lambda: delete_uow,  # type: ignore[arg-type]
        connector_execution=present_connector,  # type: ignore[arg-type]
        recover_existing_result=lambda _command: _applied_response(),
    )(RecoverDeleteCommand("cmd-p", "hash", "action-1", "attempt-1", 3, 1))
    assert present.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert present_connector.write_calls == 0

    absent_connector = _RecoveryConnector(absent=True)
    absent = RecoverDeleteHandler(
        unit_of_work_factory=lambda: delete_uow,  # type: ignore[arg-type]
        connector_execution=absent_connector,  # type: ignore[arg-type]
        recover_existing_result=lambda _command: _applied_response(),
    )(RecoverDeleteCommand("cmd-a", "hash", "action-1", "attempt-1", 3, 1))
    assert absent.applied is True
    assert absent_connector.write_calls == 0


def test_update_recovery_uses_canonical_subset_projection_for_all_three_states() -> None:
    arguments = {"task_id": "task-1", "task_list_id": "list-1", "payload": {"title": "after"}}
    expected = {"payload": {"title": "after"}}
    source = {"resource_id": "task-1", "version": "1", "payload": {"title": "before"}}
    recovered: list[object] = []
    failed: list[object] = []

    def run(snapshot: ResourceSnapshot, command_id: str) -> object:
        uow = _recovery_uow(tool_name="tasks_update_task", expected=expected, source=source, arguments=arguments)
        return RecoverUpdateHandler(
            unit_of_work_factory=lambda: uow,  # type: ignore[arg-type]
            connector_execution=_RecoveryConnector(snapshot=snapshot),  # type: ignore[arg-type]
            recover_existing_result=lambda command: recovered.append(command) or _applied_response(),
            resolve_as_failed=lambda command: failed.append(command) or _applied_response(ActionStatus.FAILED.value),
        )(RecoverUpdateCommand(command_id, "hash", "action-1", "attempt-1", 3, 1))

    expected_result = run(_task_snapshot(title="after", version="2", extra={"notes": "provider-extra"}), "cmd-e")
    assert expected_result.action_status == ActionStatus.EXECUTED.value
    assert len(recovered) == 1 and failed == []

    source_result = run(_task_snapshot(title="before", version="1", extra={"notes": "irrelevant-extra"}), "cmd-s")
    assert source_result.action_status == ActionStatus.FAILED.value
    assert len(failed) == 1

    third_result = run(_task_snapshot(title="someone-else", version="3", extra={"notes": "extra"}), "cmd-t")
    assert third_result.applied is False
    assert third_result.result_code == ResultCode.RECOVERY_REQUIRED.value


def _verification_uow(*, expected_title: str = "C3", verification_status: ActionStatus = ActionStatus.VERIFIED, attempt_status: ExecutionAttemptStatus = ExecutionAttemptStatus.SUCCEEDED, approval_action_id: str = "action-1") -> _Uow:
    action = SimpleNamespace(
        id="action-1", plan_id="plan-1", tool_name="tasks_update_task",
        arguments_json=dumps({"task_id": "task-1", "task_list_id": "list-1", "payload": {"title": expected_title}}),
        expected_json=dumps({"payload": {"title": expected_title}}), target_resource_ref_id=None,
        status=ActionStatus.EXECUTED.value, effect_type="UPDATE", version=1,
    )
    attempt = SimpleNamespace(id="attempt-1", approval_id="approval-1", status=attempt_status, result_resource_ref_id=None)
    approval = SimpleNamespace(id="approval-1", action_id=approval_action_id)
    plan = SimpleNamespace(id="plan-1", run_id="run-1")
    run = SimpleNamespace(id="run-1", status=RunStatus.VERIFYING)
    return _Uow(action=action, attempt=attempt, approval=approval, plan=plan, run=run, verification_status=verification_status)


def test_verification_normalization_valid_chain_and_mismatch_semantics() -> None:
    normalized = normalize_actual_verification_projection(tool_name="tasks_update_task", actual={"payload": {"title": "C3", "due": "2026-08-22T00:00:00Z"}})
    assert normalized["payload"]["due"] == "2026-08-22"  # type: ignore[index]
    assert calculate_verification_subset_diff({"payload": {"title": "C3"}}, normalized) == []

    valid_uow = _verification_uow()
    valid_connector = _VerificationConnector(snapshot=_task_snapshot(title="C3", extra={"notes": "extra"}))
    valid = VerifyActionHandler(
        unit_of_work_factory=lambda: valid_uow,  # type: ignore[arg-type]
        now_ms=lambda: 10_000,
        connector_execution=valid_connector,  # type: ignore[arg-type]
    )(VerifyActionCommand("verify-ok", "hash", "action-1", "attempt-1", 1, "verification-1"))
    assert valid.applied is True
    assert valid.action_status == ActionStatus.VERIFIED.value
    assert valid_connector.read_calls == 1

    mismatch_uow = _verification_uow(expected_title="expected", verification_status=ActionStatus.MISMATCH)
    mismatch = VerifyActionHandler(
        unit_of_work_factory=lambda: mismatch_uow,  # type: ignore[arg-type]
        now_ms=lambda: 10_000,
        connector_execution=_VerificationConnector(snapshot=_task_snapshot(title="actual")),  # type: ignore[arg-type]
    )(VerifyActionCommand("verify-m", "hash", "action-1", "attempt-1", 1, "verification-2"))
    assert mismatch.action_status == ActionStatus.MISMATCH.value
    assert mismatch_uow.runs.recovery_required == 1


def test_verification_foreign_succeeded_attempt_fails_closed_before_read() -> None:
    uow = _verification_uow(approval_action_id="foreign-action")
    connector = _VerificationConnector(snapshot=_task_snapshot(title="C3"))
    result = VerifyActionHandler(
        unit_of_work_factory=lambda: uow,  # type: ignore[arg-type]
        now_ms=lambda: 10_000,
        connector_execution=connector,  # type: ignore[arg-type]
    )(VerifyActionCommand("verify-foreign", "hash", "action-1", "attempt-1", 1, "verification-f"))
    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    assert connector.read_calls == connector.write_calls == 0
    assert uow.verifications.items == []


def test_verification_unknown_result_fails_closed_before_read() -> None:
    uow = _verification_uow(attempt_status=ExecutionAttemptStatus.UNKNOWN_RESULT)
    connector = _VerificationConnector(snapshot=_task_snapshot(title="C3"))
    result = VerifyActionHandler(
        unit_of_work_factory=lambda: uow,  # type: ignore[arg-type]
        now_ms=lambda: 10_000,
        connector_execution=connector,  # type: ignore[arg-type]
    )(VerifyActionCommand("verify-unknown", "hash", "action-1", "attempt-1", 1, "verification-u"))
    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    assert connector.read_calls == connector.write_calls == 0
