"""Canonical Planning persistence boundary over the confirmation runtime.

Tool Route remains the only connector-selection authority.  This runtime
rejoins frozen route identity to the legacy plan shape and passes connector_id
explicitly through application persistence DTOs; persistence never infers it
from source/tool names and uses no ContextVar side channel.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from json import dumps
from typing import Any, cast

from google_work_agent.adapters.connectors.execution_router import ConnectorExecutionRouter
from google_work_agent.adapters.connectors.google_workspace import GOOGLE_WORKSPACE_CONNECTOR_ID
from google_work_agent.adapters.langgraph.workflow_adapter import (
    LangGraphWorkflowRuntime as _ConfirmationLangGraphWorkflowRuntime,
)
from google_work_agent.adapters.langgraph.connector_execution_scope import (
    ConnectorBoundWriteExecutionPhaseCoordinator,
)
from google_work_agent.adapters.langgraph.graph_state import (
    GraphState,
    _acquired_resource_by_handle,
    _require_state_value,
    _resource_handle_for_ref,
)
from google_work_agent.application.read_contracts import (
    PublishReadOnlyPlanCommand,
    ReadActionDraft,
    ReadEvidenceDraft,
    SaveReadOnlyPlanCommand,
)
from google_work_agent.application.write_plan_contracts import (
    PublishWritePlanCommand,
    SaveWritePlanCommand,
    WriteActionDraft,
    WriteEvidenceDraft,
)
from google_work_agent.application.calendar_conflicts import CALENDAR_CONFLICT_TOOLS
from google_work_agent.application.feasibility import evidence_feasibility_risk
from google_work_agent.ports.connectors.execution import (
    ConnectorExecutionPort,
)
from google_work_agent.application.resource_ref_projection import resource_ref_from_snapshot
from google_work_agent.application.task_duplicates import TASK_CREATE_TOOL, evidence_duplicate_risk
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import resolve_evidence_projection
from google_work_agent.application.write_verification_projection import (
    build_expected_verification_projection,
)
from google_work_agent.domain import CalendarWorkHours
from google_work_agent.ports import EvidenceOriginType, ResourceSnapshot, ResourceType


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
    """Join write actions to their frozen OutputToolRouteV1 identities."""

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


def target_resource_connector_ids_from_actions(
    *,
    plan_draft: ActionPlanDraftV1,
    action_connector_ids: Mapping[str, str],
) -> dict[str, str]:
    """Return the unambiguous connector for each target resource handle."""

    resource_connectors: dict[str, str] = {}
    for index, action in enumerate(plan_draft["actions"]):
        if action["effect"] == "READ":
            continue
        resource_handle = action.get("target_resource_ref_id")
        if resource_handle is None:
            continue
        if not isinstance(resource_handle, str) or not resource_handle:
            raise ValueError(f"write action target resource handle is invalid at index {index}")
        action_id = action["action_id"]
        connector_id = action_connector_ids.get(action_id)
        if not isinstance(connector_id, str) or not connector_id:
            raise ValueError(f"write action connector binding is missing: {action_id}")
        existing = resource_connectors.get(resource_handle)
        if existing is not None and existing != connector_id:
            raise ValueError(
                "target resource handle maps to multiple connectors; "
                f"handle={resource_handle!r}, connectors={sorted({existing, connector_id})}"
            )
        resource_connectors[resource_handle] = connector_id
    return resource_connectors


def connector_ids_for_read_actions_from_frozen_routes(
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
) -> dict[str, str]:
    """Resolve legacy READ actions from frozen InputToolRouteV1 capabilities."""

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
        connector_ids[action_id] = next(iter(matching_connectors))
    return connector_ids


class LangGraphWorkflowRuntime(_ConfirmationLangGraphWorkflowRuntime):
    """Canonical runtime with deterministic Expected and explicit connector persistence."""

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
                    {GOOGLE_WORKSPACE_CONNECTOR_ID: cast(ConnectorExecutionPort, legacy_execution)}
                )
        else:
            execution_router = ConnectorExecutionRouter(connector_execution_backends)
        kwargs["connector_execution"] = execution_router

        super().__init__(
            *args, default_calendar_id_provider=default_calendar_id_provider, **kwargs
        )
        self._connector_execution_router = execution_router

        raw_execution_phase = self._write_execution_phase
        connector_bound_phase = ConnectorBoundWriteExecutionPhaseCoordinator(
            delegate=raw_execution_phase,
            unit_of_work_factory=self._unit_of_work_factory,
        )
        self._write_execution_phase = connector_bound_phase
        self._write_execution_node._execution_phase = connector_bound_phase
        self._write_recovery._execution_phase = connector_bound_phase
        self._invocation._resume_reauth_execution = self._write_execution_node

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        plan_draft = replace_llm_expected_with_deterministic_projection(plan_draft)
        connector_ids = connector_ids_from_frozen_routes(state=state, plan_draft=plan_draft)
        run_id = state["run_id"]
        run_version = self._current_run_version(run_id)
        replan_from_plan_id = state.get("__replan_from_plan_id__")
        revision_no = 1
        plan_id = self._required_string(plan_draft.get("plan_id"), "plan_id")
        action_id_map = {a["action_id"]: a["action_id"] for a in plan_draft["actions"]}
        evidence_id_map = {item: item for item in plan_draft["evidence_refs"]}
        if replan_from_plan_id is not None:
            plans = self._plans_for_run(run_id)
            if not any(plan.id == replan_from_plan_id for plan in plans):
                raise LookupError(f"replan source not found: {replan_from_plan_id}")
            revision_no = max(plan.revision_no for plan in plans) + 1
            plan_id = self._id_factory()
            action_id_map = {a["action_id"]: self._id_factory() for a in plan_draft["actions"]}
            evidence_id_map = {item: self._id_factory() for item in plan_draft["evidence_refs"]}

        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
        evidence_drafts = {
            item["evidence_id"]: item
            for item in resolve_evidence_projection(
                store=self._evidence_store, run_id=run_id, retrieval_result=retrieval_result
            )
        }
        mapped_evidence = tuple(
            WriteEvidenceDraft(
                evidence_id=evidence_id_map[evidence_id],
                origin_type=EvidenceOriginType.DERIVED,
                kind=evidence_drafts[evidence_id]["kind"],
                excerpt=evidence_drafts[evidence_id]["excerpt"],
                locator_json=None
                if evidence_drafts[evidence_id].get("locator") is None
                else dumps(evidence_drafts[evidence_id]["locator"], sort_keys=True),
            )
            for evidence_id in plan_draft["evidence_refs"]
        )
        acquisition = _require_state_value(state["acquisition_result"], "acquisition_result")
        mapped_actions: list[WriteActionDraft] = []
        for action in plan_draft["actions"]:
            connector_id = connector_ids[action["action_id"]]
            target_ref_id = self._resolve_target_resource_ref_for_connector(
                run_id=run_id,
                connector_id=connector_id,
                resource_handle=action.get("target_resource_ref_id"),
                acquisition_result=acquisition,
            )
            mapped_actions.append(
                WriteActionDraft(
                    action_id=action_id_map[action["action_id"]],
                    connector_id=connector_id,
                    position=action["position"],
                    tool_name=action["tool_name"],
                    arguments=action["arguments"],
                    expected=action["expected"],
                    evidence_ids=tuple(evidence_id_map[item] for item in action["evidence_refs"]),
                    depends_on_action_ids=tuple(
                        action_id_map[item] for item in action.get("depends_on_action_ids", [])
                    ),
                    target_resource_ref_id=target_ref_id,
                    risk=(
                        evidence_duplicate_risk(
                            arguments=action["arguments"],
                            acquisition_result=acquisition,
                            checked_at_ms=self._now_ms(),
                        )
                        if action["tool_name"] == TASK_CREATE_TOOL
                        else self._calendar_plan_risk(state=state, action=action)
                        if action["tool_name"] in CALENDAR_CONFLICT_TOOLS
                        else {}
                    ),
                )
            )
        save_response = self._save_write_plan(
            SaveWritePlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "save_write_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                revision_no=revision_no,
                summary_text=self._required_string(plan_draft.get("summary"), "summary"),
                expected_run_version=run_version,
                actions=tuple(mapped_actions),
                evidence=mapped_evidence,
            )
        )
        if not save_response.applied:
            raise RuntimeError(f"save_write_plan failed: {save_response.result_code}")
        publish_response = self._publish_write_plan(
            PublishWritePlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "publish_write_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                expected_run_version=save_response.run_version,
            )
        )
        if not publish_response.applied:
            raise RuntimeError(f"publish_write_plan failed: {publish_response.result_code}")
        return plan_id

    def _persist_read_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        connector_ids = connector_ids_for_read_actions_from_frozen_routes(
            state=state, plan_draft=plan_draft
        )
        run_id = state["run_id"]
        run_version = self._current_run_version(run_id)
        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
        evidence_drafts = {
            item["evidence_id"]: item
            for item in resolve_evidence_projection(
                store=self._evidence_store, run_id=run_id, retrieval_result=retrieval_result
            )
        }
        mapped_evidence = tuple(
            ReadEvidenceDraft(
                evidence_id=evidence_id,
                origin_type=EvidenceOriginType.DERIVED,
                kind=evidence_drafts[evidence_id]["kind"],
                excerpt=evidence_drafts[evidence_id]["excerpt"],
                locator_json=None
                if evidence_drafts[evidence_id].get("locator") is None
                else dumps(evidence_drafts[evidence_id]["locator"], sort_keys=True),
            )
            for evidence_id in plan_draft["evidence_refs"]
        )
        mapped_actions = tuple(
            ReadActionDraft(
                action_id=action["action_id"],
                connector_id=connector_ids[action["action_id"]],
                position=action["position"],
                tool_name=action["tool_name"],
                arguments=action["arguments"],
                expected=action["expected"],
                evidence_ids=tuple(action["evidence_refs"]),
                depends_on_action_ids=tuple(action.get("depends_on_action_ids", [])),
                target_resource_ref_id=action.get("target_resource_ref_id"),
            )
            for action in plan_draft["actions"]
        )
        plan_id = self._required_string(plan_draft.get("plan_id"), "plan_id")
        save_response = self._save_read_plan(
            SaveReadOnlyPlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "save_read_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                revision_no=1,
                summary_text=self._required_string(plan_draft.get("summary"), "summary"),
                expected_run_version=run_version,
                actions=mapped_actions,
                evidence=mapped_evidence,
            )
        )
        if not save_response.applied:
            raise RuntimeError(f"save_read_plan failed: {save_response.result_code}")
        publish_response = self._publish_read_plan(
            PublishReadOnlyPlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "publish_read_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                expected_run_version=save_response.run_version,
            )
        )
        if not publish_response.applied:
            raise RuntimeError(f"publish_read_plan failed: {publish_response.result_code}")
        return plan_id

    def _resolve_target_resource_ref_for_connector(
        self,
        *,
        run_id: str,
        connector_id: str,
        resource_handle: str | None,
        acquisition_result: AcquisitionResultV1,
    ) -> str | None:
        if resource_handle is None:
            return None
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.resource_refs.get_by_id(resource_handle)
            if existing is not None:
                if existing.connector_id != connector_id:
                    raise ValueError("target ResourceRef connector does not match frozen route")
                return existing.id
            for resource_ref in unit_of_work.resource_refs.list_by_run(run_id):
                if resource_ref.connector_id == connector_id and resource_handle == _resource_handle_for_ref(resource_ref):
                    return resource_ref.id
            resource = _acquired_resource_by_handle(
                acquisition_result=acquisition_result, resource_handle=resource_handle
            )
            if resource is None:
                raise LookupError(
                    f"target resource handle was not acquired for this run: {resource_handle}"
                )
            payload = cast(dict[str, object], resource["payload"])
            snapshot = ResourceSnapshot(
                fixture_snapshot_id=str(resource.get("fixture_snapshot_id") or "runtime"),
                resource_type=ResourceType(str(resource["resource_type"])),
                resource_id=str(resource["resource_id"]),
                parent_id=cast(str | None, resource.get("parent_id")),
                related_resource_ids=tuple(
                    str(item) for item in cast(list[object], resource.get("related_resource_ids") or [])
                ),
                version=str(resource.get("version") or ""),
                recovery_fingerprint=cast(str | None, resource.get("recovery_fingerprint")),
                payload=payload,
            )
            resource_ref = resource_ref_from_snapshot(
                run_id=run_id,
                connector_id=connector_id,
                snapshot=snapshot,
                captured_at_ms=self._now_ms(),
            )
            unit_of_work.resource_refs.upsert(resource_ref)
            persisted = unit_of_work.resource_refs.get_by_unique_key(
                run_id=run_id,
                connector_id=connector_id,
                resource_type=resource_ref.resource_type.value,
                resource_id=resource_ref.resource_id,
            )
            if persisted is None:
                raise RuntimeError("target resource reference was not persisted")
            unit_of_work.commit()
            return persisted.id


__all__ = [
    "LangGraphWorkflowRuntime",
    "connector_ids_for_read_actions_from_frozen_routes",
    "connector_ids_from_frozen_routes",
    "replace_llm_expected_with_deterministic_projection",
    "target_resource_connector_ids_from_actions",
]