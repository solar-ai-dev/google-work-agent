"""Canonical Planning persistence boundary layered over confirmation runtime.

The current release graph still carries the legacy ``ActionPlanDraftV1``
shape through Review/Domain Validation.  This wrapper removes one remaining
legacy authority before the full PlanningStateV2 migration: an LLM-authored
``expected`` snapshot is never persisted as verification truth.  Instead the
expected projection is rebuilt deterministically from the final business
arguments immediately before the legacy persistence service is invoked.

Note: since the Canonical Planning Production Migration, the ACTION
assembler (``planning_plan_assembler.assemble_action_plan_draft_v1_compat``)
already builds this same deterministic projection at *assembly* time -- this
override is a defensive, idempotent re-derivation of an already-correct
value immediately before persistence (calling the same pure function twice
with the same arguments), not a second, potentially-diverging authority. It
still matters for the ANSWER-only-adjacent revision path and as a
persistence-boundary safety net; removing it is a separate, optional
cleanup, not required for migration CLOSED.

Resolving the Task/Calendar container defaults themselves (used to bind the
per-route selected Tool schema before the canonical Argument Writer ever
sees it) is owned by the base runtime's own construction -- see
``runtime.py``'s ``default_tasklist_id_provider``/
``default_calendar_id_provider`` handling, which is where the
``PlanningArgumentOrchestrator`` is actually built and injected into
``PlanningSubgraph``. This subclass only resolves the Calendar default from
the LLM runtime's shared SettingsService when the caller does not supply one
explicitly, then forwards it down.
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
        super().__init__(
            *args, default_calendar_id_provider=default_calendar_id_provider, **kwargs
        )

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        deterministic_plan = replace_llm_expected_with_deterministic_projection(plan_draft)
        return super()._persist_write_plan(state, deterministic_plan)


__all__ = ["LangGraphWorkflowRuntime", "replace_llm_expected_with_deterministic_projection"]
