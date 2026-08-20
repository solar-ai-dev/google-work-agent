from __future__ import annotations

import pytest

from google_work_agent.application.workflows.review_v2_tools import (
    REVIEW_V2_INSPECT_TOOLS,
    ReviewV2ToolCallError,
    review_tool_call_to_candidate_v2,
)
from google_work_agent.ports import LLMToolCall, ToolCallProviderResponse


def _response(name: str, arguments: dict[str, object]) -> ToolCallProviderResponse:
    return ToolCallProviderResponse(
        calls=(LLMToolCall(name=name, arguments=arguments),),
        model="test",
        provider_request_id=None,
        input_tokens=None,
        output_tokens=None,
        latency_ms=1,
    )


def test_tool_names_remain_status_discriminators() -> None:
    assert [tool.name for tool in REVIEW_V2_INSPECT_TOOLS] == [
        "review_pass",
        "review_revise",
        "review_retrieve_more",
        "review_route_reconsideration",
        "review_confirm",
        "review_block",
    ]


def test_retrieve_more_maps_directly_to_canonical_evidence_gaps() -> None:
    candidate = review_tool_call_to_candidate_v2(
        _response(
            "review_retrieve_more",
            {
                "evidence_gaps": [
                    {
                        "code": "MISSING_RECIPIENT",
                        "description": "recipient identity is missing",
                        "required_information": ["recipient email"],
                    }
                ]
            },
        )
    )
    assert candidate["status"] == "RETRIEVE_MORE"
    assert "issues" not in candidate
    assert candidate["evidence_gaps"][0]["code"] == "MISSING_RECIPIENT"


def test_pass_cannot_smuggle_confirmation_argument() -> None:
    with pytest.raises(ReviewV2ToolCallError, match="contain only summary"):
        review_tool_call_to_candidate_v2(
            _response("review_pass", {"summary": "ok", "confirmation": {}})
        )


def test_block_requires_structured_blocker_shape() -> None:
    with pytest.raises(ReviewV2ToolCallError):
        review_tool_call_to_candidate_v2(
            _response("review_block", {"blockers": ["legacy blocker"]})
        )
