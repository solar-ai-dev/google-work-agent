from __future__ import annotations

from collections.abc import Mapping
from json import dumps
from types import SimpleNamespace
from typing import Any, cast

import pytest
from tests.support.legacy_write.contracts import LegacyWriteResultMaterializer
from tests.support.legacy_write.execute_action import (
    ExecuteActionCommand,
    ExecuteActionHandler,
)
from tests.support.legacy_write.recover_create import (
    RecoverCreateCommand,
    RecoverCreateHandler,
)
from tests.support.legacy_write.recover_delete import (
    RecoverDeleteCommand,
    RecoverDeleteHandler,
)
from tests.support.legacy_write.recover_send import (
    RecoverSendCommand,
    RecoverSendHandler,
)
from tests.support.legacy_write.recover_update import (
    RecoverUpdateCommand,
    RecoverUpdateHandler,
    RecoverUpdateResult,
)
from tests.support.legacy_write.verify_action import (
    VerifyActionCommand,
    VerifyActionHandler,
)

from google_work_agent.application.use_cases.claim.write_execution_integrity import (
    CLAIM_TOKEN_VERSION,
    issue_claim_token,
)
from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultCommand,
    RecoverExistingResultResult,
)
from google_work_agent.application.use_cases.execution_attempt.resolve_as_failed import (
    ResolveAsFailedCommand,
    ResolveAsFailedResult,
)
from google_work_agent.application.use_cases.verification.write_verification_projection import (
    calculate_verification_subset_diff,
    normalize_actual_verification_projection,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

_SIGNING_SECRET = "c3-signing-secret"
_SERVICE_INSTANCE_ID = "svc-c3"


class _ByIdRepo:
    def __init__(self, values: dict[str, Any], *, plan_bundles: bool = False) -> None:
        self.values = values
        self.plan_bundles = plan_bundles

    def get_by_id(self, value_id: str) -> Any | None:
        return self.values.get(value_id)

    def get(self, value_id: str) -> Any | None:
        return self.values.get(value_id)

    def load_bundle(self, value_id: str) -> Any | None:
        value = self.values.get(value_id)
        if value is None or not self.plan_bundles:
            return value
        return SimpleNamespace(
            plan=value, actions=(), dependencies=(), evidence=(), action_evidence=()
        )

    def get_active_for_approval(self, value_id: str) -> Any | None:
        return self.values.get(value_id)

    def list_by_run(self, run_id: str) -> list[Any]:
        return [item for item in self.values.values() if getattr(item, "run_id", None) == run_id]

    def get_current(self, run_id: str) -> Any | None:
        return next(
            (item for item in self.values.values() if getattr(item, "run_id", None) == run_id),
            None,
        )

    def update_if_version_and_status(
        self, value_id: str, *args: object, **kwargs: object
    ) -> Any | None:
        item = self.values.get(value_id)
        if item is None:
            return None
        if args and isinstance(args[-1], dict):
            kwargs = {**args[-1], **kwargs}
        next_status = kwargs.get("next_status", kwargs.get("status"))
        if next_status is not None:
            item.status = next_status
        if hasattr(item, "version"):
            item.version += 1
        return item


class _CommandReceipts:
    def __init__(self) -> None:
        self.received: list[str] = []
        self.finished: list[str] = []

    def get_by_command_id(self, _command_id: str) -> None:
        return None

    def reserve_or_replay(self, *, command_id: str, **_kwargs: object) -> None:
        self.received.append(command_id)

    def store_result(self, *, command_id: str, **_kwargs: object) -> None:
        self.finished.append(command_id)

    def has_durable_cancel_intent(self, _run_id: str) -> bool:
        return False


class _Sink:
    def __init__(self) -> None:
        self.items: list[object] = []

    def append(self, item: object) -> None:
        self.items.append(item)


class _VerificationRepo:
    def __init__(self) -> None:
        self.items: list[object] = []

    def list_by_attempt(self, _attempt_id: str) -> list[object]:
        return list(self.items)

    def get_latest_for_attempt(self, _attempt_id: str) -> object | None:
        return self.items[-1] if self.items else None

    def insert(self, item: object) -> None:
        self.items.append(item)


class _Actions(_ByIdRepo):
    def __init__(
        self, values: dict[str, Any], verification_status: ActionStatusV1 | None = None
    ) -> None:
        super().__init__(values)
        self.verification_status = verification_status

    def list_dependents(self, _action_id: str) -> tuple[str, ...]:
        return ()

    def is_dependency_ready(self, _action_id: str) -> bool:
        return True

    def update_if_version_and_status(self, value_id: str, *args: object, **kwargs: object) -> bool:
        item = self.values.get(value_id)
        if item is None:
            return False
        values = args[-1] if args and isinstance(args[-1], dict) else kwargs
        status = self.verification_status or values.get("status")
        if status is not None:
            item.status = status.value if isinstance(status, ActionStatusV1) else status
        if "version" in values:
            item.version = values["version"]
        return True


class _Runs(_ByIdRepo):
    def __init__(self, values: dict[str, Any]) -> None:
        super().__init__(values)
        self.recovery_required = 0

    def set_recovery_required(self, _run_id: str) -> None:
        self.recovery_required += 1

    def update_if_version_and_status(
        self, value_id: str, *args: object, **kwargs: object
    ) -> Any | None:
        updated = super().update_if_version_and_status(value_id, *args, **kwargs)
        if updated is not None and RunStatusV1(updated.status) is RunStatusV1.RECOVERY_REQUIRED:
            self.recovery_required += 1
        return updated


class _Uow:
    def __init__(
        self,
        *,
        action: Any,
        attempt: Any,
        approval: Any | None = None,
        plan: Any | None = None,
        run: Any | None = None,
        verification_status: ActionStatusV1 | None = None,
    ) -> None:
        self.actions = _Actions({action.id: action}, verification_status)
        self.execution_attempts = _ByIdRepo({attempt.id: attempt})
        self.approvals = _ByIdRepo({} if approval is None else {approval.id: approval})
        self.plans = _ByIdRepo({} if plan is None else {plan.id: plan}, plan_bundles=True)
        self.runs = _Runs({} if run is None else {run.id: run})
        self.resource_refs = _ByIdRepo({})
        self.command_receipts = _CommandReceipts()
        self.verifications = _VerificationRepo()
        self.approvals = self.approvals
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
    def __init__(self, snapshot: ResourceSnapshot, unit_of_work: _Uow) -> None:
        self.snapshot = snapshot
        self.unit_of_work = unit_of_work
        self.prepare_calls = 0
        self.execute_calls = 0

    def prepare_write(self, *, arguments: dict[str, object], **_kwargs: object) -> object:
        assert self.unit_of_work.commits == 1
        self.prepare_calls += 1
        return SimpleNamespace(arguments=arguments)

    def execute_write(self, _request: object) -> ResourceSnapshot:
        assert self.unit_of_work.commits == 1
        self.execute_calls += 1
        return self.snapshot


class _RecoveryConnector:
    def __init__(
        self,
        *,
        candidates: list[ResourceSnapshot] | None = None,
        snapshot: ResourceSnapshot | None = None,
        absent: bool = False,
    ) -> None:
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


def _task_snapshot(
    *,
    title: str,
    resource_id: str = "task-1",
    version: str = "1",
    extra: dict[str, object] | None = None,
) -> ResourceSnapshot:
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


def _execution_fixture(
    *,
    attempt_status: ExecutionAttemptStatusV1 = ExecutionAttemptStatusV1.CLAIMED,
    run_status: RunStatusV1 = RunStatusV1.WAITING_APPROVAL,
) -> tuple[_Uow, str, _ExecutionConnector]:
    arguments = {"task_list_id": "list-1", "payload": {"title": "C3"}}
    arguments_hash = calculate_canonical_json_hash(arguments)
    action = SimpleNamespace(
        id="action-1",
        plan_id="plan-1",
        tool_name="tasks_create_task",
        arguments_json=dumps(arguments),
        arguments_hash=arguments_hash,
        status=ActionStatusV1.EXECUTING.value,
        version=1,
        updated_at_ms=1_000,
    )
    approval = SimpleNamespace(
        id="approval-1",
        action_id="action-1",
        status=ApprovalStatusV1.CONSUMED,
        recovery_fingerprint="fp-1",
        consumed_at_ms=1_000,
    )
    attempt = SimpleNamespace(
        id="attempt-1", approval_id="approval-1", status=attempt_status, version=1
    )
    plan = SimpleNamespace(
        id="plan-1", run_id="run-1", status=PlanStatusV1.WAITING_APPROVAL, revision_no=1
    )
    run = SimpleNamespace(id="run-1", status=run_status, version=1)
    uow = _Uow(action=action, attempt=attempt, approval=approval, plan=plan, run=run)
    connector = _ExecutionConnector(_task_snapshot(title="C3"), uow)
    token = issue_claim_token(
        {
            "version": CLAIM_TOKEN_VERSION,
            "action_id": "action-1",
            "approval_id": "approval-1",
            "attempt_id": "attempt-1",
            "execution_attempt_id": "attempt-1",
            "tool_name": "tasks_create_task",
            "arguments_hash": arguments_hash,
            "approval_arguments_hash": arguments_hash,
            "execution_arguments_hash": arguments_hash,
            "service_instance_id": _SERVICE_INSTANCE_ID,
            "nonce": "nonce-1",
            "issued_at_ms": 1_000,
            "expires_at_ms": 31_000,
        },
        signing_secret=_SIGNING_SECRET,
    )
    return uow, token, connector


def _execute_handler(
    uow: _Uow, connector: _ExecutionConnector, now_ms: int = 2_000
) -> ExecuteActionHandler:
    return ExecuteActionHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, uow),
        connector_execution=cast(LegacyWriteResultMaterializer, connector),
        now_ms=lambda: now_ms,
        signing_secret=_SIGNING_SECRET,
        service_instance_id=_SERVICE_INSTANCE_ID,
    )


