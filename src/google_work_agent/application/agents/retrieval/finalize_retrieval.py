"""Canonical Retrieval deterministic operation: finalize_retrieval."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, cast

from google_work_agent.application.workflows.handoff_contracts import (
    AcquisitionResultV1,
    EvidenceDraftV1,
    EvidenceSelectionResultV2,
    RequestIntentV2,
    RetrievalResultV1,
    RetrievalSourceStatusV1,
    SufficiencyResultV2,
)
from google_work_agent.application.workflows.retrieval_rounds import retrieval_round_count
from google_work_agent.application.workflows.retrieval_sufficiency import (
    missing_information_projection,
    source_statuses_prompt_projection,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2


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
) -> RetrievalResultV1:
    """Materialize the only parent-facing Retrieval business artifact."""
    selected_ids = list(selection_result["selected_segment_ids"])
    selected = set(selected_ids)
    evidence = [item for item in evidence_drafts if item["segment_id"] in selected]
    route_meta = tool_route_plan["input_plan"]["meta"]
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": artifact_id,
            "revision": 1,
            "based_on": [
                {
                    "artifact_id": request_intent["meta"]["artifact_id"],
                    "revision": request_intent["meta"]["revision"],
                },
                {
                    "artifact_id": route_meta["artifact_id"],
                    "revision": route_meta["revision"],
                },
            ],
        },
        "coverage": _coverage(sufficiency_result["status"], acquisition_result),
        "context_bundle_ref": None,
        "evidence_refs": [item["evidence_id"] for item in evidence],
        "selected_segment_ids": selected_ids,
        "source_resource_refs": _unique(item["resource_handle"] for item in evidence),
        "source_statuses": _source_statuses(tool_route_plan, acquisition_result),
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
) -> list[RetrievalSourceStatusV1]:
    return [
        {
            "route_id": str(item["route_id"]),
            "status": cast(
                Literal["COMPLETE", "PARTIAL", "FAILED", "NOT_ATTEMPTED"],
                item["status"],
            ),
            "reason_codes": [] if item["failure_kind"] is None else [str(item["failure_kind"])],
        }
        for item in source_statuses_prompt_projection(
            tool_route_plan=tool_route_plan,
            acquisition_result=acquisition_result,
        )
    ]


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
