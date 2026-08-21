"""V2 post-approval persistence identity preservation boundary.

Legacy canonical persistence intentionally keeps its historical behavior of
allocating new plan/action/evidence ids whenever ``__replan_from_plan_id__`` is
present.  Runtime R2.1 must not change that behavior globally.  This subclass
uses the typed R2.1 marker only for a reviewed V2 generation whose plan/action
ids were already allocated before Review/Domain Validation.
"""

from __future__ import annotations

from json import dumps
from typing import cast

from google_work_agent.adapters.langgraph.canonical_planning_runtime import (
    LangGraphWorkflowRuntime as _CanonicalPlanningRuntime,
    connector_ids_from_frozen_routes,
    replace_llm_expected_with_deterministic_projection,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState, _require_state_value
from google_work_agent.application import (
    PublishWritePlanCommand,
    SaveWritePlanCommand,
    WriteActionDraft,
    WriteEvidenceDraft,
)
from google_work_agent.application.calendar_conflicts import CALENDAR_CONFLICT_TOOLS
from google_work_agent.application.task_duplicates import TASK_CREATE_TOOL, evidence_duplicate_risk
from google_work_agent.application.workflows.handoff_contracts import ActionPlanDraftV1
from google_work_agent.application.workflows.post_approval_replan_v2 import (
    PostApprovalReplanV2Error,
    validate_post_approval_replan_identity,
    validate_preallocated_plan_identity,
)
from google_work_agent.application.workflows.retrieval_evidence_store import resolve_evidence_projection
from google_work_agent.ports import EvidenceOriginType, PlanStatus

_POST_APPROVAL_REPLAN_KEY = "__v2_post_approval_replan_identity__"


class ProductionV2PersistenceIdentityError(RuntimeError):
    """Reviewed V2 identity cannot be proven equal to durable persistence."""


class ProductionV2PersistenceRuntime(_CanonicalPlanningRuntime):
    """Canonical persistence plus one V2-only preallocated identity branch."""

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        raw_identity = state.get(_POST_APPROVAL_REPLAN_KEY)
        if raw_identity is None:
            return super()._persist_write_plan(state, plan_draft)
        try:
            identity = validate_post_approval_replan_identity(raw_identity)
        except PostApprovalReplanV2Error as exc:
            raise ProductionV2PersistenceIdentityError(str(exc)) from exc
        if identity["phase"] != "IDENTITY_PREALLOCATED":
            raise ProductionV2PersistenceIdentityError(
                "post-approval persistence reached before V2 identity preallocation"
            )
        if state.get("__replan_from_plan_id__") != identity["source_plan_id"]:
            raise ProductionV2PersistenceIdentityError(
                "post-approval persistence source plan does not match rollover contract"
            )
        return self._persist_preallocated_v2_replan(
            state=state,
            plan_draft=plan_draft,
            source_plan_id=identity["source_plan_id"],
            identity=identity,
        )

    def _persist_preallocated_v2_replan(
        self,
        *,
        state: GraphState,
        plan_draft: ActionPlanDraftV1,
        source_plan_id: str,
        identity: object,
    ) -> str:
        plan_draft = replace_llm_expected_with_deterministic_projection(plan_draft)
        connector_ids = connector_ids_from_frozen_routes(state=state, plan_draft=plan_draft)
        run_id = cast(str, state["run_id"])
        run_version = self._current_run_version(run_id)
        plan_id = self._required_string(plan_draft.get("plan_id"), "plan_id")
        action_ids = [
            self._required_string(action.get("action_id"), "action_id")
            for action in plan_draft["actions"]
        ]
        try:
            typed_identity = validate_post_approval_replan_identity(identity)
            validate_preallocated_plan_identity(
                identity=typed_identity,
                plan_id=plan_id,
                action_ids=action_ids,
            )
        except PostApprovalReplanV2Error as exc:
            raise ProductionV2PersistenceIdentityError(str(exc)) from exc

        plans = self._plans_for_run(run_id)
        source_plan = next((plan for plan in plans if plan.id == source_plan_id), None)
        if source_plan is None:
            raise ProductionV2PersistenceIdentityError(
                f"post-approval replan source not found: {source_plan_id}"
            )
        if source_plan.status is not PlanStatus.SUPERSEDED:
            raise ProductionV2PersistenceIdentityError(
                "post-approval source plan must be SUPERSEDED before fresh persistence"
            )
        if any(plan.id == plan_id for plan in plans):
            raise ProductionV2PersistenceIdentityError(
                "preallocated V2 plan id already exists in the durable run"
            )
        revision_no = max(plan.revision_no for plan in plans) + 1

        # V2 plan/action ids are already official Review/DV authority. Preserve
        # them exactly; only durable Evidence ids are newly allocated here.
        action_id_map = {action_id: action_id for action_id in action_ids}
        evidence_id_map: dict[str, str] = {}
        allocated_evidence_ids: set[str] = set()
        for evidence_ref in plan_draft["evidence_refs"]:
            durable_evidence_id = self._id_factory()
            if not durable_evidence_id or durable_evidence_id == evidence_ref:
                raise ProductionV2PersistenceIdentityError(
                    "post-approval replan requires a fresh durable Evidence id"
                )
            if durable_evidence_id in allocated_evidence_ids:
                raise ProductionV2PersistenceIdentityError(
                    "durable Evidence id factory produced a duplicate id"
                )
            allocated_evidence_ids.add(durable_evidence_id)
            evidence_id_map[evidence_ref] = durable_evidence_id

        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
        evidence_drafts = {
            item["evidence_id"]: item
            for item in resolve_evidence_projection(
                store=self._evidence_store,
                run_id=run_id,
                retrieval_result=retrieval_result,
            )
        }
        if set(plan_draft["evidence_refs"]) - set(evidence_drafts):
            raise ProductionV2PersistenceIdentityError(
                "post-approval persistence references unavailable current-run Evidence"
            )
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
            for evidence_id in plan_draft["evidence_refs"]
        )

        acquisition = _require_state_value(state["acquisition_result"], "acquisition_result")
        mapped_actions: list[WriteActionDraft] = []
        for action in plan_draft["actions"]:
            action_id = cast(str, action["action_id"])
            connector_id = connector_ids[action_id]
            target_ref_id = self._resolve_target_resource_ref_for_connector(
                run_id=run_id,
                connector_id=connector_id,
                resource_handle=action.get("target_resource_ref_id"),
                acquisition_result=acquisition,
            )
            mapped_actions.append(
                WriteActionDraft(
                    action_id=action_id_map[action_id],
                    connector_id=connector_id,
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
                request_hash=self._request_hash(
                    {"kind": "save_write_plan", "plan_id": plan_id}
                ),
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
            raise ProductionV2PersistenceIdentityError(
                f"save_write_plan failed: {save_response.result_code}"
            )
        self._prove_saved_identity(
            run_id=run_id,
            plan_id=plan_id,
            revision_no=revision_no,
            action_ids=action_ids,
        )

        publish_response = self._publish_write_plan(
            PublishWritePlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash(
                    {"kind": "publish_write_plan", "plan_id": plan_id}
                ),
                plan_id=plan_id,
                run_id=run_id,
                expected_run_version=save_response.run_version,
            )
        )
        if not publish_response.applied:
            raise ProductionV2PersistenceIdentityError(
                f"publish_write_plan failed: {publish_response.result_code}"
            )
        return plan_id

    def _prove_saved_identity(
        self,
        *,
        run_id: str,
        plan_id: str,
        revision_no: int,
        action_ids: list[str],
    ) -> None:
        """Read the just-saved generation back before it can become approvable."""

        with self._unit_of_work_factory() as unit_of_work:
            plan = unit_of_work.plans.get_by_id(plan_id)
            if plan is None or plan.run_id != run_id:
                raise ProductionV2PersistenceIdentityError(
                    "saved V2 plan identity is not durable for this run"
                )
            if plan.revision_no != revision_no:
                raise ProductionV2PersistenceIdentityError(
                    "saved V2 plan revision_no differs from allocated durable revision"
                )
            actions = sorted(
                unit_of_work.actions.list_by_plan(plan_id),
                key=lambda item: item.position,
            )
        durable_action_ids = [action.id for action in actions]
        if durable_action_ids != action_ids:
            raise ProductionV2PersistenceIdentityError(
                "saved durable Action ids differ from Review/DV V2 Action ids"
            )


__all__ = [
    "ProductionV2PersistenceIdentityError",
    "ProductionV2PersistenceRuntime",
]
