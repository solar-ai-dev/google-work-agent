"""Reserved corrective-plan persistence with revision-local child identities."""

from __future__ import annotations

from json import dumps
from typing import Any, cast

from google_work_agent.adapters.langgraph.canonical_planning_runtime import (
    _active_target_resource_connector_ids,
    connector_ids_from_frozen_routes,
    replace_llm_expected_with_deterministic_projection,
    target_resource_connector_ids_from_actions,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState, _require_state_value
from google_work_agent.adapters.persistence.connector_identity import bind_action_connector_ids
from google_work_agent.application.calendar_conflicts import CALENDAR_CONFLICT_TOOLS
from google_work_agent.application.task_duplicates import TASK_CREATE_TOOL, evidence_duplicate_risk
from google_work_agent.application.workflows.handoff_contracts import ActionPlanDraftV1
from google_work_agent.application.workflows.retrieval_evidence_store import (
    resolve_evidence_projection,
)
from google_work_agent.application.write_plan_contracts import (
    PublishWritePlanCommand,
    SaveWritePlanCommand,
    WriteActionDraft,
    WriteEvidenceDraft,
)
from google_work_agent.ports import EvidenceOriginType, PlanRecord, PlanStatus


def persist_reserved_corrective_write_plan(
    runtime: Any,
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
    reserved_plan: PlanRecord,
) -> str:
    """Populate one Domain-reserved corrective revision without allocating N+2.

    The Plan destination is already durable authority from ResolveRecovery.
    Planning still owns fresh revision-local Action/Evidence persistence identities,
    including dependency and Action-Evidence link remapping. Ordinary replan
    allocation remains in the legacy persistence path and is not used here.
    """

    run_id = cast(str, state["run_id"])
    if reserved_plan.run_id != run_id or reserved_plan.status is not PlanStatus.DRAFT:
        raise ValueError("corrective destination must be a DRAFT Plan owned by the Run")

    plans = runtime._plans_for_run(run_id)
    if not plans:
        raise LookupError(f"no plans found for corrective run: {run_id}")
    latest_plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms))
    if latest_plan.id != reserved_plan.id or latest_plan.revision_no != reserved_plan.revision_no:
        raise ValueError("corrective destination must be the latest reserved Plan revision")

    deterministic_plan = replace_llm_expected_with_deterministic_projection(plan_draft)
    logical_action_ids = [action["action_id"] for action in deterministic_plan["actions"]]
    logical_evidence_ids = list(deterministic_plan["evidence_refs"])
    if len(set(logical_action_ids)) != len(logical_action_ids):
        raise ValueError("corrective plan contains duplicate logical Action ids")
    if len(set(logical_evidence_ids)) != len(logical_evidence_ids):
        raise ValueError("corrective plan contains duplicate logical Evidence ids")

    action_id_map = {action_id: runtime._id_factory() for action_id in logical_action_ids}
    evidence_id_map = {evidence_id: runtime._id_factory() for evidence_id in logical_evidence_ids}
    persisted_ids = tuple(action_id_map.values()) + tuple(evidence_id_map.values())
    if len(set(persisted_ids)) != len(persisted_ids):
        raise ValueError("corrective persistence id factory returned duplicate child ids")
    logical_ids = set(logical_action_ids) | set(logical_evidence_ids)
    if any(item in logical_ids for item in persisted_ids):
        raise ValueError("corrective persistence requires fresh child ids")

    logical_connector_ids = connector_ids_from_frozen_routes(
        state=state,
        plan_draft=deterministic_plan,
    )
    persisted_connector_ids = {
        action_id_map[action_id]: connector_id
        for action_id, connector_id in logical_connector_ids.items()
    }
    target_resource_connectors = target_resource_connector_ids_from_actions(
        plan_draft=deterministic_plan,
        action_connector_ids=logical_connector_ids,
    )

    retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
    evidence_drafts = {
        item["evidence_id"]: item
        for item in resolve_evidence_projection(
            store=runtime._evidence_store,
            run_id=run_id,
            retrieval_result=retrieval_result,
        )
    }

    # Reuse the canonical Planning wrapper's existing connector binding only
    # for connector-neutral target ResourceRef resolution. It is not the
    # corrective identity authority: Plan destination and child ID remapping
    # above are explicit code-owned values.
    target_token = _active_target_resource_connector_ids.set(dict(target_resource_connectors))
    try:
        mapped_evidence = tuple(
            WriteEvidenceDraft(
                evidence_id=evidence_id_map[evidence_id],
                origin_type=EvidenceOriginType.DERIVED,
                kind=evidence_drafts[evidence_id]["kind"],
                excerpt=evidence_drafts[evidence_id]["excerpt"],
                locator_json=(
                    None
                    if evidence_drafts[evidence_id].get("locator") is None
                    else dumps(evidence_drafts[evidence_id]["locator"], sort_keys=True)
                ),
            )
            for evidence_id in logical_evidence_ids
        )
        mapped_actions = tuple(
            WriteActionDraft(
                action_id=action_id_map[action["action_id"]],
                position=action["position"],
                tool_name=action["tool_name"],
                arguments=action["arguments"],
                expected=action["expected"],
                evidence_ids=tuple(evidence_id_map[item] for item in action["evidence_refs"]),
                depends_on_action_ids=tuple(
                    action_id_map[item] for item in action.get("depends_on_action_ids", [])
                ),
                target_resource_ref_id=runtime._resolve_target_resource_ref_id(
                    run_id=run_id,
                    resource_handle=action.get("target_resource_ref_id"),
                    acquisition_result=_require_state_value(
                        state["acquisition_result"], "acquisition_result"
                    ),
                ),
                risk=(
                    evidence_duplicate_risk(
                        arguments=action["arguments"],
                        acquisition_result=_require_state_value(
                            state["acquisition_result"], "acquisition_result"
                        ),
                        checked_at_ms=runtime._now_ms(),
                    )
                    if action["tool_name"] == TASK_CREATE_TOOL
                    else runtime._calendar_plan_risk(state=state, action=action)
                    if action["tool_name"] in CALENDAR_CONFLICT_TOOLS
                    else {}
                ),
            )
            for action in deterministic_plan["actions"]
        )

        with bind_action_connector_ids(persisted_connector_ids):
            run_version = runtime._current_run_version(run_id)
            save_response = runtime._save_write_plan(
                SaveWritePlanCommand(
                    command_id=runtime._id_factory(),
                    request_hash=runtime._request_hash(
                        {"kind": "save_corrective_write_plan", "plan_id": reserved_plan.id}
                    ),
                    plan_id=reserved_plan.id,
                    run_id=run_id,
                    revision_no=reserved_plan.revision_no,
                    summary_text=runtime._required_string(
                        deterministic_plan.get("summary"), "summary"
                    ),
                    expected_run_version=run_version,
                    actions=mapped_actions,
                    evidence=mapped_evidence,
                )
            )
            if not save_response.applied:
                raise RuntimeError(
                    f"save corrective write plan failed: {save_response.result_code}"
                )
            publish_response = runtime._publish_write_plan(
                PublishWritePlanCommand(
                    command_id=runtime._id_factory(),
                    request_hash=runtime._request_hash(
                        {"kind": "publish_corrective_write_plan", "plan_id": reserved_plan.id}
                    ),
                    plan_id=reserved_plan.id,
                    run_id=run_id,
                    expected_run_version=save_response.run_version,
                )
            )
            if not publish_response.applied:
                raise RuntimeError(
                    f"publish corrective write plan failed: {publish_response.result_code}"
                )
    finally:
        _active_target_resource_connector_ids.reset(target_token)

    return reserved_plan.id


__all__ = ["persist_reserved_corrective_write_plan"]
