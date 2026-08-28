from __future__ import annotations

from typing import Literal, Required, TypedDict

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    StateArtifactMetaV1,
)

ToolRouteEffect = Literal["CREATE", "UPDATE", "SEND", "DELETE"]


class InputToolRouteV1(TypedDict):
    route_id: str
    resource_type: str
    connector_id: str
    allowed_read_tool_ids: list[str]
    required: bool
    reason_codes: list[str]


class OutputToolRouteV1(TypedDict):
    route_id: str
    resource_type: str
    connector_id: str
    effect: ToolRouteEffect
    selected_tool_id: str
    reason_codes: list[str]


class InputRoutePlanV1(TypedDict):
    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    input_routes: list[InputToolRouteV1]


class AnswerOutputPlanV1(TypedDict):
    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    output_mode: Required[Literal["ANSWER"]]


class ActionOutputPlanV1(TypedDict):
    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    output_mode: Required[Literal["ACTION"]]
    output_routes: list[OutputToolRouteV1]


OutputPlanV1 = AnswerOutputPlanV1 | ActionOutputPlanV1


class ToolRoutePlanV2(TypedDict):
    schema_version: Required[Literal[2]]
    input_plan: InputRoutePlanV1
    output_plan: OutputPlanV1
    tool_registry_version: str


class ScopeExpansionRequiredV1(TypedDict):
    schema_version: Required[Literal[1]]
    kind: Required[Literal["SCOPE_EXPANSION_REQUIRED"]]
    reason_codes: list[str]
    required_resource_types: list[str]


class ToolRouteResultV1(TypedDict):
    schema_version: Required[Literal[1]]
    disposition: Literal["ROUTE_READY", "NO_TOOL_NEEDED", "NEEDS_CONFIRMATION", "BLOCKED"]
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: ScopeExpansionRequiredV1 | None
    reason_codes: list[str]
