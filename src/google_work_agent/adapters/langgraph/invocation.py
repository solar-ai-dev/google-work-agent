"""LangGraph invocation, checkpoint, and result projection boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from langgraph.types import Command

from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.domain import RunStatus
from google_work_agent.ports import (
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)


class WorkflowInvocationCoordinator:
    """Own graph invocation and translate persisted state into runtime results."""

    def __init__(
        self,
        *,
        graph: Any,
        graph_profile: GraphProfile,
        initial_state: Callable[[WorkflowStartRequest], GraphState],
        current_run_status: Callable[[str], str],
        latest_unknown_action: Callable[[str], object | None],
        recovery_node: Callable[[GraphState], GraphState],
        has_executed_action: Callable[[str], bool],
        recover_executed_actions: Callable[[GraphState, str], GraphState],
        mark_stalled_claims_as_unknown: Callable[[str], bool],
        cancel_signal_lock: Any,
        cancel_signals: set[str],
        resume_reauth_execution: Callable[[GraphState], GraphState] | None = None,
    ) -> None:
        self._graph = graph
        self._graph_profile = graph_profile
        self._initial_state = initial_state
        self._current_run_status = current_run_status
        self._latest_unknown_action = latest_unknown_action
        self._recovery_node = recovery_node
        self._has_executed_action = has_executed_action
        self._recover_executed_actions = recover_executed_actions
        self._mark_stalled_claims_as_unknown = mark_stalled_claims_as_unknown
        self._resume_reauth_execution = resume_reauth_execution
        self._cancel_signal_lock = cancel_signal_lock
        self._cancel_signals = cancel_signals

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        config = self.config_for_thread(request.workflow_key)
        self._graph.invoke(self._initial_state(request), config=config)
        return self.result_from_thread(
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        config = self.config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if not snapshot.values and not snapshot.next:
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.CHECKPOINT_MISSING,
                payload={},
            )
        if not self.is_profile_compatible(cast(GraphState, snapshot.values)):
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                payload={"graph_profile": self._graph_profile.value},
            )
        if snapshot.next:
            # A real interrupt() is pending (e.g. WAITING_CONFIRMATION,
            # PREFLIGHT_REAPPROVAL_REQUIRED) -- Command(resume=...) is the
            # correct way to feed the user's response back into it.
            self._graph.invoke(Command(resume=request.resume_payload), config=config)
            return self.result_from_thread(
                workflow_key=request.workflow_key,
                run_id=request.run_id,
            )
        # No pending interrupt: the prior invocation already reached END via
        # a normal conditional edge (e.g. REAUTH_REQUIRED, RECOVERY_REQUIRED
        # ending the graph without ever calling interrupt()).
        # Command(resume=...) is a no-op against a thread with no pending
        # task, so this resume must instead continue from persisted Domain
        # facts -- the same mechanism recover_open_run already uses.
        state = self._continue_from_domain_facts(
            values=cast(GraphState, snapshot.values),
            run_id=request.run_id,
            allow_reauth_resume=request.resume_kind == "REAUTH_COMPLETED",
        )
        if state is None:
            return self.result_from_thread(
                workflow_key=request.workflow_key,
                run_id=request.run_id,
            )
        return self.workflow_result_from_state(
            state=state,
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def request_cancel(self, request: WorkflowCancelRequest) -> WorkflowInvocationResult:
        with self._cancel_signal_lock:
            self._cancel_signals.add(request.run_id)
        return WorkflowInvocationResult(
            run_id=request.run_id,
            workflow_key=request.workflow_key,
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"phase": "cancel_requested", "reason_code": request.reason_code},
        )

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        config = self.config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if not snapshot.values and not snapshot.next:
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.CHECKPOINT_MISSING,
                payload={},
            )
        if not self.is_profile_compatible(cast(GraphState, snapshot.values)):
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                payload={"graph_profile": self._graph_profile.value},
            )
        state = self._continue_from_domain_facts(
            values=cast(GraphState, snapshot.values),
            run_id=request.run_id,
            allow_reauth_resume=False,
        )
        if state is None:
            return self.result_from_thread(
                workflow_key=request.workflow_key,
                run_id=request.run_id,
            )
        return self.workflow_result_from_state(
            state=state,
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def _continue_from_domain_facts(
        self,
        *,
        values: GraphState,
        run_id: str,
        allow_reauth_resume: bool = True,
    ) -> GraphState | None:
        """Resolve the next state from durable facts plus an explicit reauth resume gate.

        Unknown-result, already-executed, and stalled-claim facts always take
        precedence so a credential pause after Claim can never cause a blind
        write resend. A pre-Claim REAUTH_REQUIRED checkpoint is re-entered only
        for the explicit REAUTH_COMPLETED resume path, never startup recovery.
        """
        if self._latest_unknown_action(run_id) is not None:
            return self._recovery_node(values)
        if self._has_executed_action(run_id):
            return self._recover_executed_actions(values, run_id)
        if self._mark_stalled_claims_as_unknown(run_id):
            return self._recovery_node(values)
        if not allow_reauth_resume:
            return None
        if self._current_run_status(run_id) != RunStatus.REAUTH_REQUIRED.value:
            return None
        execution_summary = values.get("execution_summary")
        if not isinstance(execution_summary, Mapping):
            return None
        if execution_summary.get("result") != "REAUTH_REQUIRED":
            return None
        action_id = execution_summary.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            return None
        if self._resume_reauth_execution is None:
            return None
        return self._resume_reauth_execution(values)

    @staticmethod
    def config_for_thread(workflow_key: str) -> dict[str, object]:
        return {"configurable": {"thread_id": workflow_key}}

    def workflow_result_from_state(
        self,
        *,
        state: GraphState,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        return self.result_from_state(
            state=state,
            workflow_key=workflow_key,
            run_id=run_id,
        )

    def result_from_thread(self, *, workflow_key: str, run_id: str) -> WorkflowInvocationResult:
        snapshot = self._graph.get_state(self.config_for_thread(workflow_key))
        state = cast(dict[str, object], dict(snapshot.values))
        # A nested Agent Subgraph's own interrupt() (e.g. Request
        # Understanding's confirm_inline) never gets a chance to commit
        # user_interrupt into the OUTER Main State -- the subgraph is still
        # mid-execution when it pauses, so its return never happens. LangGraph
        # still bubbles the pending interrupt's payload up to the top-level
        # task list regardless of nesting depth, so that is the fallback
        # source of truth for the paused-run projection.
        if not state.get("user_interrupt"):
            pending = _first_pending_confirmation_interrupt(snapshot.tasks)
            if pending is not None:
                state["user_interrupt"] = pending
        return self.result_from_state(
            state=cast(GraphState, state),
            workflow_key=workflow_key,
            run_id=run_id,
        )

    def result_from_state(
        self,
        *,
        state: GraphState,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        run_status = self._current_run_status(run_id)
        terminal_statuses = {
            RunStatus.COMPLETED.value,
            RunStatus.BLOCKED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        }
        if run_status in terminal_statuses:
            outcome = WorkflowOutcome.COMPLETED
        elif run_status == RunStatus.RECOVERY_REQUIRED.value:
            outcome = WorkflowOutcome.RECOVERY_REQUIRED
        elif run_status == RunStatus.REAUTH_REQUIRED.value:
            outcome = WorkflowOutcome.ACCEPTED
        else:
            outcome = WorkflowOutcome.ACCEPTED
        if run_status in terminal_statuses:
            with self._cancel_signal_lock:
                self._cancel_signals.discard(run_id)
        return WorkflowInvocationResult(
            run_id=run_id,
            workflow_key=workflow_key,
            outcome=outcome,
            payload={
                "phase": state.get("workflow_phase"),
                "finalize_intent": state.get("finalize_intent"),
                "user_interrupt": state.get("user_interrupt"),
                "execution_summary": state.get("execution_summary"),
                "verification_summary": state.get("verification_summary"),
                "run_status": run_status,
                "graph_profile": self._graph_profile.value,
            },
        )

    def is_profile_compatible(self, state: GraphState) -> bool:
        prompt_context = state.get("prompt_context")
        if not isinstance(prompt_context, dict):
            return True
        persisted_profile = prompt_context.get("graph_profile")
        if not isinstance(persisted_profile, str):
            return True
        return persisted_profile == self._graph_profile.value


def _first_pending_confirmation_interrupt(tasks: Sequence[Any]) -> dict[str, object] | None:
    """Find a paused CONFIRMATION interrupt's own payload anywhere in the
    task list, regardless of nesting depth -- LangGraph bubbles a nested
    subgraph's pending interrupt up to its containing top-level task
    automatically, no ``subgraphs=True`` snapshot required."""
    for task in tasks:
        for pending in task.interrupts:
            value = pending.value
            if isinstance(value, Mapping) and value.get("interrupt_kind") == "CONFIRMATION":
                return {key: item for key, item in value.items() if key != "run_id"}
    return None
