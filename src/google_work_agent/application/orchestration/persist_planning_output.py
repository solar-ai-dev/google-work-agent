"""One-way ActionPlanDraftV2 projection into the legacy persistence DTO shape.

This module is a persistence adapter only. It never constructs a V1 Work
Analysis artifact and never returns a V1 plan to Planning/Review routing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    EvidenceDraftV1,
    RequestIntentV2,
)
from google_work_agent.application.use_cases.verification.write_verification_projection import (
    build_expected_verification_projection,
)
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.ports.connector.contracts.google_workspace import ResourceType


class V2PersistenceProjectionError(ValueError):
    """A V2 plan cannot be projected into the durable write boundary safely."""


_TARGET_SPECS: dict[str, tuple[str, str, str | None]] = {
    "gmail_update_draft": (ResourceType.GMAIL_DRAFT.value, "draft_id", None),
    "gmail_send": (ResourceType.GMAIL_DRAFT.value, "draft_id", None),
    "tasks_update_task": (ResourceType.TASK.value, "task_id", "task_list_id"),
    "tasks_delete_task": (ResourceType.TASK.value, "task_id", "task_list_id"),
    "calendar_update_event": (
        ResourceType.CALENDAR_EVENT.value,
        "event_id",
        "calendar_id",
    ),
    "calendar_delete_event": (
        ResourceType.CALENDAR_EVENT.value,
        "event_id",
        "calendar_id",
    ),
}


def project_action_plan_v2_for_persistence(
    *,
    run_id: str,
    request_intent: RequestIntentV2,
    plan: ActionPlanDraftV2,
    tool_route_plan: ToolRoutePlanV2,
    evidence_drafts: Sequence[EvidenceDraftV1],
    resource_refs_by_handle: Mapping[str, ResourceRefRecord],
) -> ActionPlanDraftV1:
    """Build the bounded legacy-shaped DTO consumed only by persistence.

    V2 plan/frozen routes own semantic identity. Expected is recomputed by
    deterministic code. Target resources are admitted only after an exact
    current-run/connector/evidence/argument match. Calendar conflict and
    optional business-deadline feasibility remain deterministic Action-owner
    risk projections during durable plan persistence.
    """

    if not run_id:
        raise V2PersistenceProjectionError("run_id is required")
    goal = request_intent.get("goal")
    if not isinstance(goal, str) or not goal:
        raise V2PersistenceProjectionError("RequestIntentV2.goal is required")
    meta = plan.get("meta")
    if not isinstance(meta, Mapping):
        raise V2PersistenceProjectionError("ActionPlanDraftV2.meta is required")
    plan_id = _required_text(meta.get("artifact_id"), "ActionPlanDraftV2 artifact_id")
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        raise V2PersistenceProjectionError("ActionPlanDraftV2.actions is required")
    routes = _frozen_output_routes(tool_route_plan)
    if len(actions) != len(routes):
        raise V2PersistenceProjectionError("V2 actions must align exactly with frozen routes")

    evidence_by_id: dict[str, EvidenceDraftV1] = {}
    for draft in evidence_drafts:
        evidence_id = draft.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise V2PersistenceProjectionError("evidence draft id is invalid")
        if evidence_id in evidence_by_id:
            raise V2PersistenceProjectionError(f"duplicate evidence id: {evidence_id}")
        evidence_by_id[evidence_id] = draft

    all_evidence_refs: list[str] = []
    all_resource_handles: list[str] = []
    legacy_actions: list[dict[str, object]] = []
    for position, (action, route) in enumerate(zip(actions, routes, strict=True), start=1):
        if not isinstance(action, Mapping):
            raise V2PersistenceProjectionError(f"V2 action is invalid at position {position}")
        route_id = _required_text(route.get("route_id"), f"route {position} id")
        tool_id = _required_text(route.get("selected_tool_id"), f"route {position} tool")
        connector_id = _required_text(route.get("connector_id"), f"route {position} connector")
        effect = route.get("effect")
        if effect not in {"CREATE", "UPDATE", "SEND", "DELETE"}:
            raise V2PersistenceProjectionError(f"route {position} is not a write effect")
        if action.get("route_id") != route_id:
            raise V2PersistenceProjectionError(f"V2 action route mismatch at position {position}")
        if action.get("tool_id") != tool_id or action.get("effect") != effect:
            raise V2PersistenceProjectionError(
                f"V2 action tool/effect mismatch at position {position}"
            )
        arguments = action.get("arguments")
        if not isinstance(arguments, Mapping):
            raise V2PersistenceProjectionError(
                f"V2 action arguments are invalid at position {position}"
            )
        raw_evidence_refs = action.get("evidence_refs")
        if not isinstance(raw_evidence_refs, list) or any(
            not isinstance(item, str) or not item for item in raw_evidence_refs
        ):
            raise V2PersistenceProjectionError(
                f"V2 action evidence is invalid at position {position}"
            )
        evidence_refs = cast(list[str], raw_evidence_refs)
        evidence_handles = _evidence_handles(evidence_refs, evidence_by_id)
        for evidence_id in evidence_refs:
            if evidence_id not in all_evidence_refs:
                all_evidence_refs.append(evidence_id)
        for handle in evidence_handles:
            if handle not in all_resource_handles:
                all_resource_handles.append(handle)

        target_handle = _target_resource_handle(
            run_id=run_id,
            connector_id=connector_id,
            tool_id=tool_id,
            effect=cast(str, effect),
            arguments=cast(Mapping[str, object], arguments),
            evidence_handles=evidence_handles,
            resource_refs_by_handle=resource_refs_by_handle,
        )
        action_id = _required_text(action.get("action_id"), f"action {position} id")
        dependencies = action.get("depends_on_action_ids")
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) or not item for item in dependencies
        ):
            raise V2PersistenceProjectionError(f"action dependencies are invalid: {action_id}")
        legacy_actions.append(
            {
                "schema_version": 2,
                "action_id": action_id,
                "position": position,
                "effect": effect,
                "tool_name": tool_id,
                "arguments": dict(arguments),
                "expected": build_expected_verification_projection(
                    tool_name=tool_id,
                    arguments=cast(Mapping[str, object], arguments),
                ),
                "evidence_refs": list(evidence_refs),
                "resource_refs": list(evidence_handles),
                "target_resource_ref_id": target_handle,
                "depends_on_action_ids": list(cast(list[str], dependencies)),
                "user_visible_reason": goal,
            }
        )

    bounded_resource_refs: list[dict[str, object]] = []
    for handle in all_resource_handles:
        resource = resource_refs_by_handle.get(handle)
        if resource is None:
            continue
        _require_current_run_resource(run_id=run_id, handle=handle, resource=resource)
        bounded_resource_refs.append(
            {
                "resource_handle": handle,
                "resource_ref_id": resource.id,
                "connector_id": resource.connector_id,
                "source": _source_for_resource_type(resource.resource_type),
                "resource_type": resource.resource_type,
                "resource_id": resource.resource_id,
                "parent_resource_id": resource.parent_resource_id,
            }
        )

    return cast(
        ActionPlanDraftV1,
        {
            "schema_version": 2,
            "status": "PLAN_READY",
            "plan_id": plan_id,
            "summary": goal,
            "objective": goal,
            "actions": legacy_actions,
            "evidence_refs": all_evidence_refs,
            "resource_refs": bounded_resource_refs,
            "confirmation": None,
        },
    )


def _target_resource_handle(
    *,
    run_id: str,
    connector_id: str,
    tool_id: str,
    effect: str,
    arguments: Mapping[str, object],
    evidence_handles: Sequence[str],
    resource_refs_by_handle: Mapping[str, ResourceRefRecord],
) -> str | None:
    if effect == "CREATE":
        return None
    spec = _TARGET_SPECS.get(tool_id)
    if spec is None:
        raise V2PersistenceProjectionError(
            f"no deterministic target ResourceRef rule for {effect} tool: {tool_id}"
        )
    resource_type, id_field, parent_field = spec
    resource_id = _required_text(arguments.get(id_field), f"{tool_id}.{id_field}")
    parent_id = None
    if parent_field is not None:
        parent_id = _required_text(arguments.get(parent_field), f"{tool_id}.{parent_field}")

    matches: list[str] = []
    for handle in evidence_handles:
        resource = resource_refs_by_handle.get(handle)
        if resource is None:
            continue
        _require_current_run_resource(run_id=run_id, handle=handle, resource=resource)
        if resource.connector_id != connector_id:
            continue
        if resource.resource_type != resource_type:
            continue
        if resource.resource_id != resource_id:
            continue
        if parent_id is not None and resource.parent_resource_id != parent_id:
            continue
        matches.append(handle)
    if len(matches) != 1:
        raise V2PersistenceProjectionError(
            "target ResourceRef must resolve to exactly one current-run evidence resource; "
            f"tool={tool_id!r}, resource_id={resource_id!r}, matches={len(matches)}"
        )
    return matches[0]


def _evidence_handles(
    evidence_refs: Sequence[str],
    evidence_by_id: Mapping[str, EvidenceDraftV1],
) -> list[str]:
    result: list[str] = []
    for evidence_id in evidence_refs:
        draft = evidence_by_id.get(evidence_id)
        if draft is None:
            raise V2PersistenceProjectionError(f"missing current evidence: {evidence_id}")
        handle = draft.get("resource_handle")
        if not isinstance(handle, str) or not handle:
            raise V2PersistenceProjectionError(f"evidence has no resource handle: {evidence_id}")
        if handle not in result:
            result.append(handle)
    return result


def _require_current_run_resource(*, run_id: str, handle: str, resource: ResourceRefRecord) -> None:
    if resource.run_id != run_id:
        raise V2PersistenceProjectionError(f"cross-run ResourceRef is forbidden: {handle}")
    if not resource.connector_id:
        raise V2PersistenceProjectionError(f"ResourceRef connector is missing: {handle}")
    if not resource.resource_id:
        raise V2PersistenceProjectionError(f"ResourceRef external id is missing: {handle}")


def _frozen_output_routes(tool_route_plan: ToolRoutePlanV2) -> list[Mapping[str, object]]:
    output_plan = tool_route_plan.get("output_plan")
    if not isinstance(output_plan, Mapping) or output_plan.get("output_mode") != "ACTION":
        raise V2PersistenceProjectionError("persistence requires frozen ACTION output plan")
    routes = output_plan.get("output_routes")
    if (
        not isinstance(routes, list)
        or not routes
        or any(not isinstance(route, Mapping) for route in routes)
    ):
        raise V2PersistenceProjectionError("frozen output routes are invalid")
    return cast(list[Mapping[str, object]], routes)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise V2PersistenceProjectionError(f"{label} is required")
    return value


def _source_for_resource_type(resource_type: str) -> str:
    if resource_type.startswith("gmail_"):
        return "GMAIL"
    if resource_type in {"task", "task_list"}:
        return "TASKS"
    if resource_type.startswith("calendar"):
        return "CALENDAR"
    raise V2PersistenceProjectionError(f"unsupported ResourceRef type: {resource_type}")


__all__ = [
    "V2PersistenceProjectionError",
    "project_action_plan_v2_for_persistence",
]
