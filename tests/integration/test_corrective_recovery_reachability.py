"""Production reachability regressions for corrective-plan continuation."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.corrective_plan_reachability import (
    CorrectivePlanContinuationRequired,
)
from google_work_agent.adapters.langgraph.freshness_workflow import (
    LangGraphWorkflowRuntime,
)
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.use_cases.recovery.resolve_mismatch_recovery import (
    ResolveMismatchRecoveryHandler,
)
from google_work_agent.application.write_actions import (
    RecoveryResolutionKind,
    ResolveMismatchRecoveryCommand,
    ResolveMismatchRecoveryService,
)
from google_work_agent.ports import (
    WorkflowCorrelationContext,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
)
from tests.integration.persistence.test_corrective_plan_persistence import (
    _aggregate_snapshot,
    _persist,
    _prepare,
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


def test_save_only_publish_failure_is_typed_and_leaves_run_nonterminal(
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


def test_runtime_projects_only_typed_corrective_condition_as_existing_accepted_outcome() -> None:
    result = LangGraphWorkflowRuntime._resume_corrective_plan_safely(
        cast(Any, _SafeResumeHarness(generic_failure=False)),
        _resume_request(),
    )

    assert result.outcome is WorkflowOutcome.ACCEPTED
    assert result.payload == {"phase": "SOLUTION_PLANNING"}


def test_runtime_does_not_swallow_generic_workflow_exception() -> None:
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


def test_startup_open_run_recovery_routes_checkpoint_marker_to_corrective_resume() -> None:
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


def test_resolve_recovery_command_replay_returns_original_reserved_plan(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "corrective-command-replay.db"
    harness, _, _ = _prepare(database_path)

    replay = ResolveMismatchRecoveryService(
        unit_of_work_factory=cast(Any, harness._unit_of_work_factory),
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


def test_production_callers_preserve_generic_failure_and_expose_real_retry_triggers() -> None:
    process_source = inspect.getsource(LocalRunCoordinator._process_item)
    startup_source = inspect.getsource(LocalRunCoordinator.start)
    recovery_handler_source = inspect.getsource(ResolveMismatchRecoveryHandler.__call__)
    recovery_source = inspect.getsource(LangGraphWorkflowRuntime.recover_open_run)

    # Generic runtime/programming failures remain terminalized exactly as before.
    assert "except Exception as error:" in process_source
    assert "WorkflowOutcome.FAILED" in process_source

    # Existing startup recovery enqueues unfinished PLANNING runs as recover work.
    assert "list_open_runs()" in startup_source
    assert 'kind="recover"' in startup_source
    assert "RunStatus.PLANNING" not in startup_source

    # Same-process command replay has a concrete producer for the same
    # registered corrective continuation.
    assert 'resume_kind="RECOVERY_CORRECTIVE_PLAN"' in recovery_handler_source
    assert 'resume_payload={"plan_id": result.plan_id}' in recovery_handler_source

    # Restart recovery consumes the durable checkpoint marker instead of
    # falling through to generic open-run recovery.
    assert '"__reserved_corrective_plan_id__"' in recovery_source
    assert 'resume_kind="RECOVERY_CORRECTIVE_PLAN"' in recovery_source
