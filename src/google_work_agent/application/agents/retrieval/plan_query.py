"""Canonical Retrieval semantic operation: plan_query."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalConstraintKindV1,
    RetrievalQueryPlanV2,
    RetrievalV2ValidationError,
    validate_retrieval_query_plan_v2,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    bind_retrieval_query_plan_output_schema,
)
from google_work_agent.application.agents.retrieval.plan_candidate_detail import (
    deterministic_candidate_detail_plan,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    RunBudgetV2,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

_DIRECT_DETAIL_TOOL_BY_RESOURCE_TYPE = {
    "EMAIL": "gmail_get_thread",
    "GMAIL_THREAD": "gmail_get_thread",
    "GMAIL_MESSAGE": "gmail_get_message",
    "GMAIL_DRAFT": "gmail_get_draft",
    "GMAIL_ATTACHMENT": "gmail_get_attachment",
    "TASK": "tasks_get_task",
    "CALENDAR_EVENT": "calendar_get_event",
}


def exact_selected_detail_plan(
    *,
    frozen_routes: Sequence[InputToolRouteV1],
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    is_followup: bool,
) -> RetrievalQueryPlanV2 | None:
    """Materialize the one initial exact-resource read with no semantic choice left."""
    if is_followup or len(frozen_routes) != 1:
        return None
    route = frozen_routes[0]
    if "RESOURCE_SELECTED" not in route["reason_codes"]:
        return None
    detail_tool = _DIRECT_DETAIL_TOOL_BY_RESOURCE_TYPE.get(route["resource_type"])
    if detail_tool is None or detail_tool not in route["allowed_read_tool_ids"]:
        return None
    resource_refs = tuple((validated_resource_refs or {}).get(route["route_id"], ()))
    if len(resource_refs) != 1:
        return None
    resource_ref = resource_refs[0]
    if not resource_ref.startswith(f"{route['resource_type'].lower()}:"):
        raise RetrievalV2ValidationError(
            "selected-resource ref does not match its frozen route",
            reason_code="RETRIEVAL_ROUTE_SCOPE_VIOLATION",
            affected_field_paths=("$.validated_resource_refs",),
        )
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": route["route_id"],
                "operation": "DETAIL_FETCH",
                "reason_codes": ["RESOURCE_SELECTED"],
                "search_spec": None,
                "detail_candidate_ref": resource_ref,
            }
        ],
        "required_information": ["selected resource detail"],
        "retrieval_order": [route["route_id"]],
    }


def deterministic_initial_query_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    validated_container_refs: Mapping[str, Collection[str]] | None,
) -> RetrievalQueryPlanV2 | None:
    """Materialize initial reads whose meaning is fully fixed by validated state."""
    selected_detail = exact_selected_detail_plan(
        frozen_routes=frozen_routes,
        validated_resource_refs=validated_resource_refs,
        is_followup="current_round_no" in prompt_input,
    )
    if selected_detail is not None:
        return selected_detail
    calendar_plan = _exact_calendar_conflict_check_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        validated_container_refs=validated_container_refs,
        is_followup="current_round_no" in prompt_input,
    )
    if calendar_plan is not None:
        return calendar_plan
    return _exact_task_duplicate_check_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        validated_container_refs=validated_container_refs,
        is_followup="current_round_no" in prompt_input,
    )


def deterministic_query_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    validated_container_refs: Mapping[str, Collection[str]] | None,
    detail_candidate_refs: Collection[str] = (),
    attempted_detail_candidate_refs: Collection[str] = (),
) -> RetrievalQueryPlanV2 | None:
    """Project deterministic initial and candidate-detail continuations."""

    candidate_detail = deterministic_candidate_detail_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        detail_candidate_refs=detail_candidate_refs,
        attempted_detail_candidate_refs=attempted_detail_candidate_refs,
    )
    if candidate_detail is not None:
        return candidate_detail
    return deterministic_initial_query_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
    )


def _exact_calendar_conflict_check_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    validated_container_refs: Mapping[str, Collection[str]] | None,
    is_followup: bool,
) -> RetrievalQueryPlanV2 | None:
    """Build the policy-required Calendar pre-read when no query choice remains."""
    if is_followup or not frozen_routes:
        return None
    if {route["resource_type"] for route in frozen_routes} != {
        "CALENDAR",
        "CALENDAR_EVENT",
        "CALENDAR_FREEBUSY",
    }:
        return None
    if any(
        not route["required"] or "POLICY_CALENDAR_CONFLICT_CHECK" not in route["reason_codes"]
        for route in frozen_routes
    ):
        return None

    request_intent = prompt_input.get("request_intent")
    if not isinstance(request_intent, Mapping):
        return None
    if "CREATE" not in _string_collection(request_intent.get("requested_effect_hints")):
        return None
    if "CALENDAR_EVENT" not in _string_collection(request_intent.get("requested_resource_hints")):
        return None
    temporal = _exact_calendar_temporal_range(request_intent.get("constraints"))
    if temporal is None:
        return None

    route_queries: list[dict[str, object]] = []
    retrieval_order: list[str] = []
    for route in frozen_routes:
        route_id = route["route_id"]
        policy = route_policies.get(route_id)
        container_refs = tuple((validated_container_refs or {}).get(route_id, ()))
        if (
            policy is None
            or "CONTAINER_REF" not in policy.supported_kinds
            or "TEMPORAL_RANGE" not in policy.supported_kinds
            or len(container_refs) != 1
        ):
            return None
        operation = "FREEBUSY" if route["resource_type"] == "CALENDAR_FREEBUSY" else "SEARCH"
        axis = "AVAILABILITY_WINDOW" if operation == "FREEBUSY" else "EVENT_TIME"
        route_queries.append(
            {
                "route_id": route_id,
                "operation": operation,
                "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "CONTAINER_REF", "container_refs": [container_refs[0]]},
                        {"kind": "TEMPORAL_RANGE", "axis": axis, **temporal},
                    ],
                },
                "detail_candidate_ref": None,
            }
        )
        retrieval_order.append(route_id)
    return cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": route_queries,
            "required_information": [
                "calendar identity",
                "events in the requested time range",
                "availability in the requested time range",
            ],
            "retrieval_order": retrieval_order,
        },
    )


def _exact_task_duplicate_check_plan(
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    validated_container_refs: Mapping[str, Collection[str]] | None,
    is_followup: bool,
) -> RetrievalQueryPlanV2 | None:
    """Build the policy-required Task duplicate pre-read from the bound list."""
    if is_followup or not frozen_routes:
        return None
    if {route["resource_type"] for route in frozen_routes} != {"TASK", "TASK_LIST"}:
        return None
    if any(
        not route["required"] or "POLICY_TASK_DUPLICATE_CHECK" not in route["reason_codes"]
        for route in frozen_routes
    ):
        return None
    request_intent = prompt_input.get("request_intent")
    if not isinstance(request_intent, Mapping):
        return None
    if (
        request_intent.get("requested_effect_hints") != ["CREATE"]
        or request_intent.get("requested_resource_hints") != ["TASK"]
        or _exact_task_title(request_intent.get("constraints")) is None
    ):
        return None

    route_queries: list[dict[str, object]] = []
    retrieval_order: list[str] = []
    for route in frozen_routes:
        route_id = route["route_id"]
        policy = route_policies.get(route_id)
        container_refs = tuple((validated_container_refs or {}).get(route_id, ()))
        if (
            policy is None
            or "CONTAINER_REF" not in policy.supported_kinds
            or len(container_refs) != 1
        ):
            return None
        route_queries.append(
            {
                "route_id": route_id,
                "operation": "SEARCH",
                "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {"kind": "CONTAINER_REF", "container_refs": [container_refs[0]]}
                    ],
                },
                "detail_candidate_ref": None,
            }
        )
        retrieval_order.append(route_id)
    return cast(
        RetrievalQueryPlanV2,
        {
            "schema_version": 2,
            "route_queries": route_queries,
            "required_information": ["existing tasks in the bound task list"],
            "retrieval_order": retrieval_order,
        },
    )


def _exact_task_title(value: object) -> str | None:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], Mapping):
        return None
    constraint = value[0]
    title = constraint.get("value")
    if (
        constraint.get("kind") != "RESOURCE"
        or constraint.get("field") != "title"
        or not isinstance(title, str)
        or not title
    ):
        return None
    return title


def _string_collection(value: object) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return frozenset()
    return frozenset(value)


def _exact_calendar_temporal_range(value: object) -> dict[str, str] | None:
    if not isinstance(value, list):
        return None
    values: dict[str, str] = {}
    for item in value:
        if not isinstance(item, Mapping) or item.get("kind") not in {"DATE", "TIME"}:
            continue
        field = item.get("field")
        item_value = item.get("value")
        if field in {"date", "start_time", "end_time", "timezone"} and isinstance(item_value, str):
            if field in values:
                return None
            values[field] = item_value
    if not {"start_time", "end_time", "timezone"}.issubset(values):
        return None
    try:
        timezone = ZoneInfo(values["timezone"])
        start = _calendar_local_datetime(values["start_time"], values.get("date"))
        end = _calendar_local_datetime(values["end_time"], values.get("date"))
        start_local = (
            start.replace(tzinfo=timezone) if start.tzinfo is None else start.astimezone(timezone)
        )
        end_local = end.replace(tzinfo=timezone) if end.tzinfo is None else end.astimezone(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    if end_local <= start_local:
        return None
    return {
        "start_local": start_local.replace(tzinfo=None).isoformat(),
        "end_local": end_local.replace(tzinfo=None).isoformat(),
        "timezone": values["timezone"],
    }


def _calendar_local_datetime(value: str, date_value: str | None) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        if date_value is None:
            raise
        return datetime.combine(date.fromisoformat(date_value), time.fromisoformat(value))


def plan_query(
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    revision_prompt_ref: PromptReference,
    output_schema: OutputSchemaDefinition,
    prompt_input: dict[str, object],
    requested_mode: RequestedModeV1,
    frozen_routes: Sequence[InputToolRouteV1],
    route_policies: Mapping[str, RouteConstraintPolicy],
    retry_budget: RunBudgetV2,
    validated_resource_refs: Mapping[str, Collection[str]] | None = None,
    validated_container_refs: Mapping[str, Collection[str]] | None = None,
    detail_candidate_refs: Collection[str] = (),
    attempted_detail_candidate_refs: Collection[str] = (),
) -> tuple[RetrievalQueryPlanV2, RunBudgetV2, bool]:
    """Plan provider-neutral retrieval intent against already-frozen input routes."""
    supported_kinds = _applicable_constraint_kinds(
        route_policies,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
    )
    planner_input = _project_route_constraint_policies(
        prompt_input, route_policies, supported_kinds=supported_kinds
    )
    is_followup = "current_round_no" in prompt_input
    bounded_output_schema = bind_retrieval_query_plan_output_schema(
        base_schema=output_schema,
        route_ids=supported_kinds,
        supported_constraint_kinds=supported_kinds,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        detail_candidate_refs=detail_candidate_refs,
        is_followup=is_followup,
    )
    deterministic_plan = deterministic_query_plan(
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
        route_policies=route_policies,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        detail_candidate_refs=detail_candidate_refs,
        attempted_detail_candidate_refs=attempted_detail_candidate_refs,
    )
    if deterministic_plan is not None:
        return (
            validate_retrieval_query_plan_v2(
                deterministic_plan,
                frozen_routes=frozen_routes,
                supported_constraint_kinds=supported_kinds,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
                detail_candidate_refs=detail_candidate_refs,
            ),
            retry_budget,
            False,
        )
    result = llm_runtime.infer(
        requested_mode,
        prompt_ref,
        planner_input,
        bounded_output_schema,
    )
    candidate = _preserve_explicit_gmail_constraints(
        result.structured_output,
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
    )
    try:
        validated = validate_retrieval_query_plan_v2(
            candidate,
            frozen_routes=frozen_routes,
            supported_constraint_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
        )
        return (
            _validate_query_plan_round(
                validated,
                is_followup=is_followup,
            ),
            retry_budget,
            True,
        )
    except RetrievalV2ValidationError as error:
        revised_plan, revised_budget = _revise_plan_once(
            llm_runtime=llm_runtime,
            revision_prompt_ref=revision_prompt_ref,
            output_schema=bounded_output_schema,
            prompt_input=planner_input,
            requested_mode=requested_mode,
            frozen_routes=frozen_routes,
            supported_kinds=supported_kinds,
            validated_resource_refs=validated_resource_refs,
            validated_container_refs=validated_container_refs,
            detail_candidate_refs=detail_candidate_refs,
            previous_output=candidate,
            failure_reason_code=error.reason_code,
            affected_field_paths=error.affected_field_paths,
            failure_detail=str(error),
            retry_budget=retry_budget,
            is_followup=is_followup,
        )
    return revised_plan, revised_budget, True


def _validate_query_plan_round(
    plan: RetrievalQueryPlanV2,
    *,
    is_followup: bool,
) -> RetrievalQueryPlanV2:
    """Reject continuation operations before a validated prior read can exist."""
    if not is_followup and any(
        query["operation"] == "NEXT_PAGE" for query in plan["route_queries"]
    ):
        raise RetrievalV2ValidationError(
            "initial retrieval cannot request NEXT_PAGE without a validated prior read result",
            reason_code="QUERY_OPERATION_FIELD_MISMATCH",
            affected_field_paths=("$.route_queries[].operation",),
        )
    expected_mode = "CHANGED" if is_followup else "INITIAL"
    for query in plan["route_queries"]:
        if query["operation"] not in {"SEARCH", "FREEBUSY"}:
            continue
        search_spec = query["search_spec"]
        if search_spec is None or search_spec["mode"] != expected_mode:
            raise RetrievalV2ValidationError(
                f"{'follow-up' if is_followup else 'initial'} search must use {expected_mode}",
                reason_code="QUERY_OPERATION_FIELD_MISMATCH",
                affected_field_paths=("$.route_queries[].search_spec.mode",),
            )
    return plan


def _project_route_constraint_policies(
    prompt_input: Mapping[str, object],
    route_policies: Mapping[str, RouteConstraintPolicy],
    *,
    supported_kinds: Mapping[str, Collection[RetrievalConstraintKindV1]],
) -> dict[str, object]:
    """Expose the existing deterministic route policy to the semantic planner."""

    result = deepcopy(dict(prompt_input))
    routes = result.get("input_routes")
    if not isinstance(routes, list):
        return result
    for route in routes:
        if not isinstance(route, dict):
            continue
        route_id = route.get("route_id")
        if not isinstance(route_id, str):
            continue
        policy = route_policies.get(route_id)
        if policy is None:
            continue
        route["supported_constraint_kinds"] = sorted(supported_kinds.get(route_id, ()))
        route["required_constraint_kinds"] = sorted(policy.required_kinds)
    return result


def _applicable_constraint_kinds(
    route_policies: Mapping[str, RouteConstraintPolicy],
    *,
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    validated_container_refs: Mapping[str, Collection[str]] | None,
) -> dict[str, frozenset[RetrievalConstraintKindV1]]:
    """Narrow supported kinds to constraints materializable from current state."""

    result: dict[str, frozenset[RetrievalConstraintKindV1]] = {}
    for route_id, policy in route_policies.items():
        applicable = set(policy.supported_kinds)
        if not (validated_resource_refs or {}).get(route_id):
            applicable.discard("RESOURCE_REF")
        if not (validated_container_refs or {}).get(route_id):
            applicable.discard("CONTAINER_REF")
        result[route_id] = frozenset(applicable)
    return result


def _revise_plan_once(
    *,
    llm_runtime: StructuredInferencePort,
    revision_prompt_ref: PromptReference,
    output_schema: OutputSchemaDefinition,
    prompt_input: dict[str, object],
    requested_mode: RequestedModeV1,
    frozen_routes: Sequence[InputToolRouteV1],
    supported_kinds: Mapping[str, frozenset[RetrievalConstraintKindV1]],
    validated_resource_refs: Mapping[str, Collection[str]] | None,
    validated_container_refs: Mapping[str, Collection[str]] | None,
    detail_candidate_refs: Collection[str],
    previous_output: object,
    failure_reason_code: str,
    affected_field_paths: tuple[str, ...],
    failure_detail: str,
    retry_budget: RunBudgetV2,
    is_followup: bool,
) -> tuple[RetrievalQueryPlanV2, RunBudgetV2]:
    signature = build_semantic_failure_signature_v1(
        node_id="retrieval.plan_query",
        failure_reason_codes=[failure_reason_code],
    )
    decision = approve_semantic_revision(retry_budget, signature=signature)
    if decision["decision"] == BudgetDecision.DENY.value:
        raise RetrievalV2ValidationError(
            "retrieval query plan revision denied: same failure signature already used"
        )
    revision = llm_runtime.infer(
        requested_mode,
        revision_prompt_ref,
        {
            "base_projection": dict(prompt_input),
            "candidate_output": previous_output,
            "failure_record": build_failure_record_v1(
                failure_reason_code=failure_reason_code,
                failure_origin="QUERY_PLANNING",
                detected_by="RUNTIME_DOMAIN_VALIDATOR",
                runtime_disposition="RETRYABLE",
                experiment_disposition="RUN_REVISION",
                affected_field_paths=list(affected_field_paths)
                or [
                    "$.route_queries",
                    "$.required_information",
                    "$.retrieval_order",
                ],
                failure_context_ids=[failure_detail],
            ),
        },
        output_schema,
    )
    candidate = _preserve_explicit_gmail_constraints(
        revision.structured_output,
        prompt_input=prompt_input,
        frozen_routes=frozen_routes,
    )
    validated = validate_retrieval_query_plan_v2(
        candidate,
        frozen_routes=frozen_routes,
        supported_constraint_kinds=supported_kinds,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
        detail_candidate_refs=detail_candidate_refs,
    )
    return (
        _validate_query_plan_round(validated, is_followup=is_followup),
        decision["run_budget"],
    )


def _preserve_explicit_gmail_constraints(
    value: object,
    *,
    prompt_input: Mapping[str, object],
    frozen_routes: Sequence[InputToolRouteV1],
) -> object:
    """Keep validated explicit Gmail values exact across semantic planning.

    The LLM still decides whether and how to search. Once it chooses an
    initial Gmail search, sender/recipient/subject strings already owned by
    RequestIntent are data, not a new semantic choice.
    """
    gmail_routes = [route for route in frozen_routes if route["resource_type"] == "GMAIL_THREAD"]
    if len(gmail_routes) != 1:
        return value
    request_intent = prompt_input.get("request_intent")
    if not isinstance(request_intent, Mapping):
        return value
    explicit_constraints = _explicit_gmail_constraints(request_intent.get("constraints"))
    if not explicit_constraints or not isinstance(value, Mapping):
        return value
    route_queries = value.get("route_queries")
    if not isinstance(route_queries, list):
        return value

    route_id = gmail_routes[0]["route_id"]
    candidate = deepcopy(dict(value))
    candidate_queries = candidate.get("route_queries")
    if not isinstance(candidate_queries, list):
        return value
    replacement_kinds = {str(item["kind"]) for item in explicit_constraints}
    for route_query in candidate_queries:
        if not isinstance(route_query, dict):
            continue
        if route_query.get("route_id") != route_id or route_query.get("operation") != "SEARCH":
            continue
        search_spec = route_query.get("search_spec")
        if not isinstance(search_spec, dict) or search_spec.get("mode") != "INITIAL":
            continue
        constraints = search_spec.get("constraints")
        if not isinstance(constraints, list):
            continue
        search_spec["constraints"] = [
            item
            for item in constraints
            if not isinstance(item, Mapping) or str(item.get("kind")) not in replacement_kinds
        ] + explicit_constraints
    return candidate


def _explicit_gmail_constraints(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    participants: list[dict[str, str]] = []
    subjects: list[str] = []
    participant_fields = {
        "sender": "SENDER",
        "sender_email": "SENDER",
        "from": "SENDER",
        "recipient": "RECIPIENT",
        "recipient_email": "RECIPIENT",
        "to": "RECIPIENT",
        "search_criteria_sender": "SENDER",
        "search_criteria_recipient": "RECIPIENT",
    }
    for item in value:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind", "")).upper()
        field = str(item.get("field", "")).strip().lower()
        values = item.get("value")
        exact_values = [values] if isinstance(values, str) else values
        if not isinstance(exact_values, list) or not all(
            isinstance(entry, str) and entry for entry in exact_values
        ):
            continue
        if kind in {"EMAIL", "PERSON", "SCOPE"} and field in participant_fields:
            participants.extend(
                {"role": participant_fields[field], "identity": entry} for entry in exact_values
            )
        elif kind in {"RESOURCE", "SCOPE", "USER_REQUIREMENT"} and field in {
            "subject",
            "search_criteria_subject",
        }:
            subjects.extend(exact_values)

    result: list[dict[str, object]] = []
    if participants:
        result.append({"kind": "PARTICIPANT", "participants": participants, "match_mode": "ALL"})
    if subjects:
        result.append({"kind": "KEYWORD", "terms": subjects, "match_mode": "PHRASE"})
    return result


# Preserved planner-input construction is owned by this query-planning operation.


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

_FOLLOWUP_SEARCH_TOOLS = frozenset(
    {
        "gmail_search_threads",
        "tasks_list_tasks",
        "calendar_list_events",
        "calendar_query_freebusy",
    }
)
_SEMANTIC_EXPANSION_KINDS = frozenset({"TEMPORAL_RANGE", "PARTICIPANT", "KEYWORD", "STATUS_SCOPE"})


def has_retrieval_followup_path(
    *,
    tool_route_plan: ToolRoutePlanV2,
    route_policies: Mapping[str, RouteConstraintPolicy],
    read_result_summaries: Sequence[Mapping[str, object]],
    query_attempts: Sequence[QueryAttemptV1],
) -> bool:
    """Return whether the frozen route can produce information not read yet."""

    if any(
        summary.get("has_next_page") is True and summary.get("exhausted") is not True
        for summary in read_result_summaries
    ):
        return True
    search_route_ids = {
        route["route_id"]
        for route in tool_route_plan["input_plan"]["input_routes"]
        if _FOLLOWUP_SEARCH_TOOLS.intersection(route["allowed_read_tool_ids"])
        and bool(
            route_policies.get(
                route["route_id"], RouteConstraintPolicy(frozenset())
            ).supported_kinds.intersection(_SEMANTIC_EXPANSION_KINDS)
        )
    }
    return any(
        attempt["route_id"] in search_route_ids
        and attempt["operation_kind"] in {"SEARCH", "FREEBUSY"}
        for attempt in query_attempts
    )


def initial_retrieval_planner_input(
    *,
    request_intent: RequestIntentV2,
    input_routes: Sequence[InputToolRouteV1],
    retrieval_budget: RetrievalBudget,
    validated_resource_refs: Mapping[str, Sequence[str]] | None = None,
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """Project exactly the initial-round V2 input contract."""
    return {
        "request_intent": request_intent,
        "input_routes": [
            _prompt_route(
                route,
                validated_resource_refs=validated_resource_refs,
                validated_container_refs=validated_container_refs,
            )
            for route in input_routes
        ],
        "retrieval_budget": retrieval_budget.as_remaining(),
    }


def followup_retrieval_planner_input(
    *,
    request_intent: RequestIntentV2,
    input_routes: Sequence[InputToolRouteV1],
    retrieval_budget: RetrievalBudget,
    followup: Mapping[str, object],
    validated_resource_refs: Mapping[str, Sequence[str]] | None = None,
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """Add only the bounded follow-up metadata permitted by the V2 contract."""
    result = initial_retrieval_planner_input(
        request_intent=request_intent,
        input_routes=input_routes,
        retrieval_budget=retrieval_budget,
        validated_resource_refs=validated_resource_refs,
        validated_container_refs=validated_container_refs,
    )
    for field in (
        "current_round_no",
        "prior_query_attempts",
        "unresolved_sufficiency_issues",
        "read_result_summaries",
    ):
        if field not in followup:
            raise ValueError(f"follow-up retrieval planner input is missing {field}")
        result[field] = followup[field]
    return result


def _prompt_route(
    route: InputToolRouteV1,
    *,
    validated_resource_refs: Mapping[str, Sequence[str]] | None = None,
    validated_container_refs: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    prompt_route: dict[str, object] = {
        "route_id": route["route_id"],
        "connector_id": route["connector_id"],
        "resource_type": coarse_resource_category(route["resource_type"]),
        "allowed_read_tool_ids": list(route["allowed_read_tool_ids"]),
        "required": route["required"],
        "reason_codes": list(route["reason_codes"]),
    }
    resource_refs = (validated_resource_refs or {}).get(route["route_id"])
    if resource_refs:
        prompt_route["resource_refs"] = list(resource_refs)
    container_refs = (validated_container_refs or {}).get(route["route_id"])
    if container_refs:
        # Pre-Prompt Runtime Closure: the only container refs the LLM is
        # ever shown are already-validated internal refs resolved by
        # deterministic code (see _validated_task_container_refs,
        # context_retrieval.py) -- never a raw provider/task_list_id the
        # model could invent on its own.
        prompt_route["container_refs"] = list(container_refs)
    return prompt_route
