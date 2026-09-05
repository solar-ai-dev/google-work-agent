import pytest

from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    review_recheck_output_schema,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema


@pytest.mark.parametrize("recheck", [False, True])
def test_review_output__requires_korean_description_in_initial_and_repair_schema(
    recheck: bool,
) -> None:
    dimension = "review.inspect_goal_and_evidence"
    schema = (
        review_recheck_output_schema((dimension,))
        if recheck else review_inspector_output_schema(dimension)
    )
    finding = {
        "dimension": dimension, "code": "SENDER_REQUIRED", "finding_kind": "CONFIRMATION",
        "description": "Please confirm the sender.", "evidence_refs": [],
        "affected_action_ids": [], "affected_route_ids": [], "required_information": ["sender"],
    }
    output = {
        "schema_version": 1, "findings": [finding],
        **({"affected_dimensions": [dimension]} if recheck else {"dimension": dimension}),
    }
    assert validate_output_schema(output, schema.json_schema)
    finding["description"] = "보낸 사람의 이름이나 이메일 주소를 알려 주시겠어요?"
    assert validate_output_schema(output, schema.json_schema) == []
