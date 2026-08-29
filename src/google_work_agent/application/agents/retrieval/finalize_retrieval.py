"""Canonical Retrieval deterministic operation: finalize_retrieval."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    StateArtifactRefV1,
)
from google_work_agent.application.agents.retrieval.resolve_availability import (
    AvailableIntervalV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    EvidenceSelectionResultV2,
    RequestIntentV2,
    RetrievalResultV1,
    RetrievalSourceStatusV1,
    SufficiencyResultV2,
)
from google_work_agent.application.orchestration.retrieval_rounds import retrieval_round_count
from google_work_agent.application.orchestration.retrieval_sufficiency import (
    missing_information_projection,
    source_statuses_prompt_projection,
)


def finalize_retrieval(
    *,
    artifact_id: str,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2,
    acquisition_result: AcquisitionResultV1,
    selection_result: EvidenceSelectionResultV2,
    evidence_drafts: list[EvidenceDraftV1],
    sufficiency_result: SufficiencyResultV2,
    current_round_no: int,
    availability_results: list[AvailableIntervalV1] | None = None,
    exclusion_obligation_segment_ids: Iterable[str] = (),
    prior_result: RetrievalResultV1 | None = None,
) -> RetrievalResultV1:
    """Materialize the only parent-facing Retrieval business artifact."""
    selected_ids = list(selection_result["selected_segment_ids"])
    selected = set(selected_ids)
    evidence = [item for item in evidence_drafts if item["segment_id"] in selected]
    route_meta = tool_route_plan["input_plan"]["meta"]
    prior_ref: list[StateArtifactRefV1] = (
        []
        if prior_result is None
        else [
            {
                "artifact_id": prior_result["meta"]["artifact_id"],
                "revision": prior_result["meta"]["revision"],
            }
        ]
    )
    artifact_identity = artifact_id if prior_result is None else prior_result["meta"]["artifact_id"]
    revision = 1 if prior_result is None else prior_result["meta"]["revision"] + 1
    excluded_ids = _unique(
        [
            *(prior_result["excluded_segment_ids"] if prior_result is not None else []),
            *selection_result["excluded_segment_ids"],
            *exclusion_obligation_segment_ids,
        ]
    )
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": artifact_identity,
            "revision": revision,
            "based_on": [
                {
                    "artifact_id": request_intent["meta"]["artifact_id"],
                    "revision": request_intent["meta"]["revision"],
                },
                {
                    "artifact_id": route_meta["artifact_id"],
                    "revision": route_meta["revision"],
                },
                *prior_ref,
            ],
        },
        "coverage": _coverage(sufficiency_result["status"], acquisition_result),
        "context_bundle_ref": None,
        "evidence_refs": [item["evidence_id"] for item in evidence],
        "selected_segment_ids": selected_ids,
        "excluded_segment_ids": excluded_ids,
        "source_resource_refs": _unique(item["resource_handle"] for item in evidence),
        "source_statuses": _source_statuses(
            tool_route_plan,
            acquisition_result,
            evidence_drafts=evidence,
        ),
        "availability_results": [dict(item) for item in (availability_results or [])],
        "missing_information": missing_information_projection(sufficiency_result["issues"]),
        "retrieval_rounds": retrieval_round_count(current_round_no=current_round_no),
    }


def _coverage(
    status: str, acquisition_result: AcquisitionResultV1
) -> Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"]:
    if status == "SUFFICIENT" and not acquisition_result["resource_handles"]:
        return "NO_FETCH_NEEDED"
    return "SUFFICIENT" if status == "SUFFICIENT" else "PARTIAL"


def _source_statuses(
    tool_route_plan: ToolRoutePlanV2,
    acquisition_result: AcquisitionResultV1,
    *,
    evidence_drafts: list[EvidenceDraftV1],
) -> list[RetrievalSourceStatusV1]:
    handles_by_source = {
        source: {
            str(handle)
            for summary in acquisition_result["source_summaries"]
            if str(summary.get("source")) == source
            for handle in cast(list[object], summary.get("resource_handles", []))
        }
        for source in ("GMAIL", "TASKS", "CALENDAR")
    }
    source_by_resource_type = {
        "EMAIL": "GMAIL",
        "TASK": "TASKS",
        "CALENDAR": "CALENDAR",
    }
    return [
        {
            "route_id": str(item["route_id"]),
            "resource_type": str(item["resource_type"]),
            "status": cast(
                Literal["COMPLETE", "PARTIAL", "FAILED", "NOT_ATTEMPTED"],
                item["status"],
            ),
            "evidence_refs": [
                draft["evidence_id"]
                for draft in evidence_drafts
                if draft["resource_handle"]
                in handles_by_source[source_by_resource_type[str(item["resource_type"])]]
            ],
            "failure_kind": _failure_kind(item["failure_kind"]),
        }
        for item in source_statuses_prompt_projection(
            tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result,
        )
    ]


def _failure_kind(
    value: object,
) -> (
    Literal["AUTH", "SCOPE", "RATE_LIMIT", "TIMEOUT", "PROVIDER", "NOT_FOUND", "BUDGET", "OTHER"]
    | None
):
    if value is None:
        return None
    normalized = str(value).upper()
    if normalized in {"AUTH", "SCOPE", "RATE_LIMIT", "TIMEOUT", "PROVIDER", "NOT_FOUND", "BUDGET"}:
        return cast(
            Literal["AUTH", "SCOPE", "RATE_LIMIT", "TIMEOUT", "PROVIDER", "NOT_FOUND", "BUDGET"],
            normalized,
        )
    return "OTHER"


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