def test_execute_action_rejects_invalid_and_expired_tokens_before_connector() -> None:
    uow, token, connector = _execution_fixture()
    handler = _execute_handler(uow, connector)
    bad_token = issue_claim_token(
        {
            "version": CLAIM_TOKEN_VERSION,
            "action_id": "action-1",
            "approval_id": "approval-1",
            "attempt_id": "attempt-1",
            "execution_attempt_id": "attempt-1",
            "tool_name": "tasks_create_task",
            "arguments_hash": "0" * 64,
            "approval_arguments_hash": "0" * 64,
            "execution_arguments_hash": "0" * 64,
            "service_instance_id": _SERVICE_INSTANCE_ID,
            "nonce": "bad",
            "issued_at_ms": 1_000,
            "expires_at_ms": 31_000,
        },
        signing_secret="wrong-secret",
    )
    with pytest.raises(PermissionError):
        handler(ExecuteActionCommand("action-1", bad_token))
    expired = _execute_handler(uow, connector, 31_000)
    with pytest.raises(PermissionError, match="expired"):
        expired(ExecuteActionCommand("action-1", token))
    assert connector.execute_calls == 0


def test_execute_action_rejects_cancel_binding_nonclaimed_and_used_nonce() -> None:
    cancelled_uow, token, connector = _execution_fixture(run_status=RunStatusV1.CANCEL_REQUESTED)
    with pytest.raises(PermissionError, match="cancellation"):
        _execute_handler(cancelled_uow, connector)(ExecuteActionCommand("action-1", token))
    assert connector.execute_calls == 0

    nonclaimed_uow, token2, connector2 = _execution_fixture(
        attempt_status=ExecutionAttemptStatusV1.SUCCEEDED
    )
    with pytest.raises(PermissionError, match="CLAIMED"):
        _execute_handler(nonclaimed_uow, connector2)(ExecuteActionCommand("action-1", token2))
    assert connector2.execute_calls == 0

    uow, token3, connector3 = _execution_fixture()
    handler = _execute_handler(uow, connector3)
    result = handler(ExecuteActionCommand("action-1", token3))
    assert result.snapshot.resource_id == "task-1"
    assert connector3.prepare_calls == connector3.execute_calls == 1
    with pytest.raises(PermissionError, match="already been used"):
        handler(ExecuteActionCommand("action-1", token3))
    assert connector3.execute_calls == 1

    bound_uow, bound_token, connector4 = _execution_fixture()
    action = bound_uow.actions.get("action-1")
    assert action is not None
    action.tool_name = "tasks_update_task"
    with pytest.raises(PermissionError, match="binding mismatch"):
        _execute_handler(bound_uow, connector4)(ExecuteActionCommand("action-1", bound_token))
    assert connector4.execute_calls == 0


