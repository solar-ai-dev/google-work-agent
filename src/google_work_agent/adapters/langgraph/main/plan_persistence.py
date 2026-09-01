"""Persist the canonical Planning artifact through frozen connector routes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from json import dumps
from typing import TYPE_CHECKING, Any, cast

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    _acquired_resource_by_handle,
    _require_state_value,
    _resource_handle_for_ref,
)
from google_work_agent.adapters.langgraph.main.validate_planning_output import (
    RunScopedResourceIdentityReader,
    resolve_exact_target_evidence_handle,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    resolve_evidence_projection,
)
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
    PlannedActionV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    RetrievalResultV1,
)
from google_work_agent.application.use_cases.action.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
)
from google_work_agent.application.use_cases.action.task_duplicates import (
    TASK_CREATE_TOOL,
    evidence_duplicate_risk,
)
from google_work_agent.application.use_cases.plan.record_review_result import (
    RecordReviewResultCommandV1,
)
from google_work_agent.application.use_cases.plan.write_plan_contracts import (
    PublishWritePlanCommand,
    SaveWritePlanCommand,
    WriteActionDraft,
    WriteEvidenceDraft,
)
from google_work_agent.application.use_cases.resource_ref.persist_resource_ref import (
    persist_registered_resource_ref,
)
from google_work_agent.application.use_cases.resource_ref.resource_ref_projection import (
    resource_ref_from_snapshot,
)
from google_work_agent.application.use_cases.verification.write_verification_projection import (
    build_expected_verification_projection,
)
from google_work_agent.domain.evidence.model import EvidenceOriginType
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)

if TYPE_CHECKING:
    from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


def connector_ids_from_frozen_routes(
    *,
    state: GraphState,
    plan: ActionPlanDraftV2,
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

    actions = plan["actions"]
    if len(actions) != len(raw_routes):
        raise ValueError("write actions must align exactly with frozen output routes")

    connector_ids: dict[str, str] = {}
    for index, (action, raw_route) in enumerate(zip(actions, raw_routes, strict=True)):
        if not isinstance(raw_route, Mapping):
            raise ValueError(f"output_routes[{index}] must be an object")
        if action["route_id"] != raw_route.get("route_id"):
            raise ValueError(f"write action route does not match frozen route at index {index}")
        if action["tool_id"] != raw_route.get("selected_tool_id"):
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


def evidence_ids_from_plan(plan: ActionPlanDraftV2) -> list[str]:
    """Return each linked Evidence id once, preserving Planning order."""

    result: list[str] = []
    for action in plan["actions"]:
        for evidence_id in action["evidence_refs"]:
            if evidence_id not in result:
                result.append(evidence_id)
    return result


def expected_for_action(action: PlannedActionV2) -> dict[str, object]:
    return build_expected_verification_projection(
        tool_name=action["tool_id"],
        arguments=action["arguments"],
    )


def target_handle_for_action(
    *,
    run_id: str,
    action: PlannedActionV2,
    evidence_by_id: Mapping[str, EvidenceDraftV1],
    resource_identity_reader: RunScopedResourceIdentityReader,
) -> str | None:
    if action["effect"] == "CREATE":
        return None
    return resolve_exact_target_evidence_handle(
        tool_id=action["tool_id"],
        arguments=action["arguments"],
        evidence_refs=action["evidence_refs"],
        evidence_by_id=evidence_by_id,
        run_id=run_id,
        resource_identity_reader=resource_identity_reader,
        path=f"ActionPlanDraftV2.actions[{action['action_id']!r}]",
    )


def _connector_id_for_evidence_handle(
    *,
    state: GraphState,
    resource_handle: str,
) -> str:
    handle_kind = resource_handle.partition(":")[0]
    if handle_kind.startswith("gmail_"):
        category = "GMAIL"
    elif handle_kind in {"task", "task_list"}:
        category = "TASK"
    elif handle_kind in {"calendar", "calendar_event", "calendar_freebusy"}:
        category = "CALENDAR"
    else:
        raise ValueError(f"unsupported evidence resource handle: {resource_handle}")
    route_plan = _require_state_value(state.get("tool_route_plan"), "tool_route_plan")
    connector_ids = {
        str(route["connector_id"])
        for route in route_plan["input_plan"]["input_routes"]
        if category in str(route["resource_type"]).upper()
    }
    if len(connector_ids) != 1:
        raise ValueError(
            "evidence ResourceRef must resolve to exactly one frozen connector; "
            f"handle={resource_handle!r}, connectors={sorted(connector_ids)}"
        )
    return next(iter(connector_ids))


def _current_retrieval_locator(
    *, retrieval_result: RetrievalResultV1, evidence: EvidenceDraftV1
) -> str:
    reason_codes = evidence.get("reason_codes", [])
    roles = [item for item in reason_codes if item in {"SUPPORTS", "CONTRADICTS", "CONTEXT"}]
    if len(roles) != 1:
        raise ValueError("selected Evidence must carry exactly one canonical context role")
    return dumps(
        {
            "retrieval_artifact_id": retrieval_result["meta"]["artifact_id"],
            "segment_id": evidence["segment_id"],
            "role": roles[0],
            "resource_handle": evidence["resource_handle"],
            "source_locator": evidence.get("locator"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class PlanPersistenceMixin:
    """Canonical runtime with deterministic Expected and explicit connector persistence."""

    if TYPE_CHECKING:
        _id_factory: Callable[[], str]
        _now_ms: Callable[[], int]
        _evidence_store: Any
        _unit_of_work_factory: Callable[[], UnitOfWork]
        _save_write_plan: Callable[[SaveWritePlanCommand], Any]
        _publish_write_plan: Callable[[PublishWritePlanCommand], Any]
        _record_review_result: Callable[[RecordReviewResultCommandV1], Any]

        def _current_run_version(self, run_id: str) -> int: ...

        def _required_string(self, value: object, field_name: str) -> str: ...

        def _plans_for_run(self, run_id: str) -> tuple[Any, ...]: ...

        def _calendar_plan_risk(
            self, *, state: GraphState, action: Mapping[str, object]
        ) -> dict[str, object]: ...

        def _request_hash(self, payload: dict[str, object]) -> str: ...

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

                def get_default_calendar_id() -> str | None:
                    return getattr(settings_service(), "default_calendar_id", None)

                default_calendar_id_provider = get_default_calendar_id

        if kwargs.get("connector_execution") is None:
            raise TypeError("connector_execution is required")

        next_initializer = cast(Callable[..., None], super().__init__)
        next_initializer(
            *args,
            default_calendar_id_provider=default_calendar_id_provider,
            **kwargs,
        )

    def _persist_write_plan(
        self,
        state: GraphState,
        plan: ActionPlanDraftV2,
        resource_identity_reader: RunScopedResourceIdentityReader,
    ) -> str:
        connector_ids = connector_ids_from_frozen_routes(state=state, plan=plan)
        run_id = state["run_id"]
        run_version = self._current_run_version(run_id)
        replan_from_plan_id = state.get("__replan_from_plan_id__")
        revision_no = 1
        plan_id = self._required_string(plan["meta"].get("artifact_id"), "plan artifact_id")
        action_id_map = {action["action_id"]: action["action_id"] for action in plan["actions"]}
        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
        evidence_ids = evidence_ids_from_plan(plan)
        evidence_id_map = {item: item for item in evidence_ids}
        if replan_from_plan_id is not None:
            plans = self._plans_for_run(run_id)
            if not any(plan.id == replan_from_plan_id for plan in plans):
                raise LookupError(f"replan source not found: {replan_from_plan_id}")
            revision_no = max(plan.revision_no for plan in plans) + 1
            plan_id = self._id_factory()
            action_id_map = {action["action_id"]: self._id_factory() for action in plan["actions"]}
            evidence_id_map = {item: self._id_factory() for item in evidence_ids}

        evidence_drafts = {
            item["evidence_id"]: item
            for item in resolve_evidence_projection(
                store=self._evidence_store, run_id=run_id, retrieval_result=retrieval_result
            )
        }
        missing_evidence = set(evidence_ids) - set(evidence_drafts)
        if missing_evidence:
            raise LookupError(
                "Planning evidence projection is unavailable: " + ",".join(sorted(missing_evidence))
            )
        acquisition = _require_state_value(state["acquisition_result"], "acquisition_result")
        mapped_evidence = tuple(
            WriteEvidenceDraft(
                evidence_id=evidence_id_map[evidence_id],
                origin_type=EvidenceOriginType.GOOGLE_RESOURCE,
                kind=evidence_drafts[evidence_id]["kind"],
                excerpt=evidence_drafts[evidence_id]["excerpt"],
                locator_json=_current_retrieval_locator(
                    retrieval_result=retrieval_result,
                    evidence=evidence_drafts[evidence_id],
                ),
                resource_ref_id=self._resolve_target_resource_ref_for_connector(
                    run_id=run_id,
                    connector_id=_connector_id_for_evidence_handle(
                        state=state,
                        resource_handle=evidence_drafts[evidence_id]["resource_handle"],
                    ),
                    resource_handle=evidence_drafts[evidence_id]["resource_handle"],
                    acquisition_result=acquisition,
                ),
            )
            for evidence_id in evidence_ids
        )
        mapped_actions: list[WriteActionDraft] = []
        for position, action in enumerate(plan["actions"], start=1):
            connector_id = connector_ids[action["action_id"]]
            target_handle = target_handle_for_action(
                run_id=run_id,
                action=action,
                evidence_by_id=evidence_drafts,
                resource_identity_reader=resource_identity_reader,
            )
            target_ref_id = self._resolve_target_resource_ref_for_connector(
                run_id=run_id,
                connector_id=connector_id,
                resource_handle=target_handle,
                acquisition_result=acquisition,
            )
            mapped_actions.append(
                WriteActionDraft(
                    action_id=action_id_map[action["action_id"]],
                    connector_id=connector_id,
                    position=position,
                    tool_name=action["tool_id"],
                    arguments=action["arguments"],
                    expected=expected_for_action(action),
                    evidence_ids=tuple(evidence_id_map[item] for item in action["evidence_refs"]),
                    depends_on_action_ids=tuple(
                        action_id_map[item] for item in action["depends_on_action_ids"]
                    ),
                    target_resource_ref_id=target_ref_id,
                    risk=(
                        evidence_duplicate_risk(
                            arguments=action["arguments"],
                            acquisition_result=acquisition,
                            checked_at_ms=self._now_ms(),
                        )
                        if action["tool_id"] == TASK_CREATE_TOOL
                        else self._calendar_plan_risk(state=state, action=action)
                        if action["tool_id"] in CALENDAR_CONFLICT_TOOLS
                        else {}
                    ),
                )
            )
        review_artifact_id, review_version = self._review_proof_for_persistence(
            state=state,
        )
        save_response = self._save_write_plan(
            SaveWritePlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "save_write_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                revision_no=revision_no,
                summary_text=self._plan_summary(state),
                expected_run_version=run_version,
                actions=tuple(mapped_actions),
                evidence=mapped_evidence,
                review_version=review_version,
            )
        )
        if not save_response.applied:
            raise RuntimeError(f"save_write_plan failed: {save_response.result_code}")
        self._persist_initial_review_pass(
            plan_id=plan_id,
            plan_revision_no=revision_no,
            review_artifact_id=review_artifact_id,
            review_version=review_version,
            action_versions={action.action_id: 0 for action in mapped_actions},
        )
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

    def _plan_summary(self, state: GraphState) -> str:
        request_intent = _require_state_value(state.get("request_intent"), "request_intent")
        return self._required_string(request_intent.get("goal"), "request_intent.goal")

    @staticmethod
    def _review_proof_for_persistence(
        *,
        state: GraphState,
    ) -> tuple[str, int]:
        review = _require_state_value(state.get("plan_review"), "plan_review")
        if review["status"] != "PASS":
            raise ValueError("only a PASS Review may open a persisted Plan approval gate")
        artifact_id = review["meta"]["artifact_id"]
        revision = review["meta"]["revision"]
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("persisted Review artifact_id is required")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("persisted Review revision must be positive")
        return artifact_id, revision

    def _persist_initial_review_pass(
        self,
        *,
        plan_id: str,
        plan_revision_no: int,
        review_artifact_id: str,
        review_version: int,
        action_versions: Mapping[str, int],
    ) -> None:
        result = self._record_review_result(
            RecordReviewResultCommandV1(
                command_id=self._id_factory(),
                plan_id=plan_id,
                expected_plan_version=plan_revision_no,
                expected_review_version=review_version,
                review_artifact_id=review_artifact_id,
                review_version=review_version,
                disposition="PASS",
                based_on_action_versions=action_versions,
            )
        )
        if not result.applied:
            raise RuntimeError(f"record_review_result failed: {result.result_code}")

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
            existing = unit_of_work.resource_refs.get(resource_handle)
            if existing is not None:
                if existing.connector_id != connector_id:
                    raise ValueError("target ResourceRef connector does not match frozen route")
                return existing.id
            for resource_ref in unit_of_work.resource_refs.list_for_run_bounded(run_id, limit=1000):
                if (
                    resource_ref.connector_id == connector_id
                    and resource_handle == _resource_handle_for_ref(resource_ref)
                ):
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
                    str(item)
                    for item in cast(list[object], resource.get("related_resource_ids") or [])
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
            persisted = persist_registered_resource_ref(unit_of_work, resource_ref)
            unit_of_work.commit()
            return persisted.id


__all__ = [
    "PlanPersistenceMixin",
    "connector_ids_from_frozen_routes",
    "evidence_ids_from_plan",
    "expected_for_action",
    "target_handle_for_action",
]
