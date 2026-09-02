"""Preflight reauth routing tests for the LangGraph structural driver."""

from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.write_execution_driver import (
    WriteExecutionDisposition,
    WriteExecutionPhaseRequest,
    WriteExecutionStructuralDriver,
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

    def current_run(self, _run_id: str) -> tuple[str, int]:
        return "ANALYZING", 7

    def project_persisted_query(self, **_kwargs: object) -> object:
        return object()

    def run_id_for_action(self, _action_id: str) -> str:
        return "run-1"


@pytest.mark.parametrize(
    "code",
    [
        GoogleWorkspaceErrorCode.AUTH_EXPIRED,
        GoogleWorkspaceErrorCode.PERMISSION_DENIED,
    ],
)
def test_preflight_credential__loss_requires__reauth_before_claim(
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

    coordinator = WriteExecutionStructuralDriver(
        id_factory=lambda: "generated-id",
        request_hash=lambda _payload: "request-hash",
        should_stop_for_cancel=lambda _run_id: False,
        preflight_write=cast(Any, preflight),
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
