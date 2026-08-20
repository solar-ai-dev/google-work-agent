from collections.abc import Callable
from typing import cast

import pytest

from google_work_agent.application.execution_phase import (
    WriteExecutionDisposition,
    WriteExecutionPhaseCoordinator,
    WriteExecutionPhaseRequest,
)
from google_work_agent.application.write_actions import (
    ClaimWriteActionService,
    ExecuteWriteActionService,
    MarkWriteActionFailedService,
    MarkWriteActionUnknownResultService,
    PreflightWriteActionService,
    RecoverUnknownCreateActionService,
    RecoverUnknownDeleteActionService,
    RecoverUnknownSendActionService,
    RecoverUnknownUpdateActionService,
    RequireWriteReauthService,
    StoreWriteActionSuccessService,
    VerifyWriteActionService,
)
from google_work_agent.ports import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    UnitOfWork,
)


class _Call:
    def __init__(self, name: str, calls: list[str], *, error: Exception | None = None) -> None:
        self._name = name
        self._calls = calls
        self._error = error

    def __call__(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self._calls.append(self._name)
        if self._error is not None:
            raise self._error
        return object()


def _unexpected_uow() -> UnitOfWork:
    raise AssertionError("preflight auth handling must not query action state")


@pytest.mark.parametrize(
    "code",
    [
        GoogleWorkspaceErrorCode.AUTH_EXPIRED,
        GoogleWorkspaceErrorCode.PERMISSION_DENIED,
    ],
)
def test_preflight_credential_loss_requires_reauth_before_claim(
    code: GoogleWorkspaceErrorCode,
) -> None:
    calls: list[str] = []
    preflight = _Call(
        "preflight",
        calls,
        error=GoogleWorkspaceGatewayError(
            code=code,
            message="credential unavailable during preflight",
            delivered=False,
            mutated=False,
        ),
    )
    claim = _Call("claim", calls)
    reauth = _Call("require_reauth", calls)
    unused = _Call("unexpected", calls)

    coordinator = WriteExecutionPhaseCoordinator(
        unit_of_work_factory=cast(Callable[[], UnitOfWork], _unexpected_uow),
        id_factory=lambda: "generated-id",
        request_hash=lambda _payload: "request-hash",
        should_stop_for_cancel=lambda _run_id: False,
        preflight_write=cast(PreflightWriteActionService, preflight),
        claim_write=cast(ClaimWriteActionService, claim),
        execute_write=cast(ExecuteWriteActionService, unused),
        store_write_success=cast(StoreWriteActionSuccessService, unused),
        begin_verification=lambda _run_id: None,
        verify_write=cast(VerifyWriteActionService, unused),
        mark_write_failed=cast(MarkWriteActionFailedService, unused),
        mark_write_unknown=cast(MarkWriteActionUnknownResultService, unused),
        require_write_reauth=cast(RequireWriteReauthService, reauth),
        recover_unknown_create=cast(RecoverUnknownCreateActionService, unused),
        recover_unknown_send=cast(RecoverUnknownSendActionService, unused),
        recover_unknown_delete=cast(RecoverUnknownDeleteActionService, unused),
        recover_unknown_update=cast(RecoverUnknownUpdateActionService, unused),
    )

    result = coordinator.execute(
        WriteExecutionPhaseRequest(
            run_id="run-1",
            action_id="action-1",
            action_version=7,
        )
    )

    assert result.disposition is WriteExecutionDisposition.REAUTH_REQUIRED
    assert result.safe_error_code == code.value
    assert calls == ["preflight", "require_reauth"]
    assert "claim" not in calls
