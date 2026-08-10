"""API planning and Google Workspace acquisition workflow nodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.contracts import (
    AdditionalAcquisitionRequestV1,
    ApiAcquisitionResult,
    ApiPlanningResult,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.application.workflows.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.workflows.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.workflows.request_understanding import (
    ClarificationQuestionV1,
    RequestIntentV1,
    build_clarification_question_v1,
)
from google_work_agent.ports import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    OutputSchemaDefinition,
    PromptReference,
    ResourceSnapshot,
    SelectedResourceRef,
    StructuredLLMResult,
    WorkflowStartRequest,
)

JsonObject = dict[str, object]
SourceName = Literal["GMAIL", "TASKS", "CALENDAR"]


class SourceFetchPlanV1(TypedDict):
    schema_version: Required[Literal[1]]
    source: SourceName
    priority: int
    reason_codes: list[str]
    constraints: dict[str, object]
    page_size: int
    max_pages: int
    max_candidates: int
    detail_limit: int
    required: bool


class SourcePlanningOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    result: Literal["PLAN_READY", "NO_FETCH_NEEDED", "NEEDS_CONFIRMATION", "BLOCKED"]
    source_fetch_plans: list[SourceFetchPlanV1]
    clarification: dict[str, object] | None
    failure: dict[str, object] | None
    validator_codes: list[str]
    llm_provider_result: dict[str, object]


class AcquisitionResultV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: Literal[
        "COMPLETE",
        "PARTIAL",
        "AUTH_REQUIRED",
        "RATE_LIMITED",
        "BUDGET_EXHAUSTED",
        "FAILED",
    ]
    resource_handles: list[str]
    source_summaries: list[dict[str, object]]
    missing_slots: list[str]
    remaining_budget: dict[str, int]


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


DEFAULT_RETRIEVAL_BUDGET = RetrievalBudget()
SOURCE_FETCH_PLAN_SCHEMA_VERSION = 1
ACQUISITION_RESULT_SCHEMA_VERSION = 1
SOURCE_FETCH_PLAN_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="source-fetch-plan-v1-list",
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
            ],
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "integer", "enum": [1]},
                "source": {"type": "string", "enum": ["GMAIL", "TASKS", "CALENDAR"]},
                "priority": {"type": "integer", "minimum": 1},
                "reason_codes": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "object"},
                "page_size": {"type": "integer", "minimum": 1},
                "max_pages": {"type": "integer", "minimum": 0},
                "max_candidates": {"type": "integer", "minimum": 0},
                "detail_limit": {"type": "integer", "minimum": 0},
                "required": {"type": "boolean"},
            },
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


class SourcePlanningValidationError(ValueError):
    """Raised when a source planning structured output is invalid."""


class ApiDiscoveryAcquisitionAgent:
    """Plan Google source reads and execute them through the existing gateway."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        gateway: GoogleWorkspaceGateway,
        prompt_ref: PromptReference | None = None,
        retrieval_budget: RetrievalBudget = DEFAULT_RETRIEVAL_BUDGET,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._gateway = gateway
        self._prompt_ref = prompt_ref or load_acquisition_plan_sources_prompt_reference(
            manifest_path
        )
        self._retrieval_budget = retrieval_budget

    @property
    def prompt_ref(self) -> PromptReference:
        return self._prompt_ref

    def plan_sources(
        self,
        *,
        request_intent: RequestIntentV1,
        request: WorkflowStartRequest,
        additional_acquisition_request: AdditionalAcquisitionRequestV1 | None = None,
    ) -> SourcePlanningOutputV1:
        llm_result = self.invoke_plan_sources_llm(
            request_intent=request_intent,
            request=request,
            additional_acquisition_request=additional_acquisition_request,
        )
        return self.build_planning_output_from_llm_result(llm_result)

    def invoke_plan_sources_llm(
        self,
        *,
        request_intent: RequestIntentV1,
        request: WorkflowStartRequest,
        additional_acquisition_request: AdditionalAcquisitionRequestV1 | None = None,
    ) -> StructuredLLMResult:
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=_planning_prompt_input(
                request_intent=request_intent,
                request=request,
                retrieval_budget=self._retrieval_budget,
                additional_acquisition_request=additional_acquisition_request,
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
        )

    def build_planning_output_from_llm_result(
        self,
        llm_result: StructuredLLMResult,
    ) -> SourcePlanningOutputV1:
        plans = validate_source_fetch_plans_v1(llm_result.structured_output)
        return _interpret_source_plans(plans=plans, llm_result=llm_result)

    def acquire(
        self,
        *,
        plans: list[SourceFetchPlanV1],
        request: WorkflowStartRequest,
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
                summary = self._acquire_one(plan=plan, request=request, remaining=remaining)
            except GoogleWorkspaceGatewayError as error:
                mapped = _map_gateway_error(error)
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

    def _acquire_one(
        self,
        *,
        plan: SourceFetchPlanV1,
        request: WorkflowStartRequest,
        remaining: dict[str, int],
    ) -> dict[str, object]:
        remaining["sources"] -= 1
        if request.entry_mode == "RESOURCE_SELECTED":
            selected = _selected_snapshots(
                gateway=self._gateway,
                plan=plan,
                selected_resources=request.selected_resources,
            )
            snapshots = selected or _acquire_planned_source(
                gateway=self._gateway,
                plan=plan,
                remaining=remaining,
            )
        elif plan["source"] == "GMAIL":
            snapshots = _acquire_gmail(gateway=self._gateway, plan=plan, remaining=remaining)
        elif plan["source"] == "TASKS":
            snapshots = _acquire_tasks(gateway=self._gateway, plan=plan, remaining=remaining)
        else:
            snapshots = _acquire_calendar(gateway=self._gateway, plan=plan, remaining=remaining)
        return {
            "schema_version": 1,
            "source": plan["source"],
            "status": "COMPLETE",
            "required": plan["required"],
            "reason_codes": list(plan["reason_codes"]),
            "resource_count": len(snapshots),
            "resource_handles": [_resource_handle(item) for item in snapshots],
            "resources": [_snapshot_summary(item) for item in snapshots],
        }


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


def load_acquisition_plan_sources_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "acquisition.plan_sources",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def build_source_planning_clarification_question(
    *,
    output: SourcePlanningOutputV1,
    request_intent: RequestIntentV1,
) -> ClarificationQuestionV1:
    clarification = _require_mapping(output["clarification"], "$.clarification")
    return build_clarification_question_v1(
        origin_target="acquisition.plan_sources",
        question=_require_string(clarification, "question", "$.clarification"),
        reason_code=_require_string(clarification, "reason_code", "$.clarification"),
        known_context_summary=request_intent["goal"]["user_visible_objective"]
        or request_intent["goal"]["summary"],
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


def _planning_prompt_input(
    *,
    request_intent: RequestIntentV1,
    request: WorkflowStartRequest,
    retrieval_budget: RetrievalBudget,
    additional_acquisition_request: AdditionalAcquisitionRequestV1 | None,
) -> dict[str, object]:
    return {
        "planning_mode": "ADDITIONAL_DATA" if additional_acquisition_request else "INITIAL",
        "request_intent": request_intent,
        "additional_acquisition_request": additional_acquisition_request,
        "entry_mode": request.entry_mode,
        "selected_resource_ids": list(request.selected_resource_ids),
        "selected_resources": [asdict(resource) for resource in request.selected_resources],
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
        },
    )
    schema_version = _require_int(plan, "schema_version", path)
    if schema_version != SOURCE_FETCH_PLAN_SCHEMA_VERSION:
        raise SourcePlanningValidationError(f"{path}.schema_version must be 1")
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
    return {
        "schema_version": 1,
        "source": cast(SourceName, source),
        "priority": priority,
        "reason_codes": _require_string_list(plan["reason_codes"], f"{path}.reason_codes"),
        "constraints": constraints,
        "page_size": page_size,
        "max_pages": max_pages,
        "max_candidates": max_candidates,
        "detail_limit": detail_limit,
        "required": required,
    }


def _plan_exceeds_budget(plan: SourceFetchPlanV1, budget: RetrievalBudget) -> bool:
    return (
        plan["max_pages"] > budget.max_pages_per_source
        or plan["page_size"] > budget.max_page_size
        or plan["max_candidates"] > budget.max_candidates_per_source
        or plan["detail_limit"] > budget.max_details_per_source
    )


def _selected_snapshots(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    selected_resources: tuple[SelectedResourceRef, ...],
) -> list[ResourceSnapshot]:
    matching = [resource for resource in selected_resources if resource.source == plan["source"]]
    snapshots: list[ResourceSnapshot] = []
    for resource in matching:
        if resource.source == "GMAIL":
            snapshots.append(_get_selected_gmail(gateway=gateway, resource=resource))
        elif resource.source == "TASKS":
            snapshots.append(_get_selected_task(gateway=gateway, resource=resource))
        elif resource.source == "CALENDAR":
            snapshots.append(_get_selected_calendar(gateway=gateway, resource=resource))
    return snapshots


def _get_selected_gmail(
    *,
    gateway: GoogleWorkspaceGateway,
    resource: SelectedResourceRef,
) -> ResourceSnapshot:
    if resource.resource_type == "THREAD":
        return gateway.get_gmail_thread(thread_id=resource.resource_id)
    if resource.resource_type == "MESSAGE":
        return gateway.get_gmail_message(message_id=resource.resource_id)
    raise ValueError(f"unsupported selected Gmail resource type: {resource.resource_type}")


def _get_selected_task(
    *,
    gateway: GoogleWorkspaceGateway,
    resource: SelectedResourceRef,
) -> ResourceSnapshot:
    if resource.resource_type != "TASK":
        raise ValueError(f"unsupported selected Tasks resource type: {resource.resource_type}")
    if resource.parent_resource_id is None:
        raise ValueError("selected task requires parent_resource_id")
    return gateway.get_task(
        task_list_id=resource.parent_resource_id,
        task_id=resource.resource_id,
    )


def _get_selected_calendar(
    *,
    gateway: GoogleWorkspaceGateway,
    resource: SelectedResourceRef,
) -> ResourceSnapshot:
    if resource.resource_type != "EVENT":
        raise ValueError(f"unsupported selected Calendar resource type: {resource.resource_type}")
    if resource.parent_resource_id is None:
        raise ValueError("selected calendar event requires parent_resource_id")
    return gateway.get_calendar_event(
        calendar_id=resource.parent_resource_id,
        event_id=resource.resource_id,
    )


def _acquire_planned_source(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    remaining: dict[str, int],
) -> list[ResourceSnapshot]:
    if plan["source"] == "GMAIL":
        return _acquire_gmail(gateway=gateway, plan=plan, remaining=remaining)
    if plan["source"] == "TASKS":
        return _acquire_tasks(gateway=gateway, plan=plan, remaining=remaining)
    return _acquire_calendar(gateway=gateway, plan=plan, remaining=remaining)


def _acquire_gmail(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    remaining: dict[str, int],
) -> list[ResourceSnapshot]:
    query = _query_from_constraints(plan["constraints"])
    page = gateway.search_gmail_threads(query=query, page_token=None, page_size=plan["page_size"])
    remaining["pages"] -= 1
    candidates = list(page.items[: plan["max_candidates"]])
    remaining["candidates"] -= len(candidates)
    detail_ids = [item.resource_id for item in candidates[: plan["detail_limit"]]]
    details = [gateway.get_gmail_thread(thread_id=thread_id) for thread_id in detail_ids]
    remaining["details"] -= len(details)
    return details


def _acquire_tasks(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    remaining: dict[str, int],
) -> list[ResourceSnapshot]:
    task_list_id = _constraint_string(plan["constraints"], "task_list_id")
    if task_list_id is None:
        lists_page = gateway.list_task_lists(page_token=None, page_size=1)
        remaining["pages"] -= 1
        if not lists_page.items:
            return []
        task_list_id = lists_page.items[0].resource_id
    page = gateway.list_tasks(
        task_list_id=task_list_id,
        page_token=None,
        page_size=plan["page_size"],
    )
    remaining["pages"] -= 1
    candidates = list(page.items[: plan["max_candidates"]])
    remaining["candidates"] -= len(candidates)
    detail_ids = [item.resource_id for item in candidates[: plan["detail_limit"]]]
    details = [
        gateway.get_task(task_list_id=task_list_id, task_id=task_id) for task_id in detail_ids
    ]
    remaining["details"] -= len(details)
    return details


def _acquire_calendar(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    remaining: dict[str, int],
) -> list[ResourceSnapshot]:
    calendar_id = _constraint_string(plan["constraints"], "calendar_id")
    if calendar_id is None:
        calendars_page = gateway.list_calendars(page_token=None, page_size=1)
        remaining["pages"] -= 1
        if not calendars_page.items:
            return []
        calendar_id = calendars_page.items[0].resource_id
    page = gateway.list_calendar_events(
        calendar_id=calendar_id,
        page_token=None,
        page_size=plan["page_size"],
    )
    remaining["pages"] -= 1
    candidates = list(page.items[: plan["max_candidates"]])
    remaining["candidates"] -= len(candidates)
    detail_ids = [item.resource_id for item in candidates[: plan["detail_limit"]]]
    details = [
        gateway.get_calendar_event(calendar_id=calendar_id, event_id=event_id)
        for event_id in detail_ids
    ]
    remaining["details"] -= len(details)
    return details


def _query_from_constraints(constraints: dict[str, object]) -> str:
    terms: list[str] = []
    for key in ("query", "topic", "person", "time"):
        value = constraints.get(key)
        if isinstance(value, str) and value.strip():
            terms.append(value.strip())
    return " ".join(terms)


def _constraint_string(constraints: dict[str, object], key: str) -> str | None:
    value = constraints.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


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


def _provider_summary(result: StructuredLLMResult) -> dict[str, object]:
    return {
        "provider": result.provider,
        "model": result.model,
        "requested_mode": result.requested_mode.value,
        "actual_runtime": result.actual_runtime.value,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "latency_ms": result.latency_ms,
        "fallback_reason": result.fallback_reason,
        "structured_output_attempts": result.structured_output_attempts,
        "provider_request_id": result.provider_request_id,
        "safe_error_code": result.safe_error_code,
    }


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


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SourcePlanningValidationError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise SourcePlanningValidationError(f"{path} keys must be strings")
        result[key] = item
    return result


def _require_exact_keys(value: dict[str, object], path: str, keys: set[str]) -> None:
    actual = set(value)
    missing = keys - actual
    extra = actual - keys
    if missing:
        raise SourcePlanningValidationError(f"{path} is missing required fields: {sorted(missing)}")
    if extra:
        raise SourcePlanningValidationError(f"{path} has unsupported fields: {sorted(extra)}")


def _require_int(value: dict[str, object], field: str, path: str) -> int:
    item = value[field]
    if not isinstance(item, int) or isinstance(item, bool):
        raise SourcePlanningValidationError(f"{path}.{field} must be integer")
    return item


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


def _require_string(value: dict[str, object], field: str, path: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise SourcePlanningValidationError(f"{path}.{field} must be string")
    return item


def _require_list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise SourcePlanningValidationError(f"{path} must be an array")
    return value


def _require_string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise SourcePlanningValidationError(f"{path} must be an array")
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise SourcePlanningValidationError(f"{path}[{index}] must be string")
    return cast(list[str], value)


def _optional_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SourcePlanningValidationError("clarification list field must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise SourcePlanningValidationError(f"clarification list entry must be string: {index}")
        result.append(item)
    return result


def _optional_option_list(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SourcePlanningValidationError("clarification options must be an array")
    return [_require_mapping(item, "$.clarification.options[]") for item in value]
