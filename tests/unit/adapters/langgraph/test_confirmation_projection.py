from google_work_agent.adapters.langgraph.confirmation_projection import (
    confirmation_response_from_state,
    with_confirmation_response,
)


def _state(owner: str) -> dict[str, object]:
    return {
        "prompt_context": {
            "confirmation_interrupt": {
                "schema_version": 1,
                "interrupt_id": "interrupt-1",
                "owner_subgraph": owner,
            },
            "confirmation_response": {
                "schema_version": 1,
                "response_kind": "FREE_TEXT",
                "selected_option_ids": [],
                "free_text": "  use the existing task  ",
            },
        }
    }


def test_confirmation_response_is_visible_only_to_originating_owner() -> None:
    state = _state("TOOL_ROUTE")

    response = confirmation_response_from_state(state, owner_subgraph="TOOL_ROUTE")

    assert response is not None
    assert response["free_text"] == "use the existing task"
    assert confirmation_response_from_state(state, owner_subgraph="PLANNING") is None


def test_confirmation_projection_never_adds_absent_response() -> None:
    base = {"request_intent": {"schema_version": 2}}

    assert with_confirmation_response(base, None) is base


def test_confirmation_projection_adds_only_bounded_response_shape() -> None:
    response = confirmation_response_from_state(
        _state("WORK_ANALYSIS"), owner_subgraph="WORK_ANALYSIS"
    )
    assert response is not None

    projection = with_confirmation_response({"evidence": []}, response)

    assert set(projection["confirmation_response"]) == {
        "schema_version",
        "response_kind",
        "selected_option_ids",
        "free_text",
    }
