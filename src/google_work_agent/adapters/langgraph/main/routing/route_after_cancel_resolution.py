"""Route the Main graph after one cancellation-settlement step."""

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_CANCEL_RESOLUTION_SUCCESSORS = frozenset(
    {"cancel_resolution", "response_synthesis", "end"}
)


def route_after_cancel_resolution(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if (
        isinstance(run_id, str)
        and should_stop_for_cancel(run_id)
        and target not in {"cancel_resolution", "response_synthesis"}
    ):
        return "end"
    if target not in ROUTE_AFTER_CANCEL_RESOLUTION_SUCCESSORS or target not in available_targets:
        raise ValueError("CANCEL_RESOLUTION returned an unregistered successor")
    return str(target)
