from typing import cast

import pytest

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    RetrievalResultV1,
)
from google_work_agent.application.agents.retrieval.finalize_retrieval import (
    RetrievalRoundLimitExceeded,
    initialize_current_round_no,
    retrieval_round_count,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)


def test_initial_round_is_zero_and_projects_one_completed_round() -> None:
    assert initialize_current_round_no(prior_result=None, tool_route_plan=_route_plan(1)) == 0
    assert retrieval_round_count(current_round_no=0) == 1


@pytest.mark.parametrize(
    ("prior_rounds", "expected_round_no", "expected_count"),
    [(1, 1, 2), (2, 2, 3)],
)
def test_same_route_continues_from_prior_completed_count(
    prior_rounds: int, expected_round_no: int, expected_count: int
) -> None:
    current_round_no = initialize_current_round_no(
        prior_result=_result(prior_rounds, route_revision=1), tool_route_plan=_route_plan(1)
    )
    assert current_round_no == expected_round_no
    assert retrieval_round_count(current_round_no=current_round_no) == expected_count


def test_same_route_additional_retrieval_is_blocked_after_three_rounds() -> None:
    with pytest.raises(RetrievalRoundLimitExceeded):
        initialize_current_round_no(
            prior_result=_result(3, route_revision=1), tool_route_plan=_route_plan(1)
        )


def test_new_input_route_revision_starts_a_new_round_chain() -> None:
    assert (
        initialize_current_round_no(
            prior_result=_result(2, route_revision=1), tool_route_plan=_route_plan(2)
        )
        == 0
    )


def _route_plan(revision: int) -> ToolRoutePlanV2:
    return cast(
        ToolRoutePlanV2,
        {
            "schema_version": 2,
            "input_plan": {
                "schema_version": 1,
                "meta": {"artifact_id": "input-route", "revision": revision, "based_on": []},
                "input_routes": [],
            },
            "output_plan": {
                "schema_version": 1,
                "meta": {"artifact_id": "output-route", "revision": 1, "based_on": []},
                "output_mode": "ANSWER",
            },
        },
    )


def _result(rounds: int, *, route_revision: int) -> RetrievalResultV1:
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": "retrieval-result",
            "revision": 1,
            "based_on": [{"artifact_id": "input-route", "revision": route_revision}],
        },
        "coverage": "PARTIAL",
        "context_bundle_ref": None,
        "evidence_refs": [],
        "selected_segment_ids": [],
        "source_resource_refs": [],
        "source_statuses": [],
        "missing_information": [],
        "retrieval_rounds": rounds,
    }
