"""One-way compatibility projection from canonical V2 plans to the legacy read port."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.api_acquisition import RetrievalBudget
from google_work_agent.application.orchestration.handoff_contracts import (
    CalendarReadMode,
    SourceName,
    TemporalQueryV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    SourceFetchPlanV1 as LegacySourceFetchPlanV1,
)
from google_work_agent.application.orchestration.retrieval_v2_contracts import SourceFetchPlanV1


class SourceFetchPlanExecutionProjectionError(ValueError):
    """The legacy read port cannot safely represent a canonical V2 read plan."""


def project_for_legacy_read_executor(
    plans: list[SourceFetchPlanV1],
    *,
    frozen_routes: list[InputToolRouteV1],
    retrieval_budget: RetrievalBudget,
) -> list[LegacySourceFetchPlanV1]:
    """Adapt validated V2 plans without granting the legacy contract planning authority.

    This is a one-way execution projection.  It deterministically lowers
    only semantic constraints the existing Google read port can represent;
    unsupported combinations fail before a connector invocation.
    """
    route_by_id = {route["route_id"]: route for route in frozen_routes}
    result: list[LegacySourceFetchPlanV1] = []
    for priority, plan in enumerate(plans, start=1):
        route = route_by_id.get(plan["route_id"])
        if route is None:
            raise SourceFetchPlanExecutionProjectionError("plan route is not frozen")
        if plan["operation_kind"] not in {"SEARCH", "FREEBUSY"}:
            raise SourceFetchPlanExecutionProjectionError(
                "legacy read executor projection currently supports SEARCH and FREEBUSY only"
            )
        constraints, calendar_read_mode, temporal_query = _legacy_constraints(plan)
        source = {"EMAIL": "GMAIL", "TASK": "TASKS", "CALENDAR": "CALENDAR"}[plan["resource_type"]]
        result.append(
            {
                "schema_version": 2,
                "source": cast(SourceName, source),
                "priority": priority,
                "reason_codes": list(route["reason_codes"]),
                "constraints": constraints,
                "page_size": retrieval_budget.max_page_size,
                "max_pages": retrieval_budget.max_pages_per_source,
                "max_candidates": retrieval_budget.max_candidates_per_source,
                "detail_limit": retrieval_budget.max_details_per_source,
                "required": route["required"],
                "calendar_read_mode": cast(CalendarReadMode | None, calendar_read_mode),
                "temporal_query": cast(TemporalQueryV1 | None, temporal_query),
            }
        )
    return result


def _legacy_constraints(
    plan: SourceFetchPlanV1,
) -> tuple[dict[str, object], str | None, dict[str, object] | None]:
    if plan["operation_kind"] == "FREEBUSY" and plan["resource_type"] != "CALENDAR":
        raise SourceFetchPlanExecutionProjectionError(
            "FREEBUSY is only supported for CALENDAR routes"
        )
    if plan["resource_type"] == "EMAIL":
        return _gmail_constraints(plan), None, None
    if plan["resource_type"] == "TASK":
        return _container_only_constraints(plan, container_key="task_list_id"), None, None
    return _calendar_constraints(plan)


def _gmail_constraints(plan: SourceFetchPlanV1) -> dict[str, object]:
    terms: list[str] = []
    for constraint in plan["effective_constraints"]:
        kind = constraint["kind"]
        value = cast(dict[str, object], constraint)
        if kind == "KEYWORD":
            values = cast(list[str], value["terms"])
            terms.append(
                " ".join(values)
                if value["match_mode"] != "PHRASE"
                else '"' + " ".join(values) + '"'
            )
        elif kind == "PARTICIPANT":
            participant_terms = [
                _gmail_participant_term(cast(dict[str, str], item))
                for item in cast(list[object], value["participants"])
            ]
            joined = " ".join(participant_terms)
            terms.append("{" + joined + "}" if value["match_mode"] == "ANY" else joined)
        elif kind == "TEMPORAL_RANGE":
            if value["axis"] != "MESSAGE_TIME":
                raise SourceFetchPlanExecutionProjectionError(
                    "temporal axis is incompatible with EMAIL"
                )
            if value["start_local"] is not None:
                terms.append("after:" + _gmail_date(cast(str, value["start_local"])))
            if value["end_local"] is not None:
                terms.append("before:" + _gmail_date(cast(str, value["end_local"])))
        elif kind == "RESOURCE_REF":
            terms.extend("rfc822msgid:" + ref for ref in cast(list[str], value["resource_refs"]))
        elif kind == "CONTAINER_REF":
            terms.extend("in:" + ref for ref in cast(list[str], value["container_refs"]))
        elif kind == "STATUS_SCOPE":
            terms.extend(_gmail_status_terms(cast(list[str], value["values"])))
        else:
            raise SourceFetchPlanExecutionProjectionError(
                f"legacy read executor has no semantic translator for {kind}"
            )
    if not terms:
        raise SourceFetchPlanExecutionProjectionError("SEARCH requires translatable constraints")
    return {"query": " ".join(terms)}


def _gmail_participant_term(participant: dict[str, str]) -> str:
    prefix = {"SENDER": "from:", "RECIPIENT": "to:", "ATTENDEE": "", "ANY": ""}[participant["role"]]
    return prefix + participant["identity"]


def _gmail_date(value: str) -> str:
    return datetime.fromisoformat(value).date().isoformat().replace("-", "/")


def _gmail_status_terms(values: list[str]) -> list[str]:
    mapping = {"DRAFT": "in:drafts", "SENT": "in:sent"}
    unsupported = set(values) - {"ANY", *mapping}
    if unsupported:
        raise SourceFetchPlanExecutionProjectionError("status scope is incompatible with EMAIL")
    return [mapping[value] for value in values if value in mapping]


def _container_only_constraints(
    plan: SourceFetchPlanV1, *, container_key: str
) -> dict[str, object]:
    constraints = plan["effective_constraints"]
    if len(constraints) != 1 or constraints[0]["kind"] != "CONTAINER_REF":
        raise SourceFetchPlanExecutionProjectionError(
            "legacy read executor has no semantic translator for "
            f"{plan['resource_type']} constraints"
        )
    refs = constraints[0]["container_refs"]
    if len(refs) != 1:
        raise SourceFetchPlanExecutionProjectionError(
            "a legacy container read requires one container ref"
        )
    return {container_key: refs[0]}


def _calendar_constraints(
    plan: SourceFetchPlanV1,
) -> tuple[dict[str, object], str, dict[str, object] | None]:
    constraints = plan["effective_constraints"]
    container = next((item for item in constraints if item["kind"] == "CONTAINER_REF"), None)
    temporal = next((item for item in constraints if item["kind"] == "TEMPORAL_RANGE"), None)
    if any(item["kind"] not in {"CONTAINER_REF", "TEMPORAL_RANGE"} for item in constraints):
        raise SourceFetchPlanExecutionProjectionError(
            "legacy read executor has no semantic translator for CALENDAR constraints"
        )
    legacy_constraints = (
        {}
        if container is None
        else _container_only_constraints(
            {**plan, "effective_constraints": [container]}, container_key="calendar_id"
        )
    )
    if temporal is None:
        if plan["operation_kind"] == "FREEBUSY":
            raise SourceFetchPlanExecutionProjectionError(
                "FREEBUSY requires a temporal range constraint"
            )
        return legacy_constraints, "EVENTS_ONLY", None
    if temporal["axis"] not in {"EVENT_TIME", "AVAILABILITY_WINDOW"}:
        raise SourceFetchPlanExecutionProjectionError("temporal axis is incompatible with CALENDAR")
    if temporal["start_local"] is None or temporal["end_local"] is None:
        raise SourceFetchPlanExecutionProjectionError(
            "calendar temporal translation requires both bounds"
        )
    timezone_value = cast(str, temporal["timezone"])
    return (
        legacy_constraints,
        "EVENTS_AND_FREEBUSY",
        {
            "schema_version": 1,
            "relation": "ABSOLUTE",
            "relative_unit": None,
            "relative_offset": None,
            "weekday": None,
            "daypart": None,
            "absolute_start": _local_to_rfc3339(cast(str, temporal["start_local"]), timezone_value),
            "absolute_end": _local_to_rfc3339(cast(str, temporal["end_local"]), timezone_value),
        },
    )


def _local_to_rfc3339(local_iso: str, timezone: str) -> str:
    """Attach the constraint's own IANA timezone to an offset-free local instant.

    ``SemanticRetrievalConstraintV1`` TEMPORAL_RANGE values are validated as
    offset-free local ISO (``_local_iso`` in retrieval_v2_contracts.py) so
    the LLM never authors a provider-facing offset itself; this is the one
    deterministic place that turns the (local, timezone) pair into the
    offset-bearing RFC3339 instant ``TimeRange``/``FreeBusy`` require.
    """
    try:
        return datetime.fromisoformat(local_iso).replace(tzinfo=ZoneInfo(timezone)).isoformat()
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise SourceFetchPlanExecutionProjectionError(
            "calendar temporal value could not be localized"
        ) from error
