"""Production reachability regressions for corrective-plan continuation."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.corrective_plan_reachability import (
    CorrectivePlanContinuationRequired,
)
from google_work_agent.adapters.langgraph.main.workflow import (
    LangGraphWorkflowRuntime,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import ResolveRecoveryHandler
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
)
from tests.support.checkpoint import sqlite_checkpoint
from tests.support.corrective_plan_persistence import (
    _aggregate_snapshot,
    _persist,
    _prepare,
)
from tests.support.resolve_recovery_adapter import (
    RecoveryResolutionKind,
    ResolveMismatchRecoveryCommand,
    ResolveMismatchRecoveryService,
)


def _correlation() -> WorkflowCorrelationContext:
    return WorkflowCorrelationContext(
        request_id="request-1",
        command_id="resolve-corrective-1",
        api_contract_version="v1",
    )


def _resume_request() -> WorkflowResumeRequest:
    return WorkflowResumeRequest(
        run_id="run-1",
        workflow_key="thread-1",
        resume_kind="RECOVERY_CORRECTIVE_PLAN",
        resume_payload={"plan_id": "reserved-plan-2"},
        correlation=_correlation(),
    )


def test_save_only_publish__failure_is_typed__and_leaves_run_nonterminal(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "corrective-production-reachability.db"
    harness, state, draft = _prepare(database_path, fail_publish_once=True)

    with pytest.raises(
        CorrectivePlanContinuationRequired,
        match="injected publish failure",
    ) as caught:
        _persist(harness, state, draft)

    assert caught.value.run_id == "run-1"
    assert caught.value.plan_id == "reserved-plan-2"
    snapshot = _aggregate_snapshot(database_path)
    assert snapshot["plans"] == [
        ("old-plan", 1, "SUPERSEDED"),
        ("reserved-plan-2", 2, "DRAFT"),
    ]
    assert snapshot["run_status"] == "PLANNING"
    assert snapshot["rev3_count"] == 0
    assert snapshot["trace_counts"] == {"WRITE_PLAN_SAVED": 1}
    assert harness.save_calls == 1
    assert harness.publish_calls == 1
    assert state["__reserved_corrective_plan_id__"] == "reserved-plan-2"


class _SafeResumeHarness:
    def __init__(self, *, generic_failure: bool) -> None:
        self.generic_failure = generic_failure

    def _resume_corrective_plan(
        self,
        request: WorkflowResumeRequest,
    ) -> WorkflowInvocationResult:
        if self.generic_failure:
            raise RuntimeError("ordinary workflow failure")
        raise CorrectivePlanContinuationRequired(
            run_id=request.run_id,
            plan_id=cast(str, request.resume_payload["plan_id"]),
            cause=RuntimeError("publish boundary interrupted"),
        )

    @staticmethod
    def _result_from_thread(
        *,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        return WorkflowInvocationResult(
            run_id=run_id,
            workflow_key=workflow_key,
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"phase": "SOLUTION_PLANNING"},
        )


def test_runtime_projects_only__typed_corrective_condition__as_existing_accepted_outcome() -> None:
    result = LangGraphWorkflowRuntime._resume_corrective_plan_safely(
        cast(Any, _SafeResumeHarness(generic_failure=False)),
        _resume_request(),
    )

    assert result.outcome is WorkflowOutcome.ACCEPTED
    assert result.payload == {"phase": "SOLUTION_PLANNING"}


def test_runtime_does__not_swallow__generic_workflow_exception() -> None:
    with pytest.raises(RuntimeError, match="ordinary workflow failure"):
        LangGraphWorkflowRuntime._resume_corrective_plan_safely(
            cast(Any, _SafeResumeHarness(generic_failure=True)),
            _resume_request(),
        )


class _Snapshot:
    def __init__(self) -> None:
        self.values = {
            "run_id": "run-1",
            "__reserved_corrective_plan_id__": "reserved-plan-2",
        }


class _Graph:
    @staticmethod
    def get_state(_: dict[str, object]) -> _Snapshot:
        return _Snapshot()


class _StartupRecoveryHarness:
    def __init__(self) -> None:
        self._graph = _Graph()
        self.resume_request: WorkflowResumeRequest | None = None

    @staticmethod
    def _config_for_thread(workflow_key: str) -> dict[str, object]:
        return {"configurable": {"thread_id": workflow_key}}

    def _resume_corrective_plan_safely(
        self,
        request: WorkflowResumeRequest,
    ) -> WorkflowInvocationResult:
        self.resume_request = request
        return WorkflowInvocationResult(
            run_id=request.run_id,
            workflow_key=request.workflow_key,
            outcome=WorkflowOutcome.ACCEPTED,
            payload={},
        )


def test_startup_open_run__recovery_routes_checkpoint__marker_to_corrective_resume() -> None:
    harness = _StartupRecoveryHarness()
    recovery = WorkflowRecoveryRequest(
        run_id="run-1",
        workflow_key="thread-1",
        domain_status="PLANNING",
        domain_version=6,
        correlation=_correlation(),
    )

    result = LangGraphWorkflowRuntime.recover_open_run(
        cast(Any, harness),
        recovery,
    )

    assert result.outcome is WorkflowOutcome.ACCEPTED
    assert harness.resume_request is not None
    assert harness.resume_request.resume_kind == "RECOVERY_CORRECTIVE_PLAN"
    assert harness.resume_request.resume_payload == {"plan_id": "reserved-plan-2"}
    assert harness.resume_request.correlation == recovery.correlation


def test_resolve_recovery__command_replay_returns__original_reserved_plan(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "corrective-command-replay.db"
    harness, _, _ = _prepare(database_path)

    replay = ResolveMismatchRecoveryService(
        unit_of_work_factory=cast(Any, harness._unit_of_work_factory),
        checkpoint_port=sqlite_checkpoint(database_path),
        now_ms=lambda: 20,
    )(
        ResolveMismatchRecoveryCommand(
            command_id="resolve-corrective-1",
            request_hash="c" * 64,
            run_id="run-1",
            action_id="old-action-1",
            expected_run_version=5,
            resolution_kind=RecoveryResolutionKind.CREATE_CORRECTIVE_PLAN,
            corrective_plan_id="must-not-replace-reserved-plan",
        )
    )

    assert replay.applied is True
    assert replay.run_status == "PLANNING"
    assert replay.result_kind == "CORRECTIVE_PLAN_REQUIRED"
    assert replay.plan_id == "reserved-plan-2"


def test_production_recovery__exposes_real__retry_triggers() -> None:
    recovery_handler_source = inspect.getsource(ResolveRecoveryHandler._apply_resolution_effects)
    recovery_source = inspect.getsource(LangGraphWorkflowRuntime.recover_open_run)

    # The exact Application owner durably reserves the corrective Plan; runtime
    # continuation consumes that durable marker instead of transient payload.
    assert '"CORRECTIVE_PLAN_REQUIRED"' in recovery_handler_source
    assert "unit_of_work.plans.insert_revision(corrective)" in recovery_handler_source

    # Restart recovery consumes the durable checkpoint marker instead of
    # falling through to generic open-run recovery.
    assert '"__reserved_corrective_plan_id__"' in recovery_source
    assert 'resume_kind="RECOVERY_CORRECTIVE_PLAN"' in recovery_source
