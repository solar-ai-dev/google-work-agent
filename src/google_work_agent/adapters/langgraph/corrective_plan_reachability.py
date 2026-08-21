"""Production reachability guard for failure-safe corrective-plan continuation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, cast

from google_work_agent.adapters.langgraph.canonical_planning_runtime import (
    _active_target_resource_connector_ids,
    connector_ids_from_frozen_routes,
    replace_llm_expected_with_deterministic_projection,
    target_resource_connector_ids_from_actions,
)
from google_work_agent.adapters.langgraph.corrective_plan_persistence import (
    _candidate_materialization_projection,
    _corrective_child_id,
    _corrective_command_id,
    _require_applied_publish_receipt,
    _require_applied_save_receipt,
    _validate_persisted_materialization,
    persist_reserved_corrective_write_plan,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState, _require_state_value
from google_work_agent.application.workflows.handoff_contracts import ActionPlanDraftV1
from google_work_agent.application.workflows.retrieval_evidence_store import (
    resolve_evidence_projection,
)
from google_work_agent.ports import PlanRecord, PlanStatus, RunStatus


class CorrectivePlanContinuationRequired(RuntimeError):
    """A verified Save-only corrective revision needs a later Publish continuation."""

    def __init__(self, *, run_id: str, plan_id: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.run_id = run_id
        self.plan_id = plan_id


class _FailureDisposition(StrEnum):
    UNSAFE = "UNSAFE"
    CONTINUATION_REQUIRED = "CONTINUATION_REQUIRED"
    ALREADY_PUBLISHED = "ALREADY_PUBLISHED"


def persist_reachable_corrective_write_plan(
    runtime: Any,
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
    reserved_plan: PlanRecord,
) -> str:
    """Persist corrective work while preserving a production-reachable retry seam.

    The underlying helper remains the single materialization implementation. If
    it raises, only durable facts can reclassify that exception:

    * exact Save receipt + exact persisted materialization + PLANNING/DRAFT +
      no durable Publish receipt -> typed non-terminal continuation;
    * exact already-published aggregate + exact Save/Publish receipts ->
      idempotent success;
    * every other exception -> unchanged generic failure.
    """

    try:
        return persist_reserved_corrective_write_plan(
            runtime,
            state=state,
            plan_draft=plan_draft,
            reserved_plan=reserved_plan,
        )
    except Exception as error:
        disposition = _classify_failure_after_corrective_save(
            runtime,
            state=state,
            plan_draft=plan_draft,
            reserved_plan=reserved_plan,
        )
        if disposition is _FailureDisposition.ALREADY_PUBLISHED:
            return reserved_plan.id
        if disposition is _FailureDisposition.CONTINUATION_REQUIRED:
            raise CorrectivePlanContinuationRequired(
                run_id=reserved_plan.run_id,
                plan_id=reserved_plan.id,
                cause=error,
            ) from error
        raise


def _classify_failure_after_corrective_save(
    runtime: Any,
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
    reserved_plan: PlanRecord,
) -> _FailureDisposition:
    """Classify only states whose current candidate is durably proven."""

    try:
        proof = _build_materialization_proof(
            runtime,
            state=state,
            plan_draft=plan_draft,
            reserved_plan=reserved_plan,
        )
    except Exception:
        return _FailureDisposition.UNSAFE

    run_id = reserved_plan.run_id
    with runtime._unit_of_work_factory() as unit_of_work:
        current_run = unit_of_work.runs.get_by_id(run_id)
        current_plan = unit_of_work.plans.get_by_id(reserved_plan.id)
        if current_run is None or current_plan is None:
            return _FailureDisposition.UNSAFE

        plans = unit_of_work.plans.list_by_run(run_id)
        if not plans:
            return _FailureDisposition.UNSAFE
        latest = max(plans, key=lambda item: (item.revision_no, item.created_at_ms))
        if latest.id != reserved_plan.id or latest.revision_no != reserved_plan.revision_no:
            return _FailureDisposition.UNSAFE

        save_receipt = unit_of_work.command_receipts.get_by_command_id(
            proof["save_command_id"]
        )
        publish_receipt = unit_of_work.command_receipts.get_by_command_id(
            proof["publish_command_id"]
        )

        try:
            _require_applied_save_receipt(
                save_receipt,
                expected_request_hash=proof["save_request_hash"],
                plan_id=reserved_plan.id,
                action_ids=proof["action_ids"],
                run_id=run_id,
            )
            _validate_persisted_materialization(
                unit_of_work=unit_of_work,
                run_id=run_id,
                plan=current_plan,
                summary_text=proof["summary_text"],
                deterministic_plan=proof["deterministic_plan"],
                action_id_map=proof["action_id_map"],
                evidence_id_map=proof["evidence_id_map"],
                evidence_drafts=proof["evidence_drafts"],
                persisted_connector_ids=proof["persisted_connector_ids"],
                target_resource_ids=proof["target_resource_ids"],
            )
        except Exception:
            return _FailureDisposition.UNSAFE

        if (
            current_run.status is RunStatus.PLANNING
            and current_plan.status is PlanStatus.DRAFT
            and publish_receipt is None
        ):
            return _FailureDisposition.CONTINUATION_REQUIRED

        if (
            current_run.status is RunStatus.WAITING_APPROVAL
            and current_plan.status is PlanStatus.WAITING_APPROVAL
        ):
            try:
                _require_applied_publish_receipt(
                    publish_receipt,
                    expected_request_hash=proof["publish_request_hash"],
                    plan_id=reserved_plan.id,
                    run_id=run_id,
                )
            except Exception:
                return _FailureDisposition.UNSAFE
            return _FailureDisposition.ALREADY_PUBLISHED

    return _FailureDisposition.UNSAFE


def _build_materialization_proof(
    runtime: Any,
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
    reserved_plan: PlanRecord,
) -> dict[str, Any]:
    """Rebuild the exact candidate authority used by the committed Save receipt."""

    run_id = cast(str, state["run_id"])
    if reserved_plan.run_id != run_id:
        raise ValueError("corrective destination must be owned by the Run")

    deterministic_plan = replace_llm_expected_with_deterministic_projection(plan_draft)
    logical_action_ids = [action["action_id"] for action in deterministic_plan["actions"]]
    logical_evidence_ids = list(deterministic_plan["evidence_refs"])
    if len(set(logical_action_ids)) != len(logical_action_ids):
        raise ValueError("corrective plan contains duplicate logical Action ids")
    if len(set(logical_evidence_ids)) != len(logical_evidence_ids):
        raise ValueError("corrective plan contains duplicate logical Evidence ids")

    action_id_map = {
        action_id: _corrective_child_id(
            kind="action",
            plan_id=reserved_plan.id,
            logical_id=action_id,
        )
        for action_id in logical_action_ids
    }
    evidence_id_map = {
        evidence_id: _corrective_child_id(
            kind="evidence",
            plan_id=reserved_plan.id,
            logical_id=evidence_id,
        )
        for evidence_id in logical_evidence_ids
    }

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
    missing_evidence = set(logical_evidence_ids) - set(evidence_drafts)
    if missing_evidence:
        raise LookupError(
            "corrective evidence projection is unavailable: "
            + ",".join(sorted(missing_evidence))
        )

    target_token = _active_target_resource_connector_ids.set(
        dict(target_resource_connectors)
    )
    try:
        target_resource_ids = {
            action["action_id"]: runtime._resolve_target_resource_ref_id(
                run_id=run_id,
                resource_handle=action.get("target_resource_ref_id"),
                acquisition_result=_require_state_value(
                    state["acquisition_result"], "acquisition_result"
                ),
            )
            for action in deterministic_plan["actions"]
        }
    finally:
        _active_target_resource_connector_ids.reset(target_token)

    summary_text = runtime._required_string(deterministic_plan.get("summary"), "summary")
    materialization_projection = _candidate_materialization_projection(
        reserved_plan=reserved_plan,
        summary_text=summary_text,
        deterministic_plan=deterministic_plan,
        action_id_map=action_id_map,
        evidence_id_map=evidence_id_map,
        evidence_drafts=evidence_drafts,
        persisted_connector_ids=persisted_connector_ids,
        target_resource_ids=target_resource_ids,
    )
    save_request_hash = runtime._request_hash(materialization_projection)
    save_command_id = _corrective_command_id(kind="save", plan_id=reserved_plan.id)
    publish_request_hash = runtime._request_hash(
        {
            "kind": "publish_corrective_write_plan_v2",
            "plan_id": reserved_plan.id,
            "revision_no": reserved_plan.revision_no,
            "save_request_hash": save_request_hash,
        }
    )
    publish_command_id = _corrective_command_id(
        kind="publish",
        plan_id=reserved_plan.id,
    )

    return {
        "deterministic_plan": deterministic_plan,
        "action_id_map": action_id_map,
        "evidence_id_map": evidence_id_map,
        "evidence_drafts": evidence_drafts,
        "persisted_connector_ids": persisted_connector_ids,
        "target_resource_ids": target_resource_ids,
        "summary_text": summary_text,
        "save_request_hash": save_request_hash,
        "save_command_id": save_command_id,
        "publish_request_hash": publish_request_hash,
        "publish_command_id": publish_command_id,
        "action_ids": tuple(action_id_map[item] for item in logical_action_ids),
    }


__all__ = [
    "CorrectivePlanContinuationRequired",
    "persist_reachable_corrective_write_plan",
]
