"""Route the Main graph after the three-profile second physical stage."""

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_STAGE_TWO_SUCCESSORS = frozenset(
    {
        "stage_one",
        "stage_two",
        "stage_three",
        "retrieval_entry",
        "planning_entry",
        "review_entry",
        "response_synthesis",
        "recovery",
        "end",
    }
)


def route_after_stage_two(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_STAGE_TWO_SUCCESSORS or target not in available_targets:
        raise ValueError("STAGE_TWO returned an unregistered successor")
    return str(target)