def _recovery_uow(
    *,
    tool_name: str,
    expected: Mapping[str, object] | None = None,
    source: Mapping[str, object] | None = None,
    arguments: Mapping[str, object] | None = None,
) -> _Uow:
    action = SimpleNamespace(
        id="action-1",
        plan_id="plan-1",
        tool_name=tool_name,
        arguments_json=dumps(arguments or {}),
        expected_json=dumps(expected or {}),
        target_resource_ref_id=None,
        status=ActionStatusV1.UNKNOWN_RESULT.value,
        version=3,
    )
    attempt = SimpleNamespace(
        id="attempt-1", approval_id="approval-1", status=ExecutionAttemptStatusV1.UNKNOWN_RESULT
    )
    approval = SimpleNamespace(
        id="approval-1",
        action_id="action-1",
        recovery_fingerprint="fp-1",
        source_snapshot_json=dumps(source or {}),
    )
    return _Uow(action=action, attempt=attempt, approval=approval)


def _applied_recovery(status: str = ActionStatusV1.EXECUTED.value) -> RecoverExistingResultResult:
    return RecoverExistingResultResult(
        True, ResultCode.TRANSITION_APPLIED.value, "action-1", status, 4, (), attempt_id="attempt-1"
    )


def _failed_recovery() -> ResolveAsFailedResult:
    return ResolveAsFailedResult(
        True,
        ResultCode.TRANSITION_APPLIED.value,
        "action-1",
        ActionStatusV1.FAILED.value,
        4,
        (),
        attempt_id="attempt-1",
    )


