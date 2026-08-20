"""Canonical Planning persistence boundary layered over confirmation runtime.

The current release graph still carries the legacy ``ActionPlanDraftV1``
shape through Review/Domain Validation. This wrapper removes remaining
legacy authority immediately before persistence: Expected is rebuilt from
business arguments, while connector identity is rejoined from the frozen
ToolRoutePlanV2 rather than authored or inferred by an LLM/persistence layer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, cast

from google_work_agent.adapters.connectors.execution_router import ConnectorExecutionRouter
from google_work_agent.adapters.connectors.google_workspace import GOOGLE_WORKSPACE_CONNECTOR_ID
from google_work_agent.adapters.langgraph.canonical_runtime import (
    LangGraphWorkflowRuntime as _ConfirmationLangGraphWorkflowRuntime,
)
from google_work_agent.adapters.langgraph.connector_execution_scope import (
    ConnectorBoundWriteExecutionPhaseCoordinator,
)
from google_work_agent.adapters.langgraph.connector_read_result import (
    ConnectorBoundCompleteReadActionService,
)
from google_work_agent.adapters.langgraph.connector_write_result import (
    ConnectorBoundStoreWriteActionSuccessService,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.persistence.connector_identity import (
    bind_action_connector_ids,
    bind_resource_connector_id,
)
from google_work_agent.application.ports import ConnectorExecutionPort
from google_work_agent.application.workflows.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
)
from google_work_agent.application.write_verification_projection import (
    build_expected_verification_projection,
)

_active_write_connector_ids: ContextVar[dict[str, str] | None] = ContextVar(
    "active_write_connector_ids", default=None
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


def connector_ids_for_read_actions_from_frozen_routes(
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
) -> dict[str, str]:
    """Resolve READ action connector identity from frozen InputToolRouteV1 capabilities.

    Legacy READ ActionDrafts do not carry route_id/connector_id. Until that DTO
    disappears, a READ tool is accepted only when the frozen input plan maps it
    to exactly one connector identity. Zero or multiple connector candidates
    fail closed instead of inferring from a tool-name prefix or ResourceSource.
    """

    raw_route_plan = state.get("tool_route_plan")
    if not isinstance(raw_route_plan, Mapping):
        raise ValueError("read persistence requires frozen tool_route_plan")
    input_plan = raw_route_plan.get("input_plan")
    if not isinstance(input_plan, Mapping):
        raise ValueError("read persistence requires input_plan")
    raw_routes = input_plan.get("input_routes")
    if not isinstance(raw_routes, list):
        raise ValueError("input_plan.input_routes must be a list")

    read_actions = [action for action in plan_draft["actions"] if action["effect"] == "READ"]
    if not read_actions:
        raise ValueError("read persistence requires at least one READ action")

    connector_ids: dict[str, str] = {}
    for action_index, action in enumerate(read_actions):
        tool_name = action["tool_name"]
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError(f"read action tool is required at index {action_index}")
        matching_connectors: set[str] = set()
        for route_index, raw_route in enumerate(raw_routes):
            if not isinstance(raw_route, Mapping):
                raise ValueError(f"input_routes[{route_index}] must be an object")
            allowed_tools = raw_route.get("allowed_read_tool_ids")
            if not isinstance(allowed_tools, list):
                raise ValueError(
                    f"input_routes[{route_index}].allowed_read_tool_ids must be a list"
                )
            if tool_name not in allowed_tools:
                continue
            connector_id = raw_route.get("connector_id")
            if not isinstance(connector_id, str) or not connector_id:
                raise ValueError(f"input_routes[{route_index}].connector_id is required")
            matching_connectors.add(connector_id)
        if len(matching_connectors) != 1:
            raise ValueError(
                "read action must map to exactly one frozen connector; "
                f"tool={tool_name!r}, connectors={sorted(matching_connectors)}"
            )
        action_id = action["action_id"]
        if not action_id:
            raise ValueError(f"read action id is empty at index {action_index}")
        if action_id in connector_ids:
            raise ValueError(f"duplicate read action id: {action_id}")
        connector_ids[action_id] = next(iter(matching_connectors))
    return connector_ids


class LangGraphWorkflowRuntime(_ConfirmationLangGraphWorkflowRuntime):
    """Canonical runtime with deterministic Expected and connector boundaries."""

    def __init__(
        self,
        *args: Any,
        default_calendar_id_provider: Callable[[], str | None] | None = None,
        connector_execution_backends: Mapping[str, ConnectorExecutionPort] | None = None,
        **kwargs: Any,
    ) -> None:
        llm_runtime = kwargs.get("llm_runtime")
        if default_calendar_id_provider is None and llm_runtime is not None:
            settings_service = getattr(llm_runtime, "settings_service", None)
            if callable(settings_service):
                default_calendar_id_provider = lambda: getattr(
                    settings_service(), "default_calendar_id", None
                )

        legacy_execution = kwargs.get("connector_execution")
        if connector_execution_backends is None:
            if isinstance(legacy_execution, ConnectorExecutionRouter):
                execution_router = legacy_execution
            else:
                if legacy_execution is None:
                    raise TypeError("connector_execution is required")
                execution_router = ConnectorExecutionRouter(
                    {
                        GOOGLE_WORKSPACE_CONNECTOR_ID: cast(
                            ConnectorExecutionPort, legacy_execution
                        )
                    }
                )
        else:
            execution_router = ConnectorExecutionRouter(connector_execution_backends)
        kwargs["connector_execution"] = execution_router

        super().__init__(
            *args, default_calendar_id_provider=default_calendar_id_provider, **kwargs
        )
        self._connector_execution_router = execution_router

        connector_bound_store = ConnectorBoundStoreWriteActionSuccessService(
            delegate=self._store_write_success,
            unit_of_work_factory=self._unit_of_work_factory,
        )
        self._store_write_success = connector_bound_store
        self._write_execution_phase._store_write_success = connector_bound_store

        self._complete_read = ConnectorBoundCompleteReadActionService(
            delegate=self._complete_read,
            unit_of_work_factory=self._unit_of_work_factory,
        )

        raw_execution_phase = self._write_execution_phase
        connector_bound_phase = ConnectorBoundWriteExecutionPhaseCoordinator(
            delegate=raw_execution_phase,
            unit_of_work_factory=self._unit_of_work_factory,
        )
        self._write_execution_phase = connector_bound_phase
        self._write_execution_node._execution_phase = connector_bound_phase
        self._write_recovery._execution_phase = connector_bound_phase

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        deterministic_plan = replace_llm_expected_with_deterministic_projection(plan_draft)
        connector_ids = connector_ids_from_frozen_routes(
            state=state,
            plan_draft=deterministic_plan,
        )
        token = _active_write_connector_ids.set(dict(connector_ids))
        try:
            with bind_action_connector_ids(connector_ids):
                return super()._persist_write_plan(state, deterministic_plan)
        finally:
            _active_write_connector_ids.reset(token)

    def _persist_read_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        connector_ids = connector_ids_for_read_actions_from_frozen_routes(
            state=state,
            plan_draft=plan_draft,
        )
        with bind_action_connector_ids(connector_ids):
            return super()._persist_read_plan(state, plan_draft)

    def _resolve_target_resource_ref_id(
        self,
        *,
        run_id: str,
        resource_handle: str | None,
        acquisition_result: AcquisitionResultV1,
    ) -> str | None:
        if resource_handle is None:
            return None
        connector_ids = _active_write_connector_ids.get()
        if connector_ids is None:
            return super()._resolve_target_resource_ref_id(
                run_id=run_id,
                resource_handle=resource_handle,
                acquisition_result=acquisition_result,
            )
        unique_connectors = set(connector_ids.values())
        if len(unique_connectors) != 1:
            raise ValueError(
                "legacy target ResourceRef projection cannot select a connector for a "
                "multi-connector write plan"
            )
        connector_id = next(iter(unique_connectors))
        with bind_resource_connector_id(connector_id):
            return super()._resolve_target_resource_ref_id(
                run_id=run_id,
                resource_handle=resource_handle,
                acquisition_result=acquisition_result,
            )


__all__ = [
    "LangGraphWorkflowRuntime",
    "connector_ids_for_read_actions_from_frozen_routes",
    "connector_ids_from_frozen_routes",
    "replace_llm_expected_with_deterministic_projection",
]
