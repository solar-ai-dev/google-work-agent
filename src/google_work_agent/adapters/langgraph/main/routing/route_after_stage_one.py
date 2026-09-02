"""Route the Main graph after the three-profile first physical stage."""

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_STAGE_ONE_SUCCESSORS = frozenset(
    {
        "stage_one",
        "stage_two",
        "retrieval_entry",
        "planning_entry",
        "response_synthesis",
        "recovery",
        "end",
    }
)


def route_after_stage_one(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_STAGE_ONE_SUCCESSORS or target not in available_targets:
        raise ValueError("STAGE_ONE returned an unregistered successor")
    return str(target)
