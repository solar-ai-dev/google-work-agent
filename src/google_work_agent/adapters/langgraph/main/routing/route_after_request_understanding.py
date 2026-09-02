"""Route the Main graph after Request Understanding."""

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_REQUEST_UNDERSTANDING_SUCCESSORS = frozenset(
    {"tool_route", "stage_one", "single_workflow", "response_synthesis", "recovery", "end"}
)


def route_after_request_understanding(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if (
        target not in ROUTE_AFTER_REQUEST_UNDERSTANDING_SUCCESSORS
        or target not in available_targets
    ):
        raise ValueError("REQUEST_UNDERSTANDING returned an unregistered successor")
    return str(target)
