"""API planning and Google Workspace acquisition workflow nodes."""

from __future__ import annotations

import time as _time_module
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from hashlib import sha256
from json import dumps
from pathlib import Path
from typing import Literal, cast

import google_work_agent.application.orchestration._schema_support as _schema
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
    allowed_input_sources,
    allowed_read_tool_ids,
)
from google_work_agent.application.orchestration.confirmation import (
    build_clarification_question_v1,
)
from google_work_agent.application.orchestration.connector_read_models import (
    NormalizedConnectorRead,
    PlannedConnectorRead,
)
from google_work_agent.application.orchestration.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.orchestration.contracts import (
    AdditionalAcquisitionRequestV1,
    ApiAcquisitionResult,
    ApiPlanningResult,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    CalendarReadMode,
    ClarificationQuestionV1,
    Daypart,
    RelativeUnit,
    RequestIntentV2,
    SourceFetchPlanV1,
    SourceName,
    SourcePlanningOutputV1,
    TemporalQueryV1,
    TemporalRelation,
    Weekday,
)
from google_work_agent.application.orchestration.retrieval_read_cache import (
    DetailTargetCacheEntry,
    ReadResultCacheEntry,
    RunScopedReadResultCache,
)
from google_work_agent.application.orchestration.temporal_query import resolve_temporal_query
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    TimeRange,
)
from google_work_agent.ports.events.observability_events import ObservabilityContext
from google_work_agent.ports.llm import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

JsonObject = dict[str, object]

DEFAULT_TIMEZONE = "Asia/Seoul"


@dataclass(frozen=True, slots=True)
class RetrievalBudget:
    max_sources: int = 3
    max_pages_per_source: int = 1
    max_page_size: int = 20
    max_candidates_per_source: int = 20
    max_details_per_source: int = 10

    def as_remaining(self) -> dict[str, int]:
        return {
            "sources": self.max_sources,
            "pages": self.max_sources * self.max_pages_per_source,
            "candidates": self.max_sources * self.max_candidates_per_source,
            "details": self.max_sources * self.max_details_per_source,
        }


@dataclass(frozen=True, slots=True)
class MaterializedRetrievalRead:
    """Local-only result of converting one successful connector read."""

    source_summary: dict[str, object]
    read_result_handle: str | None
    segment_handles: tuple[str, ...]


DEFAULT_RETRIEVAL_BUDGET = RetrievalBudget()
SOURCE_FETCH_PLAN_SCHEMA_VERSION = 2
TEMPORAL_QUERY_SCHEMA_VERSION = 1
ACQUISITION_RESULT_SCHEMA_VERSION = 1
_TEMPORAL_QUERY_JSON_SCHEMA = {
    "type": "object",
    "required": [
        "schema_version",
        "relation",
        "relative_unit",
        "relative_offset",
        "weekday",
        "daypart",
        "absolute_start",
        "absolute_end",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "relation": {"type": "string", "enum": ["RELATIVE", "ABSOLUTE"]},
        "relative_unit": {"type": ["string", "null"], "enum": ["DAY", "WEEK", None]},
        "relative_offset": {"type": ["integer", "null"]},
        "weekday": {
            "type": ["string", "null"],
            "enum": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN", None],
        },
        "daypart": {
            "type": ["string", "null"],
            "enum": ["MORNING", "AFTERNOON", "EVENING", None],
        },
        "absolute_start": {"type": ["string", "null"]},
        "absolute_end": {"type": ["string", "null"]},
    },
}
SOURCE_FETCH_PLAN_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="source-fetch-plan-v2-list",
    json_schema={
        "type": "array",
        "items": {
            "type": "object",
            "required": [
                "schema_version",
                "source",
                "priority",
                "reason_codes",
                "constraints",
                "page_size",
                "max_pages",
                "max_candidates",
                "detail_limit",
                "required",
                "calendar_read_mode",
                "temporal_query",
            ],
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "integer", "enum": [2]},
                "source": {"type": "string", "enum": ["GMAIL", "TASKS", "CALENDAR"]},
                "priority": {"type": "integer", "minimum": 1},
                "reason_codes": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "object"},
                "page_size": {"type": "integer", "minimum": 1},
                "max_pages": {"type": "integer", "minimum": 0},
                "max_candidates": {"type": "integer", "minimum": 0},
                "detail_limit": {"type": "integer", "minimum": 0},
                "required": {"type": "boolean"},
                "calendar_read_mode": {
                    "type": ["string", "null"],
                    "enum": ["EVENTS_ONLY", "EVENTS_AND_FREEBUSY", None],
                },
                "temporal_query": {
                    "oneOf": [{"type": "null"}, _TEMPORAL_QUERY_JSON_SCHEMA],
                },
            },
            # docs/05 section 8 (Calendar Typed Query 계약): these cross-field
            # rules are expressible in JSON Schema, so they belong here (where
            # the provider's own schema-repair loop can fix them) rather than
            # relying on the semantic validator to catch them after the fact.
            "allOf": [
                {
                    "if": {"properties": {"source": {"enum": ["GMAIL", "TASKS"]}}},
                    "then": {
                        "properties": {
                            "calendar_read_mode": {"const": None},
                            "temporal_query": {"const": None},
                        }
                    },
                },
                {
                    "if": {"properties": {"source": {"const": "CALENDAR"}}},
                    "then": {
                        "properties": {
                            "calendar_read_mode": {"enum": ["EVENTS_ONLY", "EVENTS_AND_FREEBUSY"]}
                        }
                    },
                },
                {
                    "if": {"properties": {"calendar_read_mode": {"const": "EVENTS_ONLY"}}},
                    "then": {"properties": {"temporal_query": {"const": None}}},
                },
                {
                    "if": {"properties": {"calendar_read_mode": {"const": "EVENTS_AND_FREEBUSY"}}},
                    "then": {"properties": {"temporal_query": _TEMPORAL_QUERY_JSON_SCHEMA}},
                },
            ],
        },
    },
)