def test_create_send_and_delete_recovery_never_blind_write() -> None:
    for handler_type, command_type, tool_name in (
        (RecoverCreateHandler, RecoverCreateCommand, "tasks_create_task"),
        (RecoverSendHandler, RecoverSendCommand, "gmail_send"),
    ):
        uow = _recovery_uow(tool_name=tool_name)
        connector = _RecoveryConnector(
            candidates=[_task_snapshot(title="a"), _task_snapshot(title="b", resource_id="task-2")]
        )
        result = cast(Any, handler_type)(
            unit_of_work_factory=lambda uow=uow: cast(UnitOfWork, uow),
            connector_execution=cast(LegacyWriteResultMaterializer, connector),
            recover_existing_result=lambda _command: _applied_recovery(),
        )(cast(Any, command_type)("cmd", "hash", "action-1", "attempt-1", 3, 1))
        assert result.result_code == ResultCode.RECOVERY_REQUIRED.value
        assert connector.write_calls == 0

    delete_uow = _recovery_uow(
        tool_name="tasks_delete_task", arguments={"task_id": "task-1", "task_list_id": "list-1"}
    )
    present_connector = _RecoveryConnector(snapshot=_task_snapshot(title="present"))
    present = RecoverDeleteHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, delete_uow),
        connector_execution=cast(LegacyWriteResultMaterializer, present_connector),
        recover_existing_result=lambda _command: _applied_recovery(),
    )(RecoverDeleteCommand("cmd-p", "hash", "action-1", "attempt-1", 3, 1))
    assert present.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert present_connector.write_calls == 0

    absent_connector = _RecoveryConnector(absent=True)
    absent = RecoverDeleteHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, delete_uow),
        connector_execution=cast(LegacyWriteResultMaterializer, absent_connector),
        recover_existing_result=lambda _command: _applied_recovery(),
    )(RecoverDeleteCommand("cmd-a", "hash", "action-1", "attempt-1", 3, 1))
    assert absent.applied is True
    assert absent_connector.write_calls == 0


def test_update_recovery_uses_canonical_subset_projection_for_all_three_states() -> None:
    arguments = {"task_id": "task-1", "task_list_id": "list-1", "payload": {"title": "after"}}
    expected = {"payload": {"title": "after"}}
    source = {"resource_id": "task-1", "version": "1", "payload": {"title": "before"}}
    recovered: list[object] = []
    failed: list[object] = []

    def recover(command: RecoverExistingResultCommand) -> RecoverExistingResultResult:
        recovered.append(command)
        return _applied_recovery()

    def fail(command: ResolveAsFailedCommand) -> ResolveAsFailedResult:
        failed.append(command)
        return _failed_recovery()

    def run(snapshot: ResourceSnapshot, command_id: str) -> RecoverUpdateResult:
        uow = _recovery_uow(
            tool_name="tasks_update_task", expected=expected, source=source, arguments=arguments
        )
        return RecoverUpdateHandler(
            unit_of_work_factory=lambda: cast(UnitOfWork, uow),
            connector_execution=cast(
                LegacyWriteResultMaterializer, _RecoveryConnector(snapshot=snapshot)
            ),
            recover_existing_result=recover,
            resolve_as_failed=fail,
        )(RecoverUpdateCommand(command_id, "hash", "action-1", "attempt-1", 3, 1))

    expected_result = run(
        _task_snapshot(title="after", version="2", extra={"notes": "provider-extra"}), "cmd-e"
    )
    assert expected_result.action_status == ActionStatusV1.EXECUTED.value
    assert len(recovered) == 1 and failed == []

    source_result = run(
        _task_snapshot(title="before", version="1", extra={"notes": "irrelevant-extra"}), "cmd-s"
    )
    assert source_result.action_status == ActionStatusV1.FAILED.value
    assert len(failed) == 1

    third_result = run(
        _task_snapshot(title="someone-else", version="3", extra={"notes": "extra"}), "cmd-t"
    )
    assert third_result.applied is False
    assert third_result.result_code == ResultCode.RECOVERY_REQUIRED.value


