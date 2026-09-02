"""Route the Main graph after the three-profile Review stage."""

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_STAGE_THREE_SUCCESSORS = frozenset(
    {
        "stage_one",
        "stage_two",
        "stage_three",
        "retrieval_entry",
        "planning_entry",
        "review_entry",
        "domain_validation",
        "waiting_approval",
        "response_synthesis",
        "recovery",
        "end",
    }
)


def route_after_stage_three(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    control = state.get("__workflow_control__")
    signal = state.get("workflow_signal")
    review_complete = state.get("plan_review") is not None or (
        isinstance(signal, Mapping) and signal.get("kind") == "ROUTE_RECONSIDERATION_REQUIRED"
    )
    if (
        isinstance(control, Mapping)
        and control.get("stage") == "REVIEW_PENDING_SETTLEMENT"
        and review_complete
    ):
        target = "review_entry"
    if target not in ROUTE_AFTER_STAGE_THREE_SUCCESSORS or target not in available_targets:
        raise ValueError("STAGE_THREE returned an unregistered successor")
    return str(target)
