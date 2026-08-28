from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.support.legacy_write.execute_claimed_action import (
    ExecuteClaimedActionCommand,
    ExecuteClaimedActionHandler,
)

from google_work_agent.application.use_cases.execution_attempt.mark_failed import (
    MarkFailedCommand,
    MarkFailedHandler,
)
from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultCommand,
    MarkUnknownResultHandler,
)
from google_work_agent.ports import (
    DeliveryCertainty,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
)


def _unexpected_uow() -> object:
    raise AssertionError("invalid delivery classification must fail before persistence")


def test_failed_requires_definitive_not_sent() -> None:
    handler = MarkFailedHandler(
        unit_of_work_factory=_unexpected_uow,  # type: ignore[arg-type]
        now_ms=lambda: 1,
    )
    with pytest.raises(ValueError, match="NOT_SENT"):
        handler(
            MarkFailedCommand(
                "cmd-failed",
                "hash",
                "action-1",
                "attempt-1",
                1,
                1,
                DeliveryCertainty.MAY_HAVE_BEEN_SENT,
                "TIMEOUT",
                "uncertain",
            )
        )


def test_unknown_result_rejects_definitive_not_sent() -> None:
    handler = MarkUnknownResultHandler(
        unit_of_work_factory=_unexpected_uow,  # type: ignore[arg-type]
        now_ms=lambda: 1,
        resume_target_registry=SimpleNamespace(),  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="possibly dispatched"):
        handler(
            MarkUnknownResultCommand(
                "cmd-unknown",
                "hash",
                "action-1",
                "attempt-1",
                1,
                1,
                DeliveryCertainty.NOT_SENT,
                "CONNECTION_CLOSED",
                "definitively not sent",
            )
        )


def _command() -> ExecuteClaimedActionCommand:
    return ExecuteClaimedActionCommand(
        command_id="finalize-1",
        request_hash="hash",
        action_id="action-1",
        attempt_id="attempt-1",
        expected_action_version=1,
        expected_attempt_version=1,
        claim_token="claim-token",
    )


def _gateway_error(*, delivered: bool, mutated: bool) -> GoogleWorkspaceGatewayError:
    return GoogleWorkspaceGatewayError(
        code=GoogleWorkspaceErrorCode.TIMEOUT,
        message="connector execution outcome",
        delivered=delivered,
        mutated=mutated,
        mcp_request_id="mcp-c3r",
    )


@pytest.mark.parametrize(
    ("delivered", "mutated", "expected_certainty", "expected_route"),
    [
        (False, False, DeliveryCertainty.NOT_SENT, "failed"),
        (True, False, DeliveryCertainty.MAY_HAVE_BEEN_SENT, "unknown"),
        (True, True, DeliveryCertainty.SENT_RESPONSE_LOST, "unknown"),
    ],
)
def test_real_execution_error_routes_to_exactly_one_durable_finalizer(
    delivered: bool,
    mutated: bool,
    expected_certainty: DeliveryCertainty,
    expected_route: str,
) -> None:
    calls: list[tuple[str, object]] = []

    def execute(_command: object) -> object:
        raise _gateway_error(delivered=delivered, mutated=mutated)

    def failed(command: MarkFailedCommand) -> object:
        calls.append(("failed", command))
        return SimpleNamespace(route="failed")

    def unknown(command: MarkUnknownResultCommand) -> object:
        calls.append(("unknown", command))
        return SimpleNamespace(route="unknown")

    def success(command: object) -> object:
        calls.append(("success", command))
        return SimpleNamespace(route="success")

    result = ExecuteClaimedActionHandler(
        execute_action=execute,  # type: ignore[arg-type]
        store_success=success,  # type: ignore[arg-type]
        mark_failed=failed,  # type: ignore[arg-type]
        mark_unknown_result=unknown,  # type: ignore[arg-type]
    )(_command())

    assert result.route == expected_route  # type: ignore[union-attr]
    assert [name for name, _command_value in calls] == [expected_route]
    routed_command = calls[0][1]
    assert routed_command.delivery_certainty is expected_certainty
    if expected_route == "unknown":
        assert calls[0][0] != "failed"
        assert routed_command.mcp_request_id == "mcp-c3r"
    else:
        assert calls[0][0] != "unknown"


def test_precondition_error_is_not_misclassified_as_delivery_outcome() -> None:
    calls: list[str] = []

    def execute(_command: object) -> object:
        raise PermissionError("claim token expired")

    def unexpected(_command: object) -> object:
        calls.append("finalized")
        return SimpleNamespace()

    handler = ExecuteClaimedActionHandler(
        execute_action=execute,  # type: ignore[arg-type]
        store_success=unexpected,  # type: ignore[arg-type]
        mark_failed=unexpected,  # type: ignore[arg-type]
        mark_unknown_result=unexpected,  # type: ignore[arg-type]
    )
    with pytest.raises(PermissionError, match="expired"):
        handler(_command())
    assert calls == []
