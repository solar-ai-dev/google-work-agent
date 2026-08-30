from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.application.use_cases.execution_attempt.execution_phase import (
    WriteExecutionDisposition,
    WriteExecutionPhaseCoordinator,
    WriteExecutionPhaseRequest,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteRunResponse,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class _Call:
    def __init__(
        self,
        name: str,
        calls: list[str],
        *,
        result: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self._name = name
        self._calls = calls
        self._result = result
        self._error = error

    def __call__(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self._calls.append(self._name)
        if self._error is not None:
            raise self._error
        return self._result if self._result is not None else object()


class _RunRepository:
    def get(self, run_id: str) -> object | None:
        return SimpleNamespace(version=7) if run_id == "run-1" else None


class _RunVersionUnitOfWork:
    def __init__(self) -> None:
        self.runs = _RunRepository()

    def __enter__(self) -> "_RunVersionUnitOfWork":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _run_version_uow() -> UnitOfWork:
    return cast(UnitOfWork, _RunVersionUnitOfWork())


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
    reauth = _Call(
        "require_reauth",
        calls,
        result=WriteRunResponse(
            applied=True,
            result_code=ResultCode.TRANSITION_APPLIED.value,
            run_id="run-1",
            run_status=RunStatusV1.REAUTH_REQUIRED.value,
            run_version=8,
            plan_id="plan-1",
            plan_status="ACTIVE",
            result_kind="REAUTH_REQUIRED",
        ),
    )
    unused = _Call("unexpected", calls)

    coordinator = WriteExecutionPhaseCoordinator(
        unit_of_work_factory=cast(Callable[[], UnitOfWork], _run_version_uow),
        id_factory=lambda: "generated-id",
        request_hash=lambda _payload: "request-hash",
        should_stop_for_cancel=lambda _run_id: False,
        preflight_write=cast(Any, preflight),
        expire_approval=None,
        refresh_expired_action=None,
        claim_execution=cast(Any, claim),
        build_claim_context=cast(Any, unused),
        begin_execution_attempt=cast(Any, unused),
        abort_claimed_execution=cast(Any, unused),
        connector_execution=cast(Any, unused),
        classify_dispatch_result=cast(Any, unused),
        store_write_success=cast(Any, unused),
        begin_verification=cast(Any, unused),
        verify_effect=cast(Any, unused),
        store_verification=cast(Any, unused),
        require_recovery=cast(Any, unused),
        resolve_recovery=cast(Any, unused),
        mark_write_failed=cast(Any, unused),
        mark_write_unknown=cast(Any, unused),
        service_instance_id="service-1",
        mcp_process_instance_id=lambda: "mcp-1",
        require_write_reauth=cast(Any, reauth),
        lookup_unknown_result=cast(Any, unused),
        recover_existing_result=cast(Any, unused),
        resolve_as_failed=cast(Any, unused),
        resolve_resource_ref=cast(Any, unused),
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
