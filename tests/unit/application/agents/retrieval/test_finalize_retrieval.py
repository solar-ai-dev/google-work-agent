from typing import cast

from tests.unit.application.workflows.test_context_retrieval import (
    _acquisition_result,
    _intent,
    _selection_output,
    _sufficiency_output,
    _tool_route_plan,
)

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    RetrievalResultV1,
)
from google_work_agent.application.agents.retrieval.finalize_retrieval import (
    finalize_retrieval,
)


def test_finalize_retrieval_preserves_full_contract_and_revision_lineage() -> None:
    prior = cast(
        RetrievalResultV1,
        {
            "schema_version": 1,
            "meta": {"artifact_id": "retrieval-1", "revision": 2, "based_on": []},
            "coverage": "PARTIAL",
            "context_bundle_ref": None,
            "evidence_refs": [],
            "selected_segment_ids": [],
            "excluded_segment_ids": ["segment-old"],
            "source_resource_refs": [],
            "source_statuses": [],
            "availability_results": [],
            "missing_information": [],
            "retrieval_rounds": 1,
        },
    )
    selection = _selection_output(["segment-1"])
    selection["excluded_segment_ids"] = ["segment-model"]
    result = finalize_retrieval(
        artifact_id="unused-new-id",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        selection_result=selection,
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "evidence-segment-1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "segment-1",
                "kind": "excerpt",
                "excerpt": "Project Alpha update",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        sufficiency_result=_sufficiency_output("SUFFICIENT"),
        current_round_no=2,
        availability_results=[
            {"start": "2026-08-31T09:00:00+09:00", "end": "2026-08-31T10:00:00+09:00"}
        ],
        exclusion_obligation_segment_ids=["segment-user"],
        prior_result=prior,
    )

    assert result["meta"]["artifact_id"] == "retrieval-1"
    assert result["meta"]["revision"] == 3
    assert {tuple(item.values()) for item in result["meta"]["based_on"]} >= {("retrieval-1", 2)}
    assert result["excluded_segment_ids"] == [
        "segment-old",
        "segment-model",
        "segment-user",
    ]
    assert result["availability_results"]
    assert set(result) == {
        "schema_version",
        "meta",
        "coverage",
        "context_bundle_ref",
        "evidence_refs",
        "selected_segment_ids",
        "excluded_segment_ids",
        "source_resource_refs",
        "source_statuses",
        "availability_results",
        "missing_information",
        "retrieval_rounds",
    }