_SOURCE_VALUES = {"GMAIL", "TASKS", "CALENDAR"}
_CONFIRMATION_REASON_CODES = {
    "NEEDS_CONFIRMATION",
    "QUERY_SCOPE_EXPANSION_REQUIRES_CONFIRMATION",
    "QUERY_LOW_CONFIDENCE_RESULTS",
}
_AUTH_ERRORS = {
    GoogleWorkspaceErrorCode.AUTH_EXPIRED,
    GoogleWorkspaceErrorCode.PERMISSION_DENIED,
}
_CALENDAR_READ_MODE_VALUES = {"EVENTS_ONLY", "EVENTS_AND_FREEBUSY"}
_TEMPORAL_RELATION_VALUES = {"RELATIVE", "ABSOLUTE"}
_RELATIVE_UNIT_VALUES = {"DAY", "WEEK"}
_WEEKDAY_VALUES = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
_DAYPART_VALUES = {"MORNING", "AFTERNOON", "EVENING"}


class SourcePlanningValidationError(ValueError):
    """Raised when a source planning structured output is invalid."""


def _default_now_ms() -> int:
    return int(_time_module.time() * 1000)


class ApiDiscoveryAcquisitionAgent:
    """Plan sources and orchestrate reads through a connector capability."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        connector_reader: ConnectorReadProjection,
        prompt_ref: PromptReference | None = None,
        retrieval_budget: RetrievalBudget = DEFAULT_RETRIEVAL_BUDGET,
        manifest_path: Path | None = None,
        now_ms: Callable[[], int] | None = None,
        timezone_provider: Callable[[], str] | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._connector_reader = connector_reader
        self._prompt_ref = prompt_ref or load_acquisition_plan_sources_prompt_reference(
            manifest_path
        )
        self._retrieval_budget = retrieval_budget
        # docs/05 section 8 (Calendar Typed Query 계약): Calendar temporal normalization is
        # deterministic code's responsibility. Both fall back to safe
        # defaults so existing callers that do not pass them keep working;
        # production wiring (see LangGraphWorkflowRuntime) supplies the real
        # ClockPort and AppSettings.timezone.
        self._now_ms = now_ms or _default_now_ms
        self._timezone_provider = timezone_provider or (lambda: DEFAULT_TIMEZONE)

    @property
    def prompt_ref(self) -> PromptReference:
        return self._prompt_ref

    @property
    def retrieval_budget(self) -> RetrievalBudget:
        """Expose the immutable executor budget to the V2 compatibility boundary."""
        return self._retrieval_budget

    def plan_sources(
        self,
        *,
        request_intent: RequestIntentV2,
        request: WorkflowStartRequest,
        additional_acquisition_request: AdditionalAcquisitionRequestV1 | None = None,
        tool_route_plan: ToolRoutePlanV2 | None = None,
    ) -> SourcePlanningOutputV1:
        llm_result = self.invoke_plan_sources_llm(
            request_intent=request_intent,
            request=request,
            additional_acquisition_request=additional_acquisition_request,
            tool_route_plan=tool_route_plan,
        )
        return self.build_planning_output_from_llm_result(
            llm_result,
            tool_route_plan=tool_route_plan,
        )

    def invoke_plan_sources_llm(
        self,
        *,
        request_intent: RequestIntentV2,
        request: WorkflowStartRequest,
        additional_acquisition_request: AdditionalAcquisitionRequestV1 | None = None,
        tool_route_plan: ToolRoutePlanV2 | None = None,
    ) -> StructuredLLMResult:
        # additional_acquisition_request is accepted but not projected into
        # the Prompt: prompt-runtime-input-contract-v1.json's
        # retrieval.plan_query entry has no field for "this is a follow-up
        # round" and its schema is additionalProperties:false. Canonical
        # (05-context-retrieval.md RetrievalStateV1.query_attempts) models
        # repeat rounds as Retrieval Local State / the retrieval.plan_query.revise
        # slot, not an extra INITIAL-prompt field -- neither is implemented
        # yet, so this parameter is a FOLLOWING_WAVE_DEPENDENCY, not silently
        # dropped functionality.
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=_plan_query_prompt_input(
                request_intent=request_intent,
                request=request,
                retrieval_budget=self._retrieval_budget,
                tool_route_plan=tool_route_plan,
            ),
            output_schema=SOURCE_FETCH_PLAN_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:acquisition.plan_sources",
            ),
            semantic_validate=(
                validate_source_fetch_plans_v1
                if tool_route_plan is None
                else lambda value: validate_source_fetch_plans_for_route(
                    value,
                    tool_route_plan=tool_route_plan,
                )
            ),
        )

    def build_planning_output_from_llm_result(
        self,
        llm_result: StructuredLLMResult,
        *,
        tool_route_plan: ToolRoutePlanV2 | None = None,
    ) -> SourcePlanningOutputV1:
        plans = (
            validate_source_fetch_plans_v1(llm_result.structured_output)
            if tool_route_plan is None
            else validate_source_fetch_plans_for_route(
                llm_result.structured_output,
                tool_route_plan=tool_route_plan,
            )
        )
        return _interpret_source_plans(plans=plans, llm_result=llm_result)

    def acquire(
        self,
        *,
        plans: list[SourceFetchPlanV1],
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2 | None = None,
        tool_route_plan: ToolRoutePlanV2 | None = None,
        read_result_cache: RunScopedReadResultCache | None = None,
        read_handle_factory: Callable[[], str] | None = None,
        page_tokens_by_source: dict[str, str] | None = None,
    ) -> AcquisitionResultV1:
        remaining = self._retrieval_budget.as_remaining()
        if not plans:
            return _acquisition_result(
                status=ApiAcquisitionResult.COMPLETE,
                source_summaries=[],
                missing_slots=[],
                remaining_budget=remaining,
            )
        if len(plans) > self._retrieval_budget.max_sources:
            return _acquisition_result(
                status=ApiAcquisitionResult.BUDGET_EXHAUSTED,
                source_summaries=[],
                missing_slots=["source budget exhausted"],
                remaining_budget=remaining,
            )

        source_summaries: list[dict[str, object]] = []
        missing_slots: list[str] = []
        for plan in sorted(plans, key=lambda item: item["priority"]):
            if _plan_exceeds_budget(plan, self._retrieval_budget):
                source_summaries.append(
                    _failed_source_summary(
                        plan=plan,
                        error_code="BUDGET_EXHAUSTED",
                        status=ApiAcquisitionResult.BUDGET_EXHAUSTED,
                    )
                )
                missing_slots.append(f"{plan['source']}:BUDGET_EXHAUSTED")
                continue
            try:
                summary = self._acquire_one(
                    plan=plan,
                    request=request,
                    remaining=remaining,
                    request_intent=request_intent,
                    tool_route_plan=tool_route_plan,
                    read_result_cache=read_result_cache,
                    read_handle_factory=read_handle_factory,
                    page_token=(page_tokens_by_source or {}).get(plan["source"]),
                )
            except GoogleWorkspaceGatewayError as error:
                mapped = _map_gateway_error(error)
                print(
                    f"[acquisition GATEWAY_ERROR] run_id={request.run_id} "
                    f"source={plan['source']} code={error.code.value} mapped={mapped} "
                    f"error={error}",
                    flush=True,
                )
                source_summaries.append(
                    _failed_source_summary(
                        plan=plan,
                        error_code=error.code.value,
                        status=mapped,
                    )
                )
                missing_slots.append(f"{plan['source']}:{error.code.value}")
                continue
            except Exception as error:
                print(
                    f"[acquisition RUNTIME_FAILURE] run_id={request.run_id} "
                    f"source={plan['source']} error_type={type(error).__name__} "
                    f"error={error}",
                    flush=True,
                )
                source_summaries.append(
                    _failed_source_summary(
                        plan=plan,
                        error_code="RUNTIME_FAILURE",
                        status=ApiAcquisitionResult.FAILED,
                    )
                )
                missing_slots.append(f"{plan['source']}:{type(error).__name__}")
                continue
            source_summaries.append(summary)
            # A COMPLETE summary can still carry a deterministic
            # post-processing failure (e.g. an EVENTS_AND_FREEBUSY plan
            # whose typed temporal_query could not be resolved) -- this
            # surfaces it as a missing_slots signal for downstream Context
            # sufficiency assessment, without downgrading the Read's own
            # operational status.
            summary_error_code = summary.get("error_code")
            if isinstance(summary_error_code, str):
                missing_slots.append(f"{plan['source']}:{summary_error_code}")

        return _acquisition_result(
            status=_choose_acquisition_status(source_summaries=source_summaries, plans=plans),
            source_summaries=source_summaries,
            missing_slots=missing_slots,
            remaining_budget=remaining,
        )

    def build_planning_state_update(self, output: SourcePlanningOutputV1) -> GraphStateUpdateV1:
        result = ApiPlanningResult(output["result"])
        phase = (
            WorkflowPhase.API_ACQUISITION
            if result is ApiPlanningResult.PLAN_READY
            else WorkflowPhase.SOURCE_PLANNING
        )
        return {
            "source_fetch_plans": output["source_fetch_plans"],
            "workflow_phase": phase.value,
            "trace_context": {
                "api_planning_result": output["result"],
                "validator_codes": list(output["validator_codes"]),
            },
        }

    def build_acquisition_state_update(self, result: AcquisitionResultV1) -> GraphStateUpdateV1:
        return {
            "acquisition_result": result,
            "workflow_phase": WorkflowPhase.API_ACQUISITION.value,
            "trace_context": {
                "api_acquisition_result": result["status"],
                "missing_slots": list(result["missing_slots"]),
            },
        }

    def materialize_retrieval_read(
        self,
        *,
        plan: SourceFetchPlanV1,
        request: WorkflowStartRequest,
        tool_route_plan: ToolRoutePlanV2,
        read_result: NormalizedConnectorRead,
        read_result_cache: RunScopedReadResultCache,
        read_handle_factory: Callable[[], str],
    ) -> MaterializedRetrievalRead:
        """Materialize an already-executed read without workflow decisions."""
        snapshots = read_result.snapshots
        summary: dict[str, object] = {
            "schema_version": 1,
            "source": plan["source"],
            "status": "COMPLETE",
            "required": plan["required"],
            "reason_codes": list(plan["reason_codes"]),
            "resource_count": len(snapshots),
            "resource_handles": [_resource_handle(item) for item in snapshots],
            "resources": [_snapshot_summary(item) for item in snapshots],
        }
        if read_result.error_code is not None:
            summary["error_code"] = read_result.error_code
        route_id = _route_id_for_source(tool_route_plan, source=plan["source"])
        handle = read_handle_factory()
        read_result_cache.put(
            handle=handle,
            entry=ReadResultCacheEntry(
                run_id=request.run_id,
                route_id=route_id,
                query_hash=_query_hash(plan),
                next_page_token=read_result.next_page_token,
                exhausted=read_result.next_page_token is None,
                result_handles=tuple(cast(list[str], summary["resource_handles"])),
                result_count=len(snapshots),
            ),
        )
        for snapshot in snapshots:
            detail_tool_id = _detail_tool_id(snapshot.resource_type.value)
            if detail_tool_id is None:
                continue
            read_result_cache.register_detail_target(
                entry=DetailTargetCacheEntry(
                    run_id=request.run_id,
                    route_id=route_id,
                    resource_handle=_resource_handle(snapshot),
                    source=plan["source"],
                    resource_type=snapshot.resource_type.value,
                    resource_id=snapshot.resource_id,
                    parent_resource_id=snapshot.parent_id,
                    detail_tool_id=detail_tool_id,
                )
            )
        return MaterializedRetrievalRead(
            source_summary=summary,
            read_result_handle=handle,
            segment_handles=tuple(cast(list[str], summary["resource_handles"])),
        )

    def _acquire_one(
        self,
        *,
        plan: SourceFetchPlanV1,
        request: WorkflowStartRequest,
        remaining: dict[str, int],
        request_intent: RequestIntentV2 | None,
        tool_route_plan: ToolRoutePlanV2 | None,
        read_result_cache: RunScopedReadResultCache | None,
        read_handle_factory: Callable[[], str] | None,
        page_token: str | None,
    ) -> dict[str, object]:
        del request_intent  # Calendar FreeBusy gating now uses only the
        # typed calendar_read_mode/temporal_query plan fields (see
        # _maybe_query_freebusy); request_intent stays accepted here only
        # so acquire()'s public signature/call sites are unaffected.
        remaining["sources"] -= 1
        now_ms = self._now_ms()
        timezone = self._timezone_provider()
        read_result = self._connector_reader.read(
            PlannedConnectorRead(
                plan=plan,
                selected_resources=request.selected_resources,
                prefer_selected_resources=request.entry_mode == "RESOURCE_SELECTED",
                remaining_budget=remaining,
                now_ms=now_ms,
                timezone=timezone,
                allowed_read_tool_ids=(
                    None
                    if tool_route_plan is None
                    else allowed_read_tool_ids(tool_route_plan, source=plan["source"])
                ),
                page_token=page_token,
            )
        )
        snapshots = read_result.snapshots
        error_code = read_result.error_code
        summary: dict[str, object] = {
            "schema_version": 1,
            "source": plan["source"],
            "status": "COMPLETE",
            "required": plan["required"],
            "reason_codes": list(plan["reason_codes"]),
            "resource_count": len(snapshots),
            "resource_handles": [_resource_handle(item) for item in snapshots],
            "resources": [_snapshot_summary(item) for item in snapshots],
        }
        if error_code is not None:
            summary["error_code"] = error_code
        if (
            read_result_cache is not None
            and read_handle_factory is not None
            and tool_route_plan is not None
        ):
            route_id = _route_id_for_source(tool_route_plan, source=plan["source"])
            read_result_cache.put(
                handle=read_handle_factory(),
                entry=ReadResultCacheEntry(
                    run_id=request.run_id,
                    route_id=route_id,
                    query_hash=_query_hash(plan),
                    next_page_token=read_result.next_page_token,
                    exhausted=read_result.next_page_token is None,
                    result_handles=tuple(cast(list[str], summary["resource_handles"])),
                    result_count=len(snapshots),
                ),
            )
            for snapshot in snapshots:
                detail_tool_id = _detail_tool_id(snapshot.resource_type.value)
                if detail_tool_id is None:
                    continue
                read_result_cache.register_detail_target(
                    entry=DetailTargetCacheEntry(
                        run_id=request.run_id,
                        route_id=route_id,
                        resource_handle=_resource_handle(snapshot),
                        source=plan["source"],
                        resource_type=snapshot.resource_type.value,
                        resource_id=snapshot.resource_id,
                        parent_resource_id=snapshot.parent_id,
                        detail_tool_id=detail_tool_id,
                    )
                )
        return summary


def validate_acquisition_result_v1(value: object) -> AcquisitionResultV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {
            "schema_version",
            "status",
            "resource_handles",
            "source_summaries",
            "missing_slots",
            "remaining_budget",
        },
    )
    if _require_int(root, "schema_version", "$") != ACQUISITION_RESULT_SCHEMA_VERSION:
        raise SourcePlanningValidationError("$.schema_version must be 1")
    status = _require_string(root, "status", "$")
    if status not in {item.value for item in ApiAcquisitionResult}:
        raise SourcePlanningValidationError("$.status is invalid")
    resource_handles = _require_string_list(root["resource_handles"], "$.resource_handles")
    source_summaries = _validate_source_summaries(root["source_summaries"])
    missing_slots = _require_string_list(root["missing_slots"], "$.missing_slots")
    remaining_budget = _validate_remaining_budget(root["remaining_budget"])
    return {
        "schema_version": 1,
        "status": cast(
            Literal[
                "COMPLETE",
                "PARTIAL",
                "AUTH_REQUIRED",
                "RATE_LIMITED",
                "BUDGET_EXHAUSTED",
                "FAILED",
            ],
            status,
        ),
        "resource_handles": resource_handles,
        "source_summaries": source_summaries,
        "missing_slots": missing_slots,
        "remaining_budget": remaining_budget,
    }


def validate_source_fetch_plans_v1(value: object) -> list[SourceFetchPlanV1]:
    if not isinstance(value, list):
        raise SourcePlanningValidationError("SourceFetchPlan output must be a list")
    plans = [_validate_source_fetch_plan(item, index) for index, item in enumerate(value)]
    return sorted(plans, key=lambda item: item["priority"])


def validate_source_fetch_plans_for_route(
    value: object,
    *,
    tool_route_plan: ToolRoutePlanV2,
) -> list[SourceFetchPlanV1]:
    """Reject source plans that escape the frozen input route."""

    plans = validate_source_fetch_plans_v1(value)
    allowed_sources = allowed_input_sources(tool_route_plan)
    unexpected = sorted({plan["source"] for plan in plans} - allowed_sources)
    if unexpected:
        raise SourcePlanningValidationError(
            f"source plan is outside frozen input route: {','.join(unexpected)}"
        )
    return plans


def load_acquisition_plan_sources_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "retrieval.plan_query",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def build_source_planning_clarification_question(
    *,
    output: SourcePlanningOutputV1,
    request_intent: RequestIntentV2,
) -> ClarificationQuestionV1:
    clarification = _require_mapping(output["clarification"], "$.clarification")
    return build_clarification_question_v1(
        origin_target="acquisition.plan_sources",
        question=_require_string(clarification, "question", "$.clarification"),
        reason_code=_require_string(clarification, "reason_code", "$.clarification"),
        known_context_summary=request_intent["goal"],
        affected_field_paths=_optional_string_list(clarification.get("affected_field_paths")),
        options=_optional_option_list(clarification.get("options")),
    )


def _interpret_source_plans(
    *,
    plans: list[SourceFetchPlanV1],
    llm_result: StructuredLLMResult,
) -> SourcePlanningOutputV1:
    if not plans:
        return _planning_output(
            result=ApiPlanningResult.NO_FETCH_NEEDED,
            plans=[],
            clarification=None,
            failure=None,
            validator_codes=["NO_FETCH_NEEDED"],
            llm_result=llm_result,
        )
    confirmation_plans = [
        plan
        for plan in plans
        if any(reason in _CONFIRMATION_REASON_CODES for reason in plan["reason_codes"])
    ]
    if confirmation_plans:
        first = confirmation_plans[0]
        return _planning_output(
            result=ApiPlanningResult.NEEDS_CONFIRMATION,
            plans=plans,
            clarification={
                "schema_version": 1,
                "question": "조회 범위를 더 구체적으로 알려주세요.",
                "affected_sources": [plan["source"] for plan in confirmation_plans],
                "reason_code": first["reason_codes"][0],
            },
            failure=None,
            validator_codes=["SOURCE_PLAN_NEEDS_CONFIRMATION"],
            llm_result=llm_result,
        )
    if not any(plan["required"] for plan in plans):
        return _planning_output(
            result=ApiPlanningResult.BLOCKED,
            plans=plans,
            clarification=None,
            failure={
                "schema_version": 1,
                "reason_code": "ACQ_REQUIRED_SOURCE_MISSING",
                "diagnostic": "source plans contain no required source",
            },
            validator_codes=["ACQ_REQUIRED_SOURCE_MISSING"],
            llm_result=llm_result,
        )
    return _planning_output(
        result=ApiPlanningResult.PLAN_READY,
        plans=plans,
        clarification=None,
        failure=None,
        validator_codes=["SOURCE_PLAN_READY"],
        llm_result=llm_result,
    )


def _planning_output(
    *,
    result: ApiPlanningResult,
    plans: list[SourceFetchPlanV1],
    clarification: dict[str, object] | None,
    failure: dict[str, object] | None,
    validator_codes: list[str],
    llm_result: StructuredLLMResult,
) -> SourcePlanningOutputV1:
    return {
        "schema_version": 1,
        "result": result.value,
        "source_fetch_plans": plans,
        "clarification": clarification,
        "failure": failure,
        "validator_codes": validator_codes,
        "llm_provider_result": _provider_summary(llm_result),
    }


def _plan_query_prompt_input(
    *,
    request_intent: RequestIntentV2,
    request: WorkflowStartRequest,
    retrieval_budget: RetrievalBudget,
    tool_route_plan: ToolRoutePlanV2 | None,
) -> dict[str, object]:
    """Typed retrieval.plan_query Prompt Runtime Input Projection.

    Field set is pinned to prompt-runtime-input-contract-v1.json's
    retrieval.plan_query entry and retrieval-plan-query-input-v1.schema.json
    (additionalProperties: false). entry_mode/selected_resource_ids/
    selected_resources are not sent here: Tool Route has already frozen
    input_routes from that same signal (Q3 boundary), and Retrieval must
    consume the frozen route rather than re-deriving or re-selecting it
    from raw request fields.
    """

    frozen_input_routes = (
        () if tool_route_plan is None else tool_route_plan["input_plan"]["input_routes"]
    )
    del request
    return {
        "request_intent": request_intent,
        "input_routes": [
            {**route, "resource_type": coarse_resource_category(route["resource_type"])}
            for route in frozen_input_routes
        ],
        "retrieval_budget": retrieval_budget.as_remaining(),
    }


def _validate_source_fetch_plan(value: object, index: int) -> SourceFetchPlanV1:
    path = f"$[{index}]"
    plan = _require_mapping(value, path)
    _require_exact_keys(
        plan,
        path,
        {
            "schema_version",
            "source",
            "priority",
            "reason_codes",
            "constraints",
            "page_size",
            "max_pages",
            "max_candidates",
            "detail_limit",
            "required",
            "calendar_read_mode",
            "temporal_query",
        },
    )
    schema_version = _require_int(plan, "schema_version", path)
    if schema_version != SOURCE_FETCH_PLAN_SCHEMA_VERSION:
        raise SourcePlanningValidationError(
            f"{path}.schema_version must be {SOURCE_FETCH_PLAN_SCHEMA_VERSION}"
        )
    source = _require_string(plan, "source", path)
    if source not in _SOURCE_VALUES:
        raise SourcePlanningValidationError(f"{path}.source is invalid")
    required = plan["required"]
    if not isinstance(required, bool):
        raise SourcePlanningValidationError(f"{path}.required must be boolean")
    priority = _require_positive_int(plan, "priority", path, minimum=1)
    page_size = _require_positive_int(plan, "page_size", path)
    max_pages = _require_positive_int(plan, "max_pages", path, minimum=0)
    max_candidates = _require_positive_int(plan, "max_candidates", path, minimum=0)
    detail_limit = _require_positive_int(plan, "detail_limit", path, minimum=0)
    constraints = _require_mapping(plan["constraints"], f"{path}.constraints")
    calendar_read_mode, temporal_query = _validate_calendar_typed_fields(plan, path, source=source)
    return {
        "schema_version": 2,
        "source": cast(SourceName, source),
        "priority": priority,
        "reason_codes": _require_string_list(plan["reason_codes"], f"{path}.reason_codes"),
        "constraints": constraints,
        "page_size": page_size,
        "max_pages": max_pages,
        "max_candidates": max_candidates,
        "detail_limit": detail_limit,
        "required": required,
        "calendar_read_mode": calendar_read_mode,
        "temporal_query": temporal_query,
    }


def _validate_calendar_typed_fields(
    plan: dict[str, object],
    path: str,
    *,
    source: str,
) -> tuple[CalendarReadMode | None, TemporalQueryV1 | None]:
    """Enforce docs/05 section 8 (Calendar Typed Query 계약)'s CALENDAR-only typed contract.

    calendar_read_mode/temporal_query are schema-required on every plan
    entry (so the shape is uniform), but semantically only meaningful for
    CALENDAR: non-CALENDAR sources must leave both null, CALENDAR must set
    a read mode, and EVENTS_AND_FREEBUSY must carry a temporal_query
    (deterministic code has nothing to compute a TimeRange from otherwise).
    """

    read_mode = _nullable_string(plan["calendar_read_mode"], f"{path}.calendar_read_mode")
    if read_mode is not None and read_mode not in _CALENDAR_READ_MODE_VALUES:
        raise SourcePlanningValidationError(f"{path}.calendar_read_mode is invalid")
    temporal_query_raw = plan["temporal_query"]
    if source != "CALENDAR":
        if read_mode is not None:
            raise SourcePlanningValidationError(
                f"{path}.calendar_read_mode must be null for source={source}"
            )
        if temporal_query_raw is not None:
            raise SourcePlanningValidationError(
                f"{path}.temporal_query must be null for source={source}"
            )
        return None, None
    if read_mode is None:
        raise SourcePlanningValidationError(f"{path}.calendar_read_mode is required for CALENDAR")
    temporal_query = (
        None
        if temporal_query_raw is None
        else _validate_temporal_query(temporal_query_raw, f"{path}.temporal_query")
    )
    if read_mode == "EVENTS_AND_FREEBUSY" and temporal_query is None:
        raise SourcePlanningValidationError(
            f"{path}.temporal_query is required when calendar_read_mode is EVENTS_AND_FREEBUSY"
        )
    return cast(CalendarReadMode, read_mode), temporal_query


def _validate_temporal_query(value: object, path: str) -> TemporalQueryV1:
    query = _require_mapping(value, path)
    _require_exact_keys(
        query,
        path,
        {
            "schema_version",
            "relation",
            "relative_unit",
            "relative_offset",
            "weekday",
            "daypart",
            "absolute_start",
            "absolute_end",
        },
    )
    schema_version = _require_int(query, "schema_version", path)
    if schema_version != TEMPORAL_QUERY_SCHEMA_VERSION:
        raise SourcePlanningValidationError(f"{path}.schema_version must be 1")
    relation = _require_string(query, "relation", path)
    if relation not in _TEMPORAL_RELATION_VALUES:
        raise SourcePlanningValidationError(f"{path}.relation is invalid")
    relative_unit = _nullable_enum(
        query["relative_unit"], f"{path}.relative_unit", _RELATIVE_UNIT_VALUES
    )
    relative_offset = query["relative_offset"]
    if relative_offset is not None and (
        not isinstance(relative_offset, int) or isinstance(relative_offset, bool)
    ):
        raise SourcePlanningValidationError(f"{path}.relative_offset must be integer or null")
    weekday = _nullable_enum(query["weekday"], f"{path}.weekday", _WEEKDAY_VALUES)
    daypart = _nullable_enum(query["daypart"], f"{path}.daypart", _DAYPART_VALUES)
    absolute_start = _nullable_string(query["absolute_start"], f"{path}.absolute_start")
    absolute_end = _nullable_string(query["absolute_end"], f"{path}.absolute_end")
    if relation == "RELATIVE" and (relative_unit is None or relative_offset is None):
        raise SourcePlanningValidationError(
            f"{path}: relation=RELATIVE requires relative_unit and relative_offset"
        )
    if relation == "ABSOLUTE" and (absolute_start is None or absolute_end is None):
        raise SourcePlanningValidationError(
            f"{path}: relation=ABSOLUTE requires absolute_start and absolute_end"
        )
    return {
        "schema_version": 1,
        "relation": cast(TemporalRelation, relation),
        "relative_unit": cast("RelativeUnit | None", relative_unit),
        "relative_offset": relative_offset,
        "weekday": cast("Weekday | None", weekday),
        "daypart": cast("Daypart | None", daypart),
        "absolute_start": absolute_start,
        "absolute_end": absolute_end,
    }


def _nullable_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourcePlanningValidationError(f"{path} must be string or null")
    return value


def _nullable_enum(value: object, path: str, allowed: set[str]) -> str | None:
    text = _nullable_string(value, path)
    if text is not None and text not in allowed:
        raise SourcePlanningValidationError(f"{path} is invalid")
    return text


def _plan_exceeds_budget(plan: SourceFetchPlanV1, budget: RetrievalBudget) -> bool:
    return (
        plan["max_pages"] > budget.max_pages_per_source
        or plan["page_size"] > budget.max_page_size
        or plan["max_candidates"] > budget.max_candidates_per_source
        or plan["detail_limit"] > budget.max_details_per_source
    )


def _resolve_temporal_query(
    *,
    temporal_query: TemporalQueryV1,
    now_ms: int,
    timezone: str,
) -> TimeRange | None:
    """Compatibility wrapper for existing private-function test imports."""
    return resolve_temporal_query(
        temporal_query=temporal_query,
        now_ms=now_ms,
        timezone=timezone,
    )


def _acquisition_result(
    *,
    status: ApiAcquisitionResult,
    source_summaries: list[dict[str, object]],
    missing_slots: list[str],
    remaining_budget: dict[str, int],
) -> AcquisitionResultV1:
    handles: list[str] = []
    for summary in source_summaries:
        value = summary.get("resource_handles")
        if isinstance(value, list):
            handles.extend(str(item) for item in value)
    return {
        "schema_version": 1,
        "status": status.value,
        "resource_handles": handles,
        "source_summaries": source_summaries,
        "missing_slots": missing_slots,
        "remaining_budget": remaining_budget,
    }


def retrieval_query_hash(plan: SourceFetchPlanV1) -> str:
    """Stable identity for a frozen source plan; raw provider query is excluded."""
    return sha256(
        dumps(
            {
                "source": plan["source"],
                "constraints": plan["constraints"],
                "page_size": plan["page_size"],
                "calendar_read_mode": plan["calendar_read_mode"],
                "temporal_query": plan["temporal_query"],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _query_hash(plan: SourceFetchPlanV1) -> str:
    return retrieval_query_hash(plan)


def _route_id_for_source(tool_route_plan: ToolRoutePlanV2 | None, *, source: str) -> str:
    if tool_route_plan is None:
        raise ValueError("read-result cache requires a frozen tool route")
    matching = sorted(
        route["route_id"]
        for route in tool_route_plan["input_plan"]["input_routes"]
        if coarse_resource_category(route["resource_type"]) == _source_category(source)
    )
    if not matching:
        raise ValueError(f"source is outside frozen input route: {source}")
    return matching[0]


def _source_category(source: str) -> str:
    return {"GMAIL": "EMAIL", "TASKS": "TASK", "CALENDAR": "CALENDAR"}[source]


def _detail_tool_id(resource_type: str) -> str | None:
    return {
        "GMAIL_THREAD": "gmail_get_thread",
        "GMAIL_MESSAGE": "gmail_get_message",
        "TASK": "tasks_get_task",
        "CALENDAR_EVENT": "calendar_get_event",
    }.get(resource_type)


def _failed_source_summary(
    *,
    plan: SourceFetchPlanV1,
    error_code: str,
    status: ApiAcquisitionResult,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": plan["source"],
        "status": status.value,
        "required": plan["required"],
        "error_code": error_code,
        "resource_count": 0,
        "resource_handles": [],
        "resources": [],
    }


def _choose_acquisition_status(
    *,
    source_summaries: list[dict[str, object]],
    plans: list[SourceFetchPlanV1],
) -> ApiAcquisitionResult:
    if _all_plans_complete(source_summaries=source_summaries, plans=plans):
        return ApiAcquisitionResult.COMPLETE
    required_auth = any(
        summary.get("required") is True
        and summary.get("status") == ApiAcquisitionResult.AUTH_REQUIRED.value
        for summary in source_summaries
    )
    if required_auth:
        return ApiAcquisitionResult.AUTH_REQUIRED
    has_usable_data = any(
        summary.get("status") == ApiAcquisitionResult.COMPLETE.value
        and isinstance(resource_count := summary.get("resource_count", 0), int)
        and resource_count > 0
        for summary in source_summaries
    )
    if has_usable_data:
        return ApiAcquisitionResult.PARTIAL
    statuses = {str(summary.get("status")) for summary in source_summaries}
    if ApiAcquisitionResult.AUTH_REQUIRED.value in statuses:
        return ApiAcquisitionResult.AUTH_REQUIRED
    if ApiAcquisitionResult.RATE_LIMITED.value in statuses:
        return ApiAcquisitionResult.RATE_LIMITED
    if ApiAcquisitionResult.BUDGET_EXHAUSTED.value in statuses:
        return ApiAcquisitionResult.BUDGET_EXHAUSTED
    return ApiAcquisitionResult.FAILED


def _all_plans_complete(
    *,
    source_summaries: list[dict[str, object]],
    plans: list[SourceFetchPlanV1],
) -> bool:
    return len(source_summaries) == len(plans) and all(
        summary.get("status") == ApiAcquisitionResult.COMPLETE.value for summary in source_summaries
    )


def _map_gateway_error(error: GoogleWorkspaceGatewayError) -> ApiAcquisitionResult:
    if error.code in _AUTH_ERRORS:
        return ApiAcquisitionResult.AUTH_REQUIRED
    if error.code is GoogleWorkspaceErrorCode.RATE_LIMITED:
        return ApiAcquisitionResult.RATE_LIMITED
    return ApiAcquisitionResult.FAILED


def _snapshot_summary(snapshot: ResourceSnapshot) -> dict[str, object]:
    return {
        "resource_handle": _resource_handle(snapshot),
        "resource_type": snapshot.resource_type.value,
        "resource_id": snapshot.resource_id,
        "parent_id": snapshot.parent_id,
        "version": snapshot.version,
        "related_resource_ids": list(snapshot.related_resource_ids),
        "payload": dict(snapshot.payload),
    }


def _resource_handle(snapshot: ResourceSnapshot) -> str:
    return f"{snapshot.resource_type.value}:{snapshot.resource_id}"


def _validate_source_summaries(value: object) -> list[dict[str, object]]:
    summaries = _require_list(value, "$.source_summaries")
    validated: list[dict[str, object]] = []
    for index, item in enumerate(summaries):
        summary = _require_mapping(item, f"$.source_summaries[{index}]")
        required = {
            "schema_version",
            "source",
            "status",
            "required",
            "resource_count",
            "resource_handles",
            "resources",
        }
        optional = {"reason_codes", "error_code"}
        actual = set(summary)
        missing = required - actual
        extra = actual - required - optional
        if missing:
            raise SourcePlanningValidationError(
                f"$.source_summaries[{index}] missing required fields: {sorted(missing)}"
            )
        if extra:
            raise SourcePlanningValidationError(
                f"$.source_summaries[{index}] has unsupported fields: {sorted(extra)}"
            )
        _require_int(summary, "schema_version", f"$.source_summaries[{index}]")
        source = _require_string(summary, "source", f"$.source_summaries[{index}]")
        if source not in _SOURCE_VALUES:
            raise SourcePlanningValidationError(f"$.source_summaries[{index}].source is invalid")
        status = _require_string(summary, "status", f"$.source_summaries[{index}]")
        if status not in {item.value for item in ApiAcquisitionResult}:
            raise SourcePlanningValidationError(f"$.source_summaries[{index}].status is invalid")
        required_flag = summary["required"]
        if not isinstance(required_flag, bool):
            raise SourcePlanningValidationError(
                f"$.source_summaries[{index}].required must be boolean"
            )
        _require_positive_int(summary, "resource_count", f"$.source_summaries[{index}]", minimum=0)
        _require_string_list(
            summary["resource_handles"], f"$.source_summaries[{index}].resource_handles"
        )
        resources = _require_list(summary["resources"], f"$.source_summaries[{index}].resources")
        for resource_index, resource in enumerate(resources):
            _require_mapping(
                resource,
                f"$.source_summaries[{index}].resources[{resource_index}]",
            )
        if "reason_codes" in summary:
            _require_string_list(
                summary["reason_codes"],
                f"$.source_summaries[{index}].reason_codes",
            )
        if "error_code" in summary and not isinstance(summary["error_code"], str):
            raise SourcePlanningValidationError(
                f"$.source_summaries[{index}].error_code must be string"
            )
        validated.append(summary)
    return validated


def _validate_remaining_budget(value: object) -> dict[str, int]:
    budget = _require_mapping(value, "$.remaining_budget")
    _require_exact_keys(budget, "$.remaining_budget", {"sources", "pages", "candidates", "details"})
    return {
        "sources": _require_positive_int(budget, "sources", "$.remaining_budget", minimum=0),
        "pages": _require_positive_int(budget, "pages", "$.remaining_budget", minimum=0),
        "candidates": _require_positive_int(
            budget,
            "candidates",
            "$.remaining_budget",
            minimum=0,
        ),
        "details": _require_positive_int(budget, "details", "$.remaining_budget", minimum=0),
    }


# Shared with the other agent workflow modules; see _schema_support module docstring.
_require_mapping = partial(_schema.require_mapping, error_cls=SourcePlanningValidationError)
_require_exact_keys = partial(_schema.require_exact_keys, error_cls=SourcePlanningValidationError)
_require_int = partial(_schema.require_int, error_cls=SourcePlanningValidationError)
_require_string = partial(_schema.require_string, error_cls=SourcePlanningValidationError)
_require_list = partial(_schema.require_list, error_cls=SourcePlanningValidationError)
_require_string_list = partial(_schema.require_string_list, error_cls=SourcePlanningValidationError)
_optional_string_list = partial(
    _schema.optional_string_list, error_cls=SourcePlanningValidationError
)
_optional_option_list = partial(
    _schema.optional_option_list, error_cls=SourcePlanningValidationError
)
_provider_summary = _schema.provider_summary


def _require_positive_int(
    value: dict[str, object],
    field: str,
    path: str,
    *,
    minimum: int = 1,
) -> int:
    item = _require_int(value, field, path)
    if item < minimum:
        raise SourcePlanningValidationError(f"{path}.{field} must be >= {minimum}")
    return item
