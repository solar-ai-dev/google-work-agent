"""Canonical Planning persistence boundary layered over confirmation runtime.

The current release graph still carries the legacy ``ActionPlanDraftV1``
shape through Review/Domain Validation.  This wrapper removes one remaining
legacy authority before the full PlanningStateV2 migration: an LLM-authored
``expected`` snapshot is never persisted as verification truth.  Instead the
expected projection is rebuilt deterministically from the final business
arguments immediately before the legacy persistence service is invoked.

It also materializes the deterministic Task/Calendar container resolver that
the canonical Planning subgraph will consume.  The Task-list provider is
already injected by the legacy runtime; Calendar defaults are resolved from an
explicit provider or, in the current production composition, the LLM runtime's
shared SettingsService.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, cast

from google_work_agent.adapters.langgraph.canonical_runtime import (
    LangGraphWorkflowRuntime as _ConfirmationLangGraphWorkflowRuntime,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.application.workflows.handoff_contracts import ActionPlanDraftV1
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
            # Legacy READ-only plans are outside the write verification contract.
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

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        deterministic_plan = replace_llm_expected_with_deterministic_projection(plan_draft)
        return super()._persist_write_plan(state, deterministic_plan)


__all__ = ["LangGraphWorkflowRuntime", "replace_llm_expected_with_deterministic_projection"]
