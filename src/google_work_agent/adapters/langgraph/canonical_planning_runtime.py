"""Canonical Planning persistence boundary layered over confirmation runtime.

The current release graph still carries the legacy ``ActionPlanDraftV1``
shape through Review/Domain Validation. This wrapper removes remaining
legacy authority immediately before persistence: Expected is rebuilt from
business arguments, while connector identity is rejoined from the frozen
ToolRoutePlanV2 rather than authored or inferred by an LLM/persistence layer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, cast

from google_work_agent.adapters.langgraph.canonical_runtime import (
    LangGraphWorkflowRuntime as _ConfirmationLangGraphWorkflowRuntime,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.persistence.connector_identity import (
    bind_action_connector_ids,
)
from google_work_agent.application.connector_write_result import (
    ConnectorBoundStoreWriteActionSuccessService,
)
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
            continue
        raw_action["expected"] = build_expected_verification_projection(
            tool_name=tool_name,
            arguments=cast(Mapping[str, object], arguments),
        )
    return cast(ActionPlanDraftV1, projected)


def connector_ids_from_frozen_routes(
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
) -> dict[str, str]:
    """Join legacy write actions back to their frozen OutputToolRouteV1 identities.

    The join is intentionally strict and positional because canonical Planning
    preserves frozen output-route order. Any tool/effect/count mismatch fails
    closed instead of guessing a connector from a tool name or provider.
    """

    raw_route_plan = state.get("tool_route_plan")
    if not isinstance(raw_route_plan, Mapping):
        raise ValueError("write persistence requires frozen tool_route_plan")
    output_plan = raw_route_plan.get("output_plan")
    if not isinstance(output_plan, Mapping) or output_plan.get("output_mode") != "ACTION":
        raise ValueError("write persistence requires ACTION output_plan")
    raw_routes = output_plan.get("output_routes")
    if not isinstance(raw_routes, list):
        raise ValueError("ACTION output_plan.output_routes must be a list")

    write_actions = [action for action in plan_draft["actions"] if action["effect"] != "READ"]
    if len(write_actions) != len(raw_routes):
        raise ValueError("write actions must align exactly with frozen output routes")

    connector_ids: dict[str, str] = {}
    for index, (action, raw_route) in enumerate(zip(write_actions, raw_routes, strict=True)):
        if not isinstance(raw_route, Mapping):
            raise ValueError(f"output_routes[{index}] must be an object")
        if action["tool_name"] != raw_route.get("selected_tool_id"):
            raise ValueError(f"write action tool does not match frozen route at index {index}")
        if action["effect"] != raw_route.get("effect"):
            raise ValueError(f"write action effect does not match frozen route at index {index}")
        connector_id = raw_route.get("connector_id")
        if not isinstance(connector_id, str) or not connector_id:
            raise ValueError(f"output_routes[{index}].connector_id is required")
        action_id = action["action_id"]
        if not action_id:
            raise ValueError(f"write action id is empty at index {index}")
        if action_id in connector_ids:
            raise ValueError(f"duplicate write action id: {action_id}")
        connector_ids[action_id] = connector_id
    return connector_ids


class LangGraphWorkflowRuntime(_ConfirmationLangGraphWorkflowRuntime):
    """Canonical runtime with deterministic Expected and connector boundaries."""

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

        # The base runtime constructs WriteExecutionPhaseCoordinator during
        # super().__init__. Replace only its success-persistence delegate with
        # a subtype that resolves connector_id from the already-persisted
        # Action, then binds that identity while ResourceRef is written.
        connector_bound_store = ConnectorBoundStoreWriteActionSuccessService(
            delegate=self._store_write_success,
            unit_of_work_factory=self._unit_of_work_factory,
        )
        self._store_write_success = connector_bound_store
        self._write_execution_phase._store_write_success = connector_bound_store

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        deterministic_plan = replace_llm_expected_with_deterministic_projection(plan_draft)
        connector_ids = connector_ids_from_frozen_routes(
            state=state,
            plan_draft=deterministic_plan,
        )
        with bind_action_connector_ids(connector_ids):
            return super()._persist_write_plan(state, deterministic_plan)


__all__ = [
    "LangGraphWorkflowRuntime",
    "connector_ids_from_frozen_routes",
    "replace_llm_expected_with_deterministic_projection",
]
