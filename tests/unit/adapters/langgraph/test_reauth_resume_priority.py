from threading import Lock
from typing import cast

from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.main.resume_checkpoint import ResumeCheckpointMixin
from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.domain.run.model import RunStatusV1


class _UnusedGraph:
    pass


def _state() -> GraphState:
    return cast(
        GraphState,
        {
            "__workflow_control__": {
                "stage": "REAUTH_REQUIRED",
                "action_id": "action-1",
            }
        },
    )


def _coordinator(
    calls: list[str],
    *,
    unknown: bool = False,
    executed: bool = False,
    stalled: bool = False,
    run_status: str = RunStatusV1.REAUTH_REQUIRED.value,
) -> WorkflowInvocationCoordinator:
    def recovery(values: GraphState) -> GraphState:
        calls.append("recovery")
        return values

    def recover_executed(values: GraphState, run_id: str) -> GraphState:
        del run_id
        calls.append("verify")
        return values

    def resume_reauth(values: GraphState) -> GraphState:
        calls.append("action_execution")
        return values

    return WorkflowInvocationCoordinator(
        graph=_UnusedGraph(),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        start_node="request_understanding",
        initial_state=lambda _request: cast(GraphState, {}),
        current_run_status=lambda _run_id: run_status,
        latest_unknown_action=lambda _run_id: object() if unknown else None,
        recovery_node=recovery,
        has_executed_action=lambda _run_id: executed,
        recover_executed_actions=recover_executed,
        mark_stalled_claims_as_unknown=lambda _run_id: stalled,
        cancel_signal_lock=Lock(),
        cancel_signals=set(),
        resume_reauth_execution=resume_reauth,
    )


def test_preclaim_reauth_checkpoint_resumes_action_execution() -> None:
    calls: list[str] = []
    coordinator = _coordinator(calls)

    result = coordinator._continue_from_domain_facts(values=_state(), run_id="run-1")

    assert result is not None
    assert calls == ["action_execution"]


def test_unknown_result_recovery_wins_over_reauth_checkpoint() -> None:
    calls: list[str] = []
    coordinator = _coordinator(calls, unknown=True)

    coordinator._continue_from_domain_facts(values=_state(), run_id="run-1")

    assert calls == ["recovery"]


def test_executed_verification_wins_over_reauth_checkpoint() -> None:
    calls: list[str] = []
    coordinator = _coordinator(calls, executed=True)

    coordinator._continue_from_domain_facts(values=_state(), run_id="run-1")

    assert calls == ["verify"]


def test_stalled_claim_becomes_unknown_before_reauth_checkpoint_resume() -> None:
    calls: list[str] = []
    coordinator = _coordinator(calls, stalled=True)

    coordinator._continue_from_domain_facts(values=_state(), run_id="run-1")

    assert calls == ["recovery"]


def test_reauth_resume_requires_explicit_checkpoint_proof() -> None:
    calls: list[str] = []
    coordinator = _coordinator(calls)
    state = _state()
    state["__workflow_control__"] = {"stage": "OTHER", "action_id": "action-1"}

    result = coordinator._continue_from_domain_facts(values=state, run_id="run-1")

    assert result is None
    assert calls == []


def test_reauth_checkpoint_does_not_resume_when_domain_status_is_not_reauth() -> None:
    calls: list[str] = []
    coordinator = _coordinator(calls, run_status=RunStatusV1.EXECUTING.value)

    result = coordinator._continue_from_domain_facts(values=_state(), run_id="run-1")

    assert result is None
    assert calls == []


def test_startup_recovery_does_not_resume_preclaim_reauth_checkpoint() -> None:
    calls: list[str] = []
    coordinator = _coordinator(calls)

    result = coordinator._continue_from_domain_facts(
        values=_state(),
        run_id="run-1",
        allow_reauth_resume=False,
    )

    assert result is None
    assert calls == []


def test_read_execution_checkpoint_resumes_at_action_execution() -> None:
    runtime = cast(ResumeCheckpointMixin, object.__new__(ResumeCheckpointMixin))
    runtime._topology = ("request_understanding",)

    target = runtime._reauth_continuation_target(
        cast(GraphState, {"workflow_phase": WorkflowPhase.READ_EXECUTION.value})
    )

    assert target == "action_execution"


def test_not_sent_reauth_checkpoint_resumes_at_safe_action_reconciliation() -> None:
    runtime = cast(ResumeCheckpointMixin, object.__new__(ResumeCheckpointMixin))
    runtime._topology = ("request_understanding",)

    target = runtime._reauth_continuation_target(
        cast(GraphState, {"workflow_phase": WorkflowPhase.ACTION_EXECUTION.value})
    )

    assert target == "action_execution"
