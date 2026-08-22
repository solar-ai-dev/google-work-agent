"""Failure-safe reserved corrective-plan persistence."""

from __future__ import annotations

from hashlib import sha256
from json import dumps, loads
from typing import Any, cast

from google_work_agent.adapters.langgraph.graph_state import (
    GraphState,
    _require_state_value,
    _resource_handle_for_ref,
)
from google_work_agent.adapters.langgraph.plan_persistence import (
    connector_ids_from_frozen_routes,
    replace_llm_expected_with_deterministic_projection,
    target_resource_connector_ids_from_actions,
)
from google_work_agent.application.calendar_conflicts import CALENDAR_CONFLICT_TOOLS
from google_work_agent.application.orchestration.handoff_contracts import ActionPlanDraftV1
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    resolve_evidence_projection,
)
from google_work_agent.application.task_duplicates import TASK_CREATE_TOOL, evidence_duplicate_risk
from google_work_agent.application.write_plan_contracts import (
    PublishWritePlanCommand,
    SaveWritePlanCommand,
    WriteActionDraft,
    WriteEvidenceDraft,
)
from google_work_agent.domain import (
    ActionStatus,
    RunStatus,
    build_p0_tool_registry,
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.ports import (
    CommandReceiptStatus,
    EvidenceOriginType,
    PlanRecord,
    PlanStatus,
)


def persist_reserved_corrective_write_plan(
    runtime: Any,
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
    reserved_plan: PlanRecord,
) -> str:
    """Materialize or continue one Domain-reserved corrective revision safely.

    Only the empty reserved DRAFT may consult current-run transient Retrieval
    evidence/acquisition. Once Save has committed children, the durable Plan
    aggregate and command receipts are the continuation authority.
    """

    run_id = cast(str, state["run_id"])
    if reserved_plan.run_id != run_id:
        raise ValueError("corrective destination must be owned by the Run")

    plans = runtime._plans_for_run(run_id)
    if not plans:
        raise LookupError(f"no plans found for corrective run: {run_id}")
    latest_plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms))
    if latest_plan.id != reserved_plan.id or latest_plan.revision_no != reserved_plan.revision_no:
        raise ValueError("corrective destination must be the latest reserved Plan revision")

    (
        deterministic_plan,
        logical_action_ids,
        logical_evidence_ids,
        action_id_map,
        evidence_id_map,
    ) = _candidate_identity_maps(
        plan_draft=plan_draft,
        reserved_plan=reserved_plan,
    )

    # Determine the durable state before consulting any transient source.
    # Materialized DRAFT and WAITING_APPROVAL must be restart-safe with an
    # empty RunScopedEvidenceStore and without acquisition rehydration.
    with runtime._unit_of_work_factory() as unit_of_work:
        current_run = unit_of_work.runs.get_by_id(run_id)
        current_plan = unit_of_work.plans.get_by_id(reserved_plan.id)
        if current_run is None or current_plan is None:
            raise LookupError("corrective Run/Plan disappeared during persistence")
        current_plans = unit_of_work.plans.list_by_run(run_id)
        if not current_plans:
            raise LookupError(f"no plans found for corrective run: {run_id}")
        current_latest = max(
            current_plans,
            key=lambda item: (item.revision_no, item.created_at_ms),
        )
        if (
            current_latest.id != reserved_plan.id
            or current_latest.revision_no != reserved_plan.revision_no
        ):
            raise ValueError("corrective destination is no longer the latest Plan revision")
        existing_actions = unit_of_work.actions.list_by_plan(reserved_plan.id)
        save_command_id = _corrective_command_id(kind="save", plan_id=reserved_plan.id)
        publish_command_id = _corrective_command_id(kind="publish", plan_id=reserved_plan.id)
        save_receipt = unit_of_work.command_receipts.get_by_command_id(save_command_id)
        publish_receipt = unit_of_work.command_receipts.get_by_command_id(publish_command_id)

        if (
            current_plan.status is PlanStatus.WAITING_APPROVAL
            and current_run.status is RunStatus.WAITING_APPROVAL
        ):
            use_durable_continuation = True
        elif current_plan.status is PlanStatus.DRAFT and current_run.status is RunStatus.PLANNING:
            if existing_actions:
                use_durable_continuation = True
            else:
                use_durable_continuation = False
                if save_receipt is not None or publish_receipt is not None:
                    raise ValueError(
                        "empty reserved corrective DRAFT conflicts with "
                        "durable command receipts"
                    )
        else:
            raise ValueError(
                "corrective persistence requires PLANNING/DRAFT or "
                "WAITING_APPROVAL/WAITING_APPROVAL"
            )

    if use_durable_continuation:
        return _continue_durable_corrective_write_plan(
            runtime,
            state=state,
            plan_draft=plan_draft,
            reserved_plan=reserved_plan,
        )

    # Empty reserved DRAFT: this is the only branch allowed to materialize
    # Evidence from current-run memory or resolve a target through acquisition.
    logical_connector_ids = connector_ids_from_frozen_routes(
        state=state,
        plan_draft=deterministic_plan,
    )
    persisted_connector_ids = {
        action_id_map[action_id]: logical_connector_ids[action_id]
        for action_id in logical_action_ids
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

    target_resource_ids = {
        action["action_id"]: runtime._resolve_target_resource_ref_for_connector(
                run_id=run_id,
                connector_id=target_resource_connectors[action["action_id"]],
                resource_handle=action.get("target_resource_ref_id"),
                acquisition_result=_require_state_value(
                    state["acquisition_result"], "acquisition_result"
                ),
            )
        for action in deterministic_plan["actions"]
    }

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
            connector_id=logical_connector_ids[action["action_id"]],
            position=action["position"],
            tool_name=action["tool_name"],
            arguments=action["arguments"],
            expected=action["expected"],
            evidence_ids=tuple(
                evidence_id_map[item] for item in action["evidence_refs"]
            ),
            depends_on_action_ids=tuple(
                action_id_map[item]
                for item in action.get("depends_on_action_ids", [])
            ),
            target_resource_ref_id=target_resource_ids[action["action_id"]],
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

    save_response = runtime._save_write_plan(
        SaveWritePlanCommand(
            command_id=save_command_id,
            request_hash=save_request_hash,
            plan_id=reserved_plan.id,
            run_id=run_id,
            revision_no=reserved_plan.revision_no,
            summary_text=summary_text,
            expected_run_version=runtime._current_run_version(run_id),
            actions=mapped_actions,
            evidence=mapped_evidence,
        )
    )
    if not save_response.applied:
        raise RuntimeError(
            f"save corrective write plan failed: {save_response.result_code}"
        )

    # From this line forward, transient evidence/acquisition is no longer
    # authoritative. Re-read the committed aggregate and continue through the
    # same durable-only path used by restart recovery.
    return _continue_durable_corrective_write_plan(
        runtime,
        state=state,
        plan_draft=plan_draft,
        reserved_plan=reserved_plan,
    )


def _continue_durable_corrective_write_plan(
    runtime: Any,
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
    reserved_plan: PlanRecord,
) -> str:
    proof = _build_durable_materialization_proof(
        runtime,
        state=state,
        plan_draft=plan_draft,
        reserved_plan=reserved_plan,
    )

    if (
        proof["run_status"] is RunStatus.WAITING_APPROVAL
        and proof["plan_status"] is PlanStatus.WAITING_APPROVAL
    ):
        return reserved_plan.id

    publish_response = runtime._publish_write_plan(
        PublishWritePlanCommand(
            command_id=proof["publish_command_id"],
            request_hash=proof["publish_request_hash"],
            plan_id=reserved_plan.id,
            run_id=reserved_plan.run_id,
            expected_run_version=proof["run_version"],
        )
    )
    if not publish_response.applied:
        raise RuntimeError(
            f"publish corrective write plan failed: {publish_response.result_code}"
        )
    return reserved_plan.id


def _build_durable_materialization_proof(
    runtime: Any,
    *,
    state: GraphState,
    plan_draft: ActionPlanDraftV1,
    reserved_plan: PlanRecord,
) -> dict[str, Any]:
    """Prove a committed corrective materialization without transient retrieval data."""

    run_id = cast(str, state["run_id"])
    if reserved_plan.run_id != run_id:
        raise ValueError("corrective destination must be owned by the Run")

    (
        deterministic_plan,
        logical_action_ids,
        _logical_evidence_ids,
        action_id_map,
        evidence_id_map,
    ) = _candidate_identity_maps(
        plan_draft=plan_draft,
        reserved_plan=reserved_plan,
    )
    logical_connector_ids = connector_ids_from_frozen_routes(
        state=state,
        plan_draft=deterministic_plan,
    )
    summary_text = runtime._required_string(deterministic_plan.get("summary"), "summary")

    with runtime._unit_of_work_factory() as unit_of_work:
        current_run = unit_of_work.runs.get_by_id(run_id)
        current_plan = unit_of_work.plans.get_by_id(reserved_plan.id)
        if current_run is None or current_plan is None:
            raise LookupError("corrective Run/Plan disappeared during durable proof")
        plans = unit_of_work.plans.list_by_run(run_id)
        if not plans:
            raise LookupError(f"no plans found for corrective run: {run_id}")
        latest = max(plans, key=lambda item: (item.revision_no, item.created_at_ms))
        if latest.id != reserved_plan.id or latest.revision_no != reserved_plan.revision_no:
            raise ValueError("corrective destination is no longer the latest Plan revision")
        valid_status_pairs = {
            (RunStatus.PLANNING, PlanStatus.DRAFT),
            (RunStatus.WAITING_APPROVAL, PlanStatus.WAITING_APPROVAL),
        }
        if (current_run.status, current_plan.status) not in valid_status_pairs:
            raise ValueError(
                "durable corrective proof requires PLANNING/DRAFT or "
                "WAITING_APPROVAL/WAITING_APPROVAL"
            )

        persisted_actions = unit_of_work.actions.list_by_plan(reserved_plan.id)
        if not persisted_actions:
            raise ValueError("durable corrective proof requires materialized Action children")

        expected_actions = {
            action_id_map[action["action_id"]]: action
            for action in deterministic_plan["actions"]
        }
        if {action.id for action in persisted_actions} != set(expected_actions):
            raise ValueError("persisted corrective Action identity set drifted")

        action_connector_reader = getattr(
            unit_of_work.actions, "connector_id_for_action", None
        )
        if not callable(action_connector_reader):
            raise RuntimeError(
                "corrective durable proof requires persisted Action connector identity"
            )
        resource_connector_reader = getattr(
            unit_of_work.resource_refs, "connector_id_for_resource_ref", None
        )
        if not callable(resource_connector_reader):
            raise RuntimeError(
                "corrective durable proof requires persisted ResourceRef connector identity"
            )

        persisted_connector_ids: dict[str, str] = {}
        target_resource_ids: dict[str, str | None] = {}
        seen_evidence: dict[str, Any] = {}

        for persisted_action in persisted_actions:
            candidate = expected_actions[persisted_action.id]
            logical_action_id = candidate["action_id"]
            expected_connector_id = logical_connector_ids.get(logical_action_id)
            if not isinstance(expected_connector_id, str) or not expected_connector_id:
                raise ValueError(
                    f"checkpoint route lacks connector identity for {logical_action_id}"
                )
            actual_connector_id = action_connector_reader(persisted_action.id)
            if actual_connector_id != expected_connector_id:
                raise ValueError("persisted corrective Action connector identity drifted")
            persisted_connector_ids[persisted_action.id] = actual_connector_id

            target_id = persisted_action.target_resource_ref_id
            target_resource_ids[logical_action_id] = target_id
            candidate_target = candidate.get("target_resource_ref_id")
            if target_id is None:
                if candidate_target is not None:
                    raise ValueError("persisted corrective target ResourceRef drifted")
            else:
                resource_ref = unit_of_work.resource_refs.get_by_id(target_id)
                if resource_ref is None or resource_ref.run_id != run_id:
                    raise ValueError(
                        "persisted corrective target ResourceRef is missing or cross-Run"
                    )
                if resource_connector_reader(target_id) != actual_connector_id:
                    raise ValueError(
                        "persisted corrective target ResourceRef connector drifted"
                    )
                durable_handles = {
                    resource_ref.id,
                    _resource_handle_for_ref(resource_ref),
                }
                if candidate_target not in durable_handles:
                    raise ValueError(
                        "checkpoint candidate target does not match persisted ResourceRef"
                    )

            expected_evidence_ids = {
                evidence_id_map[item] for item in candidate["evidence_refs"]
            }
            linked_evidence = unit_of_work.evidence.list_by_action(persisted_action.id)
            if {item.id for item in linked_evidence} != expected_evidence_ids:
                raise ValueError("persisted corrective Action-Evidence links drifted")
            for evidence in linked_evidence:
                existing = seen_evidence.get(evidence.id)
                if existing is not None and existing != evidence:
                    raise ValueError(
                        "persisted corrective Evidence identity is inconsistent"
                    )
                seen_evidence[evidence.id] = evidence

        expected_persisted_evidence_ids = set(evidence_id_map.values())
        if set(seen_evidence) != expected_persisted_evidence_ids:
            raise ValueError("persisted corrective Evidence identity set drifted")

        logical_by_persisted = {
            persisted_id: logical_id
            for logical_id, persisted_id in evidence_id_map.items()
        }
        evidence_drafts: dict[str, Any] = {}
        for persisted_id, evidence in seen_evidence.items():
            logical_id = logical_by_persisted[persisted_id]
            if (
                evidence.run_id != run_id
                or evidence.origin_type is not EvidenceOriginType.DERIVED
                or evidence.resource_ref_id is not None
                or evidence.message_id is not None
            ):
                raise ValueError("persisted corrective Evidence projection drifted")
            locator = None
            if evidence.locator_json is not None:
                locator = loads(evidence.locator_json)
            evidence_drafts[logical_id] = {
                "kind": evidence.kind,
                "excerpt": evidence.excerpt,
                "locator": locator,
            }

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
        save_receipt = unit_of_work.command_receipts.get_by_command_id(save_command_id)
        action_ids = tuple(action_id_map[item] for item in logical_action_ids)
        _require_applied_save_receipt(
            save_receipt,
            expected_request_hash=save_request_hash,
            plan_id=reserved_plan.id,
            action_ids=action_ids,
            run_id=run_id,
        )

        # Receipt equality proves that the current checkpoint candidate plus
        # durable Evidence/target/connector projection is the exact Save input.
        # Then validate that every persisted child row/link still matches it.
        _validate_persisted_materialization(
            unit_of_work=unit_of_work,
            run_id=run_id,
            plan=current_plan,
            summary_text=summary_text,
            deterministic_plan=deterministic_plan,
            action_id_map=action_id_map,
            evidence_id_map=evidence_id_map,
            evidence_drafts=evidence_drafts,
            persisted_connector_ids=persisted_connector_ids,
            target_resource_ids=target_resource_ids,
        )

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
        publish_receipt = unit_of_work.command_receipts.get_by_command_id(
            publish_command_id
        )

        if (
            current_run.status is RunStatus.PLANNING
            and current_plan.status is PlanStatus.DRAFT
        ):
            if publish_receipt is not None:
                raise ValueError(
                    "materialized corrective DRAFT has an unexpected durable Publish receipt"
                )
        else:
            _require_applied_publish_receipt(
                publish_receipt,
                expected_request_hash=publish_request_hash,
                plan_id=reserved_plan.id,
                run_id=run_id,
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
            "action_ids": action_ids,
            "run_status": current_run.status,
            "plan_status": current_plan.status,
            "run_version": current_run.version,
            "publish_receipt_present": publish_receipt is not None,
        }


def _candidate_identity_maps(
    *,
    plan_draft: ActionPlanDraftV1,
    reserved_plan: PlanRecord,
) -> tuple[
    ActionPlanDraftV1,
    list[str],
    list[str],
    dict[str, str],
    dict[str, str],
]:
    deterministic_plan = replace_llm_expected_with_deterministic_projection(plan_draft)
    logical_action_ids = [action["action_id"] for action in deterministic_plan["actions"]]
    logical_evidence_ids = list(deterministic_plan["evidence_refs"])
    if len(set(logical_action_ids)) != len(logical_action_ids):
        raise ValueError("corrective plan contains duplicate logical Action ids")
    if len(set(logical_evidence_ids)) != len(logical_evidence_ids):
        raise ValueError("corrective plan contains duplicate logical Evidence ids")
    linked_evidence_ids = {
        evidence_id
        for action in deterministic_plan["actions"]
        for evidence_id in action["evidence_refs"]
    }
    if linked_evidence_ids != set(logical_evidence_ids):
        raise ValueError("corrective plan evidence_refs must equal the linked Evidence set")

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
    persisted_ids = tuple(action_id_map.values()) + tuple(evidence_id_map.values())
    if len(set(persisted_ids)) != len(persisted_ids):
        raise ValueError("corrective persistence generated duplicate child ids")
    logical_ids = set(logical_action_ids) | set(logical_evidence_ids)
    if any(item in logical_ids for item in persisted_ids):
        raise ValueError("corrective persistence requires fresh child ids")
    return (
        deterministic_plan,
        logical_action_ids,
        logical_evidence_ids,
        action_id_map,
        evidence_id_map,
    )


def _corrective_child_id(*, kind: str, plan_id: str, logical_id: str) -> str:
    return sha256(
        f"google-work-agent:corrective:{kind}:{plan_id}:{logical_id}".encode("utf-8")
    ).hexdigest()


def _corrective_command_id(*, kind: str, plan_id: str) -> str:
    return sha256(
        f"google-work-agent:corrective-command:{kind}:{plan_id}".encode("utf-8")
    ).hexdigest()


def _candidate_materialization_projection(
    *,
    reserved_plan: PlanRecord,
    summary_text: str,
    deterministic_plan: ActionPlanDraftV1,
    action_id_map: dict[str, str],
    evidence_id_map: dict[str, str],
    evidence_drafts: dict[str, Any],
    persisted_connector_ids: dict[str, str],
    target_resource_ids: dict[str, str | None],
) -> dict[str, object]:
    evidence_projection = [
        {
            "logical_evidence_id": evidence_id,
            "persisted_evidence_id": evidence_id_map[evidence_id],
            "kind": evidence_drafts[evidence_id]["kind"],
            "excerpt": evidence_drafts[evidence_id]["excerpt"],
            "locator_json": (
                None
                if evidence_drafts[evidence_id].get("locator") is None
                else dumps(evidence_drafts[evidence_id]["locator"], sort_keys=True)
            ),
        }
        for evidence_id in deterministic_plan["evidence_refs"]
    ]
    action_projection = []
    for action in deterministic_plan["actions"]:
        persisted_action_id = action_id_map[action["action_id"]]
        action_projection.append(
            {
                "logical_action_id": action["action_id"],
                "persisted_action_id": persisted_action_id,
                "position": action["position"],
                "tool_name": action["tool_name"],
                "arguments_hash": calculate_canonical_json_hash(action["arguments"]),
                "expected_json": canonicalize_json_value(action["expected"]),
                "evidence_ids": [evidence_id_map[item] for item in action["evidence_refs"]],
                "depends_on_action_ids": [
                    action_id_map[item]
                    for item in action.get("depends_on_action_ids", [])
                ],
                "target_resource_ref_id": target_resource_ids[action["action_id"]],
                "connector_id": persisted_connector_ids[persisted_action_id],
            }
        )
    return {
        "kind": "save_corrective_write_plan_v2",
        "plan_id": reserved_plan.id,
        "revision_no": reserved_plan.revision_no,
        "summary_text": summary_text,
        "actions": action_projection,
        "evidence": evidence_projection,
    }


def _require_applied_save_receipt(
    receipt: Any,
    *,
    expected_request_hash: str,
    plan_id: str,
    action_ids: tuple[str, ...],
    run_id: str,
) -> None:
    if (
        receipt is None
        or receipt.command_type != "SaveWritePlan"
        or receipt.aggregate_type != "Run"
        or receipt.aggregate_id != run_id
        or receipt.status is not CommandReceiptStatus.APPLIED
        or receipt.request_hash != expected_request_hash
        or receipt.response_json is None
    ):
        raise ValueError("corrective materialization is not proven by the Save receipt")
    payload = loads(receipt.response_json)
    if (
        payload.get("applied") is not True
        or payload.get("plan_id") != plan_id
        or tuple(payload.get("action_ids", ())) != action_ids
    ):
        raise ValueError("corrective Save receipt does not match persisted materialization")


def _require_applied_publish_receipt(
    receipt: Any,
    *,
    expected_request_hash: str,
    plan_id: str,
    run_id: str,
) -> None:
    if (
        receipt is None
        or receipt.command_type != "PublishWritePlan"
        or receipt.aggregate_type != "Run"
        or receipt.aggregate_id != run_id
        or receipt.status is not CommandReceiptStatus.APPLIED
        or receipt.request_hash != expected_request_hash
        or receipt.response_json is None
    ):
        raise ValueError("published corrective Plan is not proven by the Publish receipt")
    payload = loads(receipt.response_json)
    if (
        payload.get("applied") is not True
        or payload.get("plan_id") != plan_id
        or payload.get("plan_status") != PlanStatus.WAITING_APPROVAL.value
    ):
        raise ValueError("corrective Publish receipt does not match durable Plan state")


def _validate_persisted_materialization(
    *,
    unit_of_work: Any,
    run_id: str,
    plan: PlanRecord,
    summary_text: str,
    deterministic_plan: ActionPlanDraftV1,
    action_id_map: dict[str, str],
    evidence_id_map: dict[str, str],
    evidence_drafts: dict[str, Any],
    persisted_connector_ids: dict[str, str],
    target_resource_ids: dict[str, str | None],
) -> None:
    if (
        plan.run_id != run_id
        or plan.summary_text != summary_text
        or plan.status not in {PlanStatus.DRAFT, PlanStatus.WAITING_APPROVAL}
    ):
        raise ValueError("persisted corrective Plan identity/summary drifted")

    persisted_actions = unit_of_work.actions.list_by_plan(plan.id)
    expected_actions = {
        action_id_map[action["action_id"]]: action
        for action in deterministic_plan["actions"]
    }
    if {action.id for action in persisted_actions} != set(expected_actions):
        raise ValueError("persisted corrective Action identity set drifted")

    registry = build_p0_tool_registry()
    connector_reader = getattr(unit_of_work.actions, "connector_id_for_action", None)
    if not callable(connector_reader):
        raise RuntimeError("corrective persistence requires durable connector identity reader")

    seen_evidence: dict[str, Any] = {}
    for persisted_action in persisted_actions:
        candidate = expected_actions[persisted_action.id]
        entry = registry.require(candidate["tool_name"])
        expected_dependencies = tuple(
            action_id_map[item] for item in candidate.get("depends_on_action_ids", [])
        )
        expected_evidence_ids = tuple(
            evidence_id_map[item] for item in candidate["evidence_refs"]
        )
        if (
            persisted_action.plan_id != plan.id
            or persisted_action.position != candidate["position"]
            or persisted_action.tool_name != candidate["tool_name"]
            or persisted_action.effect_type != entry.effect_type.value
            or persisted_action.approval_requirement != entry.approval_requirement.value
            or persisted_action.verification_policy != entry.verification_policy.value
            or persisted_action.recovery_policy != entry.recovery_policy.value
            or persisted_action.target_resource_ref_id
            != target_resource_ids[candidate["action_id"]]
            or persisted_action.status != ActionStatus.PROPOSED.value
            or persisted_action.version != 0
            or persisted_action.arguments_hash
            != calculate_canonical_json_hash(candidate["arguments"])
            or persisted_action.arguments_json != canonicalize_json_value(candidate["arguments"])
            or persisted_action.expected_json != canonicalize_json_value(candidate["expected"])
            or connector_reader(persisted_action.id)
            != persisted_connector_ids[persisted_action.id]
            or set(unit_of_work.action_dependencies.list_dependencies(persisted_action.id))
            != set(expected_dependencies)
        ):
            raise ValueError("persisted corrective Action projection drifted")

        linked_evidence = unit_of_work.evidence.list_by_action(persisted_action.id)
        if {item.id for item in linked_evidence} != set(expected_evidence_ids):
            raise ValueError("persisted corrective Action-Evidence links drifted")
        for evidence in linked_evidence:
            existing = seen_evidence.get(evidence.id)
            if existing is not None and existing != evidence:
                raise ValueError("persisted corrective Evidence identity is inconsistent")
            seen_evidence[evidence.id] = evidence

    expected_evidence_ids = set(evidence_id_map.values())
    if set(seen_evidence) != expected_evidence_ids:
        raise ValueError("persisted corrective Evidence identity set drifted")
    logical_by_persisted = {
        persisted_id: logical_id
        for logical_id, persisted_id in evidence_id_map.items()
    }
    for persisted_id, evidence in seen_evidence.items():
        logical_id = logical_by_persisted[persisted_id]
        candidate = evidence_drafts[logical_id]
        expected_locator_json = (
            None
            if candidate.get("locator") is None
            else dumps(candidate["locator"], sort_keys=True)
        )
        if (
            evidence.run_id != run_id
            or evidence.origin_type is not EvidenceOriginType.DERIVED
            or evidence.resource_ref_id is not None
            or evidence.message_id is not None
            or evidence.kind != candidate["kind"]
            or evidence.excerpt != candidate["excerpt"]
            or evidence.locator_json != expected_locator_json
        ):
            raise ValueError("persisted corrective Evidence projection drifted")


__all__ = ["persist_reserved_corrective_write_plan"]