def _verification_uow(
    *,
    expected_title: str = "C3",
    verification_status: ActionStatusV1 = ActionStatusV1.VERIFIED,
    attempt_status: ExecutionAttemptStatusV1 = ExecutionAttemptStatusV1.SUCCEEDED,
    approval_action_id: str = "action-1",
) -> _Uow:
    action = SimpleNamespace(
        id="action-1",
        plan_id="plan-1",
        tool_name="tasks_update_task",
        arguments_json=dumps(
            {"task_id": "task-1", "task_list_id": "list-1", "payload": {"title": expected_title}}
        ),
        expected_json=dumps({"payload": {"title": expected_title}}),
        target_resource_ref_id=None,
        status=ActionStatusV1.EXECUTED.value,
        effect_type="UPDATE",
        version=1,
    )
    attempt = SimpleNamespace(
        id="attempt-1", approval_id="approval-1", status=attempt_status, result_resource_ref_id=None
    )
    approval = SimpleNamespace(id="approval-1", action_id=approval_action_id)
    plan = SimpleNamespace(id="plan-1", run_id="run-1")
    run = SimpleNamespace(id="run-1", status=RunStatusV1.VERIFYING, version=1)
    return _Uow(
        action=action,
        attempt=attempt,
        approval=approval,
        plan=plan,
        run=run,
        verification_status=verification_status,
    )


def test_verification_normalization_valid_chain_and_mismatch_semantics() -> None:
    normalized = normalize_actual_verification_projection(
        tool_name="tasks_update_task",
        actual={"payload": {"title": "C3", "due": "2026-08-22T00:00:00Z"}},
    )
    normalized_payload = cast(dict[str, object], normalized["payload"])
    assert normalized_payload["due"] == "2026-08-22"
    assert calculate_verification_subset_diff({"payload": {"title": "C3"}}, normalized) == []

    valid_uow = _verification_uow()
    valid_connector = _VerificationConnector(
        snapshot=_task_snapshot(title="C3", extra={"notes": "extra"})
    )
    valid = VerifyActionHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, valid_uow),
        now_ms=lambda: 10_000,
        connector_execution=cast(LegacyWriteResultMaterializer, valid_connector),
    )(VerifyActionCommand("verify-ok", "hash", "action-1", "attempt-1", 1, "verification-1"))
    assert valid.applied is True
    assert valid.action_status == ActionStatusV1.VERIFIED.value
    assert valid_connector.read_calls == 1

    mismatch_uow = _verification_uow(
        expected_title="expected", verification_status=ActionStatusV1.MISMATCH
    )
    mismatch = VerifyActionHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, mismatch_uow),
        now_ms=lambda: 10_000,
        connector_execution=cast(
            LegacyWriteResultMaterializer,
            _VerificationConnector(snapshot=_task_snapshot(title="actual")),
        ),
    )(VerifyActionCommand("verify-m", "hash", "action-1", "attempt-1", 1, "verification-2"))
    assert mismatch.action_status == ActionStatusV1.MISMATCH.value
    assert mismatch_uow.runs.recovery_required == 1


def test_verification_foreign_succeeded_attempt_fails_closed_before_read() -> None:
    uow = _verification_uow(approval_action_id="foreign-action")
    connector = _VerificationConnector(snapshot=_task_snapshot(title="C3"))
    result = VerifyActionHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, uow),
        now_ms=lambda: 10_000,
        connector_execution=cast(LegacyWriteResultMaterializer, connector),
    )(VerifyActionCommand("verify-foreign", "hash", "action-1", "attempt-1", 1, "verification-f"))
    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    assert connector.read_calls == connector.write_calls == 0
    assert uow.verifications.items == []


def test_verification_unknown_result_fails_closed_before_read() -> None:
    uow = _verification_uow(attempt_status=ExecutionAttemptStatusV1.UNKNOWN_RESULT)
    connector = _VerificationConnector(snapshot=_task_snapshot(title="C3"))
    result = VerifyActionHandler(
        unit_of_work_factory=lambda: cast(UnitOfWork, uow),
        now_ms=lambda: 10_000,
        connector_execution=cast(LegacyWriteResultMaterializer, connector),
    )(VerifyActionCommand("verify-unknown", "hash", "action-1", "attempt-1", 1, "verification-u"))
    assert result.applied is False
    assert result.result_code == ResultCode.STATE_CONFLICT.value
    assert connector.read_calls == connector.write_calls == 0
