from pathlib import Path

import pytest

from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.application.use_cases.operational_replay import (
    OperationalCommandConflict,
    OperationalCommandUncertain,
    execute_operational_command,
)
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


def test_operational_command_executes_once_and_replays_bounded_result(tmp_path: Path) -> None:
    replay = FilesystemOperationalCommandReplayAdapter(tmp_path)
    execution_refs: list[str] = []

    def execute(operation_ref: str) -> tuple[str, object]:
        execution_refs.append(operation_ref)
        return "result-1", {"accepted": True}

    first = execute_operational_command(
        replay_port=replay,
        command_id="command-1",
        operation_kind="TEST_OPERATION",
        request_payload={"value": 1},
        reconcile=lambda operation_ref: OperationalReconcileResultV1("SAFE_TO_RETRY", None, None),
        execute=execute,
    )
    second = execute_operational_command(
        replay_port=replay,
        command_id="command-1",
        operation_kind="TEST_OPERATION",
        request_payload={"value": 1},
        reconcile=lambda operation_ref: OperationalReconcileResultV1("SAFE_TO_RETRY", None, None),
        execute=execute,
    )

    assert first.replayed is False
    assert second.replayed is True
    assert second.bounded_result == {"accepted": True}
    assert execution_refs == [first.operation_ref]


def test_operational_command_rejects_same_identity_with_different_input(tmp_path: Path) -> None:
    replay = FilesystemOperationalCommandReplayAdapter(tmp_path)
    execute_operational_command(
        replay_port=replay,
        command_id="command-1",
        operation_kind="TEST_OPERATION",
        request_payload={"value": 1},
        reconcile=lambda operation_ref: OperationalReconcileResultV1("SAFE_TO_RETRY", None, None),
        execute=lambda operation_ref: ("result-1", {"accepted": True}),
    )

    with pytest.raises(OperationalCommandConflict):
        execute_operational_command(
            replay_port=replay,
            command_id="command-1",
            operation_kind="TEST_OPERATION",
            request_payload={"value": 2},
            reconcile=lambda operation_ref: OperationalReconcileResultV1(
                "SAFE_TO_RETRY", None, None
            ),
            execute=lambda operation_ref: ("result-2", {"accepted": False}),
        )


def test_reserved_command_reconciles_before_any_retry(tmp_path: Path) -> None:
    replay = FilesystemOperationalCommandReplayAdapter(tmp_path)
    execute_calls: list[str] = []

    with pytest.raises(RuntimeError, match="simulated crash"):
        execute_operational_command(
            replay_port=replay,
            command_id="command-1",
            operation_kind="TEST_OPERATION",
            request_payload={"value": 1},
            reconcile=lambda operation_ref: OperationalReconcileResultV1(
                "SAFE_TO_RETRY", None, None
            ),
            execute=lambda operation_ref: (_ for _ in ()).throw(RuntimeError("simulated crash")),
        )

    def must_not_execute(operation_ref: str) -> tuple[str, object]:
        execute_calls.append(operation_ref)
        return "unexpected", {"accepted": False}

    recovered = execute_operational_command(
        replay_port=replay,
        command_id="command-1",
        operation_kind="TEST_OPERATION",
        request_payload={"value": 1},
        reconcile=lambda operation_ref: OperationalReconcileResultV1(
            "COMPLETED", "result-recovered", {"accepted": True}
        ),
        execute=must_not_execute,
    )

    assert recovered.replayed is True
    assert recovered.result_ref == "result-recovered"
    assert execute_calls == []


def test_uncertain_reconciliation_never_executes_again(tmp_path: Path) -> None:
    replay = FilesystemOperationalCommandReplayAdapter(tmp_path)
    with pytest.raises(RuntimeError, match="simulated crash"):
        execute_operational_command(
            replay_port=replay,
            command_id="command-1",
            operation_kind="TEST_OPERATION",
            request_payload={"value": 1},
            reconcile=lambda operation_ref: OperationalReconcileResultV1(
                "SAFE_TO_RETRY", None, None
            ),
            execute=lambda operation_ref: (_ for _ in ()).throw(RuntimeError("simulated crash")),
        )

    with pytest.raises(OperationalCommandUncertain):
        execute_operational_command(
            replay_port=replay,
            command_id="command-1",
            operation_kind="TEST_OPERATION",
            request_payload={"value": 1},
            reconcile=lambda operation_ref: OperationalReconcileResultV1(
                "UNCERTAIN", "recovery-1", None
            ),
            execute=lambda operation_ref: (_ for _ in ()).throw(
                AssertionError("uncertain command must not execute")
            ),
        )
