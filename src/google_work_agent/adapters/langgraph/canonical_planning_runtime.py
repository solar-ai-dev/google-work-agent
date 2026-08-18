"""Canonical Planning runtime layered over confirmation/runtime composition.

The downstream Review/Domain/Persistence boundary still consumes the legacy
``ActionPlanDraftV1`` shape, but the public SIX_ROLE_BASELINE runtime now
rebinds Planning before first invocation so ACTION authoring is performed by
the canonical per-output-route Argument Writer and deterministic assembler.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, cast

from google_work_agent.adapters.langgraph.canonical_runtime import (
    LangGraphWorkflowRuntime as _ConfirmationLangGraphWorkflowRuntime,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.planning import PlanningSubgraph
from google_work_agent.application.workflows.handoff_contracts import ActionPlanDraftV1
from google_work_agent.application.workflows.planning_argument_orchestrator import (
    PlanningArgumentOrchestrator,
)
from google_work_agent.application.workflows.planning_argument_writer import PlanningArgumentWriter
from google_work_agent.application.workflows.planning_arguments import DefaultContainerResolver
from google_work_agent.application.write_verification_projection import (
    build_expected_verification_projection,
)


def replace_llm_expected_with_deterministic_projection(
    plan_draft: ActionPlanDraftV1,
) -> ActionPlanDraftV1:
    """Return a defensive plan copy whose write Expected values are code-owned."""

    projected = deepcopy(plan_draft)
    actions = projected.get("actions")
    if not isinstance(actions, list):
        raise ValueError("plan_draft.actions must be a list")

    for index, raw_action in enumerate(actions):
        if not isinstance(raw_action, dict):
            raise ValueError(f"plan_draft.actions[{index}] must be an object")
        tool_name = raw_action.get("tool_name")
        arguments = raw_action.get("arguments")
        effect = raw_action.get("effect")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError(f"plan_draft.actions[{index}].tool_name is required")
        if not isinstance(arguments, Mapping):
            raise ValueError(f"plan_draft.actions[{index}].arguments must be an object")
        if effect == "READ":
            continue
        raw_action["expected"] = build_expected_verification_projection(
            tool_name=tool_name,
            arguments=cast(Mapping[str, object], arguments),
        )
    return cast(ActionPlanDraftV1, projected)


class LangGraphWorkflowRuntime(_ConfirmationLangGraphWorkflowRuntime):
    """Canonical runtime with deterministic write Expected/container boundaries."""

    def __init__(
        self,
        *args: Any,
        default_calendar_id_provider: Callable[[], str | None] | None = None,
        **kwargs: Any,
    ) -> None:
        llm_runtime = kwargs.get("llm_runtime")
        if default_calendar_id_provider is None and llm_runtime is not None:
            settings_service = getattr(llm_runtime, "settings_service", None)
            if callable(settings_service):
                default_calendar_id_provider = lambda: getattr(
                    settings_service(), "default_calendar_id", None
                )
        self._default_calendar_id_provider = default_calendar_id_provider
        super().__init__(*args, **kwargs)

        self._planning_default_container_resolver = DefaultContainerResolver(
            default_tasklist_id_provider=self._default_tasklist_id_provider,
            default_calendar_id_provider=self._default_calendar_id_provider,
        )
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            self._install_canonical_planning_subgraph(
                prompt_manifest_path=kwargs.get("prompt_manifest_path")
            )

    def _install_canonical_planning_subgraph(self, *, prompt_manifest_path: Any) -> None:
        writer = PlanningArgumentWriter(
            llm_runtime=self._llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._planning_argument_writer = writer
        self._planning_argument_orchestrator = PlanningArgumentOrchestrator(
            writer=writer,
            default_container_resolver=self._planning_default_container_resolver,
        )
        self._planning_subgraph = PlanningSubgraph(
            agent=self._planning,
            id_factory=self._id_factory,
            graph_profile=self._graph_profile,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
            argument_orchestrator=self._planning_argument_orchestrator,
        ).build()
        self._graph_composition.replace_binding("planning", self._planning_subgraph)
        self._native_agent_subgraphs = self._graph_composition.native_subgraphs()
        self._graph = self._build_graph()
        self._invocation = WorkflowInvocationCoordinator(
            graph=self._graph,
            graph_profile=self._graph_profile,
            initial_state=self._initial_state,
            current_run_status=self._current_run_status,
            latest_unknown_action=self._latest_unknown_action,
            recovery_node=self._write_recovery.recover_unknown,
            has_executed_action=self._has_executed_action,
            recover_executed_actions=self._write_recovery.recover_executed,
            mark_stalled_claims_as_unknown=self._mark_stalled_claims_as_unknown,
            cancel_signal_lock=self._cancel_signal_lock,
            cancel_signals=self._cancel_signals,
        )

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        deterministic_plan = replace_llm_expected_with_deterministic_projection(plan_draft)
        return super()._persist_write_plan(state, deterministic_plan)


__all__ = ["LangGraphWorkflowRuntime", "replace_llm_expected_with_deterministic_projection"]
